import asyncio
import copy
import json
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from textual.widgets import Input, Static, TextArea
from textual.containers import VerticalScroll

from python_lab.catalog import CatalogError, load_missions
from python_lab.cli import PythonLabCLI
from python_lab.models import TestResult as RunnerResult
from python_lab.test_runner import solution_fingerprint
from python_lab.tui.app import PythonLabTUI
from python_lab.tui.screens import ExplainScreen, PlanScreen
from python_lab.tui.widgets import Composer, cycle_progress


def _cli(app):
    buffer = StringIO()
    return PythonLabCLI(app, Console(file=buffer, record=True, width=120)), buffer


def _run_tui(app, callback, size=(80, 24)):
    tui = PythonLabTUI(app)

    async def scenario():
        async with tui.run_test(size=size) as pilot:
            await pilot.pause()
            await callback(tui, pilot)

    asyncio.run(scenario())


async def _submit(tui, pilot, command):
    composer = tui.query_one("#composer", Composer)
    composer.focus()
    composer.value = command
    await pilot.press("enter")
    await pilot.pause()


def test_catalog_loads_optional_teaching_content_without_requiring_it(app):
    folder = app.missions[0].test_path.parent
    payload = json.loads((folder / "mission.json").read_text(encoding="utf-8"))
    payload.update(learning_objectives=["Agrupar registros."], reflection_questions=["Por quê?"])
    (folder / "mission.json").write_text(json.dumps(payload), encoding="utf-8")
    (folder / "README.md").write_text("# Enunciado", encoding="utf-8")
    mission = load_missions(folder.parent)[0]
    assert mission.learning_objectives == ("Agrupar registros.",)
    assert mission.reflection_questions == ("Por quê?",)
    assert mission.briefing_path == folder / "README.md"
    assert mission.concepts_path is None


