"""CI diagnostics retain failures despite long captured output."""

import importlib.util
from pathlib import Path


def formatter():
    source = Path(__file__).resolve().parents[1] / "scripts/ci_failure_summary.py"
    assert source.is_file(), "Bounded CI failure formatter missing"
    spec = importlib.util.spec_from_file_location("ci_failure_summary", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.summarize


def test_failure_names_survive_long_repeated_output(tmp_path):
    summarize = formatter()
    log = tmp_path / "pytest.log"
    log.write_text("FAILED tests/test_native.py::test_copy - AssertionError\n" + "x" * 25000, encoding="utf-8")
    junit = tmp_path / "pytest.xml"
    junit.write_text('<testsuites><testsuite><testcase classname="tests.test_native" name="test_copy"><failure message="AssertionError: stale copy">traceback\n' + 'x' * 25000 + '</failure></testcase></testsuite></testsuites>', encoding="utf-8")
    diagnostic = summarize(log, junit)
    assert "tests.test_native::test_copy" in diagnostic
    assert "AssertionError: stale copy" in diagnostic
    assert len(diagnostic) <= 6000
    assert "x" * 100 not in diagnostic


def test_missing_or_invalid_junit_keeps_bounded_log_failure(tmp_path):
    summarize = formatter()
    log = tmp_path / "pytest.log"
    log.write_text("FAILED tests/test_native.py::test_copy - AssertionError\n" + "long output " * 2500, encoding="utf-8")
    junit = tmp_path / "pytest.xml"
    for content in [None, "broken XML"]:
        if content is not None:
            junit.write_text(content, encoding="utf-8")
        diagnostic = summarize(log, junit)
        assert "FAILED tests/test_native.py::test_copy" in diagnostic
        assert len(diagnostic) <= 6000
