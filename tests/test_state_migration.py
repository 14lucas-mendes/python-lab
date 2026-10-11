import json
import os
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from python_lab.models import AppProgress, MissionProgress
from python_lab.progress import ProgressError, ProgressRepository
from python_lab.session import MAX_SESSIONS, SessionLog
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
    assert {item["id"] for item in imported if item["ended_at"] is None} == {"0", "1"}
    retained_closed = [item["id"] for item in imported if item["ended_at"] is not None]
    assert len(retained_closed) == MAX_SESSIONS - 2
    assert retained_closed == [str(index) for index in range(25 - (MAX_SESSIONS - 2), 25)]
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


def _old_sqlite(path, *, reference=False, hints=2, maximum=None):
    """Keep a live WAL connection, so a raw file copy would lose real rows."""
    import sqlite3
    db = sqlite3.connect(path)
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA wal_autocheckpoint=0')
    db.execute('CREATE TABLE progress (id INTEGER PRIMARY KEY, payload TEXT NOT NULL, revision INTEGER NOT NULL)')
    item = {'status': 'started', 'hints_revealed': hints, 'reference_viewed': reference}
    if maximum is not None:
        item['max_assistance_level'] = maximum
    old_evidence = {'skill': 'debugging', 'mission': '001', 'result': 'demonstrated', 'help_level': 1,
                    'tests_passed': True, 'explanation': 'old', 'timestamp': 'old-time'}
    payload = json.dumps({'current_mission_id': '001', 'missions': {'001': item}, 'evidence': [old_evidence]})
    db.execute('INSERT INTO progress VALUES (1,?,7)', (payload,))
    db.commit()
    return db, payload, old_evidence


@pytest.mark.parametrize('reference,hints,maximum,expected', [(True, 1, None, 4), (False, 8, None, 3),
                                                            (False, 2, None, 2), (True, 2, 1, 1)])
def test_versioned_migration_backs_up_live_wal_and_preserves_old_evidence(tmp_path, reference, hints, maximum, expected):
    import sqlite3
    target = tmp_path / 'lab.sqlite3'
    live, raw, evidence = _old_sqlite(target, reference=reference, hints=hints, maximum=maximum)
    try:
        stale = ProgressRepository(target)
        stale._revision = 7
        progress = ProgressRepository(target).load()
        assert progress.missions['001'].max_assistance_level == expected
        assert progress.evidence[0] == {**evidence, 'assistance_level': None, 'origin': 'legacy'}
        with sqlite3.connect(target) as db:
            assert db.execute('PRAGMA user_version').fetchone()[0] == 2
            assert db.execute('SELECT revision FROM progress').fetchone()[0] == 8
        backups = list((tmp_path / 'backups').glob('*.bak'))
        assert len(backups) == 1
        restored = tmp_path / 'restored.sqlite3'
        restored.write_bytes(backups[0].read_bytes())
        with sqlite3.connect(restored) as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert db.execute('SELECT payload,revision FROM progress').fetchone() == (raw, 7)
            assert db.execute('PRAGMA user_version').fetchone()[0] == 0
        with pytest.raises(ProgressError, match='Conflito'):
            stale.save(progress)
        assert ProgressRepository(target).load() == progress
        assert len(list((tmp_path / 'backups').glob('*.bak'))) == 1
    finally:
        live.close()


@pytest.mark.parametrize('failure', ['backup', 'write'])
def test_sqlite_schema_migration_failure_preserves_original_rows_and_version(tmp_path, monkeypatch, failure):
    import sqlite3
    target = tmp_path / 'lab.sqlite3'
    live, raw, _ = _old_sqlite(target)
    try:
        if failure == 'backup':
            def fail(*args):
                raise OSError('backup unavailable')
            monkeypatch.setattr('python_lab.storage.database._backup_database', fail)
        else:
            live.execute("CREATE TRIGGER reject_migration BEFORE UPDATE ON progress BEGIN SELECT RAISE(ABORT, 'migration denied'); END")
            live.commit()
        with pytest.raises(ProgressError, match='backup unavailable|migration denied'):
            ProgressRepository(target).load()
        assert live.execute('SELECT payload,revision FROM progress').fetchone() == (raw, 7)
        assert live.execute('PRAGMA user_version').fetchone()[0] == 0
        assert live.execute("SELECT name FROM sqlite_master WHERE name='assistance_events'").fetchone() is None
        live.execute('CREATE TABLE original_still_usable (value TEXT)')
        live.execute("INSERT INTO original_still_usable VALUES ('ok')")
        live.commit()
        assert live.execute('SELECT value FROM original_still_usable').fetchone()[0] == 'ok'
    finally:
        live.close()


@pytest.mark.parametrize('field,value', [('max_assistance_level', True), ('max_assistance_level', 5),
                                       ('max_assistance_level', -1), ('max_assistance_level', '2'),
                                       ('attempt_id', False), ('attempt_id', '')])
def test_codec_rejects_malformed_assistance_fields(field, value):
    with pytest.raises(ProgressError):
        decode_progress(json.dumps({'missions': {'001': {field: value}}}).encode())


@pytest.mark.parametrize('level', [True, -1, 5, '2', 1.0])
def test_codec_rejects_invalid_nested_evidence_levels(level):
    item = {'skill': 'debugging', 'mission': '001', 'result': 'demonstrated', 'help_level': 1,
            'tests_passed': True, 'explanation': 'old', 'timestamp': 'old-time', 'assistance_level': level}
    with pytest.raises(ProgressError):
        decode_progress(json.dumps({'missions': {'001': {}}, 'evidence': [item]}).encode())


