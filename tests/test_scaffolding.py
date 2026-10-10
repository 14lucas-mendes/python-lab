"""Offline scaffold contracts; no generated project is installed or executed here."""

from dataclasses import FrozenInstanceError
from importlib import resources
from pathlib import Path
import socket
import subprocess
import tomllib

import pytest

from python_lab.assistant.errors import AssistantError


def scaffold_api():
    # Assert absence as a RED failure, rather than an import/collection error.
    assert resources.files("python_lab").joinpath("scaffolding").is_dir(), "C3 scaffolding service is missing"
    from python_lab.scaffolding import ScaffoldResult, ScaffoldService
    from python_lab.scaffolding import registry
    return ScaffoldResult, ScaffoldService, registry


@pytest.mark.parametrize("template", ["cli", "fastapi"])
def test_registered_project_structure_and_name_normalization(tmp_path, template):
    Result, Service, registry = scaffold_api()
    target = tmp_path / "my-app"
    result = Service().create(template, target)
    expected = {
        "pyproject.toml", "README.md", ".gitignore",
        "src/my_app/__init__.py", "src/my_app/main.py", "tests/test_app.py",
    }
    assert isinstance(result, Result)
    assert result.target == target
    assert result.template == template
    assert {path.relative_to(target).as_posix() for path in result.files} == expected
    assert set(registry.TEMPLATES) == {"cli", "fastapi"}
    assert all(path.is_file() for path in result.files)
    with pytest.raises(FrozenInstanceError):
        result.template = "changed"
    manifest = tomllib.loads((target / "pyproject.toml").read_text())
    assert manifest["project"]["name"] == "my-app"
    assert "pytest" in " ".join(manifest["project"]["optional-dependencies"]["dev"])
    assert ".venv/" in (target / ".gitignore").read_text()
    readme = (target / "README.md").read_text()
    for command in ["python -m venv .venv", ".venv/bin/python", ".venv\\Scripts\\python.exe", 'pip install -e ".[dev]"', "-m pytest"]:
        assert command in readme
    assert "__package__" not in "".join(path.read_text() for path in result.files)
    if template == "cli":
        assert manifest["project"]["scripts"] == {"my_app": "my_app.main:main"}
        assert "--name" in (target / "src/my_app/main.py").read_text()
        assert "Olá, Ana!" in (target / "tests/test_app.py").read_text()
        assert manifest["project"]["dependencies"] == []
    else:
        assert "fastapi" in " ".join(manifest["project"]["dependencies"])
        assert "httpx" in " ".join(manifest["project"]["optional-dependencies"]["dev"])
        assert "TestClient" in (target / "tests/test_app.py").read_text()
        assert "/health" in (target / "tests/test_app.py").read_text()


def test_generation_is_offline_and_never_starts_processes(tmp_path, monkeypatch):
    _, Service, _ = scaffold_api()
    def forbidden(*args, **kwargs):
        pytest.fail("Scaffolding attempted network/install/execution")
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    Service().create("cli", tmp_path / "cli_app")
    Service().create("fastapi", tmp_path / "web_app")


@pytest.mark.parametrize("kind", ["directory", "file", "symlink", "dangling_symlink"])
def test_existing_target_is_preserved(tmp_path, kind):
    _, Service, _ = scaffold_api()
    target = tmp_path / "my_app"
    if kind == "directory":
        target.mkdir()
        original = target / "keep.txt"
        original.write_text("keep")
    elif kind == "file":
        original = target
        target.write_text("keep")
    else:
        original = tmp_path / "original"
        if kind == "symlink":
            original.write_text("keep")
        try:
            target.symlink_to(original)
        except OSError as exc:
            pytest.skip(f"Symlinks unavailable: {exc}")
    with pytest.raises(AssistantError, match="exist"):
        Service().create("cli", target)
    if kind != "dangling_symlink":
        assert original.read_text() == "keep"
    if "symlink" in kind:
        assert target.is_symlink()


@pytest.mark.parametrize("name", ["", ".", "..", "bad name", "3app", "class", "bad.app", "bad/app/../escape", r"bad\app", "bad:app"])
def test_invalid_names_and_traversal_are_rejected(tmp_path, name, monkeypatch):
    _, Service, _ = scaffold_api()
    monkeypatch.chdir(tmp_path)
    with pytest.raises(AssistantError):
        Service().create("cli", Path(name))
    assert list(tmp_path.iterdir()) == []


def test_unknown_template_does_not_create_target(tmp_path):
    _, Service, _ = scaffold_api()
    with pytest.raises(AssistantError, match="[Tt]emplate"):
        Service().create("unregistered", tmp_path / "app")
    assert not (tmp_path / "app").exists()


@pytest.mark.parametrize("path", ["../outside.txt", "/absolute.txt", r"..\outside.txt", "C:/outside.txt", "src/../outside.txt", "src//main.py"])
def test_malicious_manifest_path_is_rejected_before_creation(tmp_path, monkeypatch, path):
    _, Service, registry = scaffold_api()
    monkeypatch.setitem(registry.TEMPLATES, "cli", (path,))
    with pytest.raises(AssistantError, match="[Pp]ath"):
        Service().create("cli", tmp_path / "app")
    assert list(tmp_path.iterdir()) == []


