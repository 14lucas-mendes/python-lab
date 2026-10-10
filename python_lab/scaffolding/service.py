"""Copy only registered resources into an exclusively created target directory."""

from importlib import resources
import keyword
import os
from pathlib import Path, PurePosixPath
import re
import stat

from python_lab.assistant.errors import AssistantError
from python_lab.scaffolding import registry
from python_lab.scaffolding.models import ScaffoldResult


def _relative_path(value: str) -> PurePosixPath:
    if (
        not value
        or "\\" in value
        or ":" in value
        or "\x00" in value
        or value.startswith("/")
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise AssistantError("Path de template deve ser relativo e sem travessia.")
    return PurePosixPath(value)


def _identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    return info.st_dev, info.st_ino


def _directories_intact(path: Path, directories: dict[Path, tuple[int, int]]) -> bool:
    """Refuse retargeted/symlinked ancestors, including during cleanup."""
    for directory, identity in directories.items():
        if directory == path or directory in path.parents:
            try:
                if not stat.S_ISDIR(directory.lstat().st_mode) or _identity(directory) != identity:
                    return False
            except OSError:
                return False
    return True


def _rollback(
    files: dict[Path, tuple[tuple[int, int], bytes]],
    directories: dict[Path, tuple[int, int]],
) -> None:
    # Never recurse: preserve replacements, edits and concurrently introduced files.
    for path, (identity, content) in reversed(tuple(files.items())):
        try:
            if (
                _directories_intact(path, directories)
                and stat.S_ISREG(path.lstat().st_mode)
                and _identity(path) == identity
                and path.read_bytes() == content
            ):
                path.unlink()
        except OSError:
            pass  # Uncertain ownership or failed cleanup leaves the user's path intact.
    for directory, identity in reversed(tuple(directories.items())):
        try:
            if _directories_intact(directory, directories) and _identity(directory) == identity:
                directory.rmdir()  # Only an empty directory can be removed.
        except OSError:
            pass


class ScaffoldService:
    def create(self, template: str, target: Path) -> ScaffoldResult:
        if template not in registry.TEMPLATES:
            raise AssistantError(f"Template desconhecido: {template}.")
        if not isinstance(target, Path):
            raise AssistantError("Destino deve ser Path.")
        package = target.name.replace("-", "_")
        if (
            not target.name
            or ".." in target.parts
            or "\\" in str(target)
            or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9])?", target.name)
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", package)
            or not package.isidentifier()
            or keyword.iskeyword(package)
        ):
            raise AssistantError("Nome de projeto Python inválido ou destino com travessia.")
        if target.exists() or target.is_symlink():
            raise AssistantError("Destino já existe.")

        # Read/validate all resources before touching the destination. Only these
        # two literal tokens are substituted; template text is never evaluated.
        root = resources.files("python_lab.scaffolding").joinpath("templates", template)
        rendered: dict[Path, bytes] = {}
        for source in registry.TEMPLATES[template]:
            source_path = _relative_path(source)
            destination = _relative_path(source.replace("__package__", package))
            path = target.joinpath(*destination.parts)
            if path in rendered:
                raise AssistantError("Path de template duplicado.")
            try:
                text = root.joinpath(*source_path.parts).read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                raise AssistantError(f"Recurso de template indisponível: {source}.") from exc
            rendered[path] = text.replace("__package__", package).replace("__distribution__", target.name).encode("utf-8")

        directories: dict[Path, tuple[int, int]] = {}
        files: dict[Path, tuple[tuple[int, int], bytes]] = {}
        try:
            try:
                target.mkdir()  # No parents/exist_ok: an existing target is never ours.
            except FileExistsError as exc:
                raise AssistantError("Destino já existe.") from exc
            directories[target] = _identity(target)
            for path, content in rendered.items():
                parents = list(path.relative_to(target).parents)[:-1]
                for relative in reversed(parents):
                    directory = target / relative
                    if directory not in directories:
                        if not _directories_intact(directory, directories):
                            raise AssistantError("Diretório de destino foi alterado.")
                        directory.mkdir()
                        directories[directory] = _identity(directory)
                if not _directories_intact(path, directories):
                    raise AssistantError("Diretório de destino foi alterado.")
                with path.open("xb") as handle:
                    info = os.fstat(handle.fileno())
                    identity = (info.st_dev, info.st_ino)
                    files[path] = (identity, b"")
                    # Ownership snapshots preserve unknown partial writes and
                    # edits after an interrupted write.
                    handle.write(content)
                    handle.flush()
                    files[path] = (identity, content)
        except (OSError, AssistantError) as exc:
            _rollback(files, directories)
            if isinstance(exc, AssistantError):
                raise
            raise AssistantError(f"Não foi possível criar projeto: {exc}") from exc
        return ScaffoldResult(target, tuple(rendered), template)
