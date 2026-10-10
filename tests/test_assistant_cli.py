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
