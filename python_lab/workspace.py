"""Capture only explicitly selected, bounded project text."""

from collections.abc import Sequence
import hashlib
import os
from pathlib import Path
import stat
import subprocess

from python_lab.assistant.errors import ContextError
from python_lab.assistant.models import (
    MAX_CONTEXT_BYTES,
    MAX_SOURCE_BYTES,
    MAX_SOURCE_FILES,
    SourceFile,
    WorkspaceSnapshot,
)


def _excluded(path: Path) -> bool:
    for part in path.parts:
        name = part.casefold()
        if name in {".git", ".venv", "__pycache__", ".env"} or name.startswith(".env."):
            return True
        if name.endswith((".pem", ".key")):
            return True
    return False


class Workspace:
    def __init__(self, root: Path):
        try:
            selected_root = Path(root).absolute()
            self.root = selected_root.resolve(strict=True)
            if not self.root.is_dir():
                raise ContextError("Root deve ser um diretório existente.")
            if _excluded(selected_root) or _excluded(self.root):
                raise ContextError("Diretório excluído do contexto.")
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise ContextError("Não foi possível resolver o diretório do workspace.") from exc

    def _selected_path(self, path: Path) -> tuple[Path, Path]:
        if not isinstance(path, Path):
            raise ContextError("Selecione arquivos usando Path.")
        selected = path if path.is_absolute() else self.root / path
        try:
            selected_relative = selected.relative_to(self.root)
            resolved = selected.resolve(strict=True)
            resolved_relative = resolved.relative_to(self.root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ContextError("Arquivo inexistente ou fora do workspace.") from exc
        if _excluded(selected_relative) or _excluded(resolved_relative):
            raise ContextError("Arquivo excluído do contexto.")
        return selected_relative, resolved

    def _git_repository(self) -> bool:
        # Standard repositories, nested roots, submodules and worktrees all have
        # Git metadata at an ancestor. An empty .git placeholder is not a repo;
        # real metadata still identifies repos when Git itself cannot run.
        try:
            known_repo = any(
                (directory / ".git").is_file()
                or (directory / ".git").is_symlink()
                or any((directory / ".git" / name).exists() for name in ("HEAD", "config", "objects", "commondir"))
                for directory in (self.root, *self.root.parents)
            )
        except OSError as exc:
            raise ContextError("Não foi possível verificar os metadados Git.") from exc
        try:
            result = subprocess.run(
                ["git", "-C", str(self.root), "rev-parse", "--is-inside-work-tree"],
                capture_output=True, timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            if known_repo:
                raise ContextError("Não foi possível verificar o repositório Git.") from exc
            return False
        if result.returncode == 0 and result.stdout.strip() == b"true":
            return True
        if known_repo:
            raise ContextError("Não foi possível verificar o repositório Git.")
        return False

    def _check_ignored(self, selected: Sequence[tuple[Path, Path]]) -> None:
        if not self._git_repository():
            return
        names = []
        for alias, resolved in selected:
            names.extend((alias.as_posix(), resolved.relative_to(self.root).as_posix()))
        try:
            result = subprocess.run(
                ["git", "-C", str(self.root), "check-ignore", "--no-index", "--stdin", "-z"],
                input=("\x00".join(names) + "\x00").encode("utf-8"),
                capture_output=True, timeout=5, check=False,
            )
        except (OSError, subprocess.TimeoutExpired, UnicodeEncodeError) as exc:
            raise ContextError("Não foi possível verificar arquivos ignorados pelo Git.") from exc
        if result.returncode == 0:
            raise ContextError("Arquivo ignorado pelo Git não pode entrar no contexto.")
        if result.returncode != 1:
            raise ContextError("Não foi possível verificar arquivos ignorados pelo Git.")

    def _capture(self, path: Path) -> bytes:
        try:
            before = path.stat()
            if not stat.S_ISREG(before.st_mode):
                raise ContextError("Selecione somente arquivos regulares.")
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino) or path.resolve(strict=True) != path:
                    raise ContextError("Arquivo mudou de destino durante a captura.")
                captured = stream.read(MAX_SOURCE_BYTES + 1)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ContextError("Não foi possível capturar o arquivo selecionado.") from exc
        if len(captured) > MAX_SOURCE_BYTES:
            raise ContextError("Arquivo excede 32768 bytes.")
        return captured

    def snapshot(self, paths: Sequence[Path]) -> WorkspaceSnapshot:
        if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes)):
            raise ContextError("Selecione explicitamente uma sequência de arquivos.")
        if len(paths) > MAX_SOURCE_FILES:
            raise ContextError("Contexto excede 20 arquivos.")
        selected = [self._selected_path(path) for path in paths]
        if len({resolved for _, resolved in selected}) != len(selected):
            raise ContextError("Contexto contém arquivos selecionados mais de uma vez.")
        if selected:
            self._check_ignored(selected)
        sources = []
        total_bytes = 0
        for _, resolved in selected:
            captured = self._capture(resolved)
            total_bytes += len(captured)
            if total_bytes > MAX_CONTEXT_BYTES:
                raise ContextError("Contexto excede 131072 bytes.")
            try:
                text = captured.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ContextError("Arquivo deve usar UTF-8.") from exc
            if any(ord(char) < 32 and char not in "\t\n\r" for char in text):
                raise ContextError("Arquivo binário não pode entrar no contexto.")
            sources.append(SourceFile(
                path=resolved.relative_to(self.root).as_posix(),
                text=text,
                sha256=hashlib.sha256(captured).hexdigest(),
            ))
        return WorkspaceSnapshot(root=self.root, sources=tuple(sources))