def test_missing_packaged_resource_leaves_no_target(tmp_path, monkeypatch):
    _, Service, registry = scaffold_api()
    monkeypatch.setitem(registry.TEMPLATES, "cli", ("missing.txt",))
    with pytest.raises(AssistantError, match="[Rr]ecurso"):
        Service().create("cli", tmp_path / "app")
    assert not (tmp_path / "app").exists()


def test_only_registered_resources_are_copied(tmp_path, monkeypatch):
    _, Service, registry = scaffold_api()
    monkeypatch.setitem(registry.TEMPLATES, "cli", ("README.md",))
    result = Service().create("cli", tmp_path / "app")
    assert result.files == (tmp_path / "app/README.md",)
    assert list(result.target.iterdir()) == list(result.files)


@pytest.mark.parametrize("introduced", [False, True])
def test_failed_write_rolls_back_only_owned_files(tmp_path, monkeypatch, introduced):
    _, Service, _ = scaffold_api()
    target = tmp_path / "app"
    original_open = Path.open
    def interrupted(path, mode="r", *args, **kwargs):
        if path == target / ".gitignore" and mode == "xb":
            if introduced:
                (target / "user.txt").write_text("keep")
                (target / "README.md").write_text("edited by user")
            raise OSError("disk interrupted")
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", interrupted)
    with pytest.raises(AssistantError, match="disk interrupted"):
        Service().create("cli", target)
    if introduced:
        assert {path.name for path in target.iterdir()} == {"user.txt", "README.md"}
        assert (target / "user.txt").read_text() == "keep"
        assert (target / "README.md").read_text() == "edited by user"
    else:
        assert not target.exists()


def test_competing_target_creation_is_preserved(tmp_path, monkeypatch):
    _, Service, _ = scaffold_api()
    target = tmp_path / "app"
    original_mkdir = Path.mkdir
    def competitor(path, *args, **kwargs):
        if path == target:
            original_mkdir(path)
            (path / "keep.txt").write_text("keep")
        return original_mkdir(path, *args, **kwargs)
    monkeypatch.setattr(Path, "mkdir", competitor)
    with pytest.raises(AssistantError, match="exist"):
        Service().create("cli", target)
    assert (target / "keep.txt").read_text() == "keep"


def test_concurrent_preexisting_output_file_is_never_overwritten(tmp_path, monkeypatch):
    _, Service, _ = scaffold_api()
    target = tmp_path / "app"
    original_open = Path.open
    def competitor(path, mode="r", *args, **kwargs):
        if path == target / "README.md" and mode == "xb":
            path.write_text("user owns this")
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", competitor)
    with pytest.raises(AssistantError):
        Service().create("cli", target)
    assert list(target.iterdir()) == [target / "README.md"]
    assert (target / "README.md").read_text() == "user owns this"


def test_replaced_owned_file_is_preserved_on_rollback(tmp_path, monkeypatch):
    _, Service, _ = scaffold_api()
    target = tmp_path / "app"
    original_open = Path.open
    def interrupted(path, mode="r", *args, **kwargs):
        if path == target / ".gitignore" and mode == "xb":
            replacement = target / "user.tmp"
            replacement.write_text("user replacement")
            replacement.replace(target / "README.md")
            raise OSError("interrupted")
        return original_open(path, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", interrupted)
    with pytest.raises(AssistantError):
        Service().create("cli", target)
    assert list(target.iterdir()) == [target / "README.md"]
    assert (target / "README.md").read_text() == "user replacement"


def test_introduced_symlink_directory_cannot_redirect_writes(tmp_path, monkeypatch):
    _, Service, _ = scaffold_api()
    target = tmp_path / "app"
    outside = tmp_path / "outside"
    outside.mkdir()
    original_mkdir = Path.mkdir
    def competitor(path, *args, **kwargs):
        if path == target / "src":
            try:
                path.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                pytest.skip(f"Symlinks unavailable: {exc}")
        return original_mkdir(path, *args, **kwargs)
    monkeypatch.setattr(Path, "mkdir", competitor)
    with pytest.raises(AssistantError):
        Service().create("cli", target)
    assert list(outside.iterdir()) == []
    assert list(target.iterdir()) == [target / "src"]
    assert (target / "src").is_symlink()


def test_fastapi_manifest_keeps_testclient_compatible_starlette(tmp_path):
    _, Service, _ = scaffold_api()
    target = tmp_path / "app"
    Service().create("fastapi", target)
    project = tomllib.loads((target / "pyproject.toml").read_text())
    assert "starlette>=0.52,<1" in project["project"]["dependencies"]


def test_explicit_package_data_covers_every_registered_resource():
    _, _, registry = scaffold_api()
    manifest = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())
    packaged = set(manifest["tool"]["setuptools"]["package-data"]["python_lab.scaffolding"])
    expected = {f"templates/{template}/{path}" for template, paths in registry.TEMPLATES.items() for path in paths}
    assert packaged == expected


@pytest.mark.parametrize("name", ["_app", "app_", "app-", "-app"])
def test_invalid_distribution_names_are_rejected_before_generation(tmp_path, name):
    _, Service, _ = scaffold_api()
    with pytest.raises(AssistantError):
        Service().create("cli", tmp_path / name)
    assert list(tmp_path.iterdir()) == []
