import subprocess
import sys
from pathlib import Path

from python_lab.test_runner import run_tests


def test_runner_uses_current_python_and_captures_output(monkeypatch, tmp_path):
    calls = {}

    class Completed:
        returncode = 0
        stdout = "2 passed"

    def fake_run(command, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        report_path = Path(command[command.index("--junitxml") + 1])
        report_path.write_text(
            '<testsuite tests="1" failures="0" errors="0" skipped="0">'
            '<testcase classname="test_example" name="test_example" />'
            "</testsuite>",
            encoding="utf-8",
        )
        return Completed()

    monkeypatch.setattr("python_lab.test_runner.subprocess.run", fake_run)
    result = run_tests(tmp_path / "tests", tmp_path)
    assert calls["command"][:3] == [sys.executable, "-m", "pytest"]
    assert result.passed is True
    assert result.output == "2 passed"


def test_runner_rejects_suite_with_only_skipped_tests(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_skip.py").write_text(
        "import pytest\n\n"
        "def test_skip():\n"
        "    pytest.skip('deliberately skipped')\n",
        encoding="utf-8",
    )

    result = run_tests(tests, tmp_path)

    assert result.return_code == 0
    assert result.passed is False


def test_runner_rejects_empty_suite(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()

    result = run_tests(tests, tmp_path)

    assert result.passed is False


def test_runner_rejects_zero_exit_without_test_report(monkeypatch, tmp_path):
    class Completed:
        returncode = 0
        stdout = ""

    monkeypatch.setattr("python_lab.test_runner.subprocess.run", lambda *args, **kwargs: Completed())

    result = run_tests(tmp_path / "tests", tmp_path)

    assert result.passed is False


def test_runner_returns_failure_after_timeout(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=kwargs.get("args", "pytest"), timeout=kwargs.get("timeout", 0)
        )

    monkeypatch.setattr("python_lab.test_runner.subprocess.run", fake_run)

    result = run_tests(tmp_path / "tests", tmp_path, timeout=0.01)

    assert result.return_code == -1
    assert result.passed is False
    assert "tempo" in result.output.lower()


def test_runner_terminates_hanging_test(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_hang.py").write_text(
        "def test_hang():\n"
        "    while True:\n"
        "        pass\n",
        encoding="utf-8",
    )

    result = run_tests(tests, tmp_path, timeout=0.2)

    assert result.return_code == -1
    assert result.passed is False


def test_runner_returns_actionable_summary_and_failures(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_failure.py").write_text(
        "def test_failure():\n    assert 1 == 2\n", encoding="utf-8"
    )

    result = run_tests(tests, tmp_path)

    assert result.passed is False
    assert "1 teste" in result.summary
    assert any("test_failure" in item for item in result.diagnostics)


def test_runner_reports_missing_pytest(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("pytest")

    monkeypatch.setattr("python_lab.test_runner.subprocess.run", fake_run)

    result = run_tests(tmp_path / "tests", tmp_path)

    assert result.passed is False
    assert result.return_code == -1
    assert "pytest" in result.output.lower()
