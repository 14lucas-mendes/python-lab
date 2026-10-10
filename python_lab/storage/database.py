"""SQLite connection and schema for learner state."""

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


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
        db.execute("CREATE TABLE IF NOT EXISTS progress (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL, revision INTEGER NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT)")
        db.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, timestamp TEXT NOT NULL, command TEXT NOT NULL, summary TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS migrations (origin TEXT PRIMARY KEY, digest TEXT NOT NULL)")
        db.commit()
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
