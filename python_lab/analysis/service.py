"""Parse captured text and inspect unchanged files with isolated local tools."""

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import threading

from python_lab.analysis.models import AnalysisReport, Issue, ToolCheck
from python_lab.app import ApplicationError
from python_lab.assistant.errors import ContextError
from python_lab.assistant.models import MAX_SOURCE_BYTES, SourceFile, WorkspaceSnapshot
from python_lab.runtime.processes import ProcessCleanupError, ProcessResult, ProcessRunner


class AnalysisError(ApplicationError):
    """A tool could not produce a complete, trustworthy analysis."""


class AnalysisCancelled(AnalysisError):
    """Analysis was cancelled; ProcessRunner has finished process cleanup."""


def _cancelled(cancel: threading.Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise AnalysisCancelled("Análise cancelada.")


def _temporary_parents() -> list[str]:
    # Enumerate only: gettempdir() probes candidates by writing a file, which
    # would violate read-only inspection if an environment path is in-project.
    candidates = [value for name in ("TMPDIR", "TEMP", "TMP") if (value := os.getenv(name))]
    if tempfile.tempdir is not None:
        candidates.append(os.fsdecode(tempfile.tempdir))
    if os.name == "nt":
        candidates.extend([
            os.path.expanduser(r"~\AppData\Local\Temp"),
            os.path.expandvars(r"%SYSTEMROOT%\Temp"),
            r"C:\temp", r"C:\tmp", r"\temp", r"\tmp",
        ])
    else:
        candidates.extend(["/tmp", "/var/tmp", "/usr/tmp"])
    candidates.append(os.getcwd())
    return candidates


def _external_temporary_directory(root: Path, cancel: threading.Event | None) -> tempfile.TemporaryDirectory:
    for candidate in _temporary_parents():
        _cancelled(cancel)
        try:
            parent = Path(candidate).resolve(strict=True)
            # Resolve and reject containment before *any* allocation or writable
            # probe. In particular, a symlink to the project is not external.
            if parent.is_relative_to(root) or not parent.is_dir():
                continue
            if not os.access(parent, os.W_OK | os.X_OK):
                continue
            return tempfile.TemporaryDirectory(prefix="python-lab-analysis-", dir=parent)
        except (OSError, RuntimeError, ValueError):
            continue  # Try another external location if allocation is denied.
    _cancelled(cancel)
    raise AnalysisError("Não há diretório temporário disponível fora do workspace.")


def _unchanged(snapshot: WorkspaceSnapshot, sources: tuple[SourceFile, ...]) -> None:
    for source in sources:
        path = snapshot.root / source.path
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(snapshot.root)
            if resolved != path or not stat.S_ISREG(path.stat().st_mode):
                raise ContextError("Arquivo mudou de destino após a captura.")
            with path.open("rb") as stream:
                data = stream.read(MAX_SOURCE_BYTES + 1)
            if hashlib.sha256(data).hexdigest() != source.sha256:
                raise ContextError("Arquivo mudou após a captura; selecione o contexto novamente.")
        except (OSError, RuntimeError, ValueError) as exc:
            raise ContextError("Não foi possível validar o arquivo capturado.") from exc


def _issue_path(value: object, snapshot: WorkspaceSnapshot, sources: tuple[SourceFile, ...]) -> str:
    if not isinstance(value, str):
        raise AnalysisError("Path inválido no resultado da ferramenta.")
    path = Path(value)
    if not path.is_absolute():
        path = snapshot.root / path
    # Do not resolve untrusted tool paths through links or accept unselected files.
    for source in sources:
        if path == snapshot.root / source.path:
            return source.path
    raise AnalysisError("Ferramenta retornou achado fora dos arquivos selecionados.")


class AnalysisService:
    def __init__(self, *, runner: ProcessRunner | None = None):
        self._runner = runner if runner is not None else ProcessRunner()

    def _run(self, tool: str, args: list[str], snapshot: WorkspaceSnapshot,
             sources: tuple[SourceFile, ...], cancel: threading.Event | None) -> ProcessResult | None:
        _cancelled(cancel)
        _unchanged(snapshot, sources)
        module = "ruff" if tool.startswith("ruff") else "mypy"
        try:
            completed = self._runner.run(
                [sys.executable, "-I", "-m", module, *args, "--",
                 *(str(snapshot.root / source.path) for source in sources)],
                cwd=snapshot.root, timeout=30.0, output_limit=1048576, cancel=cancel,
            )
        except ProcessCleanupError:
            raise  # Cleanup uncertainty must never become ordinary cancellation.
        except FileNotFoundError:
            _unchanged(snapshot, sources)
            _cancelled(cancel)
            return None
        except OSError as exc:
            _unchanged(snapshot, sources)
            raise AnalysisError(f"Não foi possível executar {tool}: {exc}") from exc
        # ProcessRunner only returns after termination and reader cleanup.
        if completed.cancelled:
            raise AnalysisCancelled("Análise cancelada.")
        _cancelled(cancel)
        _unchanged(snapshot, sources)
        if completed.timed_out:
            raise AnalysisError(f"{tool} excedeu o tempo limite de 30 segundos.")
        if completed.truncated:
            raise AnalysisError(f"Resultado de {tool} excedeu o limite de saída.")
        missing = f"{sys.executable}: No module named {module}"
        if completed.return_code == 1 and completed.output.strip() in {missing, missing.replace(module, f"'{module}'")}:
            return None
        allowed_codes = (0, 1, 2) if tool in {"ruff-format", "mypy"} else (0, 1)
        if completed.return_code not in allowed_codes:
            raise AnalysisError(f"{tool} falhou (código {completed.return_code}): {completed.output}")
        return completed

    def inspect(self, snapshot: WorkspaceSnapshot, *, typing: bool = False,
                cancel: threading.Event | None = None) -> AnalysisReport:
        _cancelled(cancel)
        sources = tuple(source for source in snapshot.sources if Path(source.path).suffix == ".py")
        if not sources:
            return AnalysisReport(())
        syntax = []
        for source in sources:
            _cancelled(cancel)
            try:
                ast.parse(source.text, filename=source.path)
            except SyntaxError as exc:
                syntax.append(Issue(source.path, exc.lineno, "SyntaxError", exc.msg, "ast"))
        checks = [ToolCheck("ast", "failed" if syntax else "passed", tuple(syntax))]

        lint = self._run("ruff", ["check", "--isolated", "--no-cache", "--output-format=json"],
                         snapshot, sources, cancel)
        checks.append(self._ruff(lint, snapshot, sources))
        formatting = self._run("ruff-format", ["format", "--check", "--isolated", "--no-cache"],
                               snapshot, sources, cancel)
        checks.append(self._format(formatting, snapshot, sources))
        if typing:
            # Both config and cache stay outside the selected project. Never load
            # project plugins or traverse project imports for type checking.
            with _external_temporary_directory(snapshot.root, cancel) as directory:
                config = Path(directory) / "mypy.ini"
                config.write_text("[mypy]\nplugins =\n", encoding="utf-8")
                typed = self._run("mypy", ["--config-file", str(config), "--no-incremental",
                    "--cache-dir", str(Path(directory) / "cache"), "--follow-imports=skip",
                    "--ignore-missing-imports", "--show-error-codes", "--no-error-summary",
                    "--no-pretty", "--no-color-output"], snapshot, sources, cancel)
                checks.append(self._mypy(typed, snapshot, sources))
        _cancelled(cancel)
        return AnalysisReport(tuple(checks))

    @staticmethod
    def _ruff(result: ProcessResult | None, snapshot: WorkspaceSnapshot,
              sources: tuple[SourceFile, ...]) -> ToolCheck:
        if result is None:
            return ToolCheck("ruff", "unavailable", ())
        try:
            payload = json.loads(result.output)
            if not isinstance(payload, list):
                raise ValueError("Expected array")
            issues = []
            for entry in payload:
                path = _issue_path(entry["filename"], snapshot, sources)
                line = entry["location"]["row"]
                if type(line) is not int or line < 1 or not isinstance(entry["message"], str):
                    raise ValueError("Invalid finding")
                # Ruff parser findings have no lint code; retain a stable code.
                code = entry["code"]
                if code is not None and (not isinstance(code, str) or not code):
                    raise ValueError("Invalid code")
                issues.append(Issue(path, line, code or "SyntaxError", entry["message"], "ruff"))
        except (ValueError, KeyError, TypeError) as exc:
            raise AnalysisError("Resultado JSON de Ruff inválido.") from exc
        if bool(issues) != (result.return_code == 1):
            raise AnalysisError("Ruff retornou código incompatível com os achados.")
        return ToolCheck("ruff", "failed" if issues else "passed", tuple(issues))

    @staticmethod
    def _format(result: ProcessResult | None, snapshot: WorkspaceSnapshot,
                sources: tuple[SourceFile, ...]) -> ToolCheck:
        if result is None:
            return ToolCheck("ruff-format", "unavailable", ())
        issues = []
        for line in result.output.splitlines():
            parsing = re.fullmatch(r"error: Failed to parse (.+?):([1-9]\d*):[1-9]\d*: (.+)", line)
            if parsing and result.return_code == 2:
                path, number, message = parsing.groups()
                issues.append(Issue(_issue_path(path, snapshot, sources), int(number),
                                    "SyntaxError", message, "ruff-format"))
            elif line.startswith("Would reformat: "):
                path = _issue_path(line.removeprefix("Would reformat: "), snapshot, sources)
                issues.append(Issue(path, None, "FORMAT", "Arquivo requer formatação.", "ruff-format"))
            elif line and not re.fullmatch(r"\d+ files? (?:would be reformatted|already formatted)(?:, \d+ files? already formatted)?", line):
                raise AnalysisError("Resultado de Ruff format inválido.")
        if bool(issues) != (result.return_code in (1, 2)) or (
            result.return_code == 2 and not any(issue.code == "SyntaxError" for issue in issues)
        ):
            raise AnalysisError("Ruff format falhou sem achados de formatação válidos.")
        return ToolCheck("ruff-format", "failed" if issues else "passed", tuple(issues))

    @staticmethod
    def _mypy(result: ProcessResult | None, snapshot: WorkspaceSnapshot,
              sources: tuple[SourceFile, ...]) -> ToolCheck:
        if result is None:
            return ToolCheck("mypy", "unavailable", ())
        issues = []
        for line in result.output.splitlines():
            match = re.fullmatch(r"(.+?):(\d+): (error|note|warning): (.+?)(?:  \[([^\]]+)\])?", line)
            if not match:
                raise AnalysisError("Resultado de Mypy inválido.")
            path, number, severity, message, code = match.groups()
            issues.append(Issue(_issue_path(path, snapshot, sources), int(number),
                                code or severity, message, "mypy"))
        if result.return_code in (1, 2) and not any(issue.code != "note" for issue in issues):
            raise AnalysisError("Mypy falhou sem diagnóstico válido.")
        if result.return_code == 2 and not any(issue.code == "syntax" for issue in issues):
            raise AnalysisError("Mypy falhou sem diagnóstico de sintaxe válido.")
        if result.return_code == 0 and issues:
            raise AnalysisError("Mypy retornou código incompatível com os achados.")
        return ToolCheck("mypy", "failed" if result.return_code else "passed", tuple(issues))
