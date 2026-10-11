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
            assert isinstance(tui.screen, ConfirmScreen)
            assert 'privilégios' in tui.screen._diff
            assert str(tmp_path / 'state') in tui.screen._diff
            await pilot.press('escape')
            await finished(tui)
            assert not (tmp_path / 'state' / 'exercise_validations').exists()
            tui._submit('/exercise-publish custom-sum')
            await pilot.pause()
            assert isinstance(tui.screen, ConfirmScreen)
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
            assert isinstance(tui.screen, ConfirmScreen)
            await pilot.press('y')
            await finished(tui)
            assert any('Revisão didática' in entry for entry in tui.transcript_entries)
            tui._submit('/exercise-publish custom-sum')
            await pilot.pause()
            assert isinstance(tui.screen, ConfirmScreen)
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
            assert isinstance(tui.screen, ConfirmScreen)
            await pilot.press('escape')
            await finished(tui)
            assert app.current_progress().max_assistance_level == 0
            tui._submit('/exercise-show custom-sum --reference')
            await pilot.pause()
            assert isinstance(tui.screen, ConfirmScreen)
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
