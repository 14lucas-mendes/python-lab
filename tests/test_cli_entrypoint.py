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
