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

    def load(self) -> AppProgress:
        if not self.path.exists():
            return AppProgress()
        raw = self.path.read_text(encoding="utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProgressError("Progresso inválido: JSON corrompido") from exc
        if not isinstance(payload, dict):
            raise ProgressError("Progresso inválido: formato inesperado")
        missions = {
            mission_id: MissionProgress(**data)
            for mission_id, data in payload.get("missions", {}).items()
        }
        return AppProgress(
            current_mission_id=payload.get("current_mission_id"),
            missions=missions,
            evidence=list(payload.get("evidence", [])),
        )

    def save(self, progress: AppProgress) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "current_mission_id": progress.current_mission_id,
            "missions": {
                mission_id: asdict(mission_progress)
                for mission_id, mission_progress in progress.missions.items()
            },
            "evidence": progress.evidence,
        }
        temp_path: Path | None = None
        try:
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
        except Exception:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise
