import pytest

from pathlib import Path

from rich.console import Console

from python_lab.cli import PythonLabCLI
from python_lab.models import Mission, TestResult as RunnerResult
from python_lab.progress import ProgressError
from python_lab.session import SessionLog
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
    assert "/session" in output
    assert "/g" in output
    assert "/?" in output


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


def test_start_shows_summary_readme_and_next_step(app):
    console = Console(record=True, width=200)
    cli = PythonLabCLI(app=app, console=console)

    cli.execute("/start 001")

    output = console.export_text()
    assert "Resumo:" in output
    assert "README.md" in output
    assert "Edite a solução" in output
    assert "Próximo:" in output
    assert "/plan" in output


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
    assert "Ciclo 1" in output
    assert "Ciclos planejados" in output
    assert "HTTP e APIs REST" in output


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


def test_test_output_survives_unencodable_characters(app, monkeypatch):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    cli.execute("/start 001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    monkeypatch.setattr(
        app,
        "run_current_tests",
        lambda: RunnerResult(False, 1, "erro \ufffd utf-8", summary="1 falho"),
    )

    assert cli.execute("/test") is True
    assert cli.execute("/test details") is True
    assert "erro" in console.export_text()


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
    assert cli.execute("/test details") is True
    assert "ValueError: [/audit]" in console.export_text()


def test_persistence_error_is_reported_without_traceback(app):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    cli.execute("/start 001")
    app.current_progress().attempts = 1
    app.persist()
    from python_lab.storage.database import connection
    with connection(app.repository.path) as db:
        db.execute("CREATE TRIGGER reject_help BEFORE UPDATE ON progress BEGIN SELECT RAISE(ABORT, 'falha de disco'); END")
        db.commit()

    assert cli.execute("/hint") is True
    output = console.export_text()
    assert "falha de disco" in output
    assert "Traceback" not in output
    assert app.current_progress().hints_revealed == 0
    with connection(app.repository.path) as db:
        assert db.execute('SELECT COUNT(*) FROM assistance_events').fetchone()[0] == 0


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


def test_aliases_dispatch_to_canonical_commands(app):
    console = Console(record=True, width=120)
    cli = PythonLabCLI(app=app, console=console)
    assert cli.execute("/g") is True
    assert "Automação e Integração de Sistemas com Python" in console.export_text()


def test_command_without_slash_suggests_canonical(app):
    console = Console(record=True)
    cli = PythonLabCLI(app=app, console=console)
    assert cli.execute("test") is True
    assert "Use /test" in console.export_text()


def test_status_includes_next_step(app):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    cli.execute("/start 001")
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    cli.execute("/status")
    output = console.export_text()
    assert "Próximo:" in output
    assert "/plan" in output


def test_passing_tests_hide_raw_pytest_output(app, monkeypatch):
    console = Console(record=True, width=100)
    cli = PythonLabCLI(app=app, console=console)
    cli.execute("/start 001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    monkeypatch.setattr(
        app,
        "run_current_tests",
        lambda: RunnerResult(True, 0, "===== 2 passed =====", summary="2 teste(s): 2 aprovado(s)"),
    )
    assert cli.execute("/test") is True
    output = console.export_text()
    assert "2 teste(s): 2 aprovado(s)" in output
    assert "===== 2 passed =====" not in output


def test_session_records_commands_and_lists_previous(app):
    log = SessionLog(app.repository.path)
    log.start()
    log.record("/help", "Ajuda exibida")
    log.close("Sessão encerrada")

    current = SessionLog(app.repository.path)
    current.start()
    console = Console(record=True, width=120)
    cli = PythonLabCLI(app=app, console=console, session_log=current)
    cli.execute("/start 001")
    cli.execute("/session")
    output = console.export_text()
    assert "Sessão atual" in output
    assert "Missão 001 iniciada" in output
    console = Console(record=True, width=120)
    cli = PythonLabCLI(app=app, console=console, session_log=current)
    cli.execute("/session all")
    assert "Sessões anteriores" in console.export_text()


