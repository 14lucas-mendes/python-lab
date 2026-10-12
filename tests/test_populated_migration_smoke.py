"""Run the portable populated migration proof through the actual CLI."""

import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/legacy-populated'
SCRIPT = ROOT / 'scripts/populated_migration_smoke.py'
OPTIMIZATION_MODES = [
    pytest.param(('-O',), None, id='flag-O'),
    pytest.param(('-OO',), None, id='flag-OO'),
    pytest.param((), '1', id='environment-1'),
    pytest.param((), '2', id='environment-2'),
]


def proof_process(arguments, flags=(), optimization=None):
    child_env = dict(os.environ)
    child_env.pop('PYTHONOPTIMIZE', None)
    if optimization is not None:
        child_env['PYTHONOPTIMIZE'] = optimization
    return subprocess.run([sys.executable, *flags, *arguments], cwd=ROOT, env=child_env,
                          capture_output=True, text=True, encoding='utf-8', timeout=30)


@pytest.mark.parametrize('flags,optimization', [pytest.param((), None, id='normal'), *OPTIMIZATION_MODES])
@pytest.mark.parametrize('installed', [False, True], ids=['current-cli', 'installed-cli'])
def test_populated_legacy_application_data_migrates_twice_via_cli(tmp_path, flags, optimization, installed):
    originals = {name: (FIXTURE / name).read_bytes() for name in ('progress.json', 'sessions.json')}
    report = tmp_path / 'migration.json'
    arguments = [str(SCRIPT), '--metadata', str(report)]
    if installed:
        cli = Path(sys.executable).with_name('lab.exe' if sys.platform == 'win32' else 'lab')
        assert cli.is_file(), 'test environment must install the actual lab entry point'
        arguments += ['--cli', str(cli)]
    result = proof_process(arguments, flags, optimization)
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


@pytest.mark.parametrize('flags,optimization', [pytest.param((), None, id='normal'), *OPTIMIZATION_MODES])
def test_populated_proof_rejects_modified_fixture_before_import(tmp_path, flags, optimization):
    from shutil import copytree
    source = tmp_path / 'modified'
    copytree(FIXTURE, source)
    # A valid JSON edit must not masquerade as application-generated evidence.
    progress = json.loads((source / 'progress.json').read_text())
    progress['missions']['001']['hints_revealed'] = 0
    (source / 'progress.json').write_text(json.dumps(progress))
    report = tmp_path / 'migration.json'
    result = proof_process([str(SCRIPT), '--source', str(source), '--metadata', str(report)], flags, optimization)
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stderr.strip() == 'Migration proof failed: fixture hash mismatch'
    assert not result.stdout
    assert not report.exists()
    assert not (source / 'lab.sqlite3').exists()


@pytest.mark.parametrize('flags,optimization', OPTIMIZATION_MODES)
@pytest.mark.parametrize('damage,diagnostic', [
    ('progress', 'full semantic progress mismatch'),
    ('event', 'exact sessions/events mismatch'),
    ('backup', 'backup bytes mismatch'),
])
def test_optimized_proof_detects_loss_after_real_cli_import(flags, optimization, damage, diagnostic):
    # The oracle itself is imported by an optimized interpreter. Only after
    # the real CLI succeeds do we damage actual temporary SQLite/backup bytes.
    harness = '''
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

script, source, damage = sys.argv[1:]
spec = importlib.util.spec_from_file_location('populated_migration_smoke', script)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)
run = subprocess.run

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

smoke.subprocess.run = damage_actual_import
try:
    metadata = smoke.prove(Path(source))
except RuntimeError as exc:
    print(str(exc), file=sys.stderr)
    raise SystemExit(1)
print(json.dumps(metadata))
'''
    result = proof_process(['-c', harness, str(SCRIPT), str(FIXTURE), damage], flags, optimization)
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stderr.strip() == diagnostic
    assert not result.stdout


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
    with pytest.raises(smoke.MigrationProofError, match=diagnostic):
        smoke.prove(FIXTURE)
    # SQLite's transaction context commits but does not close. Holding these
    # actual connections makes the Windows temporary-file cleanup contract
    # observable on every platform, rather than relying on garbage collection.
    assert connections
    for db in connections:
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            db.execute('SELECT 1')
