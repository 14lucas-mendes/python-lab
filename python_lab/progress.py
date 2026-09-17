import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from python_lab.models import AppProgress, MissionProgress


class ProgressError(Exception):
    pass


class ProgressRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._loaded = False
        self._revision: str | None = None

    def _current_revision(self) -> str | None:
        if not self.path.exists():
            return None
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    def load(self) -> AppProgress:
        if not self.path.exists():
            self._loaded = True
            self._revision = None
            return AppProgress()
        try:
            raw = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProgressError(f"Não foi possível ler o progresso: {exc}") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProgressError("Progresso inválido: JSON corrompido") from exc
        if not isinstance(payload, dict):
            raise ProgressError("Progresso inválido: formato inesperado")
        current_mission_id = payload.get("current_mission_id")
        if current_mission_id is not None and not isinstance(current_mission_id, str):
            raise ProgressError("Progresso inválido: current_mission_id deve ser texto ou nulo")
        raw_missions = payload.get("missions", {})
        if not isinstance(raw_missions, dict):
            raise ProgressError("Progresso inválido: missions deve ser um objeto")
        missions: dict[str, MissionProgress] = {}
        for mission_id, data in raw_missions.items():
            if not isinstance(mission_id, str) or not isinstance(data, dict):
                raise ProgressError("Progresso inválido: missão malformada")
            try:
                mission = MissionProgress(**data)
            except (TypeError, ValueError) as exc:
                raise ProgressError(
                    f"Progresso inválido: dados da missão {mission_id} malformados"
                ) from exc
            if (
                mission.status not in {"available", "started", "completed"}
                or not isinstance(mission.attempts, int)
                or isinstance(mission.attempts, bool)
                or mission.attempts < 0
                or not isinstance(mission.tests_passed, bool)
                or not isinstance(mission.hints_revealed, int)
                or isinstance(mission.hints_revealed, bool)
                or mission.hints_revealed < 0
                or not isinstance(mission.reference_viewed, bool)
                or (mission.explanation is not None and not isinstance(mission.explanation, str))
                or (
                    mission.plan is not None
                    and (
                        not isinstance(mission.plan, dict)
                        or any(not isinstance(value, str) for value in mission.plan.values())
                    )
                )
                or (mission.tested_solution_path is not None and not isinstance(mission.tested_solution_path, str))
                or (mission.tested_solution_fingerprint is not None and not isinstance(mission.tested_solution_fingerprint, str))
                or not isinstance(mission.attempt_history, list)
                or any(not isinstance(item, dict) for item in mission.attempt_history)
            ):
                raise ProgressError(f"Progresso inválido: dados da missão {mission_id} inválidos")
            missions[mission_id] = mission
        evidence = payload.get("evidence", [])
        if not isinstance(evidence, list) or any(not isinstance(item, dict) for item in evidence):
            raise ProgressError("Progresso inválido: evidence deve ser uma lista de objetos")
        if current_mission_id is not None and current_mission_id not in missions:
            raise ProgressError("Progresso inválido: missão atual não encontrada")
        self._loaded = True
        self._revision = self._current_revision()
        return AppProgress(
            current_mission_id=current_mission_id,
            missions=missions,
            evidence=list(evidence),
        )

    def save(self, progress: AppProgress) -> None:
        temp_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self._loaded and self._current_revision() != self._revision:
                raise ProgressError(
                    "Conflito de progresso: o arquivo foi alterado por outra sessão"
                )
            payload = {
                "current_mission_id": progress.current_mission_id,
                "missions": {
                    mission_id: asdict(mission_progress)
                    for mission_id, mission_progress in progress.missions.items()
                },
                "evidence": progress.evidence,
            }
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                dir=self.path.parent,
                suffix=".tmp",
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except ProgressError:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise
        except Exception as exc:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise ProgressError(f"Não foi possível salvar o progresso: {exc}") from exc
        self._loaded = True
        self._revision = self._current_revision()
