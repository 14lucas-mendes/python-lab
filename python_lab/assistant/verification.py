"""Explicit, hash-bound checks for an applied single-file proposal."""

import ast
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import tempfile
from typing import Literal

from python_lab.analysis.service import _external_temporary_directory
from python_lab.assistant.errors import AssistantError, ContextError
from python_lab.assistant.models import PatchProposal
from python_lab.runtime.processes import ProcessCleanupError, ProcessRunner
from python_lab.test_runner import _pytest_report_details
from python_lab.workspace import Workspace


@dataclass(frozen=True)
class VerificationCheck:
    name: Literal["ast", "ruff", "pytest"]
    status: Literal["passed", "failed", "unavailable", "cancelled"]
    detail: str


@dataclass(frozen=True)
class VerificationResult:
    status: Literal["unverified", "passed", "failed", "cancelled"]
    checks: tuple[VerificationCheck, ...]
    sha256: str | None = None
    selected_sources: tuple[tuple[str, str], ...] = ()


class VerificationStore:
    """Workspace-scoped private records; an ID is always an opaque hash key."""

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)

    def _path(self, proposal: PatchProposal) -> Path:
        key = hashlib.sha256(proposal.id.encode("utf-8")).hexdigest()
        return self.data_dir / "verifications" / f"{key}.json"

    def save(
        self, proposal: PatchProposal, workspace: Workspace, result: VerificationResult
    ) -> None:
        directory = self._path(proposal).parent
        if self.data_dir.is_symlink():
            raise AssistantError("Estado de verificação não pode ser symlink.")
        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink():
            raise AssistantError("Estado de verificação não pode ser symlink.")
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink():
            raise AssistantError("Estado de verificação mudou de destino.")
        if os.name == "posix":
            directory.chmod(0o700)
        record = self._path(proposal)
        if record.exists() and self.load(proposal, workspace) is None:
            raise AssistantError(
                "ID de verificação pertence a outra proposta ou workspace."
            )
        payload = {
            "workspace": str(workspace.root),
            "proposal": asdict(proposal),
            "result": asdict(result),
        }
        temporary = None
        try:
            fd, name = tempfile.mkstemp(
                prefix=".python-lab-verification-", dir=directory
            )
            temporary = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                if os.name == "posix":
                    os.fchmod(stream.fileno(), 0o600)
                json.dump(payload, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, record)
            temporary = None
        except (OSError, TypeError, ValueError) as exc:
            raise AssistantError("Não foi possível salvar verificação.") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def load(
        self, proposal: PatchProposal, workspace: Workspace
    ) -> VerificationResult | None:
        try:
            with self._path(proposal).open(encoding="utf-8") as stream:
                payload = json.load(stream)
            if payload["workspace"] != str(workspace.root) or payload[
                "proposal"
            ] != json.loads(json.dumps(asdict(proposal))):
                return None
            raw = payload["result"]
            checks = tuple(VerificationCheck(**item) for item in raw["checks"])
            fingerprints = raw.get("selected_sources", [])
            if not isinstance(fingerprints, list):
                return None
            if fingerprints and (
                len(fingerprints) != len(proposal.selected_paths)
                or any(
                    not isinstance(item, list)
                    or len(item) != 2
                    or item[0] != path
                    or not isinstance(item[1], str)
                    or len(item[1]) != 64
                    or any(char not in "0123456789abcdef" for char in item[1])
                    for item, path in zip(fingerprints, proposal.selected_paths)
                )
            ):
                return None
            return VerificationResult(
                raw["status"], checks, raw["sha256"],
                tuple((path, digest) for path, digest in fingerprints),
            )
        except (OSError, ValueError, TypeError, KeyError):
            return None


