import asyncio
from pathlib import Path

from python_lab.assistant.commands import AssistantCommands
from python_lab.assistant.history import ConversationRepository
from python_lab.assistant.models import AssistantAnswer, CodeReference, Usage
from python_lab.assistant.service import AssistantService
from python_lab.analysis.service import AnalysisService
from python_lab.workspace import Workspace
from tests.helpers.assistant import RecordingProvider


def test_diagnose_then_explain_cause(tmp_path):
    (tmp_path / 'broken.py').write_text('value = 1 / 0\n', encoding='utf-8')
    (tmp_path / 'trace.txt').write_text('ZeroDivisionError: division by zero\n', encoding='utf-8')
    workspace = Workspace(tmp_path)
    answer = AssistantAnswer('Division by zero', 'The denominator is zero.', ('Inspect denominator',),
        (CodeReference('broken.py', 1, 1),), 0, Usage(4, 2))
    provider = RecordingProvider(answer)
    service = AssistantService(provider, AnalysisService(), ConversationRepository(tmp_path / 'history.sqlite3'))
    commands = AssistantCommands(service, workspace, 'assistant')
    diagnosed = asyncio.run(commands.diagnose(('--traceback', 'trace.txt', '--file', 'broken.py')))
    explained = asyncio.run(commands.explain(('broken.py',)))
    assert diagnosed.ok and explained.ok
    assert provider.requests[0].traceback.startswith('ZeroDivisionError')
    assert provider.requests[1].action == 'explain'
    assert (tmp_path / 'broken.py').read_text() == 'value = 1 / 0\n'


def test_mission_hint_tests_then_explanation_stays_user_owned(app, tmp_path):
    source = tmp_path / 'student.py'
    source.write_text('def solve():\n    return 2\n', encoding='utf-8')
    suite = tmp_path / 'test_student.py'
    suite.write_text("import os, runpy\ndef test_solution():\n    assert runpy.run_path(os.environ['PYTHON_LAB_SOLUTION'])['solve']() == 2\n", encoding='utf-8')
    from dataclasses import replace
    app.missions[0] = replace(app.missions[0], test_path=suite, solution_path=source)
    workspace = Workspace(tmp_path)
    provider = RecordingProvider(AssistantAnswer('Try a map', 'Track totals by key.', (),
        (CodeReference('student.py', 1, 1),), 1, Usage(4, 2)))
    service = AssistantService(provider, AnalysisService(), ConversationRepository(tmp_path / 'history.sqlite3'))
    app.start('001')
    app.save_plan(dict(input='x', output='y', steps='z', risks='w'))
    app.run_current_tests()
    app.next_hint()
    commands = AssistantCommands(service, workspace, 'tutor', app=app)
    answer = asyncio.run(commands.explain(('student.py', '--level', '1')))
    assert answer.ok and provider.requests[0].mission_id == '001'
    assert app.progress.current_mission_id == '001'
    assert app.current_progress().explanation is None
    result = app.run_current_tests()
    assert result.passed
    app.save_explanation('I grouped minutes by equipment and verified ties.')
    app.complete_current_mission()
    assert app.progress.missions['001'].status == 'completed'
    assert source.read_text(encoding='utf-8') == 'def solve():\n    return 2\n'
