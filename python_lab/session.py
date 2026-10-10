"""Independent SQLite session and event records."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from python_lab.storage.database import connection
from python_lab.storage.errors import SessionError

MAX_SESSIONS = 20
MAX_EVENTS = 200


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prune(db: sqlite3.Connection) -> None:
    db.execute("DELETE FROM sessions WHERE id IN (SELECT id FROM sessions WHERE ended_at IS NOT NULL ORDER BY started_at DESC, rowid DESC LIMIT -1 OFFSET ?)", (MAX_SESSIONS,))


class SessionLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._current: dict[str, object] | None = None

    @property
    def current_session(self) -> dict[str, object] | None:
        return self._current

    @property
    def is_open(self) -> bool:
        return self._current is not None and self._current["ended_at"] is None

    def load(self) -> list[dict[str, object]]:
        try:
            with connection(self.path) as db:
                rows = db.execute("SELECT id,started_at,ended_at FROM sessions ORDER BY started_at,rowid").fetchall()
                sessions = []
                for session_id, started, ended in rows:
                    events = [dict(timestamp=t, command=c, summary=s) for t,c,s in db.execute("SELECT timestamp,command,summary FROM events WHERE session_id=? ORDER BY id", (session_id,))]
                    sessions.append(dict(id=session_id, started_at=started, ended_at=ended, events=events))
                return sessions
        except (sqlite3.Error, OSError, ValueError) as exc:
            raise SessionError(f"Histórico de sessão inválido ou indisponível: {exc}") from exc

    def start(self) -> None:
        now = _now()
        session_id = uuid4().hex
        try:
            with connection(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("INSERT INTO sessions(id,started_at,ended_at) VALUES (?,?,NULL)", (session_id, now))
                _prune(db)
                db.commit()
        except (sqlite3.Error, OSError, ValueError) as exc:
            raise SessionError(f"Não foi possível iniciar a sessão: {exc}") from exc
        self._current = dict(id=session_id, started_at=now, ended_at=None, events=[])

    def record(self, command: str, summary: str) -> None:
        if self._current is None:
            self.start()
        if not self.is_open:
            raise SessionError("Sessão encerrada")
        assert self._current is not None
        event = dict(timestamp=_now(), command=command, summary=summary)
        try:
            with connection(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT ended_at FROM sessions WHERE id=?", (self._current["id"],)).fetchone()
                if row is None or row[0] is not None:
                    raise SessionError("Sessão encerrada")
                db.execute("INSERT INTO events(session_id,timestamp,command,summary) VALUES (?,?,?,?)", (self._current["id"], *event.values()))
                db.execute("DELETE FROM events WHERE id IN (SELECT id FROM events WHERE session_id=? ORDER BY id DESC LIMIT -1 OFFSET ?)", (self._current["id"], MAX_EVENTS))
                db.commit()
        except (sqlite3.Error, OSError, ValueError) as exc:
            raise SessionError(f"Não foi possível registrar evento: {exc}") from exc
        self._current["events"] = self.current_events()

    def try_record(self, command: str, summary: str) -> str | None:
        """Record best-effort, returning an error without logging that error again."""
        try:
            self.record(command, summary)
        except SessionError as exc:
            return str(exc)
        return None

    def close(self, summary: str | None = None) -> None:
        if not self.is_open:
            return
        assert self._current is not None
        ended = _now()
        try:
            with connection(self.path) as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT ended_at FROM sessions WHERE id=?", (self._current["id"],)).fetchone()
                if row is None or row[0] is not None:
                    db.rollback()
                    self._current["ended_at"] = row[0] if row else ended
                    return
                if summary:
                    db.execute("INSERT INTO events(session_id,timestamp,command,summary) VALUES (?,?,?,?)", (self._current["id"], ended, "/exit", summary))
                    db.execute("DELETE FROM events WHERE id IN (SELECT id FROM events WHERE session_id=? ORDER BY id DESC LIMIT -1 OFFSET ?)", (self._current["id"], MAX_EVENTS))
                db.execute("UPDATE sessions SET ended_at=? WHERE id=?", (ended, self._current["id"]))
                _prune(db)
                db.commit()
        except (sqlite3.Error, OSError, ValueError) as exc:
            raise SessionError(f"Não foi possível encerrar a sessão: {exc}") from exc
        self._current["ended_at"] = ended
        self._current["events"] = self.current_events()

    def current_events(self) -> list[dict[str, object]]:
        if self._current is None:
            return []
        return next((session["events"] for session in self.load() if session["id"] == self._current["id"]), [])

    def previous_sessions(self) -> list[dict[str, object]]:
        return [session for session in self.load() if self._current is None or session["id"] != self._current["id"]]
