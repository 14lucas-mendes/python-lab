"""Neutral contracts shared by the classic and Textual adapters."""
import importlib
import subprocess
import sys

import pytest


def commands():
    return importlib.import_module("python_lab.commands")


@pytest.mark.parametrize("quote", ['"', "'"])
def test_parser_preserves_quoted_path(quote):
    command = commands().parse_command(f'/project {quote}C:\\Meus Projetos\\lab{quote}')
    assert command.name == "/project"
    assert command.args == ("C:\\Meus Projetos\\lab",)


@pytest.mark.parametrize("line,args", [
    (r"/project C:\lab", (r"C:\lab",)),
    ('/project "C:\\Meus Projetos\\"', ("C:\\Meus Projetos\\",)),
    (' /T details ', ("details",)),
    ("/explain 'Entrada e saída' sem erros", ("Entrada e saída", "sem", "erros")),
])
def test_parser_handles_aliases_and_arguments(line, args):
    parsed = commands().parse_command(line)
    assert parsed.args == args
    assert parsed.name == ("/test" if line.strip().startswith("/T") else line.split()[0])


def test_parser_rejects_unclosed_quote():
    with pytest.raises(ValueError, match="quot|aspas"):
        commands().parse_command('/project "unfinished')


def test_dispatcher_uses_neutral_results_and_aliases():
    module = commands()
    dispatcher = module.CommandDispatcher()
    received = []
    def handler(args):
        received.append(args)
        return module.CommandResult(True, "done", {"args": list(args)})
    dispatcher.register("/test", handler)
    result = dispatcher.dispatch(module.Command("/t", ("details",)))
    assert received == [("details",)]
    assert result.ok and result.data == {"args": ["details"]}
    assert not result.exit_requested
    dispatcher.register("/exit", lambda args: module.CommandResult(True, "closed", {}, True))
    assert dispatcher.dispatch(module.parse_command("/q")).exit_requested


def test_unknown_dispatch_is_actionable():
    module = commands()
    result = module.CommandDispatcher().dispatch(module.parse_command("/unknown"))
    assert not result.ok and "/help" in result.message


def test_command_module_does_not_import_ui_dependencies():
    code = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'rich', 'textual'}:
            raise AssertionError(fullname)
sys.meta_path.insert(0, Block())
from python_lab.commands import parse_command, CommandDispatcher
assert parse_command('/t details').name == '/test'
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_classic_and_tui_use_the_same_parser(app):
    from rich.console import Console
    from python_lab.cli import PythonLabCLI
    from python_lab.tui.app import PythonLabTUI

    cli = PythonLabCLI(app, Console(record=True))
    assert cli.execute('/mission "001"') is True
    assert "Missão 001" in cli.console.export_text()
    tui = PythonLabTUI(app)
    assert tui._split_command('/mission "001"') == ("/mission", "001")


def test_bad_quotes_leave_classic_and_tui_usable(app):
    from rich.console import Console
    from python_lab.cli import PythonLabCLI
    from python_lab.tui.app import PythonLabTUI
    cli = PythonLabCLI(app, Console(record=True))
    assert cli.execute('/mission "001') is True
    assert "aspas" in cli.console.export_text().lower()
    # Submission errors belong in the transcript; no exception escapes the UI.
    tui = PythonLabTUI(app)
    tui._submit('/mission "001')
    assert "aspas" in tui.transcript_entries[-1].lower()


def test_classic_pilot_journeys_001_and_006(tmp_path):
    """Keep every production file untouched while exercising real mission suites."""
    from dataclasses import replace
    from pathlib import Path
    from shutil import copytree
    from rich.console import Console
    from python_lab.cli import PythonLabCLI, build_app
    from python_lab.session import SessionLog

    root = Path(__file__).resolve().parent.parent
    catalog = tmp_path / "catalog"
    copytree(root / "data", catalog / "data")
    for slug in ("001-consolidar-falhas", "006-classificar-ordens"):
        copytree(root / "missions" / slug, catalog / "missions" / slug)
    app = build_app(catalog, data_dir=tmp_path / "state")
    app.missions = [replace(mission, solution_path=mission.test_path.parent / "reference_solution.py")
                    for mission in app.missions]
    session = SessionLog(app.repository.path)
    session.start()
    console = Console(record=True, width=120)
    cli = PythonLabCLI(app, console, session)
    answers = iter(["Dados da missão", "Contrato de saída", "Compreender e verificar", "Casos extremos"] * 2)
    console.input = lambda prompt="": next(answers)
    for mission_id in ("001", "006"):
        assert cli.execute(f"/mission {mission_id}") is True
        assert app.progress.current_mission_id is None
        assert cli.execute(f"/start {mission_id}") is True
        assert cli.execute("/concepts") is True
        assert app.current_progress().hints_revealed == 0
        assert cli.execute("/p") is True
        assert cli.execute("/t") is True
        assert app.status_snapshot().tests_current, console.export_text()
        assert cli.execute("/test details") is True
        assert app.current_progress().attempts == 1
        assert cli.execute('/e "Verifiquei a precedência e os casos extremos."') is True
        assert app.progress.current_mission_id is None
        assert app.repository.load().missions[mission_id].status == "completed"
    assert cli.execute("/q") is False
    assert not session.is_open
    assert app.repository.path == tmp_path / "state" / "lab.sqlite3"
    assert {item["mission"] for item in app.progress.evidence} == {"001", "006"}
