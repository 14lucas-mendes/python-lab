"""Metadata-only, workspace-bound assistant conversation history."""

from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from python_lab.assistant.errors import AssistantError
from python_lab.assistant.models import AssistantAnswer, AssistantRequest
from python_lab.storage.database import connection


@dataclass(frozen=True)
class ConversationReference:
    request_id: str
    workspace: Path
    mission_id: str | None
    created_at: str
    action: str


class ConversationRepository:
    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)

    def error_references(self, workspace: Path, *, mission_id: str | None) -> tuple[ConversationReference, ...]:
        """Read local error metadata for exactly one workspace/mission scope.

        A diagnose request or an explicitly supplied traceback is an observed
        error-related conversation, not proof that the mission's tests failed.
        Avoid the writable connection helper: this read must not create or
        migrate a database, nor fetch source, prompt, traceback or answer data.
        """
        try:
            if not self.database_path.exists():
                return ()
            root = Path(workspace).resolve()
            uri = self.database_path.resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=5)) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='conversations'").fetchone() is None:
                    return ()
                rows = db.execute("""SELECT request_id, workspace, mission_id, created_at, action
                    FROM conversations
                    WHERE workspace=? AND mission_id IS ?
                        AND (action='diagnose' OR traceback_sha256 IS NOT NULL)
                    ORDER BY created_at, request_id""", (str(root), mission_id)).fetchall()
            return tuple(ConversationReference(identity, Path(scope), mission, timestamp, action)
                         for identity, scope, mission, timestamp, action in rows)
        except (sqlite3.Error, OSError, ValueError, RuntimeError) as exc:
            raise AssistantError(f"Não foi possível consultar o histórico de assistência: {exc}") from exc

    def append(self, request: AssistantRequest, answer: AssistantAnswer, *, request_id: str | None = None) -> str:
        identity = request_id if request_id is not None else uuid4().hex
        if not isinstance(identity, str) or not identity:
            raise AssistantError("ID local da requisição inválido.")
        sources = json.dumps(
            [{"path": source.path, "sha256": source.sha256} for source in request.snapshot.sources],
            ensure_ascii=False,
        )
        # Free-form response fields can quote entire selected files or traceback
        # lines. Keep a digest for correlation and only structured metadata.
        response_bytes = json.dumps(asdict(answer), ensure_ascii=False).encode("utf-8")
        response = json.dumps({
            "sha256": hashlib.sha256(response_bytes).hexdigest(),
            "assistance_level": answer.assistance_level,
            "references": [asdict(reference) for reference in answer.references],
            "usage": asdict(answer.usage),
        }, ensure_ascii=False)
        try:
            with connection(self.database_path) as db:
                db.execute("""CREATE TABLE IF NOT EXISTS conversations (
                    request_id TEXT PRIMARY KEY, workspace TEXT NOT NULL, created_at TEXT NOT NULL,
                    action TEXT NOT NULL, mode TEXT NOT NULL, level INTEGER NOT NULL,
                    mission_id TEXT, sources TEXT NOT NULL, prompt_sha256 TEXT NOT NULL,
                    traceback_sha256 TEXT, answer TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL
                )""")
                db.execute("""INSERT OR IGNORE INTO conversations
                    (request_id, workspace, created_at, action, mode, level, mission_id,
                     sources, prompt_sha256, traceback_sha256, answer, input_tokens, output_tokens)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    identity, str(request.snapshot.root), datetime.now(timezone.utc).isoformat(),
                    request.action, request.mode, request.level, request.mission_id, sources,
                    hashlib.sha256(request.prompt.encode('utf-8')).hexdigest(),
                    hashlib.sha256(request.traceback.encode('utf-8')).hexdigest() if request.traceback is not None else None,
                    response, answer.usage.input_tokens, answer.usage.output_tokens,
                ))
                db.commit()
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            raise AssistantError(f"Não foi possível salvar o histórico de assistência: {exc}") from exc
        return identity
