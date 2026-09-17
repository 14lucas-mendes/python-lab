import pytest

from python_lab.cli import main


def test_external_help_prints_usage_and_exits(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "usage:" in captured.out.lower()
    assert "python-lab" in captured.out


def test_external_version_prints_version_and_exits(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "0.1.0" in captured.out


def test_external_argument_is_rejected(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--nonsense"])

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "argumento inválido" in captured.err.lower()
