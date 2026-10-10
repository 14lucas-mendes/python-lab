import json
import os
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from python_lab.models import AppProgress, MissionProgress
from python_lab.progress import ProgressError, ProgressRepository
from python_lab.session import SessionLog
from python_lab.storage.migration import migrate_json_state
from python_lab.storage.migration import _backup
from python_lab.cli import build_app, main
from python_lab.storage.codecs import decode_progress
from python_lab.storage.database import connection


def _legacy(directory):
    directory.mkdir()
    progress = {"current_mission_id": "001", "missions": {"001": asdict(MissionProgress(status="started"))}, "evidence": []}
    sessions = {"sessions": [{"id": "one", "started_at": "2026-01-01T00:00:00+00:00", "ended_at": None, "events": [{"timestamp": "2026-01-01T00:00:01+00:00", "command": "/status", "summary": "ok"}]}]}
    (directory / "progress.json").write_bytes(json.dumps(progress).encode())
    (directory / "sessions.json").write_bytes(json.dumps(sessions).encode())


def test_migration_is_idempotent(tmp_path):
    legacy = tmp_path / "legacy"
    _legacy(legacy)
    originals = {name: (legacy / name).read_bytes() for name in ("progress.json", "sessions.json")}
    target = tmp_path / "state" / "lab.sqlite3"
    first = migrate_json_state(legacy, target)
    second = migrate_json_state(legacy, target)
    assert first.imported is True and second.imported is False
    assert len(first.backup_paths) == 2
    assert {path.read_bytes() for path in first.backup_paths} == set(originals.values())
    assert all((legacy / name).read_bytes() == value for name, value in originals.items())
    assert ProgressRepository(target).load().current_mission_id == "001"
    assert ProgressRepository(target).load() == decode_progress(originals["progress.json"])
    assert SessionLog(target).load()[0]["events"][0]["summary"] == "ok"


def test_bad_migration_rolls_back(tmp_path):
    legacy = tmp_path / "legacy"
    _legacy(legacy)
    (legacy / "sessions.json").write_bytes(b"{broken")
    target = tmp_path / "state" / "lab.sqlite3"
    repo = ProgressRepository(target)
    repo.save(AppProgress())
    before = repo.load()
    originals = [(legacy / name).read_bytes() for name in ("progress.json", "sessions.json")]
    with pytest.raises(Exception, match="inválido"):
        migrate_json_state(legacy, target)
    assert ProgressRepository(target).load() == before
    assert SessionLog(target).load() == []
    assert [(legacy / name).read_bytes() for name in ("progress.json", "sessions.json")] == originals


def test_migration_rejects_existing_user_state(tmp_path):
    legacy = tmp_path / "legacy"
    _legacy(legacy)
    target = tmp_path / "state" / "lab.sqlite3"
    repo = ProgressRepository(target)
    repo.save(AppProgress(missions={"002": MissionProgress(status="started")}, current_mission_id="002"))
    with pytest.raises(ProgressError, match="(?i)estado|progresso"):
        migrate_json_state(legacy, target)
    assert ProgressRepository(target).load().current_mission_id == "002"


def test_first_open_points_to_migration_without_creating_state(tmp_path):
    from shutil import copytree
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    catalog = tmp_path / "catalog"
    copytree(root / "data", catalog / "data")
    copytree(root / "missions", catalog / "missions")
    (catalog / "data" / "progress.json").write_text(json.dumps({"current_mission_id": "001", "missions": {"001": asdict(MissionProgress(status="started"))}, "evidence": []}))
    state = tmp_path / "state"
    with pytest.raises(ProgressError, match="lab migrate --from-dir"):
        build_app(catalog, data_dir=state)
    assert not (state / "lab.sqlite3").exists()


def test_real_history_blocks_open_even_after_empty_seed(tmp_path):
    from shutil import copytree
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    catalog = tmp_path / "catalog"
    copytree(root / "data", catalog / "data")
    copytree(root / "missions", catalog / "missions")
    (catalog / "data" / "sessions.json").write_text(json.dumps({"sessions": [{"id": "s", "started_at": "t", "ended_at": None, "events": []}]}))
    state = tmp_path / "state"
    repo = ProgressRepository(state / "lab.sqlite3")
    repo.save(AppProgress())
    with pytest.raises(ProgressError, match="lab migrate --from-dir"):
        build_app(catalog, data_dir=state)


def test_cli_migrate_imports_explicit_directory(tmp_path):
    legacy = tmp_path / "legacy"
    _legacy(legacy)
    target = tmp_path / "state"
    assert main(["migrate", "--from-dir", str(legacy), "--data-dir", str(target)]) == 0
    assert ProgressRepository(target / "lab.sqlite3").load().current_mission_id == "001"