@pytest.mark.parametrize("field,value", [("learning_objectives", "texto"), ("reflection_questions", [3]), ("learning_objectives", [""])])
def test_catalog_rejects_invalid_teaching_metadata(app, field, value):
    folder = app.missions[0].test_path.parent
    payload = json.loads((folder / "mission.json").read_text(encoding="utf-8"))
    payload[field] = value
    (folder / "mission.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CatalogError, match=field):
        load_missions(folder.parent)


def test_reading_briefing_and_concepts_is_read_only_even_when_blocked(app, add_teaching_content):
    add_teaching_content()
    app.missions[0] = replace(app.missions[0], prerequisites=("999",))
    before = copy.deepcopy(app.progress)
    seed = app.repository.path.read_bytes()
    cli, buffer = _cli(app)
    cli.execute("/mission 001")
    cli.execute("/concepts 001")
    assert "Lista de registros" in buffer.getvalue()
    assert "Acumulação" in buffer.getvalue()
    assert app.progress == before
    assert app.repository.path.read_bytes() == seed


def test_content_commands_without_current_mission_guide_selection(app):
    cli, buffer = _cli(app)
    cli.execute("/mission")
    cli.execute("/concepts")
    assert "/mission <id>" in buffer.getvalue()
    assert "/concepts <id>" in buffer.getvalue()
    assert app.progress.current_mission_id is None


def test_legacy_missing_content_and_unreadable_optional_content_are_actionable(app, add_teaching_content):
    cli, buffer = _cli(app)
    cli.execute("/mission 001")
    cli.execute("/concepts 001")
    assert "Enunciado indisponível" in buffer.getvalue()
    assert "Apoio conceitual indisponível" in buffer.getvalue()
    add_teaching_content()
    app.missions[0].concepts_path.write_bytes(b"\xff")
    cli.execute("/concepts 001")
    assert "UTF-8" in buffer.getvalue()


def test_start_presents_briefing_and_explain_presents_reflection(app, add_teaching_content):
    add_teaching_content()
    cli, buffer = _cli(app)
    cli.execute("/start 001")
    assert "Lista de registros" in buffer.getvalue()
    cli.execute("/explain Tratei o empate explicitamente.")
    assert "Como você resolve um empate?" in buffer.getvalue()
    assert app.current_progress().explanation == "Tratei o empate explicitamente."


def test_test_details_reuses_last_output_without_new_attempt(app, monkeypatch):
    app.start("001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    monkeypatch.setattr("python_lab.app.run_tests", lambda *args: RunnerResult(False, 1, "SAÍDA COMPLETA [literal]", "Um teste falhou", ("caso vazio: incorreto",)))
    cli, buffer = _cli(app)
    cli.execute("/test")
    assert "caso vazio: incorreto" in buffer.getvalue()
    assert "SAÍDA COMPLETA" not in buffer.getvalue()
    attempts = app.current_progress().attempts
    buffer.seek(0)
    buffer.truncate(0)
    cli.execute("/test details")
    assert "SAÍDA COMPLETA [literal]" in buffer.getvalue()
    assert app.current_progress().attempts == attempts == 1
    fresh_cli, fresh_buffer = _cli(app)
    fresh_cli.execute("/test details")
    assert "SAÍDA COMPLETA" in fresh_buffer.getvalue()


def test_test_details_has_no_result_in_new_session_and_rejects_unknown_args(app):
    cli, buffer = _cli(app)
    cli.execute("/test details")
    cli.execute("/test nonsense")
    assert "Nenhum resultado" in buffer.getvalue()
    assert "Uso:" in buffer.getvalue()
    assert app.progress.current_mission_id is None


def test_stage_progress_detects_solution_edited_after_passing(app, tmp_path):
    app.start("001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    solution = tmp_path / "solution.py"
    solution.write_text("x = 1", encoding="utf-8")
    progress = app.current_progress()
    progress.tests_passed = True
    progress.tested_solution_path = str(solution)
    progress.tested_solution_fingerprint = solution_fingerprint(solution)
    assert cycle_progress(app) == (3, 4)
    solution.write_text("x = 2", encoding="utf-8")
    assert cycle_progress(app) == (2, 4)


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
def test_tui_content_multiline_plan_cancel_and_keyboard_navigation(app, size, add_teaching_content):
    add_teaching_content()

    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/start 001")
        assert tui.query_one("#mission-header").region.height > 0
        assert tui.query_one("#composer").region.bottom <= size[1]
        await _submit(tui, pilot, "/concepts")
        assert "Acumulação" in "\n".join(tui.transcript_entries)
        assert app.current_progress().hints_revealed == 0
        await _submit(tui, pilot, "/plan")
        assert isinstance(tui.screen, PlanScreen)
        tui.query_one("#plan-input", Input).value = "dicionários"
        tui.query_one("#plan-output", Input).value = "totais"
        tui.query_one("#plan-steps", TextArea).load_text("Acumular\nComparar")
        tui.query_one("#plan-risks", TextArea).load_text("Lista vazia\nEmpate")
        await pilot.press("escape")
        await pilot.pause()
        assert app.current_progress().plan is None
        await _submit(tui, pilot, "/plan")
        tui.query_one("#plan-input", Input).value = "dicionários"
        tui.query_one("#plan-output", Input).value = "totais"
        tui.query_one("#plan-steps", TextArea).load_text("Acumular\nComparar")
        tui.query_one("#plan-risks", TextArea).load_text("Lista vazia\nEmpate")
        tui.query_one("#plan-save").focus()
        await pilot.press("enter")
        await pilot.pause()
        assert app.current_progress().plan["steps"] == "Acumular\nComparar"
        assert "Comparar" in "\n".join(tui.transcript_entries)
        await _submit(tui, pilot, "/explain")
        assert isinstance(tui.screen, ExplainScreen)
        assert "empate" in str(tui.query_one("#reflection", Static).renderable)
        await pilot.press("escape")
        await pilot.pause()
        assert app.current_progress().explanation is None

    _run_tui(app, scenario, size)


def test_tui_refreshes_stale_tests_without_a_command(app, tmp_path):
    app.start("001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    solution = tmp_path / "solution.py"
    solution.write_text("x = 1", encoding="utf-8")
    progress = app.current_progress()
    progress.tests_passed = True
    progress.tested_solution_path = str(solution)
    progress.tested_solution_fingerprint = solution_fingerprint(solution)

    async def scenario(tui, pilot):
        assert "[x] Testes atuais" in str(tui.query_one("#stages", Static).renderable)
        solution.write_text("x = 2", encoding="utf-8")
        tui._refresh_status()
        await pilot.pause()
        assert "[ ] Testes atuais" in str(tui.query_one("#stages", Static).renderable)
        assert "/test" in str(tui.query_one("#actions", Static).renderable)

    _run_tui(app, scenario)


def test_tui_test_details_does_not_launch_a_second_worker(app, monkeypatch):
    app.start("001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    monkeypatch.setattr("python_lab.app.run_tests", lambda *args: RunnerResult(False, 1, "DETALHE COMPLETO", "Teste falhou", ("Lista vazia",)))

    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/test")
        await tui.workers.wait_for_complete()
        await pilot.pause()
        assert "DETALHE COMPLETO" not in "\n".join(tui.transcript_entries)
        await _submit(tui, pilot, "/test details")
        assert "DETALHE COMPLETO" in "\n".join(tui.transcript_entries)
        assert app.current_progress().attempts == 1

    _run_tui(app, scenario)


def test_tui_long_content_scrolls_from_composer_and_survives_resize(app, add_teaching_content):
    add_teaching_content()
    app.missions[0].briefing_path.write_text(
        "# Enunciado\n\n" + "\n\n".join(f"Etapa {i}: comparação e validação." for i in range(80)),
        encoding="utf-8",
    )
    before = app.repository.path.read_bytes()

    async def scenario(tui, pilot):
        await _submit(tui, pilot, "/mission 001")
        content = tui.query_one("#content", VerticalScroll)
        assert content.max_scroll_y > 0
        await pilot.press("pagedown")
        await pilot.pause()
        assert content.scroll_y > 0
        await pilot.press("pageup")
        await pilot.pause()
        assert content.scroll_y == 0
        await pilot.resize_terminal(120, 40)
        await pilot.pause()
        await _submit(tui, pilot, "/help")
        assert tui.query_one("#composer").region.bottom <= 40
        assert tui.output_console.width == 116
        assert app.repository.path.read_bytes() == before
        assert app.progress.current_mission_id is None

    _run_tui(app, scenario)


def test_tui_resumes_with_unreadable_briefing_without_crashing(app, add_teaching_content):
    add_teaching_content()
    app.start("001")
    app.missions[0].briefing_path.write_bytes(b"\xff")

    async def scenario(tui, pilot):
        assert "UTF-8" in "\n".join(tui.transcript_entries)
        await _submit(tui, pilot, "/concepts")
        assert "Acumulação" in "\n".join(tui.transcript_entries)

    _run_tui(app, scenario)


def test_cached_output_belongs_to_mission_and_does_not_survive_app_restart(app):
    app.start("001")
    app.remember_test_result(RunnerResult(True, 0, "Resultado de 001"))
    app.missions.append(replace(app.missions[0], id="002"))
    app.start("002")
    cli, buffer = _cli(app)
    cli.execute("/test details")
    assert "Nenhum resultado" in buffer.getvalue()
    assert "Resultado de 001" not in buffer.getvalue()
    app.start("001")
    cli.execute("/test details")
    assert "Resultado de 001" in buffer.getvalue()
    from python_lab.app import PythonLabApp
    restarted = PythonLabApp(app.goal, app.skills, app.missions, app.repository, app.project_root)
    assert restarted.last_test_result() is None
