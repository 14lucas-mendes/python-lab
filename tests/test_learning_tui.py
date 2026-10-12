import asyncio
import copy
import time

from python_lab.tui.app import PythonLabTUI
from python_lab.tui.screens import ConfirmScreen
from tests.test_learning_cli import learning, DraftProvider
from tests.test_exercise_drafts import sample_draft


async def finished(tui):
    deadline = time.monotonic() + 10
    while tui._assistant_task is not None and time.monotonic() < deadline:
        await asyncio.sleep(.01)
    assert tui._assistant_task is None


async def confirmation(tui):
    deadline = time.monotonic() + 10
    while not (isinstance(tui.screen, ConfirmScreen) and tui.screen.is_mounted):
        assert tui._assistant_task is not None, (
            'Action ended before confirmation: ' + repr(tui.transcript_entries))
        assert time.monotonic() < deadline, (
            'Confirmation deadline reached with an active action: ' + repr(tui.transcript_entries))
        await asyncio.sleep(.01)
    assert isinstance(tui.screen, ConfirmScreen)


def test_tui_submit_practice_is_readonly_without_provider(app, tmp_path):
    tui = PythonLabTUI(app)
    tui.cli.learning = learning(app, tmp_path / 'state')
    before = copy.deepcopy(app.progress)
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/practice')
            await pilot.pause()
            assert any('registrad' in entry for entry in tui.transcript_entries)
            assert app.progress == before
    asyncio.run(run())


def test_tui_draft_literal_and_validation_cancel_no_effect(app, tmp_path):
    tui = PythonLabTUI(app)
    tui.cli.learning = learning(app, tmp_path / 'state', DraftProvider())
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/exercise "soma de valores"')
            await finished(tui)
            assert any('[red]Implemente' in entry for entry in tui.transcript_entries)
            assert not any('return sum' in entry for entry in tui.transcript_entries)
            tui._submit('/exercise-validate custom-sum --yes')
            await pilot.pause()
            await confirmation(tui)
            assert 'privilégios' in tui.screen._diff
            assert str(tmp_path / 'state') in tui.screen._diff
            await pilot.press('escape')
            await finished(tui)
            assert not (tmp_path / 'state' / 'exercise_validations').exists()
            tui._submit('/exercise-publish custom-sum')
            await pilot.pause()
            await confirmation(tui)
            await pilot.press('escape')
            await finished(tui)
            assert not (tmp_path / 'state' / 'custom_catalog').exists()
    asyncio.run(run())


def test_tui_saved_draft_validate_then_publish_modal_offline(app, tmp_path):
    tui = PythonLabTUI(app)
    tui.cli.learning = learning(app, tmp_path / 'state')
    tui.cli.learning.exercises.save_draft(sample_draft())
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/exercise-validate custom-sum')
            await pilot.pause()
            await confirmation(tui)
            await pilot.press('y')
            await finished(tui)
            assert any('Revisão didática' in entry for entry in tui.transcript_entries)
            tui._submit('/exercise-publish custom-sum')
            await pilot.pause()
            await confirmation(tui)
            assert 'custom_catalog' in tui.screen._diff
            await pilot.press('y')
            await finished(tui)
            assert (tmp_path / 'state' / 'custom_catalog' / 'custom-sum').exists()
    asyncio.run(run())


def test_tui_reference_cancel_and_captured_attempt(app, tmp_path):
    app.start('001')
    tui = PythonLabTUI(app)
    tui.cli.learning = learning(app, tmp_path / 'state')
    tui.cli.learning.exercises.save_draft(sample_draft())
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/exercise-show custom-sum --reference --yes')
            await pilot.pause()
            await confirmation(tui)
            await pilot.press('escape')
            await finished(tui)
            assert app.current_progress().max_assistance_level == 0
            tui._submit('/exercise-show custom-sum --reference')
            await pilot.pause()
            await confirmation(tui)
            captured = app.current_progress().attempt_id
            app.current_progress().status = 'completed'
            app.persist()
            app.start('001')  # response must remain bound to the pre-modal attempt
            assert app.current_progress().attempt_id != captured
            await pilot.press('y')
            await finished(tui)
            assert app.current_progress().max_assistance_level == 0
    asyncio.run(run())


