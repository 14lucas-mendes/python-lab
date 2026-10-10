import asyncio
import json
from pathlib import Path

import pytest

from python_lab.assistant.commands import AssistantCommands
from python_lab.assistant.models import AssistantAnswer, CodeReference, Usage
from python_lab.assistant.service import AssistantService
from python_lab.assistant.history import ConversationRepository
from python_lab.analysis.service import AnalysisService
from python_lab.cli import main
from python_lab.commands import Command, CommandDispatcher
from python_lab.workspace import Workspace
from tests.helpers.assistant import RecordingProvider


def test_async_dispatch_is_explicit():
    dispatcher = CommandDispatcher()
    async def answer(args):
        return __import__('python_lab.commands', fromlist=['CommandResult']).CommandResult(True, args[0], {})
    dispatcher.register_async('/explain-code', answer)
    assert 'async' in dispatcher.dispatch(Command('/explain-code', ('x',))).message.lower()
    assert asyncio.run(dispatcher.dispatch_async(Command('/explain-code', ('x',)))).message == 'x'


def test_check_works_without_provider_and_reports_findings(tmp_path):
    (tmp_path / 'broken.py').write_text('def broken(:\n', encoding='utf-8')
    commands = AssistantCommands(None, Workspace(tmp_path), 'assistant')
    result = asyncio.run(commands.check(('broken.py',)))
    assert result.ok and result.data['checks']
    assert any(check['status'] == 'failed' for check in result.data['checks'])
    assert 'broken.py' in result.message
    assert 'failed' in result.message or 'falhou' in result.message


def test_explain_captures_workspace_mode_and_mission(tmp_path, app):
    (tmp_path / 'sample.py').write_text('print(1)\n', encoding='utf-8')
    snapshot = Workspace(tmp_path).snapshot((Path('sample.py'),))
    provider = RecordingProvider(AssistantAnswer('Summary', 'Explanation', ('Step',),
        (CodeReference('sample.py', 1, 1),), 0, Usage(3, 2)))
    service = AssistantService(provider, AnalysisService(), ConversationRepository(tmp_path / 'history.sqlite3'))
    app.start('001')
    commands = AssistantCommands(service, Workspace(tmp_path), 'tutor', app=app)
    result = asyncio.run(commands.explain(('sample.py',)))
    assert result.ok and result.message.startswith('Summary')
    assert 'sample.py:1' in result.message
    assert '2' in result.message and 'tokens' in result.message.lower()
    assert provider.requests[0].mission_id == '001'
    assert provider.requests[0].mode == 'tutor'
    assert app.current_progress().status == 'started'


def test_json_check_and_config_exit_codes(tmp_path, capsys):
    (tmp_path / 'code.py').write_text('print(1)\n', encoding='utf-8')
    state = tmp_path / 'state'
    assert main(['check', 'code.py', '--project', str(tmp_path), '--data-dir', str(state), '--json']) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['schema_version'] == 1 and payload['action'] == 'check' and payload['ok']
    assert main(['explain', 'code.py', '--project', str(tmp_path), '--data-dir', str(state), '--json']) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload['schema_version'] == 1 and not payload['ok']
    assert 'provider' in payload['message'].lower()


def test_unreadable_selection_is_useful_error(tmp_path, capsys):
    assert main(['check', 'absent.py', '--project', str(tmp_path), '--data-dir', str(tmp_path / 'state'), '--json']) == 2
    payload = json.loads(capsys.readouterr().out)
    assert 'arquivo' in payload['message'].lower()


def test_missing_assistant_configuration_keeps_version_available(capsys):
    with pytest.raises(SystemExit) as result:
        main(['--version'])
    assert result.value.code == 0
    assert 'python-lab' in capsys.readouterr().out


