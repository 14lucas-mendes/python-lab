import hashlib
import json
from pathlib import Path
import sys
import threading

import pytest

from python_lab.assistant.errors import AssistantError
from python_lab.assistant.models import FileChange, PatchProposal
from python_lab.assistant.patches import PatchService
from python_lab.assistant.verification import VerificationService, VerificationStore
from python_lab.runtime.processes import ProcessRunner
from python_lab.workspace import Workspace


def proposal(tmp_path, after):
    source = tmp_path / "a.py"
    source.write_text("def f():\n    return 1\n")
    workspace = Workspace(tmp_path)
    snap = workspace.snapshot([source])
    patch = PatchProposal(
        "p1", FileChange("a.py", snap.sources[0].sha256, after), "fix", ("a.py",)
    )
    return workspace, patch


def test_no_check_is_not_a_verified_patch(tmp_path):
    workspace, patch = proposal(tmp_path, "def f():\n    return 2\n")
    result = VerificationService(ProcessRunner()).run(patch, workspace, checks=())
    assert result.status == "unverified" and result.checks == ()


def test_real_wrong_then_correct_patch_and_later_edit_invalidates_status(tmp_path):
    (tmp_path / "test_a.py").write_text(
        "from a import f\ndef test_f(): assert f() == 2\n"
    )
    workspace, wrong = proposal(tmp_path, "def f():\n    return 3\n")
    store = VerificationStore(tmp_path / ".state")
    service = VerificationService(ProcessRunner(), store=store)
    patches = PatchService(workspace, tmp_path / ".state")
    patches.apply(wrong, confirmed=True)
    failed = service.run(wrong, workspace, checks=("ast", "pytest"))
    assert failed.status == "failed" and failed.checks[-1].name == "pytest"
    assert service.current(wrong, workspace).status == "failed"
    # A fresh proposal is required after the first patch was applied.
    fresh = workspace.snapshot([Path("a.py")])
    right = PatchProposal(
        "p2",
        FileChange("a.py", fresh.sources[0].sha256, "def f():\n    return 2\n"),
        "fix",
        ("a.py",),
    )
    patches.apply(right, confirmed=True)
    passed = service.run(right, workspace, checks=("ast", "pytest"))
    assert (
        passed.status == "passed"
        and passed.sha256
        == hashlib.sha256(right.change.after_text.encode()).hexdigest()
    )
    assert service.current(right, workspace).status == "passed"
    (tmp_path / "a.py").write_text("def f():\n    return 4\n")
    assert service.current(right, workspace).status == "unverified"


def test_nonempty_check_requires_applied_bytes_and_known_name(tmp_path):
    workspace, patch = proposal(tmp_path, "def f():\n    return 2\n")
    service = VerificationService(ProcessRunner())
    with pytest.raises(AssistantError):
        service.run(patch, workspace, checks=("ast",))
    with pytest.raises(AssistantError):
        service.run(patch, workspace, checks=("echo hi",))


@pytest.mark.parametrize(
    "kind", ["missing_junit", "zero", "skipped", "cancelled", "missing_pytest"]
)
def test_pytest_infrastructure_and_empty_evidence_never_pass(tmp_path, kind):
    from python_lab.runtime.processes import ProcessResult

    workspace, patch = proposal(tmp_path, "def f():\n    return 2\n")
    PatchService(workspace, tmp_path / ".state").apply(patch, confirmed=True)

    class Runner:
        def run(self, argv, cwd, **kwargs):
            report = Path(argv[argv.index("--junitxml") + 1])
            if kind == "zero":
                report.write_text(
                    '<testsuite tests="0" failures="0" errors="0" skipped="0"/>'
                )
            if kind == "skipped":
                report.write_text(
                    '<testsuite tests="1" failures="0" errors="0" skipped="1"/>'
                )
            if kind == "missing_pytest":
                return ProcessResult(
                    1, f"{sys.executable}: No module named pytest", False, False, False
                )
            return ProcessResult(
                -1 if kind == "cancelled" else 0, "", False, kind == "cancelled", False
            )

    result = VerificationService(Runner()).run(patch, workspace, checks=("pytest",))
    assert result.status != "passed"
    expected = (
        "cancelled" if kind == "cancelled"
        else "unavailable" if kind == "missing_pytest"
        else "failed"
    )
    assert result.checks[0].status == expected
    if kind == "missing_pytest":
        assert "Pytest indisponível" in result.checks[0].detail


def test_ast_failure_is_recorded_for_applied_patch(tmp_path):
    workspace, patch = proposal(tmp_path, "def f(:\n")
    PatchService(workspace, tmp_path / ".state").apply(patch, confirmed=True)
    result = VerificationService(ProcessRunner()).run(patch, workspace, checks=("ast",))
    assert result.status == "failed" and result.checks[0].name == "ast"


