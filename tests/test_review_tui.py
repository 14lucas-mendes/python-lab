import asyncio
import time

import pytest
from textual.widgets import Static

from python_lab.cli import AssistantRuntime
from python_lab.tui.app import PythonLabTUI
from python_lab.tui.screens import ConfirmScreen
from tests.test_review_cli import proposal


async def wait_action(tui):
    deadline = time.monotonic() + 5
    while tui._assistant_task is not None and time.monotonic() < deadline:
        await asyncio.sleep(.01)
    assert tui._assistant_task is None


@pytest.mark.parametrize('confirm', [False, True])
def test_tui_diff_confirmation_preserves_or_applies_bytes(app, tmp_path, confirm):
    source = tmp_path / 'bug.py'
    source.write_text('x=1\n')
    patch = proposal(tmp_path, tmp_path, text='x=2\n')
    tui = PythonLabTUI(app, assistant_project=tmp_path)
    tui.cli.assistant_runtime = AssistantRuntime(tmp_path, app)

    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit(f'/apply {patch.id}')
            for _ in range(200):
                if isinstance(tui.screen, ConfirmScreen):
                    break
                await asyncio.sleep(.01)
            assert isinstance(tui.screen, ConfirmScreen)
            assert tui._assistant_task is not None
            literal = str(tui.screen.query_one('#patch-diff', Static).render())
            assert str(source.resolve()) in literal and '+x=2' in literal and '-x=1' in literal
            assert source.read_text() == 'x=1\n'
            await pilot.pause()
            await pilot.press('y' if confirm else 'escape')
            await wait_action(tui)
            assert source.read_text() == ('x=2\n' if confirm else 'x=1\n')
    asyncio.run(run())


def test_tui_changed_source_at_confirmation_rejects_write(app, tmp_path):
    source = tmp_path / 'bug.py'
    source.write_text('x=1\n')
    patch = proposal(tmp_path, tmp_path, text='x=2\n')
    tui = PythonLabTUI(app, assistant_project=tmp_path)
    tui.cli.assistant_runtime = AssistantRuntime(tmp_path, app)

    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit(f'/apply {patch.id}')
            for _ in range(200):
                if isinstance(tui.screen, ConfirmScreen):
                    break
                await asyncio.sleep(.01)
            assert isinstance(tui.screen, ConfirmScreen)
            source.write_text('external=3\n')
            await pilot.pause()
            await pilot.press('y')
            await wait_action(tui)
            assert source.read_text() == 'external=3\n'
            assert 'alterado' in '\n'.join(tui.transcript_entries)
    asyncio.run(run())


def test_tui_cancel_during_diff_confirmation_closes_modal_without_write(app, tmp_path):
    source = tmp_path / 'bug.py'
    source.write_text('x=1\n')
    patch = proposal(tmp_path, tmp_path, text='x=2\n')
    tui = PythonLabTUI(app, assistant_project=tmp_path)
    tui.cli.assistant_runtime = AssistantRuntime(tmp_path, app)

    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit(f'/apply {patch.id} --yes')
            for _ in range(200):
                if isinstance(tui.screen, ConfirmScreen):
                    break
                await asyncio.sleep(.01)
            assert isinstance(tui.screen, ConfirmScreen)
            tui._submit('/cancel')
            await wait_action(tui)
            await pilot.pause()
            assert not isinstance(tui.screen, ConfirmScreen)
            assert source.read_text() == 'x=1\n'
    asyncio.run(run())


def test_tui_unmount_with_pending_confirmation_preserves_bytes(app, tmp_path):
    source = tmp_path / 'bug.py'
    source.write_text('x=1\n')
    patch = proposal(tmp_path, tmp_path, text='x=2\n')
    tui = PythonLabTUI(app, assistant_project=tmp_path)
    tui.cli.assistant_runtime = AssistantRuntime(tmp_path, app)

    async def run():
        async with tui.run_test() as pilot:
            await pilot.pause()
            tui._submit(f'/apply {patch.id}')
            for _ in range(200):
                if isinstance(tui.screen, ConfirmScreen):
                    break
                await asyncio.sleep(.01)
            assert isinstance(tui.screen, ConfirmScreen)
            await pilot.pause()
        assert source.read_text() == 'x=1\n'
    asyncio.run(run())


@pytest.mark.parametrize("cleanup_failed", [False, True])
def test_tui_verify_cancellation_keeps_slot_until_actual_process_cleanup(app, tmp_path, cleanup_failed):
    import threading
    from python_lab.runtime.processes import ProcessCleanupError, ProcessRunner
    from python_lab.workspace import Workspace
    from tests.test_process_runner import assert_tree_stopped

    project = tmp_path / 'project'
    project.mkdir()
    (project / 'bug.py').write_text('x=1\n')
    child = (
        "import os,time\nfrom pathlib import Path\n"
        "Path('ready').write_text(str(os.getpid()))\n"
        "while not Path('release').exists(): time.sleep(.01)\n"
        "Path('leaked').write_text('survived')\ntime.sleep(30)\n"
    )
    (project / 'test_tree.py').write_text(
        "import subprocess,sys,time\n"
        "def test_child():\n"
        f"    subprocess.Popen([sys.executable, '-c', {child!r}], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "    time.sleep(30)\n"
    )
    state = tmp_path / 'patch-state'
    patch = proposal(project, state, text='x=2\n')
    runtime = AssistantRuntime(state, app)
    commands = runtime.commands(Workspace(project), 'assistant', app=app)
    assert asyncio.run(commands.apply((patch.id, '--yes'))).ok
    cleaned, release_worker = threading.Event(), threading.Event()

    class Runner(ProcessRunner):
        def run(self, *args, **kwargs):
            result = super().run(*args, **kwargs)
            cleaned.set()
            assert release_worker.wait(5)
            if cleanup_failed:
                raise ProcessCleanupError("cleanup could not be confirmed")
            return result

    commands.verification.runner = Runner()
    tui = PythonLabTUI(app, assistant_project=project)
    tui.cli.assistant_runtime = runtime
    tui.cli.assistant_handlers = lambda **kwargs: commands

    async def run():
        try:
            async with tui.run_test() as pilot:
                await pilot.pause()
                tui._submit(f'/verify {patch.id} --check pytest')
                deadline = time.monotonic() + 10
                while not (project / 'ready').exists() and time.monotonic() < deadline:
                    await asyncio.sleep(.01)
                assert (project / 'ready').exists()
                tui._submit('/cancel')
                assert await asyncio.to_thread(cleaned.wait, 5)
                assert_tree_stopped(project)
                assert tui._assistant_task is not None
                tui._submit('/new cli must-not-start --path ignored')
                assert 'Ação em curso' in tui.transcript_entries[-1]
                release_worker.set()
                await wait_action(tui)
                transcript = '\n'.join(tui.transcript_entries)
                if cleanup_failed:
                    assert 'cleanup could not be confirmed' in transcript
                else:
                    assert 'Ação cancelada' in transcript
        finally:
            release_worker.set()
    asyncio.run(run())
