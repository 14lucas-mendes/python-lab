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


def test_complete_starter_cannot_validate_via_reference_rewriting_copy(tmp_path):
    svc = service(tmp_path)
    draft = sample_draft()
    reference = ('from pathlib import Path\n'
                 'Path(__file__).with_name("starter.py").write_text("def total(values): return None\\n")\n'
                 'def total(values): return sum(values)\n')
    path = svc.save_draft(replace(draft, starter=draft.reference, reference=reference))
    result = svc.validate(path, execution_confirmed=True)
    assert not result.passed, 'a rewritten temporary starter is not the reviewed starter'
    assert (path / 'starter.py').read_text() == draft.reference
    with pytest.raises(AssistantError):
        svc.publish(path, ROOT, approved=True)


@pytest.mark.parametrize('material', ['tests/test_exercise.py', 'tests/conftest.py', 'reference_solution.py', 'pytest.ini'])
def test_reference_cannot_mutate_tested_material(tmp_path, material):
    svc = service(tmp_path)
    draft = sample_draft()
    reference = ('from pathlib import Path\n'
                 f'changed = Path(__file__).parent / {material!r}\n'
                 'changed.write_bytes(changed.read_bytes() + b"\\n# modified tested copy\\n")\n'
                 'def total(values): return sum(values)\n')
    path = svc.save_draft(replace(draft, reference=reference))
    assert not svc.validate(path, execution_confirmed=True).passed
    with pytest.raises(AssistantError):
        svc.publish(path, ROOT, approved=True)


def test_starter_cannot_mutate_suite_while_failing_contract(tmp_path):
    svc = service(tmp_path)
    starter = ('from pathlib import Path\n'
               'changed = Path(__file__).parent / "tests/test_exercise.py"\n'
               'changed.write_bytes(changed.read_bytes() + b"\\n# changed by starter\\n")\n'
               'def total(values): return None\n')
    path = svc.save_draft(replace(sample_draft(), starter=starter))
    assert not svc.validate(path, execution_confirmed=True).passed
    with pytest.raises(AssistantError):
        svc.publish(path, ROOT, approved=True)


def test_each_selection_gets_its_own_reviewed_execution_copy(tmp_path):
    class RecordingRunner(ProcessRunner):
        def __init__(self):
            super().__init__()
            self.captures = []
        def run(self, argv, cwd, **kwargs):
            self.captures.append((cwd, (cwd / 'starter.py').read_bytes(),
                                  (cwd / 'tests/test_exercise.py').read_bytes()))
            return super().run(argv, cwd, **kwargs)
    runner = RecordingRunner()
    svc = service(tmp_path, runner)
    draft = sample_draft()
    path = svc.save_draft(draft)
    assert svc.validate(path, execution_confirmed=True).passed
    assert len(runner.captures) == 2
    assert runner.captures[0][0] != runner.captures[1][0]
    assert all(starter == draft.starter.encode() and tests == draft.tests.encode()
               for _, starter, tests in runner.captures)


def test_published_exercise_uses_existing_runner_solution_and_starter_default(tmp_path, monkeypatch):
    from python_lab.test_runner import run_tests
    monkeypatch.delenv('PYTHON_LAB_SOLUTION', raising=False)
    svc = service(tmp_path)
    draft = sample_draft()
    path = svc.save_draft(draft)
    assert svc.validate(path, execution_confirmed=True).passed
    published = svc.publish(path, ROOT, approved=True)
    correct = tmp_path / 'student.py'
    correct.write_text(draft.reference, encoding='utf-8')
    result = run_tests(published / 'tests', ROOT, solution_path=correct)
    assert result.passed and result.return_code == 0, result.output
    default = run_tests(published / 'tests', ROOT)
    assert not default.passed and default.return_code == 1
    assert '2 falho(s)' in default.summary
    assert all('assert' in diagnostic for diagnostic in default.diagnostics)
    assert 'TypeError' not in default.output


def test_explicit_validation_selection_overrides_ordinary_solution_environment(tmp_path, monkeypatch):
    external = tmp_path / 'unexpected.py'
    external.write_text('raise RuntimeError("wrong solution selected")\n')
    monkeypatch.setenv('PYTHON_LAB_SOLUTION', str(external))
    svc = service(tmp_path)
    path = svc.save_draft(sample_draft())
    assert svc.validate(path, execution_confirmed=True).passed


def test_published_runner_tolerates_same_harness_loaded_as_plugin_alias(tmp_path, monkeypatch):
    """Windows junction aliases can register the same conftest source twice."""
    import os
    from python_lab.test_runner import run_tests
    monkeypatch.delenv('PYTHON_LAB_SOLUTION', raising=False)
    svc = service(tmp_path)
    draft = sample_draft()
    path = svc.save_draft(draft)
    assert svc.validate(path, execution_confirmed=True).passed
    published = svc.publish(path, ROOT, approved=True)
    conftest = published / 'tests' / 'conftest.py'
    alias = tmp_path / 'duplicate_exercise_harness.py'
    alias.write_text('import runpy\nglobals().update(runpy.run_path(' + repr(str(conftest)) + '))\n', encoding='utf-8')
    # Real subprocess loads the actual saved conftest source first through this
    # distinct plugin identity, then again through its ordinary catalog path.
    monkeypatch.setenv('PYTEST_PLUGINS', 'duplicate_exercise_harness')
    monkeypatch.setenv('PYTHONPATH', str(tmp_path) + os.pathsep + os.getenv('PYTHONPATH', ''))
    correct = tmp_path / 'correct.py'
    correct.write_text(draft.reference, encoding='utf-8')
    result = run_tests(published / 'tests', ROOT, solution_path=correct)
    assert result.passed and result.return_code == 0, result.output
    default = run_tests(published / 'tests', ROOT)
    assert not default.passed and default.return_code == 1, default.output
    assert '2 falho(s)' in default.summary
    assert 'already added' not in default.output
    (published / 'tests' / 'test_exercise.py').write_text(
        'raise RuntimeError("genuine collection defect")\n', encoding='utf-8')
    broken = run_tests(published / 'tests', ROOT, solution_path=correct)
    assert not broken.passed and broken.return_code == 2, broken.output
    assert 'genuine collection defect' in broken.output
