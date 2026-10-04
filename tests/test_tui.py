import asyncio

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
    session = session_log or SessionLog(lab.project_root / "data" / "sessions.json")
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
        tui.query_one("#plan-steps", Input).value = "acumular e comparar"
        tui.query_one("#plan-risks", Input).value = "lista vazia"
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
    monkeypatch.setattr(app, "run_current_tests", lambda: next(results))

    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/test")
        await _wait_tests(tui, pilot)
        assert "falharam" in _transcript(tui)
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
    session = SessionLog(app.project_root / "data" / "sessions.json")
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
    session = SessionLog(app.project_root / "data" / "sessions.json")
    session.start()

    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/exit")
        await pilot.pause()
        assert tui._exit

    _drive(app, scenario, session_log=session)
    assert session._current is not None
    assert session._current.get("ended_at") is not None
