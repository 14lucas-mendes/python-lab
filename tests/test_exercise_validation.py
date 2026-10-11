"""Real temporary suites enforce execution review and fresh publication."""
from dataclasses import replace
import json
import threading

import pytest

from python_lab.assistant import AssistantError
from python_lab.runtime.processes import ProcessRunner
from tests.test_exercise_drafts import ROOT, sample_draft, service


def installed_bytes():
    return {str(p.relative_to(ROOT)): p.read_bytes() for p in (ROOT / 'missions').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}


def test_confirmation_and_approval_precede_even_path_reads(tmp_path, monkeypatch):
    sample_draft()
    monkeypatch.setattr(ProcessRunner, 'run', lambda *a, **kw: pytest.fail('executed without confirmation'))
    svc = service(tmp_path)
    with pytest.raises(AssistantError, match='confirma'):
        svc.validate(tmp_path / 'missing', execution_confirmed=False)
    with pytest.raises(AssistantError, match='aprova'):
        svc.publish(tmp_path / 'missing', ROOT, approved=False)


def test_real_contract_and_publish_preserve_installed_and_previous_custom(tmp_path):
    svc = service(tmp_path)
    before = installed_bytes()
    for id in ['custom-sum', 'custom-next']:
        path = svc.save_draft(sample_draft(id))
        result = svc.validate(path, execution_confirmed=True)
        assert result.passed and result.fingerprint
        published = svc.publish(path, ROOT, approved=True)
        assert published == tmp_path / 'state' / 'custom_catalog' / id
        assert (published / 'mission.json').exists()
    assert installed_bytes() == before
    from python_lab.catalog import compose_missions
    assert len(compose_missions(ROOT, tmp_path / 'state' / 'custom_catalog')) == 13


@pytest.mark.parametrize('file', ['draft.json', 'mission.json', 'README.md', 'starter.py', 'reference_solution.py', 'tests/test_exercise.py', 'criteria.json', 'hints.json', 'tests/conftest.py'])
def test_every_draft_file_is_hash_bound(tmp_path, file):
    svc = service(tmp_path)
    path = svc.save_draft(sample_draft())
    assert svc.validate(path, execution_confirmed=True).passed
    target = path / file
    target.write_bytes(target.read_bytes() + b'\n')
    with pytest.raises(AssistantError, match='mudou|valid'):
        svc.publish(path, ROOT, approved=True)
    assert not (tmp_path / 'state' / 'custom_catalog' / 'custom-sum').exists()


@pytest.mark.parametrize('tests,starter', [
    ('', 'def total(values): return None'),
    ('def test_nothing():\n    pass\n', 'def total(values): return None'),
    ('import pytest\n@pytest.mark.skip\ndef test_skip(): pass\n', 'def total(values): return None'),
    ('def test_total(solution):\n    assert solution.total([1]) == 1\n', 'def total(: pass'),
    ('def test_total(solution):\n    assert solution.total([1]) == 1\n', 'import missing_dependency'),
    ('def test_total(solution):\n    assert solution.total([1]) == 1\n', 'def total(values):\n    raise RuntimeError("infra")\n'),
])
def test_vacuous_skipped_or_infrastructure_are_not_contract_failure(tmp_path, tests, starter):
    svc = service(tmp_path)
    draft = replace(sample_draft(), tests=tests or '# empty suite\n', starter=starter)
    path = svc.save_draft(draft)
    assert not svc.validate(path, execution_confirmed=True).passed
    assert path.exists()
    with pytest.raises(AssistantError):
        svc.publish(path, ROOT, approved=True)


def test_publication_rechecks_collisions_and_complete_custom_graph(tmp_path):
    svc = service(tmp_path)
    first = svc.save_draft(sample_draft('custom-first'))
    assert svc.validate(first, execution_confirmed=True).passed
    installed = svc.publish(first, ROOT, approved=True)
    second = svc.save_draft(sample_draft('custom-second'))
    assert svc.validate(second, execution_confirmed=True).passed
    mission = json.loads((installed / 'mission.json').read_text())
    mission['prerequisites'] = ['custom-first']
    (installed / 'mission.json').write_text(json.dumps(mission))
    with pytest.raises(AssistantError):
        svc.publish(second, ROOT, approved=True)
    assert not (installed.parent / 'custom-second').exists()


def test_temp_allocation_never_probes_draft_with_hostile_tmpdir(tmp_path, monkeypatch):
    svc = service(tmp_path)
    path = svc.save_draft(sample_draft())
    before = {p.relative_to(path): p.read_bytes() for p in path.rglob('*') if p.is_file()}
    monkeypatch.setenv('TMPDIR', str(path))
    assert svc.validate(path, execution_confirmed=True).passed
    assert {p.relative_to(path): p.read_bytes() for p in path.rglob('*') if p.is_file()} == before


def test_cancelled_real_process_never_validates_or_publishes(tmp_path):
    import time
    svc = service(tmp_path)
    draft = replace(sample_draft(), reference='import time\ntime.sleep(60)\ndef total(values): return sum(values)\n')
    path = svc.save_draft(draft)
    event = threading.Event()
    timer = threading.Timer(.3, event.set)
    timer.start()
    start = time.monotonic()
    try:
        result = svc.validate(path, execution_confirmed=True, cancel=event)
    finally:
        timer.cancel()
    assert result.cancelled and not result.passed
    assert time.monotonic() - start < 10
    with pytest.raises(AssistantError):
        svc.publish(path, ROOT, approved=True)


def test_reference_must_pass_before_starter_can_authorize_publication(tmp_path):
    svc = service(tmp_path)
    path = svc.save_draft(replace(sample_draft(), reference='def total(values): return 99\n'))
    result = svc.validate(path, execution_confirmed=True)
    assert not result.passed
    with pytest.raises(AssistantError):
        svc.publish(path, ROOT, approved=True)


