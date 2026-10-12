import asyncio
import time
from pathlib import Path

from textual.widgets import Static

from python_lab.assistant.history import ConversationRepository
from python_lab.assistant.service import AssistantService
from python_lab.analysis.service import AnalysisService
from python_lab.tui.app import PythonLabTUI
from python_lab.tui.widgets import Composer
from tests.helpers.assistant import BlockingProvider


def test_cancel_releases_composer(app, tmp_path):
    (tmp_path / 'code.py').write_text('print(1)\n', encoding='utf-8')
    started = asyncio.Event()
    service = AssistantService(BlockingProvider(started), AnalysisService(), ConversationRepository(tmp_path / 'history.sqlite3'))
    tui = PythonLabTUI(app, assistant_project=tmp_path, assistant_service=service)

    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/explain-code code.py')
            await asyncio.wait_for(started.wait(), 5)
            assert tui._assistant_task is not None
            tui._submit('/cancel')
            deadline = time.monotonic() + 5
            while tui._assistant_task is not None and time.monotonic() < deadline:
                await asyncio.sleep(.01)
            assert not tui.query_one('#composer', Composer).disabled
            assert tui.query_one('#composer', Composer).placeholder == "Digite / para comandos"
            assert not any('Summary' in text for text in tui.transcript_entries)
    asyncio.run(run())


def test_tui_switches_project_and_mode_without_losing_mission(app, tmp_path):
    tui = PythonLabTUI(app)
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/start 001')
            tui._submit(f'/project "{tmp_path}"')
            tui._submit('/mode tutor')
            assert tui.assistant_mode == 'tutor'
            assert tui.assistant_project == tmp_path.resolve()
            assert app.progress.current_mission_id == '001'
            tui._submit('/project off')
            assert app.progress.current_mission_id == '001'
    asyncio.run(run())


def test_cancel_before_assistant_task_starts_restores_composer(app, tmp_path):
    (tmp_path / 'code.py').write_text('print(1)\n', encoding='utf-8')
    tui = PythonLabTUI(app, assistant_project=tmp_path)
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/check code.py')
            tui._submit('/cancel')
            deadline = time.monotonic() + 2
            while tui._assistant_task is not None and time.monotonic() < deadline:
                await asyncio.sleep(.01)
            assert not tui.query_one('#composer', Composer).disabled
    asyncio.run(run())


def test_cancel_command_is_typeable_during_action(app, tmp_path):
    (tmp_path / 'code.py').write_text('print(1)\n', encoding='utf-8')
    started = asyncio.Event()
    service = AssistantService(BlockingProvider(started), AnalysisService(), ConversationRepository(tmp_path / 'history.sqlite3'))
    tui = PythonLabTUI(app, assistant_project=tmp_path, assistant_service=service)
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/explain-code code.py')
            await asyncio.wait_for(started.wait(), 5)
            composer = tui.query_one('#composer', Composer)
            assert not composer.disabled
            composer.focus()
            composer.value = '/cancel'
            await pilot.press('enter')
            deadline = time.monotonic() + 5
            while tui._assistant_task is not None and time.monotonic() < deadline:
                await asyncio.sleep(.01)
            assert tui._assistant_task is None
    asyncio.run(run())


def test_tui_check_and_diagnose_share_handlers(app, tmp_path):
    from python_lab.assistant.models import AssistantAnswer, CodeReference, Usage
    from tests.helpers.assistant import RecordingProvider
    (tmp_path / 'code.py').write_text('value = 1 / 0\n', encoding='utf-8')
    (tmp_path / 'trace.txt').write_text('ZeroDivisionError: division by zero\n', encoding='utf-8')
    provider = RecordingProvider(AssistantAnswer('Division by zero', 'Inspect denominator.', (),
        (CodeReference('code.py', 1, 1),), 0, Usage(4, 2)))
    service = AssistantService(provider, AnalysisService(), ConversationRepository(tmp_path / 'history.sqlite3'))
    tui = PythonLabTUI(app, assistant_project=tmp_path, assistant_service=service)
    async def wait_action():
        deadline = time.monotonic() + 5
        while tui._assistant_task is not None and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        assert tui._assistant_task is None
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/check code.py')
            await wait_action()
            assert 'Verificação local concluída' in '\n'.join(tui.transcript_entries)
            tui._submit('/diagnose --traceback trace.txt --file code.py')
            await wait_action()
            assert provider.requests[0].action == 'diagnose'
            assert provider.requests[0].traceback.startswith('ZeroDivisionError')
            assert 'Division by zero' in '\n'.join(tui.transcript_entries)
    asyncio.run(run())


def test_tui_default_mode_tracks_mission_and_explicit_override(app, tmp_path):
    from python_lab.assistant.models import AssistantAnswer, CodeReference, Usage
    from tests.helpers.assistant import RecordingProvider
    (tmp_path / 'code.py').write_text('print(1)\n', encoding='utf-8')
    provider = RecordingProvider(AssistantAnswer('Summary', 'Explanation', (),
        (CodeReference('code.py', 1, 1),), 0, Usage(3, 2)))
    service = AssistantService(provider, AnalysisService(), ConversationRepository(tmp_path / 'history.sqlite3'))
    tui = PythonLabTUI(app, assistant_project=tmp_path, assistant_service=service)
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            async def ask():
                tui._submit('/explain-code code.py')
                deadline = time.monotonic() + 5
                while tui._assistant_task is not None and time.monotonic() < deadline:
                    await asyncio.sleep(.01)
                assert tui._assistant_task is None
            await ask()
            tui._submit('/start 001')
            await ask()
            tui._submit('/mode assistant')
            await ask()
    asyncio.run(run())
    assert [request.mode for request in provider.requests] == ['assistant', 'tutor', 'assistant']
    assert provider.requests[1].mission_id is None  # unrelated project selection
