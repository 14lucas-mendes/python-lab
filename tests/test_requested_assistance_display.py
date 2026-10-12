"""The local request is authoritative in each user-facing assistant adapter."""

import asyncio
import json
import time

import pytest

from python_lab.analysis import AnalysisService
from python_lab.assistant.history import ConversationRepository
from python_lab.assistant.models import AssistantAnswer, CodeReference, ReviewReply, Usage
from python_lab.assistant.service import AssistantService
from python_lab.cli import AssistantRuntime, main
from python_lab.storage.database import connection
from python_lab.tui.app import PythonLabTUI
from python_lab.workspace import Workspace


@pytest.mark.parametrize('action', ['explain', 'diagnose', 'review'])
@pytest.mark.parametrize('adapter', ['commands', 'cli', 'tui'])
def test_downgraded_help_displays_captured_requested_level(app, tmp_path, monkeypatch, capsys, action, adapter):
    app.start('001')
    source = app.current_mission().solution_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('value = 1 / 0\n', encoding='utf-8')
    name = source.relative_to(tmp_path).as_posix()
    (tmp_path / 'trace.txt').write_text('ZeroDivisionError: division by zero\n', encoding='utf-8')
    before = source.read_bytes()
    attempt = app.current_progress().attempt_id
    requested, declared = (3, 1) if action == 'review' else (4, 2)
    answer = AssistantAnswer('Summary', 'Explanation', (), (CodeReference(name, 1, 1),), declared, Usage(3, 2))
    captured = []

    class Provider:
        async def generate(self, request):
            captured.append(request)
            await asyncio.sleep(0)
            # Navigation during the request cannot change its display or identity.
            app.progress.current_mission_id = None
            return answer

        async def review(self, request):
            return ReviewReply(await self.generate(request), ())

    history = ConversationRepository(app.repository.path)
    service = AssistantService(Provider(), AnalysisService(), history,
                              on_assistance=app.record_assistance,
                              capture_attempt=app.capture_assistance_attempt)
    monkeypatch.setattr(AssistantRuntime, 'get_service', lambda self: service)
    args = (name,) if action == 'review' else (name, '--level', str(requested))
    if action == 'diagnose':
        args += ('--traceback', 'trace.txt')
    runtime = AssistantRuntime(app.repository.path.parent, app)
    if adapter == 'commands':
        commands = runtime.commands(Workspace(tmp_path), 'tutor', app=app)
        result = asyncio.run(getattr(commands, action)(args))
        assert result.ok
        message, data = result.message, result.data
    elif adapter == 'cli':
        assert main([action, *args, '--project', str(tmp_path), '--data-dir', str(app.repository.path.parent), '--json']) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload['schema_version'] == 1 and payload['ok'] and payload['action'] == action
        message, data = payload['message'], payload['data']
    else:
        tui = PythonLabTUI(app, assistant_project=tmp_path, assistant_service=service)
        tui.cli.assistant_runtime = runtime

        async def run():
            async with tui.run_test() as pilot:
                await pilot.pause()
                command = '/explain-code' if action == 'explain' else '/' + action
                tui._submit(command + ' ' + ' '.join(args))
                deadline = time.monotonic() + 25
                while tui._assistant_task is not None and time.monotonic() < deadline:
                    await asyncio.sleep(.01)
                assert tui._assistant_task is None, tui.transcript_entries
        asyncio.run(run())
        message, data = '\n'.join(tui.transcript_entries), None
    assert f'Ajuda nível {requested}' in message
    assert f'Ajuda nível {declared}' not in message
    assert captured[0].level == requested and captured[0].mode in ('tutor', 'assistant')
    if data is not None:
        assert data['requested_assistance_level'] == requested
        raw = data['advice'] if action == 'review' else data
        assert raw['assistance_level'] == declared
    assert source.read_bytes() == before
    with connection(app.repository.path) as db:
        event = db.execute('SELECT mission_id,action,level,attempt_id FROM assistance_events').fetchone()
        expected = (None, action, requested, None) if adapter == 'cli' else ('001', action, requested, attempt)
        assert event == expected
        assert db.execute('SELECT level FROM conversations').fetchone()[0] == requested
        columns = {row[1] for row in db.execute('PRAGMA table_info(conversations)')}
        assert not columns & {'source', 'prompt', 'response', 'traceback'}
    if adapter != 'cli':
        progress = app.repository.load().missions['001']
        assert progress.max_assistance_level == requested
        assert progress.reference_viewed is (requested == 4)
        assert progress.status == 'started' and app.progress.evidence == []
