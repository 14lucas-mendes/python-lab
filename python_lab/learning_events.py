"""Deduplicated help records and progress changes share a SQLite transaction."""

import copy
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from python_lab.models import AppProgress
from python_lab.progress import ProgressRepository, encode_progress
from python_lab.storage.codecs import decode_progress
from python_lab.storage.database import connection
from python_lab.storage.errors import ProgressError


@dataclass(frozen=True)
class AssistanceEvent:
    mission_id: str | None
    action: str
    level: int
    timestamp: str
    request_id: str

    def __post_init__(self) -> None:
        if type(self.level) is not int or not 0 <= self.level <= 4:
            raise ValueError("Nível de assistência deve estar entre 0 e 4")
        if self.mission_id is not None and (not isinstance(self.mission_id, str) or not self.mission_id.strip()):
            raise ValueError("Identificador de missão inválido")
        for key in ("action", "timestamp", "request_id"):
            value = getattr(self, key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Evento de assistência: {key} inválido")


class AssistanceRecorder:
    def __init__(self, database_path: Path):
        self.database_path = database_path

    def record(
        self, event: AssistanceEvent, *, repository: ProgressRepository | None = None,
        progress: AppProgress | None = None, attempt_id: str | None = None,
    ) -> None:
        """Public record(event) also works without an application/repository.

        Internal callers supply their CAS revision and captured attempt. Local
        state is refreshed only after commit; a late answer remains historical.
        """
        if repository is not None and repository.path.resolve() != self.database_path.resolve():
            raise ProgressError("Evento e progresso devem usar o mesmo banco")
        if (repository is None) != (progress is None):
            raise ProgressError("Progresso e revisão devem ser fornecidos juntos")
        if attempt_id is not None and (not isinstance(attempt_id, str) or not attempt_id.strip()):
            raise ProgressError("Identidade de tentativa inválida")
        try:
            with connection(self.database_path) as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT payload, revision FROM progress WHERE id=1").fetchone()
                revision = row[1] if row else None
                persisted = decode_progress(row[0].encode("utf-8")) if row else AppProgress()
                candidate = copy.deepcopy(progress) if progress is not None else persisted
                mission = candidate.missions.get(event.mission_id) if event.mission_id else None
                if event.mission_id is not None and mission is None:
                    raise ProgressError(f"Missão não encontrada para registrar ajuda: {event.mission_id}")
                captured_attempt = attempt_id if attempt_id is not None else (mission.attempt_id if mission else None)
                identity = (event.mission_id, event.action, event.level, captured_attempt)
                existing = db.execute("SELECT mission_id,action,level,attempt_id FROM assistance_events WHERE request_id=?", (event.request_id,)).fetchone()
                if existing:
                    if existing != identity:
                        raise ProgressError("Identidade request_id de assistência divergente")
                    candidate = persisted
                else:
                    if repository is not None and revision != repository._revision:
                        raise ProgressError("Conflito de progresso: outra sessão salvou alterações")
                    # A patch is full help regardless of its supplied level.
                    effective_level = 4 if event.action == "apply" else event.level
                    if mission and mission.attempt_id == captured_attempt and mission.status == "started":
                        mission.max_assistance_level = max(mission.max_assistance_level, effective_level)
                        if effective_level == 4:
                            mission.reference_viewed = True
                    db.execute("INSERT INTO assistance_events(request_id,mission_id,action,level,timestamp,attempt_id) VALUES (?,?,?,?,?,?)",
                               (event.request_id, event.mission_id, event.action, event.level, event.timestamp, captured_attempt))
                    if row or progress is not None:
                        payload = encode_progress(candidate)
                        revision = (revision or 0) + 1
                        if row:
                            db.execute("UPDATE progress SET payload=?,revision=? WHERE id=1", (payload, revision))
                        else:
                            db.execute("INSERT INTO progress(id,payload,revision) VALUES (1,?,?)", (payload, revision))
                db.commit()
            if repository is not None and progress is not None:
                repository._revision = revision
                progress.current_mission_id = candidate.current_mission_id
                progress.missions = candidate.missions
                progress.evidence = candidate.evidence
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            raise ProgressError(f"Não foi possível registrar assistência: {exc}") from exc
