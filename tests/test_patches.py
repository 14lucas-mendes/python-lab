"""A proposal only replaces one captured source after explicit confirmation."""

import json
import os
import stat
from pathlib import Path

import pytest

from python_lab.assistant.errors import AssistantError
from python_lab.assistant.models import FileChange, PatchProposal
from python_lab.assistant.patches import PatchService
from python_lab.workspace import Workspace


def setup_patch(tmp_path, *, before=b"x=1\n", after="x=2\n"):
    root = tmp_path / "project"
    root.mkdir()
    source = root / "a.py"
    source.write_bytes(before)
    workspace = Workspace(root)
    captured = workspace.snapshot([source]).sources[0]
    proposal = PatchProposal("p1", FileChange("a.py", captured.sha256, after), "fix", ("a.py",))
    return source, PatchService(workspace, tmp_path / "state"), proposal


def test_preview_is_literal_diff_and_writes_nothing(tmp_path):
    source, service, proposal = setup_patch(tmp_path)
    diff = service.preview(proposal)
    assert "-x=1\n" in diff and "+x=2\n" in diff
    assert source.read_bytes() == b"x=1\n"
    assert not (tmp_path / "state").exists()


def test_apply_preserves_exact_old_bytes_and_permissions(tmp_path):
    source, service, proposal = setup_patch(tmp_path, before=b"x='ol\xc3\xa1'\r\n", after="x='novo'\n")
    source.chmod(0o640)
    result = service.apply(proposal, confirmed=True)
    assert result == source
    assert source.read_bytes() == b"x='novo'\n"
    assert stat.S_IMODE(source.stat().st_mode) == 0o640
    assert b"x='ol\xc3\xa1'\r\n" in [p.read_bytes() for p in (tmp_path / "state").rglob("*") if p.is_file()]


def test_stale_patch_preserves_new_edit(tmp_path):
    source, service, proposal = setup_patch(tmp_path)
    source.write_text("x=3\n")
    with pytest.raises(AssistantError, match="alterad"):
        service.apply(proposal, confirmed=True)
    assert source.read_text() == "x=3\n"


def test_missing_confirmation_does_not_write(tmp_path):
    source, service, proposal = setup_patch(tmp_path)
    with pytest.raises(AssistantError, match="confirm"):
        service.apply(proposal, confirmed=False)
    assert source.read_bytes() == b"x=1\n"
    assert not (tmp_path / "state").exists()


def test_patch_destination_must_be_selected_source(tmp_path):
    source, service, proposal = setup_patch(tmp_path)
    (source.parent / "b.py").write_text("b=1\n")
    with pytest.raises(AssistantError, match="selecionad"):
        PatchProposal("p2", FileChange("b.py", proposal.change.before_sha256, "b=2\n"), "fix", ("a.py",))
    assert (source.parent / "b.py").read_text() == "b=1\n"


def test_traversal_and_external_symlink_are_rejected(tmp_path):
    source, service, proposal = setup_patch(tmp_path)
    outside = tmp_path / "outside.py"
    outside.write_text("secret\n")
    for path in ("../outside.py", "link.py"):
        if path == "link.py":
            (source.parent / path).symlink_to(outside)
        with pytest.raises(AssistantError):
            unsafe = PatchProposal("p2", FileChange(path, proposal.change.before_sha256, "bad\n"), "fix", (path,))
            service.apply(unsafe, confirmed=True)
    assert outside.read_text() == "secret\n"


def test_symlink_retargeted_after_preview_cannot_apply(tmp_path):
    source, service, proposal = setup_patch(tmp_path)
    service.preview(proposal)
    outside = tmp_path / "outside.py"
    outside.write_text("secret\n")
    source.unlink()
    source.symlink_to(outside)
    with pytest.raises(AssistantError):
        service.apply(proposal, confirmed=True)
    assert outside.read_text() == "secret\n"


def test_invalid_utf8_and_byte_limit_rejected(tmp_path):
    _, service, proposal = setup_patch(tmp_path)
    for text in ("\ud800", "é" * 16385):
        with pytest.raises(AssistantError):
            invalid = PatchProposal("p2", FileChange("a.py", proposal.change.before_sha256, text), "fix", ("a.py",))
            service.preview(invalid)


def test_backup_failure_preserves_original(tmp_path):
    source, service, proposal = setup_patch(tmp_path)
    (tmp_path / "state").write_text("not a directory")
    with pytest.raises(AssistantError):
        service.apply(proposal, confirmed=True)
    assert source.read_bytes() == b"x=1\n"


def test_replace_failure_preserves_original(tmp_path, monkeypatch):
    source, service, proposal = setup_patch(tmp_path)
    def fail_replace(*args, **kwargs):
        raise OSError("injected replace failure")
    monkeypatch.setattr("python_lab.assistant.patches.os.replace", fail_replace)
    with pytest.raises(AssistantError, match="substitu"):
        service.apply(proposal, confirmed=True)
    assert source.read_bytes() == b"x=1\n"


