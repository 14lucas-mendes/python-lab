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
    assert "0.4.0" in captured.out


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


def test_classic_unreadable_fingerprint_guides_retest_before_prompt(app, monkeypatch):
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
    assert app.tests_are_current() is False
    assert "Execute /test novamente para a solução atual" in console.export_text()


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


def test_classic_without_assistant_extra(tmp_path):
    """An optional SDK import must break this actual fresh-process journey."""
    import subprocess
    import sys
    code = """
import importlib.abc, sys
class BlockSDK(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'openai', 'anthropic', 'google', 'litellm'}:
            raise AssertionError('optional SDK imported: ' + fullname)
sys.meta_path.insert(0, BlockSDK())
from python_lab.cli import main
for flag in ['--help', '--version']:
    try:
        main([flag])
    except SystemExit as exc:
        assert exc.code == 0
assert main(['--classic', '--data-dir', sys.argv[1]]) == 0
"""
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path / "state")],
                            input="/missions\n/exit\n", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "001" in result.stdout and "011" in result.stdout
    assert (tmp_path / "state" / "lab.sqlite3").exists()


def test_help_and_version_bypass_state_initialization(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("state initialized")
    monkeypatch.setattr("python_lab.cli.build_app", forbidden)
    for flag in ("--help", "--version"):
        with pytest.raises(SystemExit) as exc:
            main([flag])
        assert exc.value.code == 0


def test_entrypoint_version_comes_from_distribution_metadata(monkeypatch, capsys):
    monkeypatch.setattr("importlib.metadata.version", lambda name: "7.8.9")
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "7.8.9" in capsys.readouterr().out


def test_classic_redirected_cp1252_handles_all_legacy_commands(tmp_path):
    """Real redirected output must match a CP1252 consumer and keep accents."""
    import os
    import subprocess
    import sys
    from python_lab.progress import ProgressRepository

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252"
    inputs = "\n".join([
        "/goal", "/skills", "/missions", "/mission 001", "/concepts 001",
        "/start 001", "/status", "/plan", "registros de manutenção", "saída válida",
        "acumular e verificar", "lista vazia", "/test", "/test details", "/hint",
        '/explain "A solução usa um dicionário."', "/history", "/session", "/evidence",
        "/help", "/exit", "",
    ])
    result = subprocess.run(
        [sys.executable, "-c", "import sys; from python_lab.cli import main; sys.exit(main(sys.argv[1:]))",
         "--classic", "--data-dir", str(tmp_path / "state")],
        input=inputs.encode("cp1252"), env=env, capture_output=True,
    )
    output = result.stdout.decode("cp1252")
    assert result.returncode == 0, result.stderr.decode("cp1252", errors="replace")
    assert "Missão atual: 001" in output
    assert "001" in output and "011" in output and "Comandos" in output
    assert "Planejamento" in output and "Saída" in output and "Pista" in output
    assert "Histórico de tentativas" in output and "Sessão atual" in output
    assert "Progresso salvo. Até a próxima sessão." in output
    progress = ProgressRepository(tmp_path / "state" / "lab.sqlite3").load().missions["001"]
    assert progress.plan["input"] == "registros de manutenção"
    assert progress.explanation == "A solução usa um dicionário."
    assert progress.attempts == 1 and progress.hints_revealed == 1
