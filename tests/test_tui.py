import asyncio

import pytest

from textual.widgets import Input, Static, TextArea

from python_lab.models import TestResult as RunnerResult
from python_lab.session import SessionLog
from python_lab.test_runner import solution_fingerprint
from python_lab.tui.app import PythonLabTUI
from python_lab.tui.screens import ConfirmScreen, PlanScreen
from python_lab.tui.widgets import CommandPalette, Composer


def _text(widget) -> str:
    return str(widget.renderable)


def _transcript(tui: PythonLabTUI) -> str:
    return "\n".join(tui.transcript_entries)


def _drive(lab, callback, session_log=None):
    session = session_log or SessionLog(lab.repository.path)
    if session._current is None:
        session.start()
    tui = PythonLabTUI(lab=lab, session_log=session)

    async def run() -> None:
        async with tui.run_test(size=(140, 40), notifications=True) as pilot:
            await pilot.pause()
            await callback(tui, pilot)

    asyncio.run(run())
    return tui, session


async def _submit(tui: PythonLabTUI, pilot, line: str) -> None:
    composer = tui.query_one("#composer", Composer)
    composer.focus()
    composer.value = line
    await pilot.press("enter")
    await pilot.pause()


async def _wait_tests(tui, pilot) -> None:
    await pilot.pause()
    if tui.workers:
        await tui.workers.wait_for_complete()
    await pilot.pause()


def test_tui_shows_banner_next_step_and_composer(app):
    async def scenario(tui, _pilot):
        transcript = _transcript(tui)
        assert "Python Lab" in transcript or "001" in transcript
        header = _text(tui.query_one("#mission-header", Static))
        assert "Ciclo" in header
        assert "Lógica, decomposição e Python core" in header
        assert "/start" in _text(tui.query_one("#next-step", Static))
        composer = tui.query_one("#composer", Composer)
        assert composer.placeholder == "Digite / para comandos"
        assert not tui.query_one("#palette", CommandPalette).display

    _drive(app, scenario)


def test_tui_slash_menu_filters_and_starts_mission(app):
    async def scenario(tui, pilot):
        composer = tui.query_one("#composer", Composer)
        composer.focus()
        await pilot.press("/")
        await pilot.pause()
        palette = tui.query_one("#palette", CommandPalette)
        assert palette.display
        assert palette.option_count > 1
        await pilot.press(*list("start"))
        await pilot.pause()
        assert palette.display
        prompts = [str(palette.get_option_at_index(index).prompt) for index in range(palette.option_count)]
        assert any("/start" in prompt for prompt in prompts)
        await pilot.press("enter")
        await pilot.pause()
        assert composer.value == "/start "
        await pilot.press(*list("001"), "enter")
        await pilot.pause()
        assert tui.lab.progress.current_mission_id == "001"
        assert "› /start 001" in tui.transcript_entries
        assert "/plan" in _text(tui.query_one("#next-step", Static))

    tui, session = _drive(app, scenario)
    commands = [event["command"] for event in session.current_events()]
    assert any(command.startswith("/start") for command in commands)


def test_tui_saves_plan_with_accents(app):
    app.start("001")

    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/plan")
        assert isinstance(tui.screen, PlanScreen)
        tui.query_one("#plan-input", Input).value = "dicionários"
        tui.query_one("#plan-output", Input).value = "totais por equipamento"
        tui.query_one("#plan-steps", TextArea).load_text("acumular e comparar")
        tui.query_one("#plan-risks", TextArea).load_text("lista vazia")
        await pilot.click("#plan-save")
        await pilot.pause()
        plan = tui.lab.current_progress().plan
        assert plan["input"] == "dicionários"
        assert "dicionários" in _transcript(tui)

    _drive(app, scenario)
    reloaded = app.repository.load()
    assert reloaded.missions["001"].plan["input"] == "dicionários"


