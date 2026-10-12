"""Explicit, byte-preserving import of legacy JSON state."""

import hashlib
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from python_lab.progress import encode_progress
from python_lab.session import MAX_EVENTS, _prune
from python_lab.storage.codecs import decode_progress, decode_sessions
from python_lab.storage.database import connection, has_user_state
from python_lab.storage.errors import ProgressError


@dataclass(frozen=True)
class MigrationReport:
    imported: bool
    backup_paths: tuple[Path, ...]


def _backup(path: Path, raw: bytes, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    destination = directory / f"{path.name}.{digest}.bak"
    if destination.exists():
        if destination.read_bytes() != raw:
            raise ProgressError(f"Backup existente divergente: {destination}")
        return destination
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.read_bytes() != raw:
                raise ProgressError(f"Backup existente divergente: {destination}")
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def migrate_json_state(legacy_dir: Path, database_path: Path) -> MigrationReport:
    inputs = {}
    try:
        for name in ("progress.json", "sessions.json"):
            source = legacy_dir / name
            if source.exists():
                inputs[name] = source.read_bytes()
        if not inputs:
            raise ProgressError(f"Nenhum estado JSON legado encontrado em {legacy_dir}")
        progress = decode_progress(inputs["progress.json"]) if "progress.json" in inputs else decode_progress(b"{}")
        sessions = decode_sessions(inputs["sessions.json"]) if "sessions.json" in inputs else ()
        ids = [session["id"] for session in sessions]
        if len(ids) != len(set(ids)):
            raise ProgressError("Histórico de sessão inválido: IDs duplicados")
        origin = str(legacy_dir.resolve())
        digest = hashlib.sha256(b"".join(name.encode() + b"\x00" + raw for name, raw in sorted(inputs.items()))).hexdigest()
        with connection(database_path) as db:
            db.execute("BEGIN IMMEDIATE")
            marker = db.execute("SELECT digest FROM migrations WHERE origin=?", (origin,)).fetchone()
            if marker:
                if marker[0] != digest:
                    raise ProgressError("Origem de migração alterada desde a importação")
                backups = tuple(_backup(legacy_dir / name, raw, database_path.parent / "backups") for name, raw in inputs.items())
                db.commit()
                return MigrationReport(False, backups)
            if has_user_state(db):
                raise ProgressError("Banco já contém estado de usuário; migração recusada")
            backups = tuple(_backup(legacy_dir / name, raw, database_path.parent / "backups") for name, raw in inputs.items())
            row = db.execute("SELECT revision FROM progress WHERE id=1").fetchone()
            payload = encode_progress(progress)
            if row:
                db.execute("UPDATE progress SET payload=?, revision=revision+1 WHERE id=1", (payload,))
            else:
                db.execute("INSERT INTO progress(id,payload,revision) VALUES (1,?,1)", (payload,))
            for session in sessions:
                db.execute("INSERT INTO sessions(id,started_at,ended_at) VALUES (?,?,?)", (session["id"], session["started_at"], session["ended_at"]))
                for event in session["events"]:
                    db.execute("INSERT INTO events(session_id,timestamp,command,summary) VALUES (?,?,?,?)", (session["id"], event["timestamp"], event["command"], event["summary"]))
                db.execute("DELETE FROM events WHERE id IN (SELECT id FROM events WHERE session_id=? ORDER BY id DESC LIMIT -1 OFFSET ?)", (session["id"], MAX_EVENTS))
            _prune(db)
            db.execute("INSERT INTO migrations(origin,digest) VALUES (?,?)", (origin, digest))
            db.commit()
        return MigrationReport(True, backups)
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise ProgressError(f"Não foi possível migrar estado: {exc}") from exc
