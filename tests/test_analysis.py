import json
import os
import tempfile
from importlib.metadata import PackageNotFoundError, version
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from python_lab.assistant.errors import ContextError
from python_lab.runtime.processes import ProcessCleanupError, ProcessResult
from python_lab.workspace import Workspace


def api():
    from python_lab.analysis import AnalysisCancelled, AnalysisError, AnalysisService
    return AnalysisService, AnalysisError, AnalysisCancelled


def result(code=0, output="", **flags):
    return ProcessResult(code, output, flags.get("timed_out", False),
                         flags.get("cancelled", False), flags.get("truncated", False))


class FakeRunner:
    def __init__(self, responses, action=None):
        self.responses = iter(responses)
        self.calls = []
        self.action = action

    def run(self, argv, cwd, **kwargs):
        self.calls.append((argv, cwd, kwargs))
        if self.action:
            self.action()
        value = next(self.responses)
        if isinstance(value, BaseException):
            raise value
        return value


def snapshot(tmp_path, text="x = 1\n", name="main.py"):
    path = tmp_path / name
    path.write_text(text)
    return Workspace(tmp_path).snapshot([path])


def missing(tool):
    return result(1, f"{sys.executable}: No module named {tool}\n")


def test_ast_syntax_findings_and_missing_tools(tmp_path):
    service, _, _ = api()
    report = service(runner=FakeRunner([missing("ruff"), missing("ruff")])).inspect(
        snapshot(tmp_path, "def broken(:\n"))
    assert [(check.tool, check.status) for check in report.checks] == [
        ("ast", "failed"), ("ruff", "unavailable"), ("ruff-format", "unavailable")]
    issue = report.checks[0].issues[0]
    assert (issue.path, issue.line, issue.code, issue.source) == ("main.py", 1, "SyntaxError", "ast")


def test_non_python_selection_does_not_receive_python_analysis(tmp_path):
    service, _, _ = api()
    (tmp_path / "README.md").write_text("This is not Python!")
    (tmp_path / "pyproject.toml").write_text("[bad syntax")
    runner = FakeRunner([])
    report = service(runner=runner).inspect(Workspace(tmp_path).snapshot([
        Path("README.md"), Path("pyproject.toml")]), typing=True)
    assert report.checks == ()
    assert runner.calls == []


def test_ruff_json_preserves_structured_findings_and_format_failure(tmp_path):
    service, _, _ = api()
    payload = [{"filename": str(tmp_path / "main.py"), "location": {"row": 1, "column": 1},
                "code": "F401", "message": "unused import"}]
    runner = FakeRunner([result(1, json.dumps(payload)),
                         result(1, "Would reformat: main.py\n1 file would be reformatted\n")])
    report = service(runner=runner).inspect(snapshot(tmp_path))
    assert [check.status for check in report.checks] == ["passed", "failed", "failed"]
    issue = report.checks[1].issues[0]
    assert (issue.path, issue.line, issue.code, issue.message, issue.source) == (
        "main.py", 1, "F401", "unused import", "ruff")
    assert report.checks[2].issues[0].code == "FORMAT"


def test_mypy_runs_only_when_requested_with_controlled_config(tmp_path):
    service, _, _ = api()
    runner = FakeRunner([result(0, "[]"), result(),
                         result(1, "main.py:1: error: Incompatible types  [assignment]\n")])
    report = service(runner=runner).inspect(snapshot(tmp_path), typing=True)
    assert report.checks[-1].tool == "mypy"
    assert report.checks[-1].status == "failed"
    assert report.checks[-1].issues[0].code == "assignment"
    for argv, cwd, _ in runner.calls:
        assert argv[:3] == [sys.executable, "-I", "-m"]
        assert cwd == tmp_path
        assert "--" in argv and argv[-1] == str(tmp_path / "main.py")
        assert "--fix" not in argv
    mypy = runner.calls[-1][0]
    config = Path(mypy[mypy.index("--config-file") + 1])
    assert not config.is_relative_to(tmp_path)
    assert "--no-incremental" in mypy and "--follow-imports=skip" in mypy
    assert not config.exists()  # Temporary artifacts are cleaned before return.


def test_mypy_not_requested(tmp_path):
    service, _, _ = api()
    runner = FakeRunner([result(0, "[]"), result()])
    report = service(runner=runner).inspect(snapshot(tmp_path))
    assert [check.tool for check in report.checks] == ["ast", "ruff", "ruff-format"]


