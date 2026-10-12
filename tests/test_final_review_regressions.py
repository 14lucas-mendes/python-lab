"""Consumer regressions for the final privacy, responsiveness and evidence gaps."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
from shutil import copytree
import sqlite3
import threading

import pytest
from rich.console import Console

from python_lab.analysis.models import AnalysisReport
from python_lab.assistant.commands import AssistantCommands
from python_lab.assistant.history import ConversationRepository
from python_lab.assistant.models import AssistantAnswer, CodeReference, FileChange, PatchProposal, ReviewReply, Usage
from python_lab.assistant.patches import PatchService
from python_lab.assistant.review import ReviewService
from python_lab.assistant.service import AssistantService
from python_lab.assistant.verification import VerificationService
from python_lab.cli import PythonLabCLI, build_app
from python_lab.commands import parse_command
from python_lab.models import MissionProgress
from python_lab.runtime.processes import ProcessRunner
from python_lab.session import MAX_SESSIONS, SessionLog
from python_lab.workspace import Workspace
from tests.helpers.assistant import RecordingProvider
from tests.test_exercise_drafts import sample_draft, service as exercise_service
from tests.test_verification import proposal


class NoTools:
    def inspect(self, *args, **kwargs):
        return AnalysisReport(())


@pytest.mark.parametrize('asynchronous', [False, True])
def test_classic_response_quotes_are_displayed_but_never_session_history(app, tmp_path, asynchronous):
    source = 'selected_private_context_5729 = 1\n'
    trace = 'private_traceback_5729\n'
    (tmp_path / 'code.py').write_text(source)
    (tmp_path / 'trace.txt').write_text(trace)
    history = ConversationRepository(tmp_path / 'history.sqlite3')
    provider = RecordingProvider(AssistantAnswer('answer', source + trace, (),
        (CodeReference('code.py', 1, 1),), 0, Usage(1, 1)))
    assistant = AssistantService(provider, NoTools(), history)

    class Runtime:
        def get_service(self):
            return assistant
        async def aclose(self):
            pass

    log = SessionLog(tmp_path / 'session.sqlite3')
    console = Console(record=True, width=200)
    cli = PythonLabCLI(app, console, session_log=log, assistant_project=tmp_path, assistant_runtime=Runtime())
    command = parse_command('/diagnose code.py --traceback trace.txt')
    try:
        if asynchronous:
            cli.start_classic_assistant(command)
            state = cli._classic_action
            if state is not None:
                assert state['done'].wait(5)
        else:
            cli._execute_assistant(command)
        display = console.export_text()
        assert source.strip() in display and trace.strip() in display
        persisted = json.dumps(log.load())
        with sqlite3.connect(history.database_path) as db:
            persisted += json.dumps(db.execute('SELECT * FROM conversations').fetchall())
        assert source.strip() not in persisted and trace.strip() not in persisted
        event = log.current_events()[-1]
        assert event['command'] == '/diagnose'
        assert 'concluída' in event['summary'].lower()
    finally:
        cli.close_assistant()


@pytest.mark.parametrize('action,blocked_file', [('check', 'code.py'), ('explain', 'code.py'),
                                              ('diagnose', 'code.py'), ('diagnose', 'trace.txt')])
def test_capture_keeps_loop_live_and_cancellation_waits_for_worker(tmp_path, monkeypatch, action, blocked_file):
    (tmp_path / 'code.py').write_text('x = 1\n')
    (tmp_path / 'trace.txt').write_text('trace\n')
    started, release, finished = (threading.Event() for _ in range(3))
    workspace = Workspace(tmp_path)
    original = workspace.snapshot

    def snapshot(paths):
        if paths[0].name == blocked_file:
            started.set()
            assert release.wait(2)
            result = original(paths)
            finished.set()
            return result
        return original(paths)

    monkeypatch.setattr(workspace, 'snapshot', snapshot)
    provider = RecordingProvider(AssistantAnswer('answer', 'answer', (), (), 0, Usage(1, 1)))
    history = ConversationRepository(tmp_path / 'history.sqlite3')
    assistant = AssistantService(provider, NoTools(), history)
    commands = AssistantCommands(assistant, workspace, 'assistant', analysis=NoTools())
    args = ('code.py', '--traceback', 'trace.txt') if action == 'diagnose' else ('code.py',)
    timer = threading.Timer(.5, release.set)
    timer.start()

    async def run():
        cancel = threading.Event()
        task = asyncio.create_task(getattr(commands, action)(args, cancel=cancel))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(.005)
            assert started.is_set() and not finished.is_set(), 'Snapshot blocked the event loop'
            task.cancel()
            await asyncio.sleep(.02)
            task.cancel()
            await asyncio.sleep(.02)
            assert cancel.is_set() and not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert finished.is_set()
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    try:
        asyncio.run(run())
    finally:
        release.set()
        timer.cancel()
    assert provider.requests == []
    assert not history.database_path.exists()


def package_app(tmp_path):
    app = build_app(data_dir=tmp_path / 'state')
    for identity in ('002', '003', '004'):
        app.progress.missions[identity] = MissionProgress(status='completed', attempt_id='done-' + identity)
    app.start('005')
    mission = app.current_mission()
    root = tmp_path / 'starter'
    copytree(mission.solution_path, root)
    app.missions[app.missions.index(mission)] = replace(mission, solution_path=root)
    return app, root


@pytest.mark.parametrize('action', ['explain', 'diagnose', 'review', 'apply'])
def test_real_package_mission_descendant_receives_assistance(tmp_path, action):
    app, root = package_app(tmp_path)
    selected = 'relatorio_operacional/report.py'
    workspace = Workspace(root)
    history = ConversationRepository(app.repository.path)
    requests = []

    class Provider:
        async def generate(self, request):
            requests.append(request)
            return AssistantAnswer('help', 'help', (), (CodeReference(selected, 1, 1),), 4, Usage(1, 1))
        async def review(self, request):
            requests.append(request)
            return ReviewReply(AssistantAnswer('help', 'help', (), (), 3, Usage(1, 1)), ())

    assistant = AssistantService(Provider(), NoTools(), history)
    patches = PatchService(workspace, tmp_path / 'patches')
    commands = AssistantCommands(assistant, workspace, 'tutor', app=app, patches=patches,
        review_factory=lambda: ReviewService(NoTools(), assistant.provider, patches, history,
            on_assistance=app.record_assistance, capture_attempt=app.capture_assistance_attempt))
    if action == 'apply':
        snap = workspace.snapshot((Path(selected),))
        patch = PatchProposal('package-fix', FileChange(selected, snap.sources[0].sha256,
            snap.sources[0].text + '\n# reviewed change\n'), 'fix', (selected,))
        patches.save(patch)
        result = asyncio.run(commands.apply((patch.id, '--yes')))
    else:
        args = (selected,) if action == 'review' else (selected, '--level', '4')
        if action == 'diagnose':
            (root / 'trace.txt').write_text('trace\n')
            args += ('--traceback', 'trace.txt')
        result = asyncio.run(getattr(commands, action)(args))
        assert requests[0].mission_id == '005'
    assert result.ok
    progress = app.current_progress()
    assert progress.max_assistance_level == (3 if action == 'review' else 4)
    if action != 'review':
        assert progress.reference_viewed
        from python_lab.learning import complete_mission
        progress.plan = {'input': 'registros', 'output': 'relatório', 'steps': 'agrupar e renderizar', 'risks': 'dados inválidos'}
        progress.tests_passed = True
        progress.explanation = 'Minha explicação local'
        assert all(item['result'] == 'practicing' for item in complete_mission(app.current_mission(), progress, []))


@pytest.mark.parametrize('action', ['explain', 'diagnose'])
def test_new_capture_await_preserves_attempt_workspace_mode(app, tmp_path, monkeypatch, action):
    solution = app.missions[0].solution_path
    solution.write_text('x = 1\n')
    app.start('001')
    old_attempt = app.current_progress().attempt_id
    workspace = Workspace(solution.parent)
    history = ConversationRepository(tmp_path / 'history.sqlite3')
    provider = RecordingProvider(AssistantAnswer('help', 'help', (), (), 4, Usage(1, 1)))
    assistant = AssistantService(provider, NoTools(), history)
    commands = AssistantCommands(assistant, workspace, 'tutor', app=app)
    started, release = threading.Event(), threading.Event()
    original = workspace.snapshot

    def snapshot(paths):
        started.set()
        assert release.wait(2)
        return original(paths)

    monkeypatch.setattr(workspace, 'snapshot', snapshot)
    args = (solution.name, '--level', '4')
    if action == 'diagnose':
        (solution.parent / 'trace.txt').write_text('trace\n')
        args += ('--traceback', 'trace.txt')
    timer = threading.Timer(.5, release.set)
    timer.start()

    async def run():
        task = asyncio.create_task(getattr(commands, action)(args))
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(.005)
            assert not release.is_set(), 'Capture must yield before completion'
            app.current_progress().status = 'completed'
            app.start('001')
            commands.workspace = Workspace(tmp_path)
            commands.mode = 'assistant'
            release.set()
            result = await task
            assert result.ok
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    try:
        asyncio.run(run())
    finally:
        release.set()
        timer.cancel()
    assert provider.requests[0].snapshot.root == workspace.root
    assert provider.requests[0].mode == 'tutor'
    assert app.current_progress().attempt_id != old_attempt
    assert app.current_progress().max_assistance_level == 0
    with sqlite3.connect(app.repository.path) as db:
        assert db.execute('SELECT attempt_id FROM assistance_events').fetchone()[0] == old_attempt


def test_verbose_passing_pytest_uses_complete_junit_and_reports_truncation(tmp_path):
    (tmp_path / 'pytest.ini').write_text('[pytest]\naddopts = -s\n')
    (tmp_path / 'test_a.py').write_text('def test_verbose():\n    print("x" * 1048640)\n    assert True\n')
    workspace, patch = proposal(tmp_path, 'def f():\n    return 2\n')
    PatchService(workspace, tmp_path / '.state').apply(patch, confirmed=True)
    result = VerificationService(ProcessRunner()).run(patch, workspace, checks=('pytest',))
    assert result.status == 'passed'
    assert 'truncad' in result.checks[0].detail.lower()


def test_verbose_exercise_preserves_junit_and_assertion_phase_evidence(tmp_path):
    draft = sample_draft()
    verbose = '    import sys\n    sys.stdout.write("x" * 1048640)\n    sys.stdout.flush()\n'
    draft = replace(draft, tests=draft.tests.replace('    assert ', verbose + '    assert '))
    svc = exercise_service(tmp_path)
    path = svc.save_draft(draft)
    result = svc.validate(path, execution_confirmed=True)
    assert result.passed
    assert 'truncad' in result.detail.lower()


@pytest.mark.parametrize('open_count', [1, 5, 22])
def test_session_retention_reserves_total_capacity_for_all_open_sessions(tmp_path, open_count):
    path = tmp_path / 'lab.sqlite3'
    closed_ids = []
    for _ in range(MAX_SESSIONS):
        log = SessionLog(path)
        log.start()
        closed_ids.append(log.current_session['id'])
        log.close()
    logs = [SessionLog(path) for _ in range(open_count)]
    for log in logs:
        log.start()
    sessions = SessionLog(path).load()
    assert {s['id'] for s in sessions if s['ended_at'] is None} == {log.current_session['id'] for log in logs}
    retained = [s['id'] for s in sessions if s['ended_at'] is not None]
    capacity = max(MAX_SESSIONS - open_count, 0)
    assert retained == (closed_ids[-capacity:] if capacity else [])


@pytest.mark.parametrize('action', ['explain', 'diagnose', 'review', 'apply'])
@pytest.mark.parametrize('alias', [False, True])
def test_package_association_excludes_unrelated_and_escaping_descendants(tmp_path, action, alias):
    app, root = package_app(tmp_path)
    (tmp_path / 'unrelated.py').write_text('x = 1\n')
    selected = 'unrelated.py'
    if alias:
        linked = root / 'outside.py'
        try:
            linked.symlink_to(tmp_path / 'unrelated.py')
        except OSError:
            pytest.skip('Platform cannot create file symlinks')
        selected = 'starter/outside.py'
    workspace = Workspace(tmp_path)
    provider = RecordingProvider(AssistantAnswer('help', 'help', (), (), 4, Usage(1, 1)))
    requests = provider.requests
    async def review(request):
        requests.append(request)
        return ReviewReply(AssistantAnswer('help', 'help', (), (), 3, Usage(1, 1)), ())
    provider.review = review
    history = ConversationRepository(app.repository.path)
    assistant = AssistantService(provider, NoTools(), history)
    patches = PatchService(workspace, tmp_path / 'patches')
    commands = AssistantCommands(assistant, workspace, 'tutor', app=app, patches=patches,
        review_factory=lambda: ReviewService(NoTools(), provider, patches, history,
            on_assistance=app.record_assistance, capture_attempt=app.capture_assistance_attempt))
    if action == 'apply':
        snap = workspace.snapshot((Path(selected),))
        source = snap.sources[0]
        patch = PatchProposal('unrelated-fix', FileChange(source.path, source.sha256, 'x = 2\n'), 'fix', (source.path,))
        patches.save(patch)
        result = asyncio.run(commands.apply((patch.id, '--yes')))
    else:
        args = (selected,) if action == 'review' else (selected, '--level', '4')
        if action == 'diagnose':
            (tmp_path / 'trace.txt').write_text('trace\n')
            args += ('--traceback', 'trace.txt')
        result = asyncio.run(getattr(commands, action)(args))
        assert requests[0].mission_id is None
    assert result.ok and app.current_progress().max_assistance_level == 0
    assert not app.current_progress().reference_viewed


@pytest.mark.parametrize('kind', ['missing', 'empty', 'skipped', 'malformed', 'failure', 'cancelled', 'timeout'])
def test_truncated_console_cannot_override_invalid_pytest_evidence(tmp_path, kind):
    from python_lab.runtime.processes import ProcessResult
    workspace, patch = proposal(tmp_path, 'def f():\n    return 2\n')
    PatchService(workspace, tmp_path / '.state').apply(patch, confirmed=True)
    class Runner:
        def run(self, argv, cwd, **kwargs):
            report = Path(argv[argv.index('--junitxml') + 1])
            evidence = {
                'empty': '<testsuite tests="0"/>',
                'skipped': '<testsuite tests="1" skipped="1"><testcase name="skip"><skipped/></testcase></testsuite>',
                'malformed': '<broken',
                'failure': '<testsuite tests="1" failures="1"><testcase name="fail"><failure/></testcase></testsuite>',
                'cancelled': '<testsuite tests="1"><testcase name="pass"/></testsuite>',
                'timeout': '<testsuite tests="1"><testcase name="pass"/></testsuite>',
            }
            if kind in evidence:
                report.write_text(evidence[kind])
            return ProcessResult(1 if kind == 'failure' else 0, 'bounded console', kind == 'timeout', kind == 'cancelled', True)
    result = VerificationService(Runner()).run(patch, workspace, checks=('pytest',))
    assert result.status == ('cancelled' if kind == 'cancelled' else 'failed')


def test_structured_ruff_truncation_still_rejects_even_valid_json(tmp_path):
    from python_lab.runtime.processes import ProcessResult
    workspace, patch = proposal(tmp_path, 'def f():\n    return 2\n')
    PatchService(workspace, tmp_path / '.state').apply(patch, confirmed=True)
    class Runner:
        def run(self, *args, **kwargs):
            return ProcessResult(0, '[]', False, False, True)
    assert VerificationService(Runner()).run(patch, workspace, checks=('ruff',)).status == 'failed'


@pytest.mark.parametrize('kind', ['missing', 'malformed', 'empty', 'skipped'])
def test_exercise_truncation_cannot_override_invalid_junit_or_phase_evidence(tmp_path, kind):
    class CorruptEvidenceRunner(ProcessRunner):
        def run(self, argv, cwd, **kwargs):
            completed = super().run(argv, cwd, **kwargs)
            report = cwd / 'reference_solution.py.xml'
            if kind == 'missing':
                report.unlink()
            elif kind == 'malformed':
                report.write_text('<broken')
            elif kind == 'empty':
                report.write_text('<testsuite tests="0"/>')
            else:
                report.write_text('<testsuite tests="1" skipped="1"><testcase name="skip"><skipped/></testcase></testsuite>')
            return replace(completed, truncated=True)
    svc = exercise_service(tmp_path, CorruptEvidenceRunner())
    path = svc.save_draft(sample_draft())
    result = svc.validate(path, execution_confirmed=True)
    assert not result.passed
    assert 'truncad' in result.detail.lower()


def test_tui_capture_cancel_keeps_action_slot_until_actual_worker_cleanup(app, tmp_path, monkeypatch):
    import time
    from python_lab.tui.app import PythonLabTUI
    from python_lab.tui.widgets import Composer
    (tmp_path / 'code.py').write_text('x = 1\n')
    started, release, finished = (threading.Event() for _ in range(3))
    original = Workspace.snapshot
    def snapshot(workspace, paths):
        started.set()
        assert release.wait(3)
        result = original(workspace, paths)
        finished.set()
        return result
    monkeypatch.setattr(Workspace, 'snapshot', snapshot)
    history = ConversationRepository(tmp_path / 'history.sqlite3')
    provider = RecordingProvider(AssistantAnswer('help', 'help', (), (), 0, Usage(1, 1)))
    assistant = AssistantService(provider, NoTools(), history)
    tui = PythonLabTUI(app, assistant_project=tmp_path, assistant_service=assistant)
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/explain-code code.py')
            for _ in range(200):
                if started.is_set():
                    break
                await asyncio.sleep(.005)
            assert started.is_set() and not finished.is_set()
            task = tui._assistant_task
            assert task is not None
            tui._submit('/cancel')
            await asyncio.sleep(.02)
            task.cancel()
            await asyncio.sleep(.02)
            assert tui._assistant_task is task and not task.done()
            assert not tui.query_one('#composer', Composer).disabled
            release.set()
            deadline = time.monotonic() + 5
            while tui._assistant_task is not None and time.monotonic() < deadline:
                await asyncio.sleep(.01)
            assert finished.is_set() and tui._assistant_task is None
            assert provider.requests == []
            assert not history.database_path.exists()
    try:
        asyncio.run(run())
    finally:
        release.set()
