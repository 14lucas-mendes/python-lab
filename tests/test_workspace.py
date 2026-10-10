import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest

from python_lab.app import ApplicationError
from python_lab.assistant.errors import ContextError
from python_lab.workspace import Workspace


def write_source(root, name="main.py", content=b"x = 1\n"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def link_or_skip(link, target):
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"Symlinks unavailable: {exc}")


@pytest.fixture
def git_repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("Git unavailable")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    return tmp_path


def test_valid_file_preserves_captured_utf8_bytes_hash_and_relative_posix_path(tmp_path):
    captured = "ação = 'olá'\r\nnext = 2\r\n".encode("utf-8")
    path = write_source(tmp_path, "nested/main.py", captured)

    snapshot = Workspace(tmp_path).snapshot([path])

    assert snapshot.root == tmp_path.resolve()
    assert len(snapshot.sources) == 1
    source = snapshot.sources[0]
    assert source.path == "nested/main.py"
    assert source.text.encode("utf-8") == captured
    assert source.sha256 == hashlib.sha256(captured).hexdigest()


def test_relative_selection_is_relative_to_workspace(tmp_path):
    write_source(tmp_path, "nested/main.py")
    snapshot = Workspace(tmp_path).snapshot([Path("nested/main.py")])
    assert snapshot.sources[0].path == "nested/main.py"


def test_absolute_selection_through_workspace_root_alias_preserves_captured_source(tmp_path):
    root = tmp_path / "project"
    captured = "ação = 'olá'\r\n".encode("utf-8")
    write_source(root, content=captured)
    alias = tmp_path / "project-alias"
    link_or_skip(alias, root)
    selected = alias / "main.py"
    assert selected.is_absolute()

    snapshot = Workspace(alias).snapshot([selected])

    assert snapshot.root == root.resolve()
    assert snapshot.sources[0].path == "main.py"
    assert snapshot.sources[0].text.encode("utf-8") == captured
    assert snapshot.sources[0].sha256 == hashlib.sha256(captured).hexdigest()


def test_retargeted_workspace_root_alias_cannot_capture_external_file(tmp_path):
    root = tmp_path / "project"
    write_source(root)
    alias = tmp_path / "project-alias"
    link_or_skip(alias, root)
    workspace = Workspace(alias)
    outside = tmp_path / "outside"
    write_source(outside, content=b"private bytes\n")
    alias.unlink()
    link_or_skip(alias, outside)

    with pytest.raises(ContextError):
        workspace.snapshot([alias / "main.py"])


def test_canonical_and_root_aliased_selections_are_duplicate_files(tmp_path):
    root = tmp_path / "project"
    canonical = write_source(root)
    alias = tmp_path / "project-alias"
    link_or_skip(alias, root)
    with pytest.raises(ContextError):
        Workspace(alias).snapshot([canonical, alias / "main.py"])


def test_only_selected_files_are_captured_without_executing_content(tmp_path):
    marker = tmp_path / "executed"
    selected = write_source(tmp_path, content=f"open({str(marker)!r}, 'w').write('bad')\n".encode())
    write_source(tmp_path, "not_selected.py", b"not shared\n")

    snapshot = Workspace(tmp_path).snapshot([selected])

    assert [source.path for source in snapshot.sources] == ["main.py"]
    assert not marker.exists()