@pytest.mark.parametrize("location", ["equal", "beneath"])
def test_temporary_config_and_cache_never_write_under_workspace(tmp_path, monkeypatch, location):
    service, _, _ = api()
    captured = snapshot(tmp_path)
    configured = tmp_path if location == "equal" else tmp_path / "configured-temp"
    configured.mkdir(exist_ok=True)
    for name in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.setenv(name, str(configured))
    # Exercise environment selection from an uncached default, including any
    # transient writable-directory probing which ordinary after-checks miss.
    monkeypatch.setattr(tempfile, "tempdir", None)
    writes = []
    actual_open = os.open
    actual_mkdir = os.mkdir

    def observe_open(path, flags, *args, **kwargs):
        if flags & os.O_CREAT:
            writes.append(Path(path).resolve())
        return actual_open(path, flags, *args, **kwargs)

    def observe_mkdir(path, *args, **kwargs):
        writes.append(Path(path).resolve())
        return actual_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", observe_open)
    monkeypatch.setattr(os, "mkdir", observe_mkdir)
    before = set(tmp_path.rglob("*"))
    observed = []

    class InspectingRunner(FakeRunner):
        def run(self, argv, cwd, **kwargs):
            if argv[3] == "mypy":
                config = Path(argv[argv.index("--config-file") + 1]).resolve()
                cache = Path(argv[argv.index("--cache-dir") + 1]).resolve()
                observed.append((config, cache))
                assert config.is_file()
                assert not config.is_relative_to(tmp_path)
                assert not cache.is_relative_to(tmp_path)
                assert set(tmp_path.rglob("*")) == before
            return super().run(argv, cwd, **kwargs)

    runner = InspectingRunner([result(0, "[]"), result(), result()])
    service(runner=runner).inspect(captured, typing=True)
    assert observed
    assert writes and all(not path.is_relative_to(tmp_path) for path in writes)
    assert set(tmp_path.rglob("*")) == before
    assert not observed[0][0].parent.exists()


def test_no_external_temporary_parent_is_domain_error_before_allocation(tmp_path, monkeypatch):
    import python_lab.analysis.service as module

    service, error, _ = api()
    captured = snapshot(tmp_path)
    configured = tmp_path / "configured-temp"
    configured.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(configured))
    monkeypatch.setattr(module, "_temporary_parents", lambda: [tmp_path, configured], raising=False)
    before = set(tmp_path.rglob("*"))
    allocated = []
    actual_directory = tempfile.TemporaryDirectory

    def observe_directory(*args, **kwargs):
        allocated.append(kwargs.get("dir"))
        return actual_directory(*args, **kwargs)

    monkeypatch.setattr(tempfile, "TemporaryDirectory", observe_directory)
    runner = FakeRunner([result(0, "[]"), result(), result()])
    with pytest.raises(error, match="temporário.*fora"):
        service(runner=runner).inspect(captured, typing=True)
    assert not allocated
    assert len(runner.calls) == 2
    assert set(tmp_path.rglob("*")) == before


def test_workspace_equal_to_os_temp_root_allocates_outside_it(tmp_path, monkeypatch):
    service, _, _ = api()
    root = Path(tempfile.gettempdir()).resolve()
    if not tmp_path.is_relative_to(root):
        pytest.skip("Pytest fixture root is outside the OS temporary parent")
    selected = tmp_path / "main.py"
    selected.write_text("x = 1\n")
    captured = Workspace(root).snapshot([selected])
    monkeypatch.setattr(tempfile, "tempdir", None)
    for name in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.setenv(name, str(root))
    observed = []

    class InspectingRunner(FakeRunner):
        def run(self, argv, cwd, **kwargs):
            if argv[3] == "mypy":
                for option in ("--config-file", "--cache-dir"):
                    path = Path(argv[argv.index(option) + 1]).resolve()
                    assert not path.is_relative_to(root)
                    observed.append(path)
            return super().run(argv, cwd, **kwargs)

    runner = InspectingRunner([result(0, "[]"), result(), result()])
    service(runner=runner).inspect(captured, typing=True)
    assert len(observed) == 2
    assert not observed[0].parent.exists()