class VerificationService:
    def __init__(
        self, runner: ProcessRunner, *, store: VerificationStore | None = None
    ):
        self.runner = runner
        self.store = store

    @staticmethod
    def _snapshot(proposal: PatchProposal, workspace: Workspace):
        if not isinstance(proposal, PatchProposal) or not isinstance(
            workspace, Workspace
        ):
            raise AssistantError("Proposta ou workspace inválido.")
        try:
            snapshot = workspace.snapshot(
                [Path(path) for path in proposal.selected_paths]
            )
        except ContextError as exc:
            raise AssistantError(f"Fontes selecionadas indisponíveis: {exc}") from exc
        if tuple(source.path for source in snapshot.sources) != proposal.selected_paths:
            raise AssistantError("Seleção mudou de destino.")
        source = next(
            (
                source
                for source in snapshot.sources
                if source.path == proposal.change.path
            ),
            None,
        )
        expected = hashlib.sha256(
            proposal.change.after_text.encode("utf-8")
        ).hexdigest()
        if source is None or source.sha256 != expected:
            raise AssistantError(
                "Arquivo aplicado mudou ou não corresponde à proposta."
            )
        return snapshot, source, expected

    def current(
        self, proposal: PatchProposal, workspace: Workspace
    ) -> VerificationResult:
        stored = (
            self.store.load(proposal, workspace) if self.store is not None else None
        )
        if stored is None or not stored.selected_sources:
            return VerificationResult("unverified", ())
        try:
            snapshot, _, digest = self._snapshot(proposal, workspace)
        except AssistantError:
            return VerificationResult("unverified", ())
        return (
            stored
            if stored.sha256 == digest and stored.selected_sources == tuple(
                (source.path, source.sha256) for source in snapshot.sources
            )
            else VerificationResult("unverified", ())
        )

    def run(
        self,
        proposal: PatchProposal,
        workspace: Workspace,
        *,
        checks: tuple[str, ...],
        cancel: threading.Event | None = None,
    ) -> VerificationResult:
        if (
            not isinstance(checks, tuple)
            or any(name not in {"ast", "ruff", "pytest"} for name in checks)
            or len(set(checks)) != len(checks)
        ):
            raise AssistantError("Checks permitidos: ast, ruff, pytest.")
        if not checks:
            return VerificationResult("unverified", ())
        if cancel is not None and cancel.is_set():
            return VerificationResult("cancelled", ())
        snapshot, source, digest = self._snapshot(proposal, workspace)
        results = []
        for name in checks:
            if cancel is not None and cancel.is_set():
                results.append(
                    VerificationCheck(name, "cancelled", "Execução cancelada.")
                )
                break
            if name == "ast":
                try:
                    ast.parse(source.text, filename=source.path)
                    check = VerificationCheck("ast", "passed", "Sintaxe válida.")
                except SyntaxError as exc:
                    check = VerificationCheck(
                        "ast", "failed", f"Linha {exc.lineno}: {exc.msg}"
                    )
            elif name == "ruff":
                try:
                    result = self.runner.run(
                        [
                            sys.executable,
                            "-I",
                            "-m",
                            "ruff",
                            "check",
                            "--isolated",
                            "--no-cache",
                            "--output-format=json",
                            "--",
                            str(workspace.root / source.path),
                        ],
                        cwd=workspace.root,
                        timeout=30.0,
                        cancel=cancel,
                    )
                except FileNotFoundError:
                    check = VerificationCheck(
                        "ruff", "unavailable", "Ruff indisponível."
                    )
                except OSError as exc:
                    if isinstance(exc, ProcessCleanupError):
                        raise
                    check = VerificationCheck(
                        "ruff", "unavailable", f"Falha ao iniciar Ruff: {exc}"
                    )
                else:
                    if result.cancelled:
                        check = VerificationCheck(
                            "ruff", "cancelled", "Execução cancelada."
                        )
                    elif result.timed_out:
                        check = VerificationCheck(
                            "ruff", "failed", "Ruff excedeu 30 segundos."
                        )
                    elif result.truncated:
                        check = VerificationCheck(
                            "ruff", "failed", "Saída de Ruff incompleta."
                        )
                    elif result.return_code == 1 and "No module named" in result.output:
                        check = VerificationCheck(
                            "ruff", "unavailable", "Ruff indisponível."
                        )
                    else:
                        try:
                            findings = json.loads(result.output)
                            if (
                                not isinstance(findings, list)
                                or (result.return_code == 0) != (len(findings) == 0)
                                or result.return_code not in (0, 1)
                            ):
                                raise ValueError()
                            check = VerificationCheck(
                                "ruff",
                                "failed" if findings else "passed",
                                f"{len(findings)} achado(s) de Ruff.",
                            )
                        except ValueError:
                            check = VerificationCheck(
                                "ruff", "failed", "Resultado de Ruff inválido."
                            )
            else:
                # Allocate outside the project even when TMPDIR points inside it.
                with _external_temporary_directory(workspace.root, cancel) as directory:
                    report = Path(directory) / "results.xml"
                    try:
                        result = self.runner.run(
                            [
                                sys.executable,
                                "-X",
                                f"pycache_prefix={Path(directory) / 'cache'}",
                                "-m",
                                "pytest",
                                str(workspace.root),
                                "-q",
                                "-p",
                                "no:cacheprovider",
                                "--junitxml",
                                str(report),
                            ],
                            cwd=workspace.root,
                            timeout=30.0,
                            cancel=cancel,
                        )
                    except FileNotFoundError:
                        check = VerificationCheck(
                            "pytest", "unavailable", "Pytest indisponível."
                        )
                    except OSError as exc:
                        if isinstance(exc, ProcessCleanupError):
                            raise
                        check = VerificationCheck(
                            "pytest", "unavailable", f"Falha ao iniciar pytest: {exc}"
                        )
                    else:
                        if result.cancelled:
                            check = VerificationCheck(
                                "pytest", "cancelled", "Execução cancelada."
                            )
                        elif result.timed_out:
                            check = VerificationCheck(
                                "pytest", "failed", "Pytest excedeu 30 segundos."
                            )
                        elif result.truncated:
                            check = VerificationCheck(
                                "pytest", "failed", "Saída de pytest incompleta."
                            )
                        elif result.return_code == 1 and "No module named pytest" in result.output:
                            check = VerificationCheck(
                                "pytest", "unavailable", "Pytest indisponível."
                            )
                        else:
                            complete, summary, diagnostics = _pytest_report_details(
                                report
                            )
                            detail = "; ".join((summary, *diagnostics))
                            check = VerificationCheck(
                                "pytest",
                                "passed"
                                if result.return_code == 0 and complete
                                else "failed",
                                detail,
                            )
            if cancel is not None and cancel.is_set():
                check = VerificationCheck(name, "cancelled", "Execução cancelada.")
            results.append(check)
            if check.status == "cancelled":
                break
        # A stale capture cannot inherit results from checks that ran on another version.
        after, _, _ = self._snapshot(proposal, workspace)
        if after != snapshot:
            raise AssistantError("Fontes selecionadas mudaram durante a verificação.")
        status = (
            "cancelled"
            if (cancel is not None and cancel.is_set())
            or any(item.status == "cancelled" for item in results)
            else (
                "passed"
                if len(results) == len(checks)
                and all(item.status == "passed" for item in results)
                else "failed"
            )
        )
        verification = VerificationResult(
            status, tuple(results), digest,
            tuple((source.path, source.sha256) for source in snapshot.sources),
        )
        if self.store is not None:
            self.store.save(proposal, workspace, verification)
        return verification