def test_tui_provider_cancellation_no_draft_or_completion(app, tmp_path):
    class SlowProvider:
        async def draft(self, request):
            started.set()
            await asyncio.Event().wait()
    started = asyncio.Event()
    tui = PythonLabTUI(app)
    tui.cli.learning = learning(app, tmp_path / 'state', SlowProvider())
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/exercise soma')
            await asyncio.wait_for(started.wait(), 5)
            tui._submit('/practice')
            assert any('Ação em curso' in item for item in tui.transcript_entries)
            tui._submit('/cancel')
            await finished(tui)
            assert not (tmp_path / 'state' / 'exercise_drafts').exists()
            assert not any('Assistência concluída' in item for item in tui.transcript_entries)
    asyncio.run(run())


def test_tui_validate_cancel_waits_for_real_process_cleanup(app, tmp_path):
    from dataclasses import replace
    from python_lab.runtime.processes import ProcessRunner
    from python_lab.tui.widgets import Composer
    import os
    from tests.test_process_runner import process_is_alive
    pid_file = tmp_path / 'child.pid'
    child_code = f"import os, pathlib, time; pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid())); time.sleep(60)"
    test_code = f"import subprocess, sys, time\ndef test_slow(solution):\n    child = subprocess.Popen([sys.executable, '-c', {child_code!r}])\n    time.sleep(60)\n"
    class Runner:
        def __init__(self):
            self.results = []
        def run(self, *args, **kwargs):
            result = ProcessRunner().run(*args, **kwargs)
            self.results.append(result)
            return result
    runner = Runner()
    tui = PythonLabTUI(app)
    tui.cli.learning = learning(app, tmp_path / 'state')
    tui.cli.learning.exercises.runner = runner
    tui.cli.learning.exercises.save_draft(replace(sample_draft(), tests=test_code))
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/exercise-validate custom-sum')
            await pilot.pause()
            await pilot.press('y')
            deadline = time.monotonic() + 5
            while not pid_file.exists() and time.monotonic() < deadline:
                await asyncio.sleep(.01)
            assert pid_file.exists()
            pid = int(pid_file.read_text())
            tui._submit('/cancel')
            assert tui._assistant_task is not None  # action slot held during cleanup
            await finished(tui)
            assert runner.results and runner.results[0].cancelled
            assert not process_is_alive(pid)
            assert not tui.query_one('#composer', Composer).disabled
            assert not (tmp_path / 'state' / 'custom_catalog').exists()
    asyncio.run(run())


def test_learning_cannot_start_while_test_worker_is_active(app, tmp_path, monkeypatch):
    import threading
    from python_lab.models import TestResult
    started = threading.Event()
    def run_tests(*, cancel=None):
        started.set()
        assert cancel.wait(5)
        return TestResult(False, -1, '', cancelled=True)
    monkeypatch.setattr(app, 'run_current_tests', run_tests)
    provider = DraftProvider()
    tui = PythonLabTUI(app)
    tui.cli.learning = learning(app, tmp_path / 'state', provider)
    app.start('001')
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/test')
            assert await asyncio.to_thread(started.wait, 5)
            tui._submit('/exercise soma')
            await pilot.pause()
            assert tui._assistant_task is None
            assert not provider.requests
            tui.action_quit_lab()
            deadline = time.monotonic() + 5
            while tui._testing and time.monotonic() < deadline:
                await asyncio.sleep(.01)
            assert not tui._testing
    asyncio.run(run())


