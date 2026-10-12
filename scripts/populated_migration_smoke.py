"""Prove actual CLI migration on temporary byte copies; emit metadata only.

The default source is a controlled snapshot written by the legacy application.
--source also permits a manual preserved-profile check without publishing data.
"""

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tests/fixtures/legacy-populated'


def hashes(inputs):
    return {name: hashlib.sha256(raw).hexdigest() for name, raw in inputs.items()}


def expected_progress(raw):
    # Compare every legacy field, adding only the documented migration inferences.
    result = json.loads(raw)
    for mission_id, mission in result['missions'].items():
        mission.setdefault('max_assistance_level', 4 if mission['reference_viewed'] else min(mission['hints_revealed'], 3))
        mission.setdefault('attempt_id', 'legacy:' + mission_id)
    for evidence in result['evidence']:
        evidence.setdefault('assistance_level', None)
        evidence.setdefault('origin', 'legacy')
    return result


def snapshot(database):
    with closing(sqlite3.connect(f'{database.resolve().as_uri()}?mode=ro', uri=True)) as db:
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',), 'SQLite integrity failed'
        assert db.execute('PRAGMA foreign_key_check').fetchall() == [], 'SQLite foreign keys failed'
        tables = ('progress', 'sessions', 'events', 'migrations', 'assistance_events')
        rows = {table: db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall() for table in tables}
        progress = json.loads(rows['progress'][0][1])
        sessions = []
        for session_id, started, ended in db.execute('SELECT id,started_at,ended_at FROM sessions ORDER BY started_at,rowid'):
            events = [dict(timestamp=t, command=c, summary=s) for t, c, s in db.execute(
                'SELECT timestamp,command,summary FROM events WHERE session_id=? ORDER BY id', (session_id,))]
            sessions.append(dict(id=session_id, started_at=started, ended_at=ended, events=events))
        return progress, sessions, rows


def prove(source, *, allow_empty_progress=False, cli=None):
    inputs = {name: (source / name).read_bytes() for name in ('progress.json', 'sessions.json')}
    input_hashes = hashes(inputs)
    provenance_path = source / 'provenance.json'
    provenance = json.loads(provenance_path.read_text(encoding='utf-8')) if provenance_path.exists() else {}
    if provenance:
        assert provenance['sha256'] == input_hashes, 'fixture hash mismatch'
    expected = expected_progress(inputs['progress.json'])
    expected_sessions = json.loads(inputs['sessions.json'])['sessions']
    counts = dict(missions=len(expected['missions']), sessions=len(expected_sessions),
                  events=sum(len(s['events']) for s in expected_sessions))
    assert counts['missions'] or allow_empty_progress, 'populated progress required'
    assert counts['sessions'] >= 2 and counts['events'] > 0, 'populated session history required'
    command = [str(cli)] if cli else [sys.executable, str(ROOT / 'lab.py')]
    # Redirected Windows stdout can otherwise use a different code page from
    # the parent decoder. Override only this subprocess's stream encoding.
    child_env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    with TemporaryDirectory(prefix='python-lab-migration-proof-') as temporary:
        root = Path(temporary)
        copies, state = root / 'legacy', root / 'state'
        copies.mkdir()
        for name, raw in inputs.items():
            (copies / name).write_bytes(raw)
        digest = hashlib.sha256(b''.join(name.encode() + b'\0' + raw for name, raw in sorted(inputs.items()))).hexdigest()
        before = None
        for index in range(2):
            result = subprocess.run([*command, 'migrate', '--from-dir', str(copies), '--data-dir', str(state)],
                                    cwd=ROOT, env=child_env, capture_output=True, text=True, encoding='utf-8', timeout=30)
            assert result.returncode == 0, f'CLI migration {index + 1} failed (exit {result.returncode})'
            expected_message = 'Estado importado.' if index == 0 else 'Estado já importado.'
            assert expected_message in result.stdout, f'CLI migration {index + 1} result missing'
            progress, sessions, rows = snapshot(state / 'lab.sqlite3')
            assert progress == expected, 'full semantic progress mismatch'
            assert sessions == expected_sessions, 'exact sessions/events mismatch'
            assert rows['migrations'] == [(str(copies.resolve()), digest)], 'import marker mismatch'
            assert not rows['assistance_events'], 'migration invented assistance events'
            if before is not None:
                assert rows == before, 'second CLI migration changed rows or revision'
            before = rows
            for name, raw in inputs.items():
                backup = state / 'backups' / f'{name}.{input_hashes[name]}.bak'
                assert backup.read_bytes() == raw, 'backup bytes mismatch'
                assert (copies / name).read_bytes() == raw, 'temporary input changed'
        assert len(list((state / 'backups').iterdir())) == len(inputs), 'duplicate backups'
    assert {name: (source / name).read_bytes() for name in inputs} == inputs, 'original input changed'
    return {'result': 'passed', 'source_sha': provenance.get('source_sha'), 'counts': counts,
            'input_sha256': input_hashes,
            'checks': ['full_progress', 'exact_sessions_events', 'backup_bytes', 'sqlite_integrity',
                       'import_marker', 'idempotent_rows', 'unchanged_inputs']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=FIXTURE)
    parser.add_argument('--metadata', type=Path)
    parser.add_argument('--cli', type=Path, help='Installed lab executable; default: current lab.py')
    parser.add_argument('--allow-empty-progress', action='store_true', help='Manual preserved-profile proof only')
    args = parser.parse_args()
    try:
        metadata = prove(args.source, allow_empty_progress=args.allow_empty_progress, cli=args.cli)
    except (AssertionError, OSError, ValueError, subprocess.SubprocessError, sqlite3.Error) as exc:
        # No source contents, credentials, environment, or state directory output.
        print(f'Migration proof failed: {exc}', file=sys.stderr)
        return 1
    output = json.dumps(metadata, indent=2) + '\n'
    if args.metadata:
        args.metadata.write_text(output, encoding='utf-8')
    print(output, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