def test_tui_runs_passing_and_failing_tests(app, monkeypatch):
    app.start("001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    results = iter(
        [
            RunnerResult(False, 1, "falha visível", summary="1 teste(s): 0 aprovado(s), 1 falho(s)"),
            RunnerResult(True, 0, "===== 1 passed =====", summary="1 teste(s): 1 aprovado(s)"),
        ]
    )
    monkeypatch.setattr(app, "run_current_tests", lambda **kwargs: next(results))

    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/test")
        await _wait_tests(tui, pilot)
        assert "falharam" in _transcript(tui)
        assert "falha visível" not in _transcript(tui)
        await _submit(tui, pilot, "/test details")
        assert "falha visível" in _transcript(tui)
        assert tui.last_test_result is not None
        assert tui.last_test_result.passed is False

        await _submit(tui, pilot, "/test")
        await _wait_tests(tui, pilot)
        assert "passaram" in _transcript(tui)
        assert tui.last_test_result is not None
        assert tui.last_test_result.passed is True

    _drive(app, scenario)


def test_tui_hint_before_test_notifies_without_crash(app):
    app.start("001")

    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/hint")
        assert tui.lab.current_progress().hints_revealed == 0
        assert tui.lab.current_progress().attempts == 0
        assert not tui._exit
        assert "Execute /test" in _transcript(tui)

    _drive(app, scenario)


