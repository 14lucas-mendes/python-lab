"""Operational adapter failures preserve actual file state and JSON contracts."""

import asyncio
from pathlib import Path

import pytest

from python_lab.app import ApplicationError
from python_lab.cli import AssistantRuntime
from python_lab.workspace import Workspace
from tests.test_review_cli import invoke, proposal


@pytest.mark.parametrize('adapter', ['cli', 'shared'])
def test_backup_failure_never_claims_applied(tmp_path, capsys, adapter):
    source = tmp_path / 'bug.py'
    source.write_bytes(b'x=1\n')
    state = tmp_path / 'state'
    patch = proposal(tmp_path, state, text='x=2\n')
    (state / 'backups').write_text('obstruction')
    if adapter == 'cli':
        code, payload = invoke(capsys, tmp_path, state, 'apply', patch.id, '--yes')
        assert code == 1
        data, message, ok = payload['data'], payload['message'], payload['ok']
    else:
        commands = AssistantRuntime(state).commands(Workspace(tmp_path), 'assistant')
        result = asyncio.run(commands.apply((patch.id, '--yes')))
        data, message, ok = result.data, result.message, result.ok
    assert not ok and data['error_kind'] == 'execution'
    assert data.get('applied') is not True
    assert 'Arquivo aplicado' not in message and 'registrar ajuda' not in message
    assert source.read_bytes() == b'x=1\n'


def test_successful_apply_callback_failure_truthfully_reports_applied(app, tmp_path, monkeypatch):
    app.start('001')
    source = app.current_mission().solution_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b'x=1\n')
    state = tmp_path / 'state'
    patch = proposal(tmp_path, state, str(source.relative_to(tmp_path)), 'x=2\n')
    calls = []
    def fail(mission_id, **identity):
        assert source.read_bytes() == b'x=2\n'
        calls.append(mission_id)
        raise ApplicationError('recording unavailable')
    monkeypatch.setattr(app, 'record_full_solution', fail)
    commands = AssistantRuntime(state, app).commands(Workspace(tmp_path), 'tutor', app=app)
    result = asyncio.run(commands.apply((patch.id, '--yes')))
    assert not result.ok and result.data['error_kind'] == 'execution'
    assert result.data['applied'] is True and 'recording unavailable' in result.message
    assert calls == ['001'] and source.read_bytes() == b'x=2\n'
    assert not app.current_progress().tests_passed and app.current_progress().status == 'started'


@pytest.mark.parametrize('adapter', ['cli', 'shared'])
@pytest.mark.parametrize('failure', ['blocked_directory', 'wrapped_write'])
def test_verification_storage_failure_is_execution_result(tmp_path, capsys, monkeypatch, adapter, failure):
    source = tmp_path / 'bug.py'
    source.write_bytes(b'x=1\n')
    state = tmp_path / 'state'
    patch = proposal(tmp_path, state, text='x=2\n')
    commands = AssistantRuntime(state).commands(Workspace(tmp_path), 'assistant')
    assert asyncio.run(commands.apply((patch.id, '--yes'))).ok
    if failure == 'blocked_directory':
        (state / 'verifications').write_text('obstruction')
    else:
        def fail(*args, **kwargs):
            raise PermissionError('verification write denied')
        monkeypatch.setattr('python_lab.assistant.verification.tempfile.mkstemp', fail)
    if adapter == 'cli':
        code, payload = invoke(capsys, tmp_path, state, 'verify', patch.id, '--check', 'ast')
        assert code == 1 and payload['schema_version'] == 1
        data, ok = payload['data'], payload['ok']
    else:
        result = asyncio.run(commands.verify((patch.id, '--check', 'ast')))
        data, ok = result.data, result.ok
    assert not ok and data['error_kind'] == 'execution'
    assert data.get('status') != 'passed'
    assert source.read_bytes() == b'x=2\n'


@pytest.mark.parametrize('adapter', ['cli', 'shared'])
def test_scaffold_permission_failure_is_execution_result(tmp_path, capsys, monkeypatch, adapter):
    state = tmp_path / 'state'
    target = tmp_path / 'myapp'
    original = Path.mkdir
    def fail(path, *args, **kwargs):
        if path == target:
            raise PermissionError('destination write denied')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'mkdir', fail)
    if adapter == 'cli':
        code, payload = invoke(capsys, tmp_path, state, 'new', 'cli', 'myapp', '--path', str(tmp_path))
        assert code == 1 and payload['schema_version'] == 1
        data, ok = payload['data'], payload['ok']
    else:
        commands = AssistantRuntime(state).commands(Workspace(tmp_path), 'assistant')
        result = asyncio.run(commands.new(('cli', 'myapp', '--path', str(tmp_path))))
        data, ok = result.data, result.ok
    assert not ok and data['error_kind'] == 'execution'
    assert not target.exists()


def test_scaffold_existing_target_race_remains_usage(tmp_path, capsys, monkeypatch):
    target = tmp_path / 'myapp'
    original = Path.mkdir
    def race(path, *args, **kwargs):
        if path == target:
            original(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'mkdir', race)
    code, payload = invoke(capsys, tmp_path, tmp_path / 'state', 'new', 'cli', 'myapp', '--path', str(tmp_path))
    assert code == 2 and payload['data']['error_kind'] == 'usage'
    assert target.is_dir() and not list(target.iterdir())