def test_fixture_assertion_is_setup_failure_not_starter_contract(tmp_path):
    svc = service(tmp_path)
    tests = ('import pytest\n@pytest.fixture\ndef broken(solution):\n'
             '    assert solution.total([1]) == 1\n'
             'def test_value(broken):\n    assert True\n')
    path = svc.save_draft(replace(sample_draft(), tests=tests))
    assert not svc.validate(path, execution_confirmed=True).passed


def test_timeout_cannot_validate(tmp_path):
    class ShortRunner(ProcessRunner):
        def run(self, argv, cwd, **kwargs):
            kwargs['timeout'] = .2
            return super().run(argv, cwd, **kwargs)
    svc = service(tmp_path, ShortRunner())
    path = svc.save_draft(replace(sample_draft(), reference='import time\ntime.sleep(60)\n'))
    assert not svc.validate(path, execution_confirmed=True).passed
    with pytest.raises(AssistantError):
        svc.publish(path, ROOT, approved=True)


def test_draft_symlinks_and_extra_material_are_rejected(tmp_path):
    svc = service(tmp_path)
    path = svc.save_draft(sample_draft())
    outside = tmp_path / 'outside'
    outside.write_text('secret')
    (path / 'starter.py').unlink()
    (path / 'starter.py').symlink_to(outside)
    with pytest.raises(AssistantError):
        svc.validate(path, execution_confirmed=True)
    assert outside.read_text() == 'secret'


def test_installed_collision_is_rejected_without_mutation(tmp_path):
    svc = service(tmp_path)
    before = installed_bytes()
    with pytest.raises(AssistantError):
        svc.save_draft(sample_draft('001'))
    assert before == installed_bytes()


def test_real_cancel_waits_for_spawned_descendant_cleanup(tmp_path):
    import concurrent.futures
    import sys
    import time
    from pathlib import Path
    if not sys.platform.startswith('linux'):
        pytest.skip('Linux /proc descendant evidence; Windows Job readiness is separate')
    marker = tmp_path / 'pids.json'
    reference = ('import json, os, subprocess, sys, time\nfrom pathlib import Path\n'
        'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
        f'Path({str(marker)!r}).write_text(json.dumps([os.getpid(), child.pid]))\n'
        'time.sleep(60)\ndef total(values): return sum(values)\n')
    svc = service(tmp_path)
    path = svc.save_draft(replace(sample_draft(), reference=reference))
    event = threading.Event()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        worker = pool.submit(svc.validate, path, execution_confirmed=True, cancel=event)
        deadline = time.monotonic() + 10
        try:
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            assert marker.exists(), 'reference did not actually spawn child'
            pids = json.loads(marker.read_text())
            assert all(Path(f'/proc/{pid}').exists() for pid in pids)
        finally:
            event.set()
        result = worker.result(timeout=10)
    assert result.cancelled and not result.passed
    for pid in pids:
        stat = Path(f'/proc/{pid}/stat')
        assert not stat.exists() or stat.read_text().rsplit(') ', 1)[1].split()[0] in {'Z', 'X'}
    with pytest.raises(AssistantError):
        svc.publish(path, ROOT, approved=True)


def test_cleanup_uncertainty_propagates_without_publication_success(tmp_path):
    from python_lab.runtime.processes import ProcessCleanupError
    class BrokenCleanup(ProcessRunner):
        def run(self, *args, **kwargs):
            raise ProcessCleanupError('termination not confirmed')
    svc = service(tmp_path, BrokenCleanup())
    path = svc.save_draft(sample_draft())
    with pytest.raises(ProcessCleanupError):
        svc.validate(path, execution_confirmed=True)
    with pytest.raises(AssistantError):
        svc.publish(path, ROOT, approved=True)


def test_two_publishers_cannot_overwrite_a_published_exercise(tmp_path):
    import concurrent.futures
    first, second = service(tmp_path), service(tmp_path)
    path = first.save_draft(sample_draft())
    assert first.validate(path, execution_confirmed=True).passed
    def publish(svc):
        try:
            return svc.publish(path, ROOT, approved=True)
        except AssistantError:
            return None
    with concurrent.futures.ThreadPoolExecutor() as pool:
        results = list(pool.map(publish, [first, second]))
    assert sum(result is not None for result in results) == 1
    published = next(result for result in results if result is not None)
    assert (published / 'reference_solution.py').read_text() == sample_draft().reference


def test_invalid_existing_custom_path_blocks_new_publication(tmp_path):
    svc = service(tmp_path)
    path = svc.save_draft(sample_draft('custom-first'))
    assert svc.validate(path, execution_confirmed=True).passed
    published = svc.publish(path, ROOT, approved=True)
    next_path = svc.save_draft(sample_draft('custom-next'))
    assert svc.validate(next_path, execution_confirmed=True).passed
    metadata = json.loads((published / 'mission.json').read_text())
    metadata['solution'] = '../escape.py'
    (published / 'mission.json').write_text(json.dumps(metadata))
    with pytest.raises(AssistantError):
        svc.publish(next_path, ROOT, approved=True)
    assert not (published.parent / 'custom-next').exists()


def test_added_file_and_unvalidated_draft_cannot_publish(tmp_path):
    svc = service(tmp_path)
    path = svc.save_draft(sample_draft())
    with pytest.raises(AssistantError):
        svc.publish(path, ROOT, approved=True)
    assert svc.validate(path, execution_confirmed=True).passed
    (path / 'extra.py').write_text('print("unexpected")')
    with pytest.raises(AssistantError):
        svc.publish(path, ROOT, approved=True)