def test_tui_supplied_service_shares_provider_and_output_budget(tmp_path, monkeypatch):
    from pathlib import Path
    from python_lab.analysis.service import AnalysisService
    from python_lab.assistant.history import ConversationRepository
    from python_lab.assistant.models import AssistantAnswer, Usage
    from python_lab.assistant.provider import UsageBudget
    from python_lab.assistant.service import AssistantService
    from python_lab.cli import build_app
    root = Path(__file__).resolve().parents[1]
    state = tmp_path / 'state'
    project = tmp_path / 'project'
    project.mkdir()
    (project / 'code.py').write_text('value = 2\n', encoding='utf-8')
    app = build_app(root, data_dir=state)
    class Provider(DraftProvider):
        def __init__(self):
            super().__init__()
            self.budget = UsageBudget(4)
        async def draft(self, request):
            reservation = self.budget.reserve(2)
            result = await super().draft(request)
            self.budget.settle(reservation, 2)
            return result
        async def generate(self, request):
            reservation = self.budget.reserve(2)
            self.requests.append(request)
            self.budget.settle(reservation, 2)
            return AssistantAnswer('Inspect the value', 'The assignment stores two.', (), (), 0, Usage(1, 2))
    provider = Provider()
    service = AssistantService(provider, AnalysisService(), ConversationRepository(state / 'lab.sqlite3'))
    tui = PythonLabTUI(app, assistant_project=project, assistant_service=service)
    runtime_calls = []
    def unavailable():
        runtime_calls.append('unexpected second provider')
        raise AssertionError('Injected service must avoid initializing the runtime provider')
    monkeypatch.setattr(tui.cli.assistant_runtime, 'get_service', unavailable)
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/practice')  # build cached learning handlers before injection
            cached = tui.cli.learning
            tui._submit('/exercise soma')
            await finished(tui)
            assert (state / 'exercise_drafts' / 'custom-sum').exists(), tui.transcript_entries
            assert tui.cli.learning is cached
            tui._submit('/explain-code code.py')
            await finished(tui)
            assert [request.action for request in provider.requests] == ['exercise', 'explain']
            assert not runtime_calls
            from python_lab.assistant.errors import AssistantError
            import pytest
            with pytest.raises(AssistantError, match='orçamento'):
                provider.budget.reserve(1)  # both sends charged the same four-token budget
    asyncio.run(run())


def test_reference_confirmation_waits_for_delayed_real_draft_read(app, tmp_path, monkeypatch):
    import threading
    app.start('001')
    tui = PythonLabTUI(app)
    tui.cli.learning = learning(app, tmp_path / 'state')
    service = tui.cli.learning.exercises
    service.save_draft(sample_draft())
    entered, release = threading.Event(), threading.Event()
    original_read = service._read
    def delayed_read(path):
        entered.set()
        assert release.wait(5), 'Read was not released'
        return original_read(path)
    monkeypatch.setattr(service, '_read', delayed_read)
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/exercise-show custom-sum --reference --yes')
            try:
                assert await asyncio.to_thread(entered.wait, 5)
                await pilot.pause()
                # Pilot idleness does not mean the shielded worker completed.
                assert tui._assistant_task is not None
                assert not isinstance(tui.screen, ConfirmScreen)
                assert app.current_progress().max_assistance_level == 0
                # The actual read completes on the next event-loop turn.
                asyncio.get_running_loop().call_soon(release.set)
                await confirmation(tui)
                assert 'nível 4' in tui.screen._diff
                await pilot.press('escape')
                await finished(tui)
                assert app.current_progress().max_assistance_level == 0
            finally:
                release.set()
    asyncio.run(run())


def test_reference_confirmation_wait_reports_actual_read_failure(app, tmp_path):
    import pytest
    app.start('001')
    tui = PythonLabTUI(app)
    tui.cli.learning = learning(app, tmp_path / 'state')
    path = tui.cli.learning.exercises.save_draft(sample_draft())
    (path / 'reference_solution.py').unlink()
    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit('/exercise-show custom-sum --reference --yes')
            with pytest.raises(AssertionError, match='Material de draft incompleto'):
                await confirmation(tui)
            assert tui._assistant_task is None
            assert app.current_progress().max_assistance_level == 0
            assert not isinstance(tui.screen, ConfirmScreen)
    asyncio.run(run())
