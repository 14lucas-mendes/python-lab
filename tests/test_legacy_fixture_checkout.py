"""Native Windows checkout must preserve application-generated fixture bytes."""

from pathlib import Path
from shutil import copytree, copyfile
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path('tests/fixtures/legacy-populated')


def test_autocrlf_checkout_preserves_legacy_fixture_provenance(tmp_path):
    source, checkout = tmp_path / 'source', tmp_path / 'windows-checkout'
    copytree(ROOT / FIXTURE, source / FIXTURE)
    if (ROOT / '.gitattributes').exists():
        copyfile(ROOT / '.gitattributes', source / '.gitattributes')

    def git(*args, cwd=source):
        result = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr

    git('init')
    git('-c', 'core.autocrlf=false', 'add', '.')
    git('-c', 'user.name=Fixture proof', '-c', 'user.email=fixture@example.invalid',
        'commit', '-m', 'Controlled legacy application fixture')
    git('-c', 'core.autocrlf=true', 'clone', '--no-local', str(source), str(checkout), cwd=tmp_path)
    for name in ('progress.json', 'sessions.json', 'provenance.json'):
        assert (checkout / FIXTURE / name).read_bytes() == (ROOT / FIXTURE / name).read_bytes(), (
            f'Windows autocrlf checkout changed {name}; provenance requires exact application bytes'
        )
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/populated_migration_smoke.py'),
                             '--source', str(checkout / FIXTURE)], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
