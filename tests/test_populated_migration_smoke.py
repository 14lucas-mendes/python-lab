"""Run the portable populated migration proof through the actual CLI."""

import hashlib
from contextlib import closing
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/legacy-populated'
SCRIPT = ROOT / 'scripts/populated_migration_smoke.py'


def test_populated_legacy_application_data_migrates_twice_via_cli(tmp_path):
    originals = {name: (FIXTURE / name).read_bytes() for name in ('progress.json', 'sessions.json')}
    report = tmp_path / 'migration.json'
    result = subprocess.run([sys.executable, str(SCRIPT), '--metadata', str(report)],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    metadata = json.loads(report.read_text(encoding='utf-8'))
    assert metadata['result'] == 'passed'
    assert metadata['counts'] == {'missions': 1, 'sessions': 2, 'events': 9}
    assert metadata['source_sha'] == 'd7a890458ec072aee7ee6ab17d2d24a621f9de2a'
    assert metadata['input_sha256'] == {name: hashlib.sha256(raw).hexdigest() for name, raw in originals.items()}
    assert all((FIXTURE / name).read_bytes() == raw for name, raw in originals.items())
    assert not (FIXTURE / 'lab.sqlite3').exists()
    assert set(metadata['checks']) == {'full_progress', 'exact_sessions_events', 'backup_bytes',
                                     'sqlite_integrity', 'import_marker', 'idempotent_rows', 'unchanged_inputs'}


def test_populated_proof_rejects_modified_fixture_before_import(tmp_path):
    from shutil import copytree
    source = tmp_path / 'modified'
    copytree(FIXTURE, source)
    # A valid JSON edit must not masquerade as application-generated evidence.
    progress = json.loads((source / 'progress.json').read_text())
    progress['missions']['001']['hints_revealed'] = 0
    (source / 'progress.json').write_text(json.dumps(progress))
    result = subprocess.run([sys.executable, str(SCRIPT), '--source', str(source)],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert 'fixture hash mismatch' in result.stdout + result.stderr
    assert not (source / 'lab.sqlite3').exists()


@pytest.mark.parametrize('damage,diagnostic', [
    ('progress', 'full semantic progress mismatch'),
    ('event', 'exact sessions/events mismatch'),
    ('backup', 'backup bytes mismatch'),
])
def test_proof_detects_semantic_or_byte_loss_after_real_cli_import(monkeypatch, damage, diagnostic):
    import importlib.util
    import sqlite3

    spec = importlib.util.spec_from_file_location('populated_migration_smoke', SCRIPT)
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    run = subprocess.run
    connect = sqlite3.connect
    connections = []

    def track_connection(*args, **kwargs):
        db = connect(*args, **kwargs)
        connections.append(db)
        return db

    def damage_actual_import(command, **kwargs):
        result = run(command, **kwargs)
        if 'migrate' in command and result.returncode == 0:
            state = Path(command[command.index('--data-dir') + 1])
            if damage == 'backup':
                next((state / 'backups').iterdir()).write_bytes(b'lost bytes')
            else:
                with closing(sqlite3.connect(state / 'lab.sqlite3')) as db, db:
                    if damage == 'progress':
                        payload = json.loads(db.execute('SELECT payload FROM progress').fetchone()[0])
                        payload['missions']['001']['max_assistance_level'] = 0
                        db.execute('UPDATE progress SET payload=?', (json.dumps(payload),))
                    else:
                        db.execute("UPDATE events SET summary='lost semantic history' WHERE id=1")
        return result

    monkeypatch.setattr(smoke.subprocess, 'run', damage_actual_import)
    monkeypatch.setattr(smoke.sqlite3, 'connect', track_connection)
    with pytest.raises(AssertionError, match=diagnostic):
        smoke.prove(FIXTURE)
    # SQLite's transaction context commits but does not close. Holding these
    # actual connections makes the Windows temporary-file cleanup contract
    # observable on every platform, rather than relying on garbage collection.
    assert connections
    for db in connections:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            db.execute('SELECT 1')