def test_tui_reference_hint_asks_for_confirmation(app):
    app.start("001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    app.current_progress().attempts = 1
    app.persist()

    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/hint")
        assert tui.lab.current_progress().hints_revealed == 1
        await _submit(tui, pilot, "/hint")
        assert isinstance(tui.screen, ConfirmScreen)
        await pilot.click("#confirm-yes")
        await pilot.pause()
        assert tui.lab.current_progress().hints_revealed == 2
        assert "Pista conceitual" in _transcript(tui)

    _drive(app, scenario)


def test_tui_explain_completes_mission(app):
    app.start("001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    solution = app.repository.path.parent / "solution.py"
    solution.write_text("def solve():\n    return 1\n", encoding="utf-8")
    progress = app.current_progress()
    progress.tests_passed = True
    progress.tested_solution_path = str(solution)
    progress.tested_solution_fingerprint = solution_fingerprint(solution)
    app.persist()

    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/explain")
        await pilot.pause()
        tui.query_one("#explain-text", TextArea).load_text(
            "Usei um dicionário para acumular os totais."
        )
        await pilot.click("#explain-save")
        await pilot.pause()
        assert tui.lab.progress.missions["001"].status == "completed"
        assert tui.lab.progress.current_mission_id is None
        assert any(item["mission"] == "001" for item in tui.lab.progress.evidence)
        assert "conclu" in _transcript(tui).lower()

    _drive(app, scenario)


def test_tui_quit_with_empty_composer_closes_session(app):
    session = SessionLog(app.repository.path)
    session.start()

    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/start 001")
        composer = tui.query_one("#composer", Composer)
        composer.focus()
        composer.value = ""
        await pilot.press("q")
        await pilot.pause()
        assert tui._exit

    _drive(app, scenario, session_log=session)
    assert session._current is not None
    assert session._current.get("ended_at") is not None
    commands = [event["command"] for event in session.current_events()]
    assert any(command.startswith("/start") for command in commands)


def test_tui_exit_command_closes_session(app):
    session = SessionLog(app.repository.path)
    session.start()

    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/exit")
        await pilot.pause()
        assert tui._exit

    _drive(app, scenario, session_log=session)
    assert session._current is not None
    assert session._current.get("ended_at") is not None


@pytest.mark.parametrize("text", ["", "  \n\t"])
def test_blank_explanation_never_reads_stdin(app, monkeypatch, text):
    from rich.console import Console
    from python_lab.tui.screens import ExplainScreen

    app.start("001")
    def forbidden(*args):
        raise AssertionError("TUI read stdin")
    monkeypatch.setattr(Console, "input", forbidden)
    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/explain")
        tui.query_one("#explain-text", TextArea).load_text(text)
        await pilot.click("#explain-save")
        await pilot.pause()
        assert isinstance(tui.screen, ExplainScreen)
        assert tui.lab.current_progress().explanation is None
        assert "vazia" in _text(tui.query_one("#explain-error", Static))
    _drive(app, scenario)


@pytest.mark.parametrize("exit_key", ["q", "/exit"])
def test_tui_conflict_can_exit_without_overwriting(app, exit_key):
    from python_lab.progress import ProgressRepository

    app.start("001")
    other = ProgressRepository(app.repository.path)
    newer = other.load()
    newer.missions["001"].explanation = "Outra sessão"
    other.save(newer)
    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/explain Texto antigo")
        assert "Conflito de progresso" in _transcript(tui)
        assert tui.lab.current_progress().explanation is None
        if exit_key == "q":
            await pilot.press("q")
            await pilot.pause()
        else:
            await _submit(tui, pilot, exit_key)
        assert tui._exit
    _drive(app, scenario)
    assert other.load().missions["001"].explanation == "Outra sessão"


def test_tui_history_failures_remain_visible_and_allow_exit(app, monkeypatch):
    from python_lab.session import SessionError

    log = SessionLog(app.repository.path)
    log.start()
    def fail(*args):
        raise SessionError("histórico indisponível")
    monkeypatch.setattr(log, "record", fail)
    monkeypatch.setattr(log, "close", fail)
    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/mission 001")
        assert "histórico indisponível" in _transcript(tui)
        await _submit(tui, pilot, "/exit")
        assert tui._exit
        assert "histórico indisponível" in _transcript(tui)
    _drive(app, scenario, log)


def test_tui_unreadable_fingerprint_keeps_composer_available(app, monkeypatch):
    app.start("001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    progress = app.current_progress()
    progress.tests_passed = True
    progress.tested_solution_path = str(app.current_mission().solution_path)
    app.persist()
    def fail(path):
        raise PermissionError("sem permissão")
    monkeypatch.setattr("python_lab.app.solution_fingerprint", fail)
    async def scenario(tui, pilot):
        assert "sem permissão" in _transcript(tui)
        await _submit(tui, pilot, "/help")
        assert "Comandos" in _transcript(tui)
        await pilot.press("q")
        await pilot.pause()
        assert tui._exit
    _drive(app, scenario)


def test_worker_cancellation_waits_for_real_process_cleanup(app, tmp_path):
    import time
    from dataclasses import replace
    from tests.test_process_runner import tree_command, assert_tree_stopped

    command = tree_command(tmp_path)
    suite = tmp_path / "test_hanging_tree.py"
    suite.write_text(
        "import subprocess\n"
        "def test_tree():\n"
        f"    subprocess.run({command!r}, check=True)\n"
    )
    app.missions[0] = replace(app.missions[0], test_path=suite)
    app.start("001")
    app.save_plan(dict(input="x", output="y", steps="z", risks="w"))

    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/test")
        deadline = time.monotonic() + 5
        while not (tmp_path / "ready").exists() and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        assert (tmp_path / "ready").exists(), "Descendant never became ready"
        worker = next(worker for worker in tui.workers if worker.name == "run-tests")
        worker.cancel()
        assert tui._testing
        assert tui.query_one("#composer", Composer).disabled
        deadline = time.monotonic() + 5
        while tui._testing and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        assert not tui._testing, "Cancellation never completed process cleanup"
        assert_tree_stopped(tmp_path)
        assert not tui.query_one("#composer", Composer).disabled
        assert tui.last_test_result is None
        assert not app.current_progress().tests_passed
        assert not app.current_progress().attempt_history
        assert not app.repository.load().missions["001"].tests_passed
        assert not any(event["command"] == "/test" for event in tui.session_log.current_events())
        assert "cancelad" in _transcript(tui).lower()

    _drive(app, scenario)


def test_cancelling_pending_worker_restores_composer(app):
    import time
    app.start("001")
    app.save_plan(dict(input="x", output="y", steps="z", risks="w"))

    async def scenario(tui, pilot):
        tui._run_tests()
        worker = next(worker for worker in tui.workers if worker.name == "run-tests")
        worker.cancel()
        deadline = time.monotonic() + 2
        while tui._testing and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        assert not tui._testing
        assert not tui.query_one("#composer", Composer).disabled
        assert app.current_progress().attempts == 0

    _drive(app, scenario)


@pytest.mark.parametrize("phase", ["save", "callback"])
@pytest.mark.parametrize("save_error", [False, True])
def test_late_worker_cancel_preserves_accepted_completion(app, monkeypatch, phase, save_error):
    import threading
    import time
    from python_lab.storage.errors import ProgressError

    app.start("001")
    app.save_plan(dict(input="x", output="y", steps="z", risks="w"))
    accepted = RunnerResult(True, 0, "accepted passing result", summary="1 aprovado")
    monkeypatch.setattr("python_lab.app.run_tests", lambda *args, **kwargs: accepted)
    entered = threading.Event()
    release = threading.Event()
    original_save = app.repository.save

    def save(progress):
        if phase == "save":
            entered.set()
            assert release.wait(5), "Save barrier was not released"
        if save_error:
            raise ProgressError("controlled save failure")
        original_save(progress)

    monkeypatch.setattr(app.repository, "save", save)

    async def scenario(tui, pilot):
        queued = []
        original_call = tui.call_from_thread

        def call(callback, *args, **kwargs):
            if phase == "callback" and callback == tui._on_tests_finished:
                queued.append((callback, args))
                entered.set()
                assert release.wait(5), "Callback barrier was not released"
                return None
            return original_call(callback, *args, **kwargs)

        monkeypatch.setattr(tui, "call_from_thread", call)
        tui._run_tests()
        deadline = time.monotonic() + 5
        while not entered.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        try:
            assert entered.is_set(), "Action did not reach the barrier"
            tui._test_worker.cancel()
            assert tui._testing
            assert tui.query_one("#composer", Composer).disabled
        finally:
            release.set()
        if phase == "callback":
            if not save_error:
                # A different repository may save newer user state before the
                # completion callback. Cancellation must not restore an older
                # snapshot over that writer's durable changes.
                from python_lab.progress import ProgressRepository
                other = ProgressRepository(app.repository.path)
                newer = other.load()
                newer.missions["001"].hints_revealed = 1
                other.save(newer)
            callback, args = queued.pop()
            callback(*args)
        deadline = time.monotonic() + 5
        while tui._testing and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        assert not tui._testing
        assert not tui.query_one("#composer", Composer).disabled
        saved = app.repository.load().missions["001"]
        if phase == "callback" and not save_error:
            assert saved.hints_revealed == 1
        progress = app.current_progress()
        events = [event for event in tui.session_log.current_events() if event["command"] == "/test"]
        assert len(events) == 1
        assert "cancelad" not in _transcript(tui).lower()
        if save_error:
            assert "controlled save failure" in _transcript(tui)
            assert not saved.tests_passed and not progress.tests_passed
            assert saved.attempts == progress.attempts == 0
            assert not saved.attempt_history and not progress.attempt_history
            assert app.last_test_result() is None and tui.last_test_result is None
        else:
            assert "passaram" in _transcript(tui)
            assert saved.tests_passed and progress.tests_passed
            assert saved.attempts == progress.attempts == 1
            assert saved.attempt_history == progress.attempt_history
            assert len(saved.attempt_history) == 1 and saved.attempt_history[0]["passed"]
            assert app.last_test_result() is accepted and tui.last_test_result is accepted

    _drive(app, scenario)


@pytest.mark.parametrize("quit_via", ["action", "key"])
def test_ctrl_c_during_tests_waits_for_descendant_cleanup_before_exit(app, tmp_path, quit_via):
    import time
    from dataclasses import replace
    from tests.test_process_runner import tree_command, assert_tree_stopped

    command = tree_command(tmp_path)
    suite = tmp_path / 'test_hanging_tree.py'
    suite.write_text('import subprocess\ndef test_tree():\n' + f'    subprocess.run({command!r}, check=True)\n')
    app.missions[0] = replace(app.missions[0], test_path=suite)
    app.start('001')
    app.save_plan(dict(input='x', output='y', steps='z', risks='w'))

    async def scenario(tui, pilot):
        await _submit(tui, pilot, '/test')
        deadline = time.monotonic() + 5
        while not (tmp_path / 'ready').exists() and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        assert (tmp_path / 'ready').exists()
        if quit_via == "key":
            await pilot.press("ctrl+c")
        else:
            tui.action_quit_lab()
        premature_exit = tui._exit and not tui._test_cleanup_done.is_set()
        if premature_exit and tui._test_worker is not None:
            # RED cleanup so the old implementation does not leak a process.
            tui._test_worker.cancel()
            deadline = time.monotonic() + 5
            while tui._testing and time.monotonic() < deadline:
                await asyncio.sleep(.01)
        assert not premature_exit, 'TUI exited before test process cleanup'
        deadline = time.monotonic() + 5
        while not tui._exit and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        assert tui._exit
        assert_tree_stopped(tmp_path)
        assert app.current_progress().attempts == 0
        assert not app.current_progress().attempt_history
    _drive(app, scenario)
