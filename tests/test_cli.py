from pathlib import Path

from rich.console import Console

from python_lab.cli import PythonLabCLI
from python_lab.models import Mission, TestResult as RunnerResult
from python_lab.progress import ProgressError
from python_lab.test_runner import solution_fingerprint


def test_help_lists_core_commands(app):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    assert cli.execute("/help") is True
    output = console.export_text()
    assert "/goal" in output
    assert "/test" in output
    assert "/explain" in output
    assert "/history" in output
    assert "/evidence" in output


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


def test_start_shows_summary_prerequisites_and_readme(app):
    console = Console(record=True, width=200)
    cli = PythonLabCLI(app=app, console=console)

    cli.execute("/start 001")

    output = console.export_text()
    assert "Resumo:" in output
    assert "Pré-requisitos: nenhum" in output
    assert "README.md" in output


def test_missions_show_blocked_status(app):
    console = Console(record=True, width=120)
    cli = PythonLabCLI(app=app, console=console)
    app.missions.append(
        Mission(
            "002",
            "blocked",
            "Blocked mission",
            "Summary",
            ("functions",),
            ("001",),
            Path("tests"),
            Path("solution.py"),
            ("Hint",),
        )
    )

    cli.execute("/missions")

    output = console.export_text()
    assert "002" in output and "bloqueada" in output


def test_exit_stops_the_loop(app):
    console = Console(record=True)
    cli = PythonLabCLI(app=app, console=console)
    assert cli.execute("/exit") is False


def test_explain_completes_mission_when_requirements_are_met(app):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    assert cli.execute("/start 001") is True
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    solution = app.repository.path.parent / "solution.py"
    solution.write_text("def solve():\n    return 1\n", encoding="utf-8")
    app.current_progress().tests_passed = True
    app.current_progress().tested_solution_path = str(solution)
    app.current_progress().tested_solution_fingerprint = solution_fingerprint(solution)
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


def test_test_requires_complete_plan(app):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    cli.execute("/start 001")

    assert cli.execute("/test") is True
    assert "planejamento" in console.export_text().lower()


def test_hint_requires_a_first_test_attempt(app):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    cli.execute("/start 001")

    assert cli.execute("/hint") is True
    assert "/test" in console.export_text().lower()


def test_test_output_treats_student_text_as_literal(app, monkeypatch):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    cli.execute("/start 001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    monkeypatch.setattr(
        app,
        "run_current_tests",
        lambda: RunnerResult(False, 1, "ValueError: [/audit]"),
    )

    assert cli.execute("/test") is True
    assert "ValueError: [/audit]" in console.export_text()


def test_persistence_error_is_reported_without_traceback(app, monkeypatch):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    cli.execute("/start 001")
    app.current_progress().attempts = 1
    monkeypatch.setattr(
        app.repository,
        "save",
        lambda progress: (_ for _ in ()).throw(ProgressError("falha de disco")),
    )

    assert cli.execute("/hint") is True
    output = console.export_text()
    assert "falha de disco" in output
    assert "Traceback" not in output


def test_explain_rejects_solution_changed_after_passing_tests(app):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    assert cli.execute("/start 001") is True
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    solution = app.repository.path.parent / "solution.py"
    solution.write_text("def solve():\n    return 1\n", encoding="utf-8")
    progress = app.current_progress()
    progress.tests_passed = True
    progress.tested_solution_path = str(solution)
    progress.tested_solution_fingerprint = solution_fingerprint(solution)
    app.persist()
    solution.write_text("def solve(:\n", encoding="utf-8")

    assert cli.execute("/explain Tentei preservar a solução.") is True
    assert "novamente" in console.export_text().lower()
    assert app.progress.missions["001"].status == "started"


def test_history_and_evidence_commands_show_learning_record(app):
    console = Console(record=True, width=120)
    cli = PythonLabCLI(app=app, console=console)
    cli.execute("/start 001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    app.current_progress().attempt_history.append(
        {
            "passed": False,
            "summary": "1 teste: 0 aprovados, 1 falho",
            "return_code": 1,
        }
    )
    cli.execute("/history")
    cli.execute("/evidence")
    output = console.export_text()
    assert "Histórico de tentativas" in output
    assert "1 teste: 0 aprovados, 1 falho" in output
    assert "Nenhuma evidência registrada" in output