def test_stale_confirmation_never_claims_applied(tmp_path):
    source = tmp_path / 'bug.py'
    source.write_bytes(b'x=1\n')
    state = tmp_path / 'state'
    patch = proposal(tmp_path, state, text='x=2\n')
    commands = AssistantRuntime(state).commands(Workspace(tmp_path), 'assistant')
    async def confirm(preview):
        source.write_bytes(b'external=3\n')
        return True
    result = asyncio.run(commands.apply((patch.id,), confirm=confirm))
    assert not result.ok and result.data['error_kind'] == 'usage'
    assert result.data.get('applied') is not True
    assert 'Arquivo aplicado' not in result.message
    assert source.read_bytes() == b'external=3\n'


@pytest.mark.parametrize('adapter', ['shared', 'tui'])
@pytest.mark.parametrize('associated', [False, True])
def test_event_cancellation_after_actual_write_preserves_applied_recording_error(app, tmp_path, monkeypatch, adapter, associated):
    import threading
    from python_lab.learning_events import AssistanceRecorder
    from python_lab.storage.errors import ProgressError
    from python_lab.tui.app import PythonLabTUI
    from python_lab.tui.screens import ConfirmScreen
    from tests.test_review_tui import wait_action

    if associated:
        app.start('001')
        source = app.current_mission().solution_path
    else:
        source = tmp_path / 'bug.py'
    source.write_bytes(b'x=1\n')
    state = tmp_path / 'patch-state'
    patch = proposal(tmp_path, state, str(source.relative_to(tmp_path)), 'x=2\n')
    cancel = threading.Event()
    recorded = []
    tui = None

    def failed_record(self, event, **kwargs):
        # The real PatchService has already replaced the selected bytes.
        assert source.read_bytes() == b'x=2\n'
        recorded.append(event.mission_id)
        action_cancel = tui._assistant_cancel if tui is not None else cancel
        assert action_cancel is not None
        action_cancel.set()
        raise ProgressError('assistance persistence failed after replacement')

    monkeypatch.setattr(AssistanceRecorder, 'record', failed_record)
    runtime = AssistantRuntime(state, app if associated or adapter == 'tui' else None)
    if adapter == 'shared':
        commands = runtime.commands(Workspace(tmp_path), 'tutor' if associated else 'assistant',
                                    app=app if associated else None)
        result = asyncio.run(commands.apply((patch.id, '--yes'), cancel=cancel))
        assert cancel.is_set()
        assert not result.ok and result.data['applied'] is True
        assert result.data['error_kind'] == 'execution'
        assert result.data['path'] == str(source)
        assert 'Arquivo aplicado; falha ao registrar ajuda:' in result.message
        assert 'assistance persistence failed after replacement' in result.message
    else:
        tui = PythonLabTUI(app, assistant_project=tmp_path)
        tui.cli.assistant_runtime = runtime
        async def run():
            async with tui.run_test() as pilot:
                await pilot.pause()
                tui._submit(f'/apply {patch.id} --yes')
                for _ in range(200):
                    if isinstance(tui.screen, ConfirmScreen):
                        break
                    await asyncio.sleep(.01)
                assert isinstance(tui.screen, ConfirmScreen)
                await pilot.pause()
                await pilot.press('y')
                await wait_action(tui)
                transcript = '\n'.join(tui.transcript_entries)
                assert 'Arquivo aplicado; falha ao registrar ajuda:' in transcript
                assert 'assistance persistence failed after replacement' in transcript
                assert 'Ação cancelada.' not in transcript
        asyncio.run(run())
    assert source.read_bytes() == b'x=2\n'
    assert recorded == ['001' if associated else None]
    assert not app.progress.evidence


@pytest.mark.parametrize('action,selected', [('check', 'code.py'), ('explain', 'code.py'),
    ('diagnose', 'code.py'), ('diagnose', 'trace.txt'), ('review', 'code.py')])
def test_event_after_readonly_snapshot_rejects_unaccepted_work(tmp_path, monkeypatch, action, selected):
    import threading
    from python_lab.assistant.commands import AssistantCommands
    from tests.test_final_review_regressions import NoTools
    (tmp_path / 'code.py').write_text('x=1\n')
    (tmp_path / 'trace.txt').write_text('trace\n')
    workspace = Workspace(tmp_path)
    original = workspace.snapshot
    cancel = threading.Event()
    captured = []
    def snapshot(paths):
        result = original(paths)
        captured.append(paths[0].name)
        if paths[0].name == selected:
            cancel.set()
        return result
    monkeypatch.setattr(workspace, 'snapshot', snapshot)
    def unexpected_service():
        pytest.fail('Cancelled snapshot proceeded to an unaccepted service')
    commands = AssistantCommands(None, workspace, 'assistant', analysis=NoTools(),
        service_factory=unexpected_service, review_factory=unexpected_service)
    args = ('code.py', '--traceback', 'trace.txt') if action == 'diagnose' else ('code.py',)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(getattr(commands, action)(args, cancel=cancel))
    assert captured[-1] == selected and cancel.is_set()
