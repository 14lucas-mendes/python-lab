import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


MAX_SESSIONS = 20
MAX_EVENTS = 200


class SessionError(Exception):
    pass


class SessionLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._sessions: list[dict[str, object]] = []
        self._current: dict[str, object] | None = None

    def load(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SessionError("Histórico de sessão inválido: JSON corrompido") from exc
        except OSError as exc:
            raise SessionError(f"Não foi possível ler o histórico de sessão: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), list):
            raise SessionError("Histórico de sessão inválido: formato inesperado")
        sessions: list[dict[str, object]] = []
        for item in payload["sessions"]:
            if isinstance(item, dict):
                sessions.append(item)
        return sessions

    def start(self) -> None:
        now = datetime.now(timezone.utc)
        self._sessions = self.load()
        self._current = {
            "id": now.strftime("%Y%m%dT%H%M%S%f"),
            "started_at": now.isoformat(),
            "ended_at": None,
            "events": [],
        }
        self._sessions.append(self._current)
        self._trim()
        self._save()

    def record(self, command: str, summary: str) -> None:
        if self._current is None:
            self.start()
        events = self._current.setdefault("events", [])
        if not isinstance(events, list):
            events = []
            self._current["events"] = events
        events.append(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "command": command,
                "summary": summary,
            }
        )
        if len(events) > MAX_EVENTS:
            self._current["events"] = events[-MAX_EVENTS:]
        self._save()

    def close(self, summary: str | None = None) -> None:
        if self._current is None:
            return
        if summary:
            self.record("/exit", summary)
        self._current["ended_at"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def current_events(self) -> list[dict[str, object]]:
        if self._current is None:
            return []
        events = self._current.get("events", [])
        return list(events) if isinstance(events, list) else []

    def previous_sessions(self) -> list[dict[str, object]]:
        return [session for session in self._sessions if session is not self._current]

    def _trim(self) -> None:
        if len(self._sessions) > MAX_SESSIONS:
            extras = len(self._sessions) - MAX_SESSIONS
            self._sessions = self._sessions[extras:]
            if self._current not in self._sessions and self._current is not None:
                self._sessions.append(self._current)
                self._sessions = self._sessions[-MAX_SESSIONS:]

    def _save(self) -> None:
        temp_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"sessions": self._sessions}
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
        except Exception as exc:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise SessionError(f"Não foi possível salvar o histórico de sessão: {exc}") from exc