def test_log_failure_keeps_cli_alive(app, monkeypatch):
    from python_lab.session import SessionError

    log = SessionLog(app.repository.path)
    log.start()
    def fail(*args):
        raise SessionError("histórico indisponível")
    monkeypatch.setattr(log, "record", fail)
    console = Console(record=True, width=120)
    cli = PythonLabCLI(app, console, log)
    assert cli.execute("/status") is True
    assert cli.execute("/unknown") is True
    output = console.export_text()
    assert "histórico indisponível" in output
    assert "Traceback" not in output


def test_try_record_returns_failure_without_recursion(app, monkeypatch):
    from python_lab.session import SessionError

    log = SessionLog(app.repository.path)
    calls = []
    def fail(command, summary):
        calls.append(command)
        raise SessionError("falha de histórico")
    monkeypatch.setattr(log, "record", fail)
    assert log.try_record("/status", "Status") == "falha de histórico"
    assert calls == ["/status"]


def test_history_and_close_failures_allow_exit(app, monkeypatch):
    from python_lab.session import SessionError

    log = SessionLog(app.repository.path)
    log.start()
    def fail(*args):
        raise SessionError("histórico indisponível")
    monkeypatch.setattr(log, "load", fail)
    monkeypatch.setattr(log, "close", fail)
    console = Console(record=True, width=120)
    cli = PythonLabCLI(app, console, log)
    assert cli.execute("/session all") is True
    assert cli.execute("/exit") is False
    assert "histórico indisponível" in console.export_text()


def test_progress_conflict_blocks_mutation_but_allows_exit(app):
    from python_lab.progress import ProgressRepository

    app.start("001")
    other = ProgressRepository(app.repository.path)
    newer = other.load()
    newer.missions["001"].explanation = "Outra sessão"
    other.save(newer)
    console = Console(record=True, width=120)
    cli = PythonLabCLI(app, console)
    assert cli.execute("/explain Estado antigo") is True
    assert app.current_progress().explanation is None
    assert cli.execute("/exit") is False
    assert "Conflito de progresso" in console.export_text()
    assert other.load().missions["001"].explanation == "Outra sessão"


def test_unreadable_fingerprint_is_actionable_without_incrementing_attempt(app, monkeypatch):
    from python_lab.app import ApplicationError
    import pytest

    app.start("001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    def fail(path):
        raise PermissionError("sem permissão")
    monkeypatch.setattr("python_lab.app.solution_fingerprint", fail)
    with pytest.raises(ApplicationError, match="solução"):
        app.run_current_tests()
    assert app.current_progress().attempts == 0
    progress = app.current_progress()
    progress.tests_passed = True
    progress.tested_solution_path = str(app.current_mission().solution_path)
    console = Console(record=True)
    cli = PythonLabCLI(app, console)
    assert cli.execute("/status") is True
    assert cli.execute("/help") is True
    assert "sem permissão" in console.export_text()


def test_removed_active_mission_is_actionable(app):
    from python_lab.app import ApplicationError, PythonLabApp
    import pytest

    app.start("001")
    with pytest.raises(ApplicationError, match="ativa.*001.*catálogo"):
        PythonLabApp(app.goal, app.skills, [], app.repository, app.project_root)


@pytest.mark.parametrize("encoding", ["cp1252", "utf-8"])
def test_supplied_console_preserves_its_encoding_and_supported_text(app, encoding):
    from io import BytesIO, TextIOWrapper
    from rich.panel import Panel

    sink = BytesIO()
    stream = TextIOWrapper(sink, encoding=encoding, errors="strict")
    console = Console(file=stream, width=100)
    cli = PythonLabCLI(app, console)
    cli.console.print(Panel("ação: ✓ → 中文 😀"))
    cli.console.file.flush()
    output = sink.getvalue().decode(encoding)
    expected = "ação: ✓ → 中文 😀" if encoding == "utf-8" else "ação: ? ? ?? ?"
    assert expected in output
    assert cli.console.file.encoding == encoding
    assert stream.encoding == encoding and stream.errors == "strict"
