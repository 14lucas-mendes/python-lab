from rich.console import Console

from python_lab.cli import PythonLabCLI


def test_help_lists_core_commands(app):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    assert cli.execute("/help") is True
    output = console.export_text()
    assert "/goal" in output
    assert "/test" in output
    assert "/explain" in output


def test_unknown_command_does_not_crash(app):
    console = Console(record=True)
    cli = PythonLabCLI(app=app, console=console)
    assert cli.execute("/desconhecido") is True
    assert "Comando desconhecido" in console.export_text()


def test_start_and_status_show_current_mission(app):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    assert cli.execute("/start 001") is True
    assert cli.execute("/status") is True
    output = console.export_text()
    assert "001" in output


def test_exit_stops_the_loop(app):
    console = Console(record=True)
    cli = PythonLabCLI(app=app, console=console)
    assert cli.execute("/exit") is False


def test_explain_completes_mission_when_requirements_are_met(app):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    assert cli.execute("/start 001") is True
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    app.current_progress().tests_passed = True
    app.persist()
    assert cli.execute("/explain Usei um dicionario para acumular.") is True
    output = console.export_text()
    assert "conclu" in output.lower()
    assert app.progress.missions["001"].status == "completed"
    assert app.progress.current_mission_id is None
    assert any(item["mission"] == "001" for item in app.progress.evidence)


def test_explain_reports_pending_requirements(app):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    assert cli.execute("/start 001") is True
    assert cli.execute("/explain Tentei algo.") is True
    output = console.export_text()
    assert "rejeitada" in output.lower()
    assert app.progress.missions["001"].status == "started"
