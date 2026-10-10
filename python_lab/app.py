import copy
from dataclasses import dataclass
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from python_lab.learning import (
    CompletionError,
    plan_is_complete,
    complete_mission,
    recommend_mission,
    reveal_hint,
    start_mission,
)
from python_lab.catalog import CatalogError
from python_lab.models import AppProgress, Goal, Mission, MissionProgress, RoadmapCycle, Skill, TestResult
from python_lab.progress import ProgressRepository
from python_lab.learning_events import AssistanceEvent, AssistanceRecorder
from python_lab.runtime.processes import ProcessCleanupError
from python_lab.test_runner import run_tests, solution_fingerprint


class ApplicationError(Exception):
    pass


class ActiveMissionError(ApplicationError):
    """Persisted active mission no longer exists in the catalog."""


def validate_active_mission(progress: AppProgress, missions: list[Mission]) -> None:
    current = progress.current_mission_id
    if current is not None and current not in {mission.id for mission in missions}:
        raise ActiveMissionError(
            f"Missão ativa {current} não existe no catálogo. "
            "Restaure o catálogo ou revise os dados migrados."
        )


def _solution_fingerprint(path: Path) -> str | None:
    try:
        return solution_fingerprint(path)
    except OSError as exc:
        raise ApplicationError(f"Não foi possível ler a solução: {path}: {exc}") from exc


@dataclass(frozen=True)
class StatusSnapshot:
    current_mission_id: str | None
    plan_complete: bool
    tests_current: bool
    next_step: str
    last_result: TestResult | None


