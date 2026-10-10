"""SQLite connection and schema for learner state."""

import sqlite3
import os
import tempfile
import time
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Iterator


SCHEMA_VERSION = 2


def _backup_database(path: Path, version: int) -> Path:
    """Copy committed WAL state using SQLite, while the caller excludes writers."""
    directory = path.parent / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.schema-{version}.", dir=directory)
    os.close(descriptor)
    temporary = Path(temporary_name)
    destination = directory / (temporary.name[1:] + ".bak")
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as source:
            with closing(sqlite3.connect(temporary)) as backup:
                source.backup(backup)
                if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Backup SQLite inválido")
        with temporary.open("rb") as output:
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        return destination
    finally:
        temporary.unlink(missing_ok=True)


def _initialize(db: sqlite3.Connection, path: Path) -> None:
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if version > SCHEMA_VERSION:
        raise ValueError(f"Versão SQLite não suportada: {version}")
    db.execute("BEGIN IMMEDIATE")
    try:
        # Another opener may already have migrated while this one waited.
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            db.commit()
            return
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        row = db.execute("SELECT payload FROM progress WHERE id=1").fetchone() if "progress" in tables else None
        payload = None
        if row:
            from python_lab.progress import encode_progress
            from python_lab.storage.codecs import decode_progress

            payload = encode_progress(decode_progress(row[0].encode("utf-8")))
        # Do not run backup() on this write-transaction connection: use a
        # separate reader while BEGIN IMMEDIATE protects the captured state.
        if tables:
            _backup_database(path, version)
        db.execute("CREATE TABLE IF NOT EXISTS progress (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL, revision INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, timestamp TEXT NOT NULL, command TEXT NOT NULL, summary TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS migrations (origin TEXT PRIMARY KEY, digest TEXT NOT NULL)")
        db.execute("CREATE TABLE assistance_events (request_id TEXT PRIMARY KEY, mission_id TEXT, action TEXT NOT NULL, level INTEGER NOT NULL CHECK(level BETWEEN 0 AND 4), timestamp TEXT NOT NULL, attempt_id TEXT)")
        if payload is not None:
            db.execute("UPDATE progress SET payload=?, revision=revision+1 WHERE id=1", (payload,))
        db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        db.commit()
    except Exception:
        db.rollback()
        raise


def _check_header(path: Path) -> None:
    if path.exists() and path.stat().st_size:
        with path.open("rb") as source:
            if source.read(16) != b"SQLite format 3\x00":
                raise ValueError(f"Arquivo inválido: não é banco SQLite: {path}. Use lab migrate --from-dir DIR --data-dir DIR")


@contextmanager
def connection(path: Path) -> Iterator[sqlite3.Connection]:
    _check_header(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    try:
        db.execute("PRAGMA busy_timeout=5000")
        db.execute("PRAGMA foreign_keys=ON")
        for attempt in range(5):
            try:
                if db.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                    db.execute("PRAGMA journal_mode=WAL")
                break
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 4:
                    raise
                time.sleep(0.1 * (attempt + 1))
        _initialize(db, path)
        yield db
    finally:
        db.close()


def has_user_state(db: sqlite3.Connection) -> bool:
    row = db.execute("SELECT payload FROM progress WHERE id=1").fetchone()
    if row:
        from python_lab.storage.codecs import decode_progress

        progress = decode_progress(row[0].encode("utf-8"))
        if progress.current_mission_id is not None or progress.missions or progress.evidence:
            return True
    return db.execute("SELECT 1 FROM sessions LIMIT 1").fetchone() is not None