def test_saved_proposal_is_bound_to_workspace(tmp_path):
    source, service, proposal = setup_patch(tmp_path)
    service.save(proposal)
    assert service.load("p1") == proposal
    other = tmp_path / "other"
    other.mkdir()
    (other / "a.py").write_bytes(source.read_bytes())
    foreign = PatchService(Workspace(other), tmp_path / "state")
    with pytest.raises(AssistantError):
        foreign.load("p1")
    with pytest.raises(AssistantError):
        foreign.apply(proposal, confirmed=True)
    assert (other / "a.py").read_bytes() == b"x=1\n"


def test_unknown_and_pathlike_ids_cannot_load(tmp_path):
    _, service, _ = setup_patch(tmp_path)
    with pytest.raises(AssistantError):
        service.load("../../outside")
    with pytest.raises(AssistantError):
        service.load("unknown")


def test_post_replace_error_reports_recovery_backup(tmp_path, monkeypatch):
    source, service, proposal = setup_patch(tmp_path)
    original_replace = __import__("os").replace
    def replace_then_fail(src, dst):
        original_replace(src, dst)
        raise OSError("failure after replacement")
    monkeypatch.setattr("python_lab.assistant.patches.os.replace", replace_then_fail)
    with pytest.raises(AssistantError, match="Backup:") as failure:
        service.apply(proposal, confirmed=True)
    assert "original preservado" not in str(failure.value)
    assert source.read_bytes() == b"x=2\n"
    backup = Path(str(failure.value).split("Backup: ", 1)[1])
    assert backup.read_bytes() == b"x=1\n"


def test_preview_marks_missing_final_newlines_without_changing_patch_bytes(tmp_path):
    source, service, proposal = setup_patch(tmp_path, before=b"x=1", after="x=2")
    diff = service.preview(proposal)
    assert "-x=1\n\\ No newline at end of file\n+x=2\n\\ No newline at end of file\n" in diff
    service.apply(proposal, confirmed=True)
    assert source.read_bytes() == b"x=2"


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are required")
def test_state_files_and_directories_are_private_even_with_permissive_umask(tmp_path):
    source, service, proposal = setup_patch(tmp_path)
    source.chmod(0o600)
    state = tmp_path / "state"
    state.mkdir(mode=0o755)
    state.chmod(0o755)
    original_umask = os.umask(0)
    try:
        service.save(proposal)
        service.apply(proposal, confirmed=True)
    finally:
        os.umask(original_umask)
    assert stat.S_IMODE(state.stat().st_mode) == 0o755
    for directory in (state / "proposals", state / "backups"):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        files = list(directory.iterdir())
        assert len(files) == 1
        assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
    assert stat.S_IMODE(source.stat().st_mode) == 0o600


def test_partial_proposal_write_can_retry_same_id(tmp_path, monkeypatch):
    _, service, proposal = setup_patch(tmp_path)
    original_dump = json.dump
    def fail_after_partial_write(payload, stream, **kwargs):
        stream.write('{"incomplete":')
        raise OSError("injected write failure")
    monkeypatch.setattr("python_lab.assistant.patches.json.dump", fail_after_partial_write)
    with pytest.raises(AssistantError, match="salvar"):
        service.save(proposal)
    monkeypatch.setattr("python_lab.assistant.patches.json.dump", original_dump)
    service.save(proposal)
    assert service.load(proposal.id) == proposal
    assert len(list((tmp_path / "state" / "proposals").iterdir())) == 1


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are required")
def test_new_state_permissions_do_not_depend_on_restrictive_umask(tmp_path):
    _, service, proposal = setup_patch(tmp_path)
    original_umask = os.umask(0o777)
    try:
        service.save(proposal)
    finally:
        os.umask(original_umask)
    state = tmp_path / "state"
    record_dir = state / "proposals"
    record = next(record_dir.iterdir())
    assert stat.S_IMODE(state.stat().st_mode) == 0o700
    assert stat.S_IMODE(record_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(record.stat().st_mode) == 0o600


@pytest.mark.parametrize("directory", ["proposals", "backups"])
def test_state_child_symlink_cannot_redirect_private_content(tmp_path, directory):
    source, service, proposal = setup_patch(tmp_path)
    state = tmp_path / "state"
    state.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (state / directory).symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlinks unavailable: {exc}")
    with pytest.raises(AssistantError):
        if directory == "proposals":
            service.save(proposal)
        else:
            service.apply(proposal, confirmed=True)
    assert list(outside.iterdir()) == []
    assert source.read_bytes() == b"x=1\n"