class PythonLabApp:
    def __init__(
        self,
        goal: Goal,
        skills: dict[str, Skill],
        missions: list[Mission],
        repository: ProgressRepository,
        project_root: Path,
        roadmap: tuple[RoadmapCycle, ...] = (),
    ) -> None:
        for mission in missions:
            for skill in mission.skills:
                if skill not in skills:
                    raise CatalogError(f"Missão {mission.id}: skill inexistente: {skill}")
        self.goal = goal
        self.skills = skills
        self.missions = missions
        self.repository = repository
        self.project_root = project_root
        self.roadmap = roadmap
        self.progress = repository.load()
        validate_active_mission(self.progress, missions)
        self._persisted_progress = copy.deepcopy(self.progress)
        # Session-only output: never persisted as learner progress.
        self.last_test_results: dict[str, TestResult] = {}
        self.last_test_mission_id: str | None = None

    def cycle_title(self, cycle: int) -> str:
        for item in self.roadmap:
            if item.cycle == cycle:
                return item.title
        return f"Ciclo {cycle}"

    def persist(self) -> None:
        previous = self._persisted_progress
        try:
            self.repository.save(self.progress)
        except Exception:
            self.progress = copy.deepcopy(previous)
            raise
        self._persisted_progress = copy.deepcopy(self.progress)

    def mission_by_id(self, mission_id: str) -> Mission:
        for mission in self.missions:
            if mission.id == mission_id:
                return mission
        raise ApplicationError(f"Missão inexistente: {mission_id}")

    def current_mission(self) -> Mission:
        if not self.progress.current_mission_id:
            raise ApplicationError("Nenhuma missão iniciada")
        return self.mission_by_id(self.progress.current_mission_id)

    def mission_content(self, mission: Mission, concepts: bool = False) -> str:
        path = mission.concepts_path if concepts else mission.briefing_path
        label = "Apoio conceitual" if concepts else "Enunciado"
        if path is None:
            return f"{label} indisponível para a missão {mission.id}. Consulte o resumo e os arquivos da missão."
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeError:
            raise ApplicationError(f"{label} com codificação inválida; use UTF-8: {path}")
        except OSError as exc:
            raise ApplicationError(f"Não foi possível ler {label.lower()}: {path}: {exc}")

    def last_test_result(self) -> TestResult | None:
        mission_id = self.progress.current_mission_id or self.last_test_mission_id
        return self.last_test_results.get(mission_id) if mission_id else None

    def remember_test_result(self, result: TestResult) -> None:
        mission_id = self.current_mission().id
        self.last_test_results[mission_id] = result
        self.last_test_mission_id = mission_id

    def current_progress(self) -> MissionProgress:
        mission = self.current_mission()
        return self.progress.missions[mission.id]

    def recommended(self) -> Mission | None:
        return recommend_mission(self.missions, self.progress)

    def start(self, mission_id: str) -> Mission:
        mission = self.mission_by_id(mission_id)
        start_mission(mission, self.progress, self.missions)
        self.persist()
        return mission

    def save_plan(self, plan: dict[str, str]) -> None:
        progress = self.current_progress()
        progress.plan = plan
        self.persist()

    def run_current_tests(
        self, solution_path: Path | None = None, *, cancel: threading.Event | None = None
    ) -> TestResult:
        mission = self.current_mission()
        progress = self.current_progress()
        if not plan_is_complete(progress.plan):
            raise ApplicationError("Planejamento incompleto: registre /plan antes de testar")
        chosen = solution_path or mission.solution_path
        chosen_path = Path(chosen).resolve()
        fingerprint = _solution_fingerprint(chosen_path)
        try:
            result = run_tests(mission.test_path, self.project_root, chosen, cancel=cancel)
        except ProcessCleanupError as exc:
            progress.tests_passed = False
            try:
                self.persist()
            except Exception as save_error:
                # persist rolls back local state on failure. Keep this action's
                # evidence invalid locally, and retain CAS instead of overwriting
                # a newer writer to reconcile an unsuccessful invalidation.
                self.progress.missions[mission.id].tests_passed = False
                raise ApplicationError(
                    f"Falha ao encerrar os testes: {exc}; "
                    f"não foi possível salvar a invalidação: {save_error}"
                ) from save_error
            raise ApplicationError(f"Falha ao encerrar os testes: {exc}") from exc
        # Completion acceptance: cancellation observed here wins. After this
        # boundary, save success/error is authoritative even if cancellation
        # arrives while the repository is committing or the UI callback waits.
        if result.cancelled or (cancel is not None and cancel.is_set()):
            progress.tests_passed = False
            self.persist()
            return TestResult(False, -1, "Execução cancelada.", summary="Execução cancelada", cancelled=True)
        progress.attempts += 1
        progress.tests_passed = result.passed
        progress.tested_solution_path = str(chosen_path)
        progress.tested_solution_fingerprint = fingerprint
        progress.attempt_history.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "passed": result.passed,
                "return_code": result.return_code,
                "summary": result.summary,
                "solution_path": str(chosen_path),
            }
        )
        self.persist()
        self.remember_test_result(result)
        return result

    def next_hint(self, confirm_reference: bool = False) -> str:
        mission = self.current_mission()
        progress = self.current_progress()
        if progress.attempts == 0:
            raise ApplicationError("Execute /test antes de pedir pistas")
        is_reference = progress.hints_revealed >= len(mission.hints) - 1
        hint = reveal_hint(mission, progress, confirm_reference=confirm_reference)
        level = 4 if is_reference else min(progress.hints_revealed, 3)
        self.record_assistance(AssistanceEvent(
            mission.id, "reference" if level == 4 else "hint", level,
            datetime.now(timezone.utc).isoformat(), uuid4().hex,
        ), attempt_id=progress.attempt_id)
        return hint

    def capture_assistance_attempt(self, mission_id: str | None) -> str | None:
        if mission_id is None:
            return None
        self.mission_by_id(mission_id)
        progress = self.progress.missions.get(mission_id)
        if progress is None or progress.status != "started":
            raise ApplicationError(f"Missão não iniciada para registrar ajuda: {mission_id}")
        return progress.attempt_id

    def record_assistance(self, event: AssistanceEvent, *, attempt_id: str | None = None) -> None:
        if event.mission_id is not None:
            self.mission_by_id(event.mission_id)
        try:
            AssistanceRecorder(self.repository.path).record(
                event, repository=self.repository, progress=self.progress, attempt_id=attempt_id,
            )
        except Exception:
            self.progress = copy.deepcopy(self._persisted_progress)
            raise
        self._persisted_progress = copy.deepcopy(self.progress)

    def record_full_solution(
        self, mission_id: str, *, request_id: str | None = None,
        action: str = "reference", attempt_id: str | None = None,
    ) -> None:
        """Record explicit level-four help on its captured mission identity."""
        if attempt_id is None:
            attempt_id = self.capture_assistance_attempt(mission_id)
        self.record_assistance(AssistanceEvent(
            mission_id, action, 4, datetime.now(timezone.utc).isoformat(), request_id or uuid4().hex,
        ), attempt_id=attempt_id)

    def tests_are_current(self) -> bool:
        progress = self.current_progress()
        if not progress.tests_passed or not progress.tested_solution_path:
            return False
        current_fingerprint = _solution_fingerprint(Path(progress.tested_solution_path))
        return (
            progress.tested_solution_fingerprint is not None
            and current_fingerprint == progress.tested_solution_fingerprint
        )

    def save_explanation(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            raise ApplicationError("A explicação não pode ser vazia")
        progress = self.current_progress()
        progress.explanation = cleaned
        self.persist()

    def complete_current_mission(self) -> list[dict[str, object]]:
        mission = self.current_mission()
        progress = self.current_progress()
        if progress.tests_passed and not self.tests_are_current():
            raise CompletionError(
                "Conclusão rejeitada: execute os testes novamente para a solução atual"
            )
        evidence = complete_mission(mission, progress, self.progress.evidence)
        self.progress.evidence.extend(evidence)
        self.progress.current_mission_id = None
        self.persist()
        return evidence

    def status_snapshot(self) -> StatusSnapshot:
        current = self.progress.current_mission_id
        plan_complete = False
        tests_current = False
        if current is None:
            recommended = self.recommended()
            next_step = ("Todas as missões concluídas." if recommended is None else
                         f"Inicie a missão {recommended.id} com /start {recommended.id}")
        else:
            progress = self.current_progress()
            plan_complete = plan_is_complete(progress.plan)
            tests_current = self.tests_are_current()
            if not plan_complete:
                next_step = "Registre o planejamento com /plan"
            elif not progress.tests_passed:
                next_step = "Edite a solução e execute /test"
            elif not tests_current:
                next_step = "Execute /test novamente para a solução atual"
            else:
                next_step = "Registre a explicação com /explain"
        return StatusSnapshot(current, plan_complete, tests_current, next_step, self.last_test_result())

    def next_step(self) -> str:
        return self.status_snapshot().next_step

    def skill_states(self) -> dict[str, str]:
        rank = {"practicing": 1, "demonstrated": 2, "consolidated": 3}
        latest: dict[str, str] = {}
        for item in self.progress.evidence:
            skill = str(item.get("skill", ""))
            result = str(item.get("result", "practicing"))
            if rank.get(result, 0) >= rank.get(latest.get(skill, ""), 0):
                latest[skill] = result
        return latest