@pytest.mark.parametrize('reference,hints,maximum,expected', [(True, 1, None, 4), (False, 5, None, 3), (False, 2, 0, 0)])
def test_json_import_derives_only_missing_assistance_and_keeps_exact_sources(tmp_path, reference, hints, maximum, expected):
    from datetime import datetime, timezone
    from python_lab.learning_events import AssistanceEvent, AssistanceRecorder
    legacy = tmp_path / 'legacy'
    _legacy(legacy)
    raw = json.loads((legacy / 'progress.json').read_bytes())
    item = raw['missions']['001']
    item.pop('attempt_id', None)
    item.pop('max_assistance_level', None)
    item['reference_viewed'] = reference
    item['hints_revealed'] = hints
    if maximum is not None:
        item['max_assistance_level'] = maximum
    raw['evidence'] = [{'skill': 'debugging', 'mission': '001', 'result': 'demonstrated', 'help_level': 1,
                        'tests_passed': True, 'explanation': 'old', 'timestamp': 'old-time'}]
    (legacy / 'progress.json').write_bytes((json.dumps(raw, indent=2) + '\n').encode())
    original = {name: (legacy / name).read_bytes() for name in ('progress.json', 'sessions.json')}
    target = tmp_path / 'state' / 'lab.sqlite3'
    first = migrate_json_state(legacy, target)
    progress = ProgressRepository(target).load()
    assert progress.missions['001'].max_assistance_level == expected
    assert progress.evidence[0]['assistance_level'] is None
    assert progress.evidence[0]['result'] == 'demonstrated'
    AssistanceRecorder(target).record(AssistanceEvent('001', 'explain', 0, datetime.now(timezone.utc).isoformat(), 'after-import'))
    second = migrate_json_state(legacy, target)
    assert first.imported and not second.imported
    with connection(target) as db:
        assert db.execute('SELECT COUNT(*) FROM assistance_events').fetchone()[0] == 1
    assert all((legacy / name).read_bytes() == value for name, value in original.items())
    assert {path.read_bytes() for path in first.backup_paths} == set(original.values())


def test_schema_backup_restores_live_wal_sessions_and_import_marker(tmp_path):
    import sqlite3
    target = tmp_path / 'lab.sqlite3'
    live, raw, _ = _old_sqlite(target)
    try:
        live.execute('CREATE TABLE sessions (id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT)')
        live.execute('CREATE TABLE events (id INTEGER PRIMARY KEY, session_id TEXT, timestamp TEXT, command TEXT, summary TEXT)')
        live.execute('CREATE TABLE migrations (origin TEXT PRIMARY KEY, digest TEXT)')
        live.execute("INSERT INTO sessions VALUES ('open', 'start', NULL)")
        live.execute("INSERT INTO events VALUES (1, 'open', 'now', '/test', 'passed')")
        live.execute("INSERT INTO migrations VALUES ('legacy-origin', 'exact-digest')")
        live.commit()
        assert target.with_name(target.name + '-wal').stat().st_size > 0
        migrated = ProgressRepository(target).load()
        assert ProgressRepository(target).load().missions['001'].attempt_id == migrated.missions['001'].attempt_id
        assert SessionLog(target).load()[0]['events'][0]['summary'] == 'passed'
        backup = next((tmp_path / 'backups').glob('*.bak'))
        restored = tmp_path / 'restored.sqlite3'
        restored.write_bytes(backup.read_bytes())
        with sqlite3.connect(restored) as db:
            assert db.execute('SELECT payload,revision FROM progress').fetchone() == (raw, 7)
            assert db.execute('SELECT * FROM sessions').fetchall() == [('open', 'start', None)]
            assert db.execute('SELECT * FROM events').fetchall() == [(1, 'open', 'now', '/test', 'passed')]
            assert db.execute('SELECT * FROM migrations').fetchall() == [('legacy-origin', 'exact-digest')]
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    finally:
        live.close()


def test_schema_backup_flush_uses_write_capable_handle_without_truncation(tmp_path, monkeypatch):
    """Windows FlushFileBuffers requires a writable handle; exercise that capability."""
    import sqlite3
    target = tmp_path / 'lab.sqlite3'
    live, raw, _ = _old_sqlite(target)
    original_fsync = os.fsync
    flushed = []

    def flush_write_capable_descriptor(descriptor):
        # A zero-byte OS write checks real descriptor access without changing
        # SQLite bytes. The old read-only handle fails with EBADF on POSIX too.
        os.write(descriptor, b'')
        original_fsync(descriptor)
        flushed.append(descriptor)

    monkeypatch.setattr('python_lab.storage.database.os.fsync', flush_write_capable_descriptor)
    try:
        assert ProgressRepository(target).load().missions['001'].max_assistance_level == 2
        assert len(flushed) == 1
        backup = next((tmp_path / 'backups').glob('*.bak'))
        with sqlite3.connect(backup) as restored:
            assert restored.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert restored.execute('SELECT payload,revision FROM progress').fetchone() == (raw, 7)
            assert restored.execute('PRAGMA user_version').fetchone()[0] == 0
    finally:
        live.close()