def test_mypy_cancellation_cleans_external_temporary_artifacts(tmp_path, monkeypatch):
    service, _, cancelled = api()
    captured = snapshot(tmp_path)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    cancel = threading.Event()
    observed = []

    class InspectingRunner(FakeRunner):
        def run(self, argv, cwd, **kwargs):
            assert kwargs["cancel"] is cancel
            if argv[3] == "mypy":
                path = Path(argv[argv.index("--config-file") + 1]).resolve()
                assert path.is_file() and not path.is_relative_to(tmp_path)
                observed.append(path)
            return super().run(argv, cwd, **kwargs)

    runner = InspectingRunner([result(0, "[]"), result(), result(cancelled=True)])
    with pytest.raises(cancelled):
        service(runner=runner).inspect(captured, typing=True, cancel=cancel)
    assert len(observed) == 1 and not observed[0].parent.exists()


def test_project_code_is_not_imported(tmp_path):
    service, _, _ = api()
    marker = tmp_path / "executed"
    captured = snapshot(tmp_path, f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
    service(runner=FakeRunner([missing("ruff"), missing("ruff")])).inspect(captured)
    assert not marker.exists()


@pytest.mark.parametrize("when", ["before", "during", "delete", "outside_symlink"])
def test_changed_source_invalidates_tool_results(tmp_path, when):
    service, _, _ = api()
    captured = snapshot(tmp_path)
    path = tmp_path / "main.py"

    def mutate():
        if when == "delete":
            path.unlink()
        elif when == "outside_symlink":
            outside = tmp_path.parent / (tmp_path.name + "-outside.py")
            outside.write_text("x = 1\n")
            path.unlink()
            try:
                path.symlink_to(outside)
            except OSError:
                pytest.skip("Symlinks unavailable")
        else:
            path.write_text("x = 2\n")

    if when == "before":
        mutate()
    runner = FakeRunner([result(0, "[]"), result()], action=mutate if when != "before" else None)
    with pytest.raises(ContextError):
        service(runner=runner).inspect(captured)
    if when == "before":
        assert not runner.calls


@pytest.mark.parametrize("response", [result(0, "not json"), result(2, "tool crashed"),
    result(0, "[]", timed_out=True), result(0, "[]", truncated=True),
    result(1, "[]"), result(0, '[{"filename":"main.py"}]'),
    result(1, '[{"filename":"outside.py","location":{"row":1},"code":"F401","message":"bad"}]'),
    OSError("launch failed")])
def test_execution_failures_never_become_passed(tmp_path, response):
    service, error, _ = api()
    with pytest.raises(error):
        service(runner=FakeRunner([response])).inspect(snapshot(tmp_path))


def test_formatter_failure_without_findings_is_domain_error(tmp_path):
    service, error, _ = api()
    with pytest.raises(error):
        service(runner=FakeRunner([result(0, "[]"), result(1, "formatter crashed")])).inspect(snapshot(tmp_path))


def test_syntax_diagnostics_from_formatter_and_mypy_are_findings(tmp_path):
    service, _, _ = api()
    payload = [{"filename": "main.py", "location": {"row": 1}, "code": "invalid-syntax", "message": "bad syntax"}]
    runner = FakeRunner([result(1, json.dumps(payload)),
        result(2, "error: Failed to parse main.py:1:12: bad syntax\n"),
        result(2, "main.py:1: error: Invalid syntax  [syntax]\n")])
    report = service(runner=runner).inspect(snapshot(tmp_path, "def broken(:\n"), typing=True)
    assert [check.status for check in report.checks] == ["failed"] * 4
    assert report.checks[2].issues[0].code == "SyntaxError"
    assert report.checks[-1].issues[0].code == "syntax"


def test_cancellation_is_propagated_after_runner_cleanup(tmp_path):
    service, _, cancelled = api()
    cancel = threading.Event()
    cleaned = []
    runner = FakeRunner([result(cancelled=True)], action=lambda: cleaned.append(True))
    with pytest.raises(cancelled):
        service(runner=runner).inspect(snapshot(tmp_path), cancel=cancel)
    assert cleaned == [True]
    assert runner.calls[0][2]["cancel"] is cancel


def test_pre_cancelled_analysis_never_launches_tools(tmp_path):
    service, _, cancelled = api()
    cancel = threading.Event()
    cancel.set()
    runner = FakeRunner([])
    with pytest.raises(cancelled):
        service(runner=runner).inspect(snapshot(tmp_path), cancel=cancel)
    assert not runner.calls


def test_cleanup_failure_remains_authoritative(tmp_path):
    service, _, _ = api()
    with pytest.raises(ProcessCleanupError, match="cannot confirm"):
        service(runner=FakeRunner([ProcessCleanupError("cannot confirm")])).inspect(snapshot(tmp_path))


def test_native_cancelled_analysis_waits_for_process_tree_cleanup(tmp_path):
    from python_lab.runtime.processes import ProcessRunner
    from tests.test_process_runner import assert_tree_stopped, tree_command, wait_for_file

    service, _, cancelled = api()
    cancel = threading.Event()
    captured = snapshot(tmp_path)

    class BlockingRunner(ProcessRunner):
        def run(self, argv, cwd, **kwargs):
            # Substitute a controlled slow tool with a real descendant. This
            # exercises AnalysisService's Event propagation and return boundary.
            return super().run(tree_command(tmp_path, closed_output=True), cwd, **kwargs)

    with ThreadPoolExecutor() as pool:
        future = pool.submit(service(runner=BlockingRunner()).inspect, captured, cancel=cancel)
        wait_for_file(tmp_path / "ready")
        cancel.set()
        with pytest.raises(cancelled):
            future.result(timeout=10)
    assert_tree_stopped(tmp_path)


def test_optional_mypy_absence_is_explicit(tmp_path):
    service, _, _ = api()
    report = service(runner=FakeRunner([missing("ruff"), missing("ruff"), missing("mypy")])).inspect(
        snapshot(tmp_path), typing=True)
    assert report.checks[-1].status == "unavailable"


def test_selected_option_like_filename_is_literal(tmp_path):
    service, _, _ = api()
    runner = FakeRunner([result(0, "[]"), result(), result()])
    service(runner=runner).inspect(snapshot(tmp_path, name="--config-file.py"), typing=True)
    for argv, _, _ in runner.calls:
        assert argv[argv.index("--") + 1:] == [str(tmp_path / "--config-file.py")]


@pytest.mark.parametrize("shadow", ["module", "package"])
def test_real_optional_tools_are_isolated_and_read_only(tmp_path, monkeypatch, shadow):
    for tool in ("ruff", "mypy"):
        try:
            version(tool)
        except PackageNotFoundError:
            pytest.skip("Optional analysis extra is absent")
    service, _, _ = api()
    marker = tmp_path / "executed"
    malicious = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    for tool in ("ruff", "mypy"):
        if shadow == "module":
            (tmp_path / f"{tool}.py").write_text(malicious)
        else:
            package = tmp_path / tool
            package.mkdir()
            (package / "__init__.py").write_text(malicious)
            (package / "__main__.py").write_text(malicious)
    (tmp_path / "evil_plugin.py").write_text(malicious)
    (tmp_path / "dependency.py").write_text(malicious)
    (tmp_path / "mypy.ini").write_text("[mypy]\nplugins = evil_plugin\n")
    (tmp_path / "pyproject.toml").write_text('[tool.ruff]\nthis_setting_does_not_exist = true\n')
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    for name in ("TMPDIR", "TEMP", "TMP"):
        monkeypatch.setenv(name, str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", None)
    main = tmp_path / "main.py"
    main.write_text("import dependency\n\nvalue: int = 1\nprint(dependency, value)\n")
    original = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    report = service().inspect(Workspace(tmp_path).snapshot([main]), typing=True)
    assert [(check.tool, check.status) for check in report.checks] == [
        ("ast", "passed"), ("ruff", "passed"), ("ruff-format", "passed"), ("mypy", "passed")]
    assert {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == original
    assert not marker.exists()
    assert not (tmp_path / ".ruff_cache").exists()
    assert not (tmp_path / ".mypy_cache").exists()

    main.write_text("def broken(:\n")
    report = service().inspect(Workspace(tmp_path).snapshot([main]), typing=True)
    assert [check.status for check in report.checks] == ["failed"] * 4

    main.write_text('import os\n\nvalue:int="wrong"\n')
    captured = Workspace(tmp_path).snapshot([main])
    before = main.read_bytes()
    report = service().inspect(captured, typing=True)
    assert [check.status for check in report.checks] == ["passed", "failed", "failed", "failed"]
    assert report.checks[1].issues[0].code == "F401"
    assert report.checks[-1].issues[0].code == "assignment"
    assert main.read_bytes() == before and not marker.exists()
    assert not (tmp_path / ".ruff_cache").exists()
    assert not (tmp_path / ".mypy_cache").exists()