def test_verification_store_rejects_foreign_id_in_shared_directory(tmp_path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    common = tmp_path / "shared"
    store = VerificationStore(common)
    first_workspace, first = proposal(left, "def f():\n    return 2\n")
    second_workspace, second = proposal(right, "def f():\n    return 2\n")
    PatchService(first_workspace, left / ".state").apply(first, confirmed=True)
    PatchService(second_workspace, right / ".state").apply(second, confirmed=True)
    service = VerificationService(ProcessRunner(), store=store)
    assert service.run(first, first_workspace, checks=("ast",)).status == "passed"
    with pytest.raises(AssistantError):
        service.run(second, second_workspace, checks=("ast",))
    assert service.current(first, first_workspace).status == "passed"


def test_cancellation_at_process_completion_never_passes(tmp_path):
    from python_lab.runtime.processes import ProcessResult

    workspace, patch = proposal(tmp_path, "def f():\n    return 2\n")
    PatchService(workspace, tmp_path / ".state").apply(patch, confirmed=True)
    cancel = threading.Event()

    class Runner:
        def run(self, argv, cwd, **kwargs):
            cancel.set()
            return ProcessResult(0, "[]", False, False, False)

    result = VerificationService(Runner()).run(
        patch, workspace, checks=("ruff",), cancel=cancel,
    )
    assert result.status == "cancelled" and result.checks[0].status == "cancelled"


def test_selected_dependency_edit_invalidates_persisted_verification(tmp_path):
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    (tmp_path / "b.py").write_text("value = 2\n")
    (tmp_path / "test_a.py").write_text(
        "from a import f\ndef test_f(): assert f() == 2\n"
    )
    workspace = Workspace(tmp_path)
    snapshot = workspace.snapshot([Path("a.py"), Path("b.py")])
    patch = PatchProposal(
        "dependencies", FileChange(
            "a.py", snapshot.sources[0].sha256,
            "from b import value\ndef f():\n    return value\n",
        ), "fix", ("a.py", "b.py"),
    )
    PatchService(workspace, tmp_path / ".state").apply(patch, confirmed=True)
    state = tmp_path / ".state"
    service = VerificationService(ProcessRunner(), store=VerificationStore(state))
    assert service.run(patch, workspace, checks=("pytest",)).status == "passed"
    # Recreate the service to prove that the selection association survives persistence.
    reloaded = VerificationService(ProcessRunner(), store=VerificationStore(state))
    assert reloaded.current(patch, workspace).status == "passed"
    (tmp_path / "b.py").write_text("value = 3\n")
    assert reloaded.current(patch, workspace).status == "unverified"
    assert reloaded.run(patch, workspace, checks=("pytest",)).status == "failed"


def test_legacy_record_needs_fresh_verification(tmp_path):
    workspace, patch = proposal(tmp_path, "def f():\n    return 2\n")
    state = tmp_path / ".state"
    PatchService(workspace, state).apply(patch, confirmed=True)
    service = VerificationService(ProcessRunner(), store=VerificationStore(state))
    assert service.run(patch, workspace, checks=("ast",)).status == "passed"
    record = next((state / "verifications").glob("*.json"))
    payload = json.loads(record.read_text())
    payload["result"].pop("selected_sources", None)
    record.write_text(json.dumps(payload))
    assert service.current(patch, workspace).status == "unverified"
    assert service.run(patch, workspace, checks=("ast",)).status == "passed"
    assert service.current(patch, workspace).status == "passed"


def test_cancellation_during_final_capture_never_publishes_passed(tmp_path):
    workspace, patch = proposal(tmp_path, "def f():\n    return 2\n")
    state = tmp_path / ".state"
    PatchService(workspace, state).apply(patch, confirmed=True)
    cancel = threading.Event()

    class CancellingWorkspace(Workspace):
        captures = 0

        def snapshot(self, paths):
            captured = super().snapshot(paths)
            self.captures += 1
            if self.captures == 2:
                cancel.set()
            return captured

    selected = CancellingWorkspace(tmp_path)
    service = VerificationService(ProcessRunner(), store=VerificationStore(state))
    result = service.run(patch, selected, checks=("ast",), cancel=cancel)
    assert cancel.is_set()
    assert result.status == "cancelled"
    assert service.current(patch, selected).status == "cancelled"


@pytest.mark.parametrize("invalid", [
    [], [["other.py", "0" * 64]], [["a.py", "invalid"]],
    [["a.py", "0" * 64]] * 21,
])
def test_incomplete_or_invalid_selected_fingerprints_are_unverified(tmp_path, invalid):
    workspace, patch = proposal(tmp_path, "def f():\n    return 2\n")
    state = tmp_path / ".state"
    PatchService(workspace, state).apply(patch, confirmed=True)
    service = VerificationService(ProcessRunner(), store=VerificationStore(state))
    assert service.run(patch, workspace, checks=("ast",)).status == "passed"
    record = next((state / "verifications").glob("*.json"))
    payload = json.loads(record.read_text())
    payload["result"]["selected_sources"] = invalid
    record.write_text(json.dumps(payload))
    assert service.current(patch, workspace).status == "unverified"


@pytest.mark.parametrize("check", ["ruff", "pytest"])
def test_verification_cleanup_failure_is_never_downgraded(tmp_path, check):
    from python_lab.runtime.processes import ProcessCleanupError

    workspace, patch = proposal(tmp_path, "def f():\n    return 2\n")
    state = tmp_path / ".state"
    PatchService(workspace, state).apply(patch, confirmed=True)
    cancel = threading.Event()

    class Runner:
        def run(self, argv, cwd, **kwargs):
            cancel.set()
            raise ProcessCleanupError("descendant still running")

    service = VerificationService(Runner(), store=VerificationStore(state))
    with pytest.raises(ProcessCleanupError, match="descendant still running"):
        service.run(patch, workspace, checks=(check,), cancel=cancel)
    assert service.current(patch, workspace).status == "unverified"