def test_one_shot_project_with_spaces_and_explicit_mode_level(tmp_path, monkeypatch, capsys):
    project = tmp_path / 'my project'
    project.mkdir()
    (project / 'my code.py').write_text('print(1)\n', encoding='utf-8')
    snapshot = Workspace(project).snapshot((Path('my code.py'),))
    provider = RecordingProvider(AssistantAnswer('Summary', 'Explanation', (),
        (CodeReference('my code.py', 1, 1),), 1, Usage(3, 2)))
    service = AssistantService(provider, AnalysisService(), ConversationRepository(tmp_path / 'data' / 'history.sqlite3'))
    monkeypatch.setattr('python_lab.cli.AssistantRuntime.get_service', lambda self: service)
    assert main(['explain', 'my code.py', '--project', str(project), '--data-dir', str(tmp_path / 'data'),
                 '--mode', 'tutor', '--level', '1', '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['data']['assistance_level'] == 1
    assert provider.requests[0].mode == 'tutor'
    assert provider.requests[0].snapshot.root == project
    assert (project / 'my code.py').read_text(encoding='utf-8') == 'print(1)\n'


def test_windows_quotes_preserve_backslashes():
    from python_lab.commands import parse_command
    assert parse_command(r'/project "C:\Users\Ada\My Project"').args == (r'C:\Users\Ada\My Project',)


def test_invalid_one_shot_level_keeps_json_envelope(tmp_path, capsys):
    code = tmp_path / 'code.py'
    code.write_text('print(1)\n', encoding='utf-8')
    assert main(['explain', 'code.py', '--project', str(tmp_path), '--level', '9', '--json']) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload['schema_version'] == 1 and payload['action'] == 'explain'
    assert payload['ok'] is False


def test_invalid_interactive_project_returns_useful_error_before_state(tmp_path, capsys):
    state = tmp_path / 'state'
    assert main(['--project', str(tmp_path / 'missing'), '--classic', '--data-dir', str(state)]) == 2
    assert 'workspace' in capsys.readouterr().out.lower()
    assert not (state / 'lab.sqlite3').exists()


def test_interactive_mode_option_reaches_tui_without_project(app, monkeypatch):
    observed = {}
    class FakeTUI:
        def __init__(self, lab, session_log=None, assistant_mode='assistant', **kwargs):
            observed['mode'] = assistant_mode
        def run(self):
            pass
    monkeypatch.setattr('python_lab.cli.build_app', lambda: app)
    monkeypatch.setattr('python_lab.cli.PythonLabTUI', FakeTUI)
    assert main(['--mode', 'tutor']) == 0
    assert observed['mode'] == 'tutor'


def test_classic_default_mode_follows_mission_and_explicit_override(app, tmp_path):
    from rich.console import Console
    from python_lab.cli import PythonLabCLI
    (tmp_path / 'code.py').write_text('print(1)\n', encoding='utf-8')
    provider = RecordingProvider(AssistantAnswer('Summary', 'Explanation', (),
        (CodeReference('code.py', 1, 1),), 0, Usage(3, 2)))
    service = AssistantService(provider, AnalysisService(), ConversationRepository(tmp_path / 'history.sqlite3'))
    class Runtime:
        def get_service(self):
            return service
        async def aclose(self):
            pass
    cli = PythonLabCLI(app, Console(record=True), assistant_project=tmp_path, assistant_runtime=Runtime())
    try:
        assert cli.execute('/explain-code code.py')
        app.start('001')
        assert cli.execute('/explain-code code.py')
        assert [request.mode for request in provider.requests] == ['assistant', 'tutor']
        assert provider.requests[1].mission_id == '001'
        assert cli.execute('/mode assistant')
        assert cli.execute('/explain-code code.py')
        assert provider.requests[2].mode == 'assistant'
    finally:
        cli.close_assistant()


def test_classic_explicit_startup_mode_survives_mission(app, tmp_path):
    from python_lab.cli import PythonLabCLI
    from rich.console import Console
    app.start('001')
    cli = PythonLabCLI(app, Console(record=True), assistant_project=tmp_path,
                       assistant_mode='assistant', mode_explicit=True)
    assert cli.effective_assistant_mode() == 'assistant'


def test_classic_cancel_reaches_blocked_provider_during_action(app, tmp_path, monkeypatch):
    import threading
    from rich.console import Console
    from python_lab.cli import _run_classic
    (tmp_path / 'code.py').write_text('print(1)\n', encoding='utf-8')
    started = threading.Event()
    second_read = threading.Event()
    cancelled = threading.Event()
    class WaitingProvider:
        async def generate(self, request):
            loop = asyncio.get_running_loop()
            self.loop = loop
            self.gate = loop.create_future()
            started.set()
            try:
                await self.gate
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return AssistantAnswer('late', 'late', (), (), 0, Usage(1, 1))
    provider = WaitingProvider()
    service = AssistantService(provider, AnalysisService(), ConversationRepository(tmp_path / 'history.sqlite3'))
    monkeypatch.setattr('python_lab.cli.AssistantRuntime.get_service', lambda self: service)
    calls = iter(['/explain-code code.py', '/cancel', '/exit'])
    def read(*args):
        value = next(calls)
        if value == '/cancel':
            assert started.wait(5)
            second_read.set()
        return value
    monkeypatch.setattr(Console, 'input', read)
    thread = threading.Thread(target=_run_classic, args=(app, None, Console(record=True), tmp_path), daemon=True)
    thread.start()
    try:
        assert started.wait(5)
        assert second_read.wait(1), 'Classic prompt did not read /cancel during the action'
        thread.join(5)
        assert not thread.is_alive()
        assert cancelled.is_set()
        import sqlite3
        history = tmp_path / 'history.sqlite3'
        if history.exists():
            with sqlite3.connect(history) as db:
                tables = db.execute("SELECT name FROM sqlite_master WHERE name='conversations'").fetchall()
                if tables:
                    assert db.execute('SELECT count(*) FROM conversations').fetchone()[0] == 0
    finally:
        if started.is_set() and not provider.gate.done():
            provider.loop.call_soon_threadsafe(provider.gate.set_result, None)
        thread.join(5)


def test_classic_cancel_waits_for_native_analysis_tree_cleanup(app, tmp_path, monkeypatch):
    import threading
    from rich.console import Console
    from python_lab.cli import _run_classic
    from python_lab.analysis.models import AnalysisReport, ToolCheck
    from python_lab.analysis.service import AnalysisCancelled
    from python_lab.runtime.processes import ProcessRunner
    from tests.test_process_runner import tree_command, assert_tree_stopped, wait_for_file
    (tmp_path / 'code.py').write_text('print(1)\n', encoding='utf-8')
    command = tree_command(tmp_path)
    cleaned = threading.Event()
    class SlowAnalysis:
        def inspect(self, snapshot, *, cancel=None):
            result = ProcessRunner().run(command, tmp_path, timeout=3, cancel=cancel)
            cleaned.set()
            if result.cancelled:
                raise AnalysisCancelled('cancelled')
            return AnalysisReport((ToolCheck('native', 'passed', ()),))
    monkeypatch.setattr('python_lab.assistant.commands.AnalysisService', SlowAnalysis)
    calls = iter(['/check code.py', '/cancel', '/exit'])
    saw_running_cancel = threading.Event()
    saw_clean_exit = threading.Event()
    def read(*args):
        value = next(calls)
        if value == '/cancel':
            wait_for_file(tmp_path / 'ready')
            if not cleaned.is_set():
                saw_running_cancel.set()
        if value == '/exit':
            if cleaned.is_set():
                assert_tree_stopped(tmp_path)
                saw_clean_exit.set()
        return value
    monkeypatch.setattr(Console, 'input', read)
    thread = threading.Thread(target=_run_classic, args=(app, None, Console(record=True), tmp_path), daemon=True)
    thread.start()
    thread.join(8)
    assert not thread.is_alive()
    assert saw_running_cancel.is_set(), '/cancel was not read until analysis returned'
    assert saw_clean_exit.is_set(), 'Next prompt was shown before native cleanup'


def test_explicit_default_mode_flag_reaches_tui_as_override(app, monkeypatch):
    from python_lab.cli import main
    observed = {}
    class FakeTUI:
        def __init__(self, lab, session_log=None, assistant_mode='assistant', mode_explicit=False, **kwargs):
            observed['mode'] = assistant_mode
            observed['explicit'] = mode_explicit
        def run(self):
            pass
    monkeypatch.setattr('python_lab.cli.build_app', lambda: app)
    monkeypatch.setattr('python_lab.cli.PythonLabTUI', FakeTUI)
    assert main(['--mode', 'assistant']) == 0
    assert observed == {'mode': 'assistant', 'explicit': True}
