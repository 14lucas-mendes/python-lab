"""Transactional progress repository."""

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from python_lab.models import AppProgress
from python_lab.storage.codecs import decode_progress
from python_lab.storage.database import connection
from python_lab.storage.errors import ProgressError


def encode_progress(progress: AppProgress) -> str:
    payload = {"current_mission_id": progress.current_mission_id,
               "missions": {key: asdict(value) for key, value in progress.missions.items()},
               "evidence": progress.evidence}
    raw = json.dumps(payload, ensure_ascii=False)
    decode_progress(raw.encode("utf-8"))
    return raw


class ProgressRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._revision: int | None = None

    def load(self) -> AppProgress:
        try:
            with connection(self.path) as db:
                row = db.execute("SELECT payload, revision FROM progress WHERE id=1").fetchone()
            if row is None:
                self._revision = None
                return AppProgress()
            progress = decode_progress(row[0].encode("utf-8"))
            self._revision = row[1]
            return progress
        except (sqlite3.Error, OSError, ValueError) as exc:
            raise ProgressError(f"Progresso inválido ou indisponível: {exc}") from exc

    def save(self, progress: AppProgress) -> None:
        try:
            payload = encode_progress(progress)
            with connection(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT revision FROM progress WHERE id=1").fetchone()
                actual = row[0] if row else None
                if actual != self._revision:
                    raise ProgressError("Conflito de progresso: outra sessão salvou alterações")
                revision = (actual or 0) + 1
                if row:
                    db.execute("UPDATE progress SET payload=?, revision=? WHERE id=1", (payload, revision))
                else:
                    db.execute("INSERT INTO progress(id,payload,revision) VALUES (1,?,?)", (payload, revision))
                db.commit()
            self._revision = revision
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            raise ProgressError(f"Não foi possível salvar o progresso: {exc}") from exc