def test_external_path_is_rejected(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = write_source(tmp_path, "outside.py")
    with pytest.raises(ContextError):
        Workspace(root).snapshot([outside])


def test_traversal_is_rejected(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    write_source(tmp_path, "outside.py")
    with pytest.raises(ContextError):
        Workspace(root).snapshot([Path("../outside.py")])


def test_similarly_prefixed_external_directory_is_rejected(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = write_source(tmp_path / "project-other")
    with pytest.raises(ContextError):
        Workspace(root).snapshot([outside])


def test_symlink_to_external_file_is_rejected(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = write_source(tmp_path, "outside.py")
    link = root / "alias.py"
    link_or_skip(link, outside)
    with pytest.raises(ContextError):
        Workspace(root).snapshot([link])


def test_internal_symlink_uses_resolved_relative_path(tmp_path):
    source = write_source(tmp_path, "nested/real.py")
    link = tmp_path / "alias.py"
    link_or_skip(link, source)
    snapshot = Workspace(tmp_path).snapshot([link])
    assert snapshot.sources[0].path == "nested/real.py"


@pytest.mark.parametrize("name", [
    ".git/config", ".venv/lib/code.py", "__pycache__/code.py", "nested/.env",
    ".env", ".env.local", ".env.production", "secret.pem", "secret.key",
    ".GIT/config", ".VENV/lib/code.py", "__PYCACHE__/code.py", ".ENV",
    ".ENV.local", "SECRET.PEM", "SECRET.KEY",
])
def test_fixed_exclusions_are_rejected(tmp_path, name):
    path = write_source(tmp_path, name)
    with pytest.raises(ContextError):
        Workspace(tmp_path).snapshot([path])


@pytest.mark.parametrize("alias,target", [
    ("alias.py", ".env.local"), ("alias.py", "secret.key"),
    ("alias.py", ".venv/code.py"), (".env.local", "safe.py"),
    ("secret.pem", "safe.py"), (".venv/alias.py", "safe.py"),
])
def test_exclusions_apply_to_both_symlink_alias_and_resolved_target(tmp_path, alias, target):
    source = write_source(tmp_path, target)
    link = tmp_path / alias
    link.parent.mkdir(parents=True, exist_ok=True)
    link_or_skip(link, source)
    with pytest.raises(ContextError):
        Workspace(tmp_path).snapshot([link])


@pytest.mark.parametrize("content", [b"abc\x00def", b"\xff\xfe", b"\x01binary"])
def test_binary_or_non_utf8_content_is_rejected(tmp_path, content):
    path = write_source(tmp_path, content=content)
    with pytest.raises(ContextError):
        Workspace(tmp_path).snapshot([path])


def test_gitignore_is_respected(git_repo):
    write_source(git_repo, ".gitignore", b"private.py\n")
    private = write_source(git_repo, "private.py")
    with pytest.raises(ContextError):
        Workspace(git_repo).snapshot([private])


def test_git_repository_allows_selected_non_ignored_file(git_repo):
    write_source(git_repo, ".gitignore", b"private.py\n")
    path = write_source(git_repo, "public.py")
    assert Workspace(git_repo).snapshot([path]).sources[0].path == "public.py"


def test_absolute_root_alias_selection_is_checked_against_canonical_git_repository(git_repo):
    write_source(git_repo, ".gitignore", b"private.py\n")
    write_source(git_repo, "public.py")
    write_source(git_repo, "private.py")
    alias = git_repo.parent / (git_repo.name + "-alias")
    link_or_skip(alias, git_repo)
    workspace = Workspace(alias)

    assert workspace.snapshot([alias / "public.py"]).sources[0].path == "public.py"
    with pytest.raises(ContextError):
        workspace.snapshot([alias / "private.py"])


def test_gitignore_is_respected_even_for_tracked_files(git_repo):
    private = write_source(git_repo, "private.py")
    subprocess.run(["git", "-C", str(git_repo), "add", "private.py"], check=True, capture_output=True)
    write_source(git_repo, ".gitignore", b"private.py\n")
    with pytest.raises(ContextError):
        Workspace(git_repo).snapshot([private])


@pytest.mark.parametrize("alias,target", [("alias.py", "private.py"), ("private.py", "safe.py")])
def test_gitignore_applies_to_alias_and_resolved_target(git_repo, alias, target):
    write_source(git_repo, ".gitignore", b"private.py\n")
    source = write_source(git_repo, target)
    link = git_repo / alias
    link_or_skip(link, source)
    with pytest.raises(ContextError):
        Workspace(git_repo).snapshot([link])


def test_gitignore_applies_when_workspace_is_nested_in_repo(git_repo):
    write_source(git_repo, ".gitignore", b"nested/private.py\n")
    private = write_source(git_repo, "nested/private.py")
    with pytest.raises(ContextError):
        Workspace(private.parent).snapshot([private])


def test_git_is_optional_for_non_repository(tmp_path, monkeypatch):
    path = write_source(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "no-git"))
    snapshot = Workspace(tmp_path).snapshot([path])
    assert snapshot.sources[0].text == "x = 1\n"


def test_empty_git_placeholder_does_not_make_directory_a_repository(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    path = write_source(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path / "no-git"))
    assert Workspace(tmp_path).snapshot([path]).sources[0].path == "main.py"


def test_known_repository_fails_closed_when_git_is_unavailable(git_repo, monkeypatch):
    path = write_source(git_repo)
    monkeypatch.setenv("PATH", str(git_repo / "no-git"))
    with pytest.raises(ContextError):
        Workspace(git_repo).snapshot([path])


def test_known_repository_fails_closed_when_ignore_check_fails(git_repo, monkeypatch):
    path = write_source(git_repo)
    original = subprocess.run

    def fail_ignore(command, **kwargs):
        if "check-ignore" in command:
            return subprocess.CompletedProcess(command, 128, b"", b"fatal: ignore failure")
        return original(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", fail_ignore)
    with pytest.raises(ContextError):
        Workspace(git_repo).snapshot([path])


def test_corrupt_git_metadata_fails_closed(git_repo):
    path = write_source(git_repo)
    (git_repo / ".git" / "HEAD").write_text("not a Git HEAD\n", encoding="utf-8")
    with pytest.raises(ContextError):
        Workspace(git_repo).snapshot([path])


def test_inherited_git_repository_variables_cannot_bypass_local_gitignore(git_repo, monkeypatch):
    other = git_repo / "other-repo"
    subprocess.run(["git", "init", "-q", str(other)], check=True, capture_output=True)
    write_source(git_repo, ".gitignore", b"private.py\n")
    private = write_source(git_repo, "private.py")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    with pytest.raises(ContextError):
        Workspace(git_repo).snapshot([private])


def test_empty_snapshot_and_empty_file_are_allowed(tmp_path):
    workspace = Workspace(tmp_path)
    assert workspace.snapshot([]).sources == ()
    path = write_source(tmp_path, content=b"")
    source = workspace.snapshot([path]).sources[0]
    assert source.text == ""
    assert source.sha256 == hashlib.sha256(b"").hexdigest()


@pytest.mark.parametrize("count,allowed", [(20, True), (21, False)])
def test_file_count_boundary(tmp_path, count, allowed):
    paths = [write_source(tmp_path, f"file{index}.py") for index in range(count)]
    if allowed:
        assert len(Workspace(tmp_path).snapshot(paths).sources) == count
    else:
        with pytest.raises(ContextError):
            Workspace(tmp_path).snapshot(paths)


@pytest.mark.parametrize("size,allowed", [(32768, True), (32769, False)])
def test_file_byte_boundary_without_silent_truncation(tmp_path, size, allowed):
    content = b"a" * size
    path = write_source(tmp_path, content=content)
    if allowed:
        assert Workspace(tmp_path).snapshot([path]).sources[0].text.encode() == content
    else:
        with pytest.raises(ContextError):
            Workspace(tmp_path).snapshot([path])


def test_file_limit_counts_utf8_bytes_rather_than_characters(tmp_path):
    path = write_source(tmp_path, content=("á" * 16385).encode())
    with pytest.raises(ContextError):
        Workspace(tmp_path).snapshot([path])


@pytest.mark.parametrize("extra,allowed", [(0, True), (1, False)])
def test_combined_source_byte_boundary(tmp_path, extra, allowed):
    paths = [write_source(tmp_path, f"file{index}.py", b"a" * 32768) for index in range(4)]
    if extra:
        paths.append(write_source(tmp_path, "extra.py", b"a"))
    if allowed:
        assert sum(len(source.text.encode()) for source in Workspace(tmp_path).snapshot(paths).sources) == 131072
    else:
        with pytest.raises(ContextError):
            Workspace(tmp_path).snapshot(paths)


@pytest.mark.parametrize("alias", [Path("main.py"), Path("./main.py")])
def test_duplicate_selected_paths_are_rejected(tmp_path, alias):
    path = write_source(tmp_path)
    with pytest.raises(ContextError):
        Workspace(tmp_path).snapshot([path, alias])


def test_duplicate_symlink_target_is_rejected(tmp_path):
    path = write_source(tmp_path)
    link = tmp_path / "alias.py"
    link_or_skip(link, path)
    with pytest.raises(ContextError):
        Workspace(tmp_path).snapshot([path, link])


def test_snapshot_hashes_exact_bytes_captured_before_file_changes(tmp_path, monkeypatch):
    captured = b"original = 1\r\n"
    path = write_source(tmp_path, content=captured)
    original_open = Path.open

    class ChangingReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def read(self, size=-1):
            content = self.stream.read(size)
            with original_open(path, "wb") as changed:
                changed.write(b"changed = 2\n")
            return content

    def changing_open(selected, *args, **kwargs):
        stream = original_open(selected, *args, **kwargs)
        if selected == path and args and args[0] == "rb":
            return ChangingReader(stream)
        return stream

    monkeypatch.setattr(Path, "open", changing_open)
    source = Workspace(tmp_path).snapshot([path]).sources[0]
    assert path.read_bytes() == b"changed = 2\n"
    assert source.text.encode() == captured
    assert source.sha256 == hashlib.sha256(captured).hexdigest()


def test_read_is_bounded_even_for_oversized_file(tmp_path, monkeypatch):
    path = write_source(tmp_path, content=b"a" * 32769)
    original_open = Path.open
    sizes = []

    class BoundedReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def read(self, size=-1):
            sizes.append(size)
            return self.stream.read(size)

    def bounded_open(selected, *args, **kwargs):
        stream = original_open(selected, *args, **kwargs)
        if selected == path and args and args[0] == "rb":
            return BoundedReader(stream)
        return stream

    monkeypatch.setattr(Path, "open", bounded_open)
    with pytest.raises(ContextError):
        Workspace(tmp_path).snapshot([path])
    assert sizes == [32769]


def test_file_replaced_by_external_symlink_before_open_is_rejected(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    path = write_source(root)
    outside = write_source(tmp_path, "outside.py", b"private bytes\n")
    original_open = Path.open

    def replaced_open(selected, *args, **kwargs):
        if selected == path and args and args[0] == "rb":
            selected.unlink()
            link_or_skip(selected, outside)
        return original_open(selected, *args, **kwargs)

    monkeypatch.setattr(Path, "open", replaced_open)
    with pytest.raises(ContextError):
        Workspace(root).snapshot([path])


@pytest.mark.parametrize("selected", [["main.py"], "main.py", None])
def test_selection_must_be_sequence_of_paths(tmp_path, selected):
    write_source(tmp_path)
    with pytest.raises(ContextError):
        Workspace(tmp_path).snapshot(selected)


@pytest.mark.parametrize("selected", [Path("missing.py"), Path("directory")])
def test_selection_must_be_existing_regular_file(tmp_path, selected):
    (tmp_path / "directory").mkdir()
    with pytest.raises(ContextError):
        Workspace(tmp_path).snapshot([selected])


@pytest.mark.parametrize("kind", ["missing", "file"])
def test_workspace_root_must_be_existing_directory(tmp_path, kind):
    root = tmp_path / kind
    if kind == "file":
        root.write_text("not a directory", encoding="utf-8")
    with pytest.raises(ContextError):
        Workspace(root)


def test_workspace_root_cannot_hide_an_excluded_directory_prefix(tmp_path):
    root = tmp_path / ".venv" / "project"
    path = write_source(root)
    with pytest.raises(ContextError):
        Workspace(root).snapshot([path])


@pytest.mark.parametrize("alias,target", [(".venv", "project"), ("project", ".venv")])
def test_fixed_exclusions_apply_to_workspace_root_alias_and_target(tmp_path, alias, target):
    root = tmp_path / target
    write_source(root)
    link = tmp_path / alias
    try:
        link.symlink_to(root, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlinks unavailable: {exc}")
    with pytest.raises(ContextError):
        Workspace(link).snapshot([Path("main.py")])


def test_public_context_error_is_application_error():
    assert issubclass(ContextError, ApplicationError)