def test_backup_failure_keeps_empty_seed_and_sources(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    _legacy(legacy)
    target = tmp_path / "state" / "lab.sqlite3"
    repo = ProgressRepository(target)
    repo.save(AppProgress())
    originals = {name: (legacy / name).read_bytes() for name in ("progress.json", "sessions.json")}

    def fail_backup(*args):
        raise OSError("backup denied")

    monkeypatch.setattr("python_lab.storage.migration._backup", fail_backup)
    with pytest.raises(ProgressError, match="backup denied"):
        migrate_json_state(legacy, target)
    assert ProgressRepository(target).load() == AppProgress()
    assert SessionLog(target).load() == []
    assert all((legacy / name).read_bytes() == value for name, value in originals.items())


def test_import_write_failure_rolls_back_progress_sessions_and_marker(tmp_path):
    legacy = tmp_path / "legacy"
    _legacy(legacy)
    originals = {name: (legacy / name).read_bytes() for name in ("progress.json", "sessions.json")}
    target = tmp_path / "state" / "lab.sqlite3"
    repo = ProgressRepository(target)
    repo.save(AppProgress())
    with connection(target) as db:
        db.execute("CREATE TRIGGER reject_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'write blocked'); END")
        db.commit()
    with pytest.raises(ProgressError, match="write blocked"):
        migrate_json_state(legacy, target)
    assert ProgressRepository(target).load() == AppProgress()
    assert SessionLog(target).load() == []
    with connection(target) as db:
        assert db.execute("SELECT COUNT(*) FROM migrations").fetchone()[0] == 0
    assert all((legacy / name).read_bytes() == value for name, value in originals.items())


def test_active_mission_missing_from_catalog_is_reported(tmp_path):
    from shutil import copytree
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    catalog = tmp_path / "catalog"
    copytree(root / "data", catalog / "data")
    copytree(root / "missions", catalog / "missions")
    state = tmp_path / "state"
    repo = ProgressRepository(state / "lab.sqlite3")
    repo.save(AppProgress(current_mission_id="removed", missions={"removed": MissionProgress(status="started")}))
    with pytest.raises(ProgressError, match="Missão ativa removed"):
        build_app(catalog, data_dir=state)


def test_migration_applies_retention_without_dropping_open_sessions(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    sessions = []
    for index in range(25):
        sessions.append({"id": str(index), "started_at": f"{index:02}",
                         "ended_at": None if index < 2 else "closed",
                         "events": [{"timestamp": str(n), "command": "/status", "summary": str(n)} for n in range(202)] if index == 0 else []})
    (legacy / "sessions.json").write_text(json.dumps({"sessions": sessions}))
    target = tmp_path / "state" / "lab.sqlite3"
    migrate_json_state(legacy, target)
    imported = SessionLog(target).load()
    assert sum(item["ended_at"] is None for item in imported) == 2
    assert sum(item["ended_at"] is not None for item in imported) == 20
    assert len(next(item for item in imported if item["id"] == "0")["events"]) == 200


def test_build_app_refuses_json_at_database_path_as_domain_error(tmp_path):
    from shutil import copytree
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    catalog = tmp_path / "catalog"
    copytree(root / "data", catalog / "data")
    copytree(root / "missions", catalog / "missions")
    state = tmp_path / "state"
    state.mkdir()
    target = state / "lab.sqlite3"
    original = (catalog / "data" / "progress.json").read_bytes()
    target.write_bytes(original)
    with pytest.raises(ProgressError, match="SQLite"):
        build_app(catalog, data_dir=state)
    assert target.read_bytes() == original


def test_backup_exclusive_publish_collision_preserves_complete_winner(tmp_path, monkeypatch):
    source = tmp_path / "progress.json"
    raw = b'{"missions": {}}\n'
    source.write_bytes(raw)
    backups = tmp_path / "backups"
    publishing = Barrier(2)
    original_link = os.link
    attempts = []

    def collide_at_publish(source_path, destination_path):
        attempts.append(destination_path)
        publishing.wait(timeout=5)
        return original_link(source_path, destination_path)

    monkeypatch.setattr("python_lab.storage.migration.os.link", collide_at_publish)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_backup, source, raw, backups) for _ in range(2)]
        paths = [future.result(timeout=10) for future in futures]

    assert len(attempts) == 2
    assert paths[0] == paths[1]
    assert paths[0].read_bytes() == raw
    assert source.read_bytes() == raw


def test_separate_databases_share_complete_backups(tmp_path, monkeypatch):
    legacy = tmp_path / "legacy"
    _legacy(legacy)
    state = tmp_path / "state"
    publishing = Barrier(2)
    original_link = os.link

    def collide_at_publish(source_path, destination_path):
        publishing.wait(timeout=5)
        return original_link(source_path, destination_path)

    monkeypatch.setattr("python_lab.storage.migration.os.link", collide_at_publish)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(migrate_json_state, legacy, state / database_name)
            for database_name in ("one.sqlite3", "two.sqlite3")
        ]
        reports = [future.result(timeout=10) for future in futures]

    assert all(report.imported for report in reports)
    assert reports[0].backup_paths == reports[1].backup_paths
    for report in reports:
        assert {path.read_bytes() for path in report.backup_paths} == {
            (legacy / "progress.json").read_bytes(), (legacy / "sessions.json").read_bytes()
        }
    assert ProgressRepository(state / "one.sqlite3").load().current_mission_id == "001"
    assert ProgressRepository(state / "two.sqlite3").load().current_mission_id == "001"
