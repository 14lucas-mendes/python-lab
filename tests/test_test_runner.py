import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import sys
from pathlib import Path

from python_lab.runtime.processes import ProcessResult
from python_lab.test_runner import run_tests


def test_runner_uses_current_python_and_captures_output(monkeypatch, tmp_path):
    calls = {}

    def fake_run(self, command, cwd, **kwargs):
        calls["command"] = command
        calls["kwargs"] = kwargs
        report_path = Path(command[command.index("--junitxml") + 1])
        report_path.write_text(
            '<testsuite tests="1" failures="0" errors="0" skipped="0">'
            '<testcase classname="test_example" name="test_example" />'
            "</testsuite>",
            encoding="utf-8",
        )
        return ProcessResult(0, "2 passed", False, False, False)

    monkeypatch.setattr("python_lab.test_runner.ProcessRunner.run", fake_run)
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
    monkeypatch.setattr("python_lab.test_runner.ProcessRunner.run",
                        lambda *args, **kwargs: ProcessResult(0, "", False, False, False))

    result = run_tests(tmp_path / "tests", tmp_path)

    assert result.passed is False


def test_runner_returns_failure_after_timeout(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        return ProcessResult(-1, "partial", True, False, False)

    monkeypatch.setattr("python_lab.test_runner.ProcessRunner.run", fake_run)

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

    monkeypatch.setattr("python_lab.test_runner.ProcessRunner.run", fake_run)

    result = run_tests(tmp_path / "tests", tmp_path)

    assert result.passed is False
    assert result.return_code == -1
    assert "pytest" in result.output.lower()


@pytest.mark.parametrize("report", ["<broken", '<testsuite tests="invalid"/>', '<testsuite tests="0"/>', '<testsuite tests="1" skipped="1"/>'])
def test_runner_rejects_invalid_or_incomplete_report(monkeypatch, tmp_path, report):
    def fake_run(self, argv, cwd, **kwargs):
        Path(argv[argv.index("--junitxml") + 1]).write_text(report)
        return ProcessResult(0, "", False, False, False)
    monkeypatch.setattr("python_lab.test_runner.ProcessRunner.run", fake_run)
    assert not run_tests(tmp_path, tmp_path).passed


@pytest.mark.parametrize("timed_out,cancelled", [(True, False), (False, True)])
def test_interruption_rejects_even_a_passing_junit(monkeypatch, tmp_path, timed_out, cancelled):
    def fake_run(self, argv, cwd, **kwargs):
        Path(argv[argv.index("--junitxml") + 1]).write_text('<testsuite tests="1"/>')
        return ProcessResult(0, "partial output", timed_out, cancelled, False)
    monkeypatch.setattr("python_lab.test_runner.ProcessRunner.run", fake_run)
    result = run_tests(tmp_path, tmp_path, cancel=threading.Event())
    assert not result.passed
    assert result.return_code == -1
    assert "partial output" in result.output


def test_runner_preserves_junit_when_output_is_truncated(tmp_path):
    tests = tmp_path / "test_noisy.py"
    tests.write_text("def test_noisy():\n    print('x' * 2097152)\n")
    result = run_tests(tests, tmp_path)
    assert result.passed
    assert result.summary.startswith("1 teste(s): 1 aprovado(s)")
    assert len(result.output.encode()) <= 1048576


def test_concurrent_runs_select_distinct_solutions_without_global_environment_changes(tmp_path):
    suites = []
    selections = []
    original = os.environ.get("PYTHON_LAB_SOLUTION")
    for index in range(2):
        solution = tmp_path / f"solution-{index}.py"
        solution.write_text(str(index))
        suite = tmp_path / f"test_selection_{index}.py"
        suite.write_text(
            "import os, time\nfrom pathlib import Path\n"
            "def test_selection():\n"
            "    time.sleep(.05)\n"
            f"    assert Path(os.environ['PYTHON_LAB_SOLUTION']).read_text() == {str(index)!r}\n"
        )
        suites.append(suite)
        selections.append(solution)
    with ThreadPoolExecutor() as pool:
        futures = [pool.submit(run_tests, suite, tmp_path, selection)
                   for suite, selection in zip(suites, selections)]
        results = [future.result(timeout=10) for future in futures]
    assert all(result.passed for result in results), [result.output for result in results]
    assert os.environ.get("PYTHON_LAB_SOLUTION") == original


def test_app_passes_cancellation_without_recording_success(app, monkeypatch):
    app.start("001")
    app.save_plan(dict(input="x", output="y", steps="z", risks="w"))
    cancel = threading.Event()

    def interrupted(*args, **kwargs):
        assert kwargs["cancel"] is cancel
        cancel.set()
        from python_lab.models import TestResult
        return TestResult(True, 0, "Late success must be ignored")

    monkeypatch.setattr("python_lab.app.run_tests", interrupted)
    result = app.run_current_tests(cancel=cancel)
    assert not result.passed
    assert not app.current_progress().tests_passed
    assert not app.current_progress().attempt_history
    assert not app.repository.load().missions["001"].tests_passed
