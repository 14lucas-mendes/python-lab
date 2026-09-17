import copy
from datetime import datetime, timezone
from pathlib import Path

from python_lab.learning import (
    CompletionError,
    PLAN_KEYS,
    complete_mission,
    recommend_mission,
    reveal_hint,
    start_mission,
)
from python_lab.models import Goal, Mission, MissionProgress, Skill, TestResult
from python_lab.progress import ProgressRepository
from python_lab.test_runner import run_tests, solution_fingerprint


class ApplicationError(Exception):
    pass


class PythonLabApp:
    def __init__(
        self,
        goal: Goal,
        skills: dict[str, Skill],
        missions: list[Mission],
        repository: ProgressRepository,
        project_root: Path,
    ) -> None:
        self.goal = goal
        self.skills = skills
        self.missions = missions
        self.repository = repository
        self.project_root = project_root
        self.progress = repository.load()
        self._persisted_progress = copy.deepcopy(self.progress)

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

    def run_current_tests(self, solution_path: Path | None = None) -> TestResult:
        mission = self.current_mission()
        progress = self.current_progress()
        if not progress.plan or not all(
            key in progress.plan and str(progress.plan[key]).strip() for key in PLAN_KEYS
        ):
            raise ApplicationError("Planejamento incompleto: registre /plan antes de testar")
        progress.attempts += 1
        chosen = solution_path or mission.solution_path
        chosen_path = Path(chosen).resolve()
        fingerprint = solution_fingerprint(chosen_path)
        result = run_tests(mission.test_path, self.project_root, chosen)
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
        return result

    def next_hint(self, confirm_reference: bool = False) -> str:
        mission = self.current_mission()
        progress = self.current_progress()
        if progress.attempts == 0:
            raise ApplicationError("Execute /test antes de pedir pistas")
        hint = reveal_hint(mission, progress, confirm_reference=confirm_reference)
        self.persist()
        return hint

    def tests_are_current(self) -> bool:
        progress = self.current_progress()
        if not progress.tests_passed or not progress.tested_solution_path:
            return False
        current_fingerprint = solution_fingerprint(Path(progress.tested_solution_path))
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

    def skill_states(self) -> dict[str, str]:
        rank = {"practicing": 1, "demonstrated": 2, "consolidated": 3}
        latest: dict[str, str] = {}
        for item in self.progress.evidence:
            skill = str(item.get("skill", ""))
            result = str(item.get("result", "practicing"))
            if rank.get(result, 0) >= rank.get(latest.get(skill, ""), 0):
                latest[skill] = result
        return latest
