import pytest

from python_lab.cli import main


def test_external_help_prints_usage_and_exits(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "usage:" in captured.out.lower()
    assert "python-lab" in captured.out
    assert "--classic" in captured.out


def test_external_version_prints_version_and_exits(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "0.3.0" in captured.out


def test_external_argument_is_rejected(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--nonsense"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "argumento inválido" in captured.err.lower()


def test_data_dir_inside_catalog_is_reported_without_traceback(capsys):
    from pathlib import Path

    catalog_data = Path(__file__).resolve().parent.parent / "data"
    assert main(["--data-dir", str(catalog_data)]) == 2
    assert "fora do catálogo" in capsys.readouterr().out


def test_classic_flag_enters_prompt_loop(app, monkeypatch, capsys):
    monkeypatch.setattr("python_lab.cli.build_app", lambda: app)
    monkeypatch.setattr(
        "rich.console.Console.input",
        lambda self, prompt="": "/exit",
    )

    assert main(["--classic"]) == 0
    captured = capsys.readouterr()
    assert "Progresso salvo" in captured.out


def test_default_launches_tui(app, monkeypatch):
    launched = {}

    class FakeTUI:
        def __init__(self, lab, session_log=None):
            launched["lab"] = lab
            launched["session"] = session_log

        def run(self):
            launched["ran"] = True

    monkeypatch.setattr("python_lab.cli.build_app", lambda: app)
    monkeypatch.setattr("python_lab.cli.PythonLabTUI", FakeTUI)

    assert main([]) == 0
    assert launched.get("ran") is True
    assert launched["lab"] is app
    assert launched["session"] is not None
    assert launched["session"]._current is not None
    assert launched["session"]._current.get("ended_at") is not None


@pytest.mark.parametrize("legacy_name,error_type", [("progress.json", "progress"), ("sessions.json", "session")])
@pytest.mark.parametrize("failure", ["directory", "permission"])
def test_first_open_legacy_io_failure_preserves_sources(tmp_path, monkeypatch, legacy_name, error_type, failure):
    from pathlib import Path
    from python_lab.cli import build_app
    from python_lab.progress import ProgressError
    from python_lab.session import SessionError

    root = tmp_path / "catalog"
    legacy = root / "data" / legacy_name
    legacy.parent.mkdir(parents=True)
    if failure == "directory":
        legacy.mkdir()
    else:
        legacy.write_bytes(b"untouched")
        original = Path.read_bytes
        def deny(path):
            if path == legacy:
                raise PermissionError("sem permissão")
            return original(path)
        monkeypatch.setattr(Path, "read_bytes", deny)
    data = tmp_path / "user-data"
    error = ProgressError if error_type == "progress" else SessionError
    with pytest.raises(error, match=legacy_name):
        build_app(root, data_dir=data)
    assert legacy.exists()
    if failure == "permission":
        assert legacy.read_text() == "untouched"
    else:
        assert list(legacy.iterdir()) == []
    assert not (data / "lab.sqlite3").exists()


@pytest.mark.parametrize("termination", [EOFError, KeyboardInterrupt])
def test_classic_interrupt_after_conflict_exits_without_overwriting(app, monkeypatch, termination):
    from python_lab.cli import _run_classic
    from python_lab.progress import ProgressRepository
    from python_lab.session import SessionLog, SessionError
    from rich.console import Console

    app.start("001")
    other = ProgressRepository(app.repository.path)
    newer = other.load()
    newer.missions["001"].explanation = "Outra sessão"
    other.save(newer)
    inputs = iter(["/explain Texto antigo"])
    def read(*args):
        try:
            return next(inputs)
        except StopIteration:
            raise termination()
    log = SessionLog(app.repository.path)
    log.start()
    def fail(*args):
        raise SessionError("falha ao encerrar histórico")
    monkeypatch.setattr(log, "close", fail)
    monkeypatch.setattr(Console, "input", read)
    console = Console(record=True, width=120)
    assert _run_classic(app, log, console) == 0
    output = console.export_text()
    assert "Conflito de progresso" in output
    assert "falha ao encerrar histórico" in output
    assert other.load().missions["001"].explanation == "Outra sessão"


@pytest.mark.parametrize("command", ["/plan", "/explain"])
def test_eof_inside_classic_input_closes_without_partial_mutation(app, monkeypatch, command):
    from python_lab.cli import PythonLabCLI
    from python_lab.session import SessionLog
    from rich.console import Console

    app.start("001")
    def end(*args):
        raise EOFError()
    monkeypatch.setattr(Console, "input", end)
    log = SessionLog(app.repository.path)
    log.start()
    cli = PythonLabCLI(app, Console(record=True), log)
    assert cli.execute(command) is False
    assert app.current_progress().plan is None
    assert app.current_progress().explanation is None
    assert not log.is_open


def test_classic_unreadable_fingerprint_surfaces_error_before_prompt(app, monkeypatch):
    from python_lab.cli import _run_classic
    from rich.console import Console

    app.start("001")
    app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})
    app.current_progress().tests_passed = True
    app.current_progress().tested_solution_path = str(app.current_mission().solution_path)
    app.persist()
    def unreadable(path):
        raise PermissionError("sem permissão")
    monkeypatch.setattr("python_lab.app.solution_fingerprint", unreadable)
    monkeypatch.setattr(Console, "input", lambda *args: "/exit")
    console = Console(record=True)
    assert _run_classic(app, None, console) == 0
    assert "sem permissão" in console.export_text()


def test_session_start_failure_keeps_classic_available(app, monkeypatch, capsys):
    from python_lab.session import SessionError

    monkeypatch.setattr("python_lab.cli.build_app", lambda: app)
    def fail(*args):
        raise SessionError("Não foi possível iniciar a sessão: histórico indisponível")
    monkeypatch.setattr("python_lab.session.SessionLog.start", fail)
    monkeypatch.setattr("rich.console.Console.input", lambda *args: "/exit")
    assert main(["--classic"]) == 0
    output = capsys.readouterr().out
    assert "histórico indisponível" in output
    assert "Traceback" not in output
