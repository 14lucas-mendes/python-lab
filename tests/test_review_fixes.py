import asyncio
from pathlib import Path

import pytest
from rich.console import Console
from textual.widgets import Static, TextArea

from python_lab.catalog import load_missions
from python_lab.cli import PythonLabCLI
from python_lab.learning import CompletionError
from python_lab.models import TestResult as RunnerResult
from python_lab.session import SessionLog
from python_lab.test_runner import solution_fingerprint
from python_lab.tui.app import PythonLabTUI
from python_lab.tui.screens import ExplainScreen, PlanScreen


def _approved_solution(app, tmp_path):
    app.start("001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    solution = tmp_path / "solution.py"
    solution.write_text("x = 1", encoding="utf-8")
    progress = app.current_progress()
    progress.tests_passed = True
    progress.tested_solution_path = str(solution)
    progress.tested_solution_fingerprint = solution_fingerprint(solution)


@pytest.mark.parametrize("error_type", [PermissionError, FileNotFoundError, OSError])
def test_test_read_error_does_not_count_attempt_and_can_retry(app, monkeypatch, error_type):
    app.start("001")
    plan = {"input": "x", "output": "y", "steps": "z", "risks": "w"}
    app.save_plan(plan)
    console = Console(record=True, width=120)
    cli = PythonLabCLI(app, console)

    def unreadable(_path):
        raise error_type("Arquivo em uso pelo editor")

    def unexpected_run(*args):
        pytest.fail("Os testes não devem executar se a solução não pôde ser lida")

    with monkeypatch.context() as patch:
        patch.setattr("python_lab.app.solution_fingerprint", unreadable)
        patch.setattr("python_lab.app.run_tests", unexpected_run)
        assert cli.execute("/test") is True
    output = console.export_text()
    assert "Não foi possível ler a solução" in output
    assert "tente novamente" in output
    assert app.current_progress().attempts == 0
    assert app.current_progress().attempt_history == []
    assert app.last_test_result() is None
    # A later save must not persist an attempt that never ran.
    app.save_plan(plan)
    stored = app.repository.load().missions["001"]
    assert stored.attempts == 0
    assert stored.attempt_history == []

    monkeypatch.setattr("python_lab.app.run_tests", lambda *args: RunnerResult(True, 0, "Teste aprovado"))
    assert cli.execute("/test") is True
    assert app.current_progress().attempts == 1
    assert len(app.current_progress().attempt_history) == 1
    assert app.last_test_result().passed is True


@pytest.mark.parametrize("error_type", [PermissionError, FileNotFoundError, OSError])
def test_unreadable_solution_is_not_current_and_cannot_complete(app, tmp_path, monkeypatch, error_type):
    _approved_solution(app, tmp_path)
    app.save_explanation("Expliquei a solução.")

    def unreadable(_path):
        raise error_type("Leitura temporariamente indisponível")

    monkeypatch.setattr("python_lab.app.solution_fingerprint", unreadable)
    assert app.tests_are_current() is False
    assert app.next_step() == "Execute /test novamente para a solução atual"
    with pytest.raises(CompletionError, match="execute os testes novamente"):
        app.complete_current_mission()
    assert app.progress.current_mission_id == "001"
    assert app.current_progress().status == "started"
    assert app.progress.evidence == []


@pytest.mark.parametrize("command,screen_type,field_id", [
    ("/plan", PlanScreen, "#plan-steps"),
    ("/explain", ExplainScreen, "#explain-text"),
])
def test_refresh_read_error_preserves_open_form_and_recovers(app, tmp_path, monkeypatch, command, screen_type, field_id):
    _approved_solution(app, tmp_path)
    tui = PythonLabTUI(app)

    def unreadable(_path):
        raise PermissionError("Arquivo em uso pelo editor")

    async def scenario():
        async with tui.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            tui._submit(command)
            await pilot.pause()
            assert isinstance(tui.screen, screen_type)
            field = tui.query_one(field_id, TextArea)
            field.load_text("Texto ainda não salvo\nCom acentuação")
            with monkeypatch.context() as patch:
                patch.setattr("python_lab.app.solution_fingerprint", unreadable)
                tui._refresh_status()
                await pilot.pause()
                assert tui.is_running
                assert isinstance(tui.screen, screen_type)
                assert field.text == "Texto ainda não salvo\nCom acentuação"
                assert "[ ] Testes atuais" in str(tui.screen_stack[0].query_one("#stages", Static).renderable)
                assert "/test" in str(tui.screen_stack[0].query_one("#actions", Static).renderable)
                assert app.current_progress().explanation is None
            tui._refresh_status()
            assert "[x] Testes atuais" in str(tui.screen_stack[0].query_one("#stages", Static).renderable)
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(scenario())


@pytest.mark.parametrize("unreadable", ["encoding", "missing"])
def test_start_with_unreadable_briefing_records_success_and_warning(app, unreadable, add_teaching_content):
    add_teaching_content()
    briefing = app.missions[0].briefing_path
    if unreadable == "encoding":
        briefing.write_bytes(b"\xff")
    else:
        briefing.unlink()
    session = SessionLog(app.project_root / "data" / "sessions.json")
    console = Console(record=True, width=120)
    cli = PythonLabCLI(app, console, session)
    assert cli.execute("/start 001") is True
    assert app.repository.load().current_mission_id == "001"
    assert session.current_events()[0]["summary"] == "Missão 001 iniciada"
    output = console.export_text()
    assert "Aviso:" in output
    if unreadable == "encoding":
        assert "UTF-8" in output
    else:
        assert "Não foi possível ler" in output


@pytest.mark.parametrize("mission_id", ["001", "006"])
def test_pilot_reflection_questions_match_briefing(mission_id):
    root = Path(__file__).resolve().parents[1]
    mission = next(mission for mission in load_missions(root / "missions") if mission.id == mission_id)
    reflection = mission.briefing_path.read_text(encoding="utf-8").split("## Reflexão final", 1)[1].split("\n## ", 1)[0]
    questions = tuple(line[2:] for line in reflection.splitlines() if line.startswith("- "))
    assert questions
    assert mission.reflection_questions == questions
