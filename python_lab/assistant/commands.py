"""Shared CLI and TUI handlers for explicit assistant and project actions."""

import asyncio
from dataclasses import asdict
from pathlib import Path
import threading
from collections.abc import Awaitable, Callable
import hashlib

from python_lab.analysis import AnalysisError, AnalysisService
from python_lab.app import PythonLabApp
from python_lab.assistant.errors import AssistantError, ContextError
from python_lab.assistant.models import AssistantMode, AssistantRequest
from python_lab.assistant.service import AssistantService
from python_lab.assistant.patches import PatchService
from python_lab.assistant.review import ReviewService
from python_lab.assistant.verification import VerificationService
from python_lab.scaffolding.service import ScaffoldService
from python_lab.scaffolding import registry
from python_lab.app import ApplicationError
from python_lab.progress import ProgressError
from python_lab.commands import CommandResult
from python_lab.runtime.processes import ProcessCleanupError
from python_lab.workspace import Workspace


class AssistantCommands:
    def __init__(self, service: AssistantService | None, workspace: Workspace,
                 mode: AssistantMode, *, app: PythonLabApp | None = None,
                 analysis: AnalysisService | None = None,
                 service_factory: Callable[[], AssistantService] | None = None,
                 patches: PatchService | None = None,
                 verification: VerificationService | None = None,
                 review_factory: Callable[[], ReviewService] | None = None):
        self.service = service
        self.workspace = workspace
        self.mode = mode
        self.app = app
        self.analysis = analysis or AnalysisService()
        self.service_factory = service_factory
        self.patches = patches
        self.verification = verification
        self.review_factory = review_factory


    def register(self, dispatcher):
        for name, handler in self.actions().items():
            dispatcher.register_async(name, handler)

    def actions(self):
        return {"/check": self.check, "/explain-code": self.explain,
                "/diagnose": self.diagnose, "/review": self.review,
                "/apply": self.apply, "/verify": self.verify, "/new": self.new}

    async def _blocking(self, function, cancel):
        if cancel.is_set():
            raise asyncio.CancelledError()
        worker = asyncio.create_task(asyncio.to_thread(function))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancel.set()
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            try:
                worker.result()
            except ProcessCleanupError:
                raise
            except Exception:
                pass
            raise

    @staticmethod
    def _error(exc, kind="usage"):
        return CommandResult(False, str(exc), {"error_kind": kind})

    @classmethod
    def _operation_error(cls, exc):
        # Services retain the operational cause without changing their public
        # validation errors. Classify only at the actual operation boundary.
        operational = isinstance(exc, OSError) or isinstance(
            exc.__cause__, (OSError, TypeError, ValueError))
        return cls._error(exc, "execution" if operational else "usage")

    async def review(self, args, *, cancel=None):
        action_cancel = cancel or threading.Event()
        try:
            snapshot = await self._blocking(
                lambda: self.workspace.snapshot(self._selection(args)), action_cancel)
            mission_id = self.app.progress.current_mission_id if self.app else None
            request = AssistantRequest("review", "Revise o código e proponha correções com diff.",
                                       self.mode, 3, snapshot, mission_id=mission_id)
            if self.review_factory is None:
                raise AssistantError("Serviço de revisão indisponível.")
            result = await self.review_factory().review(request, cancel=action_cancel)
            data = asdict(result)
            previews = []
            lines = ["Revisão local concluída; sugestões não são verificação executada."]
            for check in result.analysis.checks:
                lines.append(f"{check.tool}: {check.status}")
                lines.extend(f"  {issue.path}: {issue.message}" for issue in check.issues)
            if result.advice is None:
                lines.append("IA indisponível: configure provider, model, LAB_API_KEY e o extra assistant.")
            else:
                lines.extend((result.advice.summary, result.advice.explanation))
            for patch in result.proposals:
                diff = await self._blocking(lambda: self.patches.preview(patch), action_cancel)
                destination = str(self.workspace.root / patch.change.path)
                previews.append({"id": patch.id, "path": destination, "diff": diff,
                                 "reason": patch.reason, "status": "unverified"})
                lines.append(f"Proposta {patch.id} · {destination}\n{diff}\nPróximo: /apply {patch.id}")
            data["proposals"] = previews
            return CommandResult(True, "\n".join(lines), data)
        except (ValueError, ContextError) as exc:
            return self._error(exc)
        except (AssistantError, AnalysisError, ProcessCleanupError) as exc:
            return self._error(exc, "execution")

    async def apply(self, args, *, cancel=None,
                    confirm: Callable[[CommandResult], Awaitable[bool]] | None = None):
        action_cancel = cancel or threading.Event()
        try:
            if len(args) not in (1, 2) or (len(args) == 2 and args[1] != "--yes"):
                raise ValueError("Uso: /apply ID [--yes].")
            if self.patches is None:
                raise AssistantError("Serviço de propostas indisponível.")
            patch = await self._blocking(lambda: self.patches.load(args[0]), action_cancel)
            diff = await self._blocking(lambda: self.patches.preview(patch), action_cancel)
            destination = self.workspace.root / patch.change.path
            mission_id = self.app.progress.current_mission_id if self.app else None
            if mission_id and self.app.mission_by_id(mission_id).solution_path.resolve() != destination.resolve():
                mission_id = None
            workspace_id = hashlib.sha256(str(self.workspace.root).encode("utf-8")).hexdigest()
            event_key = f"apply:{workspace_id}:{patch.id}:{patch.change.before_sha256}"
            data = {"id": patch.id, "path": str(destination), "diff": diff,
                    "status": "unverified", "event_key": event_key}
            preview = CommandResult(False, f"Destino: {destination}\n{diff}\nConfirme com --yes: lab apply {patch.id} --yes.",
                                    {**data, "error_kind": "usage"})
            # A TUI always asks, even when its input includes --yes.
            confirmed = await confirm(preview) if confirm else len(args) == 2
            if not confirmed:
                return preview
            def write():
                if action_cancel.is_set():
                    raise asyncio.CancelledError()
                self.patches.apply(patch, confirmed=True)
                if mission_id is not None:
                    try:
                        self.app.record_full_solution(mission_id)
                    except (ApplicationError, ProgressError, OSError) as exc:
                        return CommandResult(False, f"Arquivo aplicado; falha ao registrar ajuda: {exc}",
                                             {**data, "error_kind": "execution", "applied": True})
                return None
            try:
                recording_failure = await self._blocking(write, action_cancel)
            except (AssistantError, OSError) as exc:
                return self._operation_error(exc)
            if recording_failure is not None:
                return recording_failure
            return CommandResult(True, f"Destino: {destination}\n{diff}\nAplicado; não verificado. Próximo: /verify {patch.id} --check ast.", data)
        except (ValueError, AssistantError, ContextError) as exc:
            return self._error(exc)
        except ProcessCleanupError as exc:
            return self._error(exc, "execution")

    async def verify(self, args, *, cancel=None):
        action_cancel = cancel or threading.Event()
        try:
            if not args or (len(args) - 1) % 2 or any(
                args[i] != "--check" for i in range(1, len(args), 2)
            ):
                raise ValueError("Uso: /verify ID [--check ast|ruff|pytest] (repetível).")
            checks = tuple(args[i] for i in range(2, len(args), 2))
            if any(name not in {"ast", "ruff", "pytest"} for name in checks) or len(set(checks)) != len(checks):
                raise ValueError("Checks permitidos sem repetição: ast, ruff, pytest.")
            if self.patches is None or self.verification is None:
                raise AssistantError("Serviço de verificação indisponível.")
            patch = await self._blocking(lambda: self.patches.load(args[0]), action_cancel)
            try:
                result = await self._blocking(lambda: self.verification.run(
                    patch, self.workspace, checks=checks, cancel=action_cancel), action_cancel)
            except (AssistantError, OSError) as exc:
                return self._operation_error(exc)
            data = {**asdict(result), "id": patch.id, "root": str(self.workspace.root)}
            lines = [f"Projeto: {self.workspace.root}", f"Verificação: {result.status}"]
            lines.extend(f"{item.name}: {item.status} · {item.detail}" for item in result.checks)
            if result.status == "unverified":
                lines.append("Selecione checks explicitamente; --check pytest executa testes/conftest neste projeto com seus privilégios.")
            ok = result.status in {"passed", "unverified"}
            if not ok:
                data["error_kind"] = "execution"
            return CommandResult(ok, "\n".join(lines), data)
        except (ValueError, AssistantError, ContextError) as exc:
            return self._error(exc)
        except ProcessCleanupError as exc:
            return self._error(exc, "execution")

    async def new(self, args, *, cancel=None):
        action_cancel = cancel or threading.Event()
        try:
            if len(args) != 4 or args[2] != "--path":
                raise ValueError(f"Uso: /new {'|'.join(registry.TEMPLATES)} NAME --path PARENT.")
            template, name, _, parent = args
            if not name or Path(name).name != name or "/" in name or "\\" in name:
                raise ValueError("Nome deve ser apenas o nome do novo projeto.")
            target = Path(parent).expanduser().resolve() / name
            try:
                result = await self._blocking(lambda: ScaffoldService().create(template, target), action_cancel)
            except AssistantError as exc:
                # An exclusively created target can lose a race to another
                # creator; that existing destination remains a usage rejection.
                cause = exc.__cause__
                if isinstance(cause, FileExistsError) and cause.filename == str(target):
                    return self._error(exc)
                return self._operation_error(exc)
            data = {"target": str(result.target), "files": [str(path) for path in result.files],
                    "template": result.template}
            lines = [f"Projeto criado: {result.target}", *data["files"],
                     f'Próximo: cd "{result.target}"', "python -m venv .venv",
                     "Ative o ambiente e execute: python -m pip install -e '.[dev]'",
                     "python -m pytest"]
            return CommandResult(True, "\n".join(lines), data)
        except (ValueError, AssistantError, ContextError) as exc:
            return self._error(exc)
        except OSError as exc:
            return self._error(exc, "execution")

    def _service(self) -> AssistantService:
        if self.service is None and self.service_factory is not None:
            self.service = self.service_factory()
        if self.service is None:
            raise AssistantError("Assistente indisponível: configure provider='openai', model e LAB_API_KEY.")
        return self.service

    def _selection(self, names: tuple[str, ...]) -> tuple[Path, ...]:
        if not names:
            raise ValueError("Selecione pelo menos um arquivo do projeto.")
        return tuple(Path(name) for name in names)

    async def _inspect(self, snapshot, cancel: threading.Event):
        worker = asyncio.create_task(asyncio.to_thread(self.analysis.inspect, snapshot, cancel=cancel))
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancel.set()
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if worker.done():
                try:
                    worker.result()
                except ProcessCleanupError as exc:
                    raise AssistantError(f"Falha ao encerrar análise local: {exc}") from exc
                except Exception:
                    pass
            raise

    async def check(self, args: tuple[str, ...], *, cancel: threading.Event | None = None) -> CommandResult:
        action_cancel = cancel or threading.Event()
        try:
            snapshot = self.workspace.snapshot(self._selection(args))
            report = await self._inspect(snapshot, action_cancel)
            lines = ["Verificação local concluída."]
            for check in report.checks:
                lines.append(f"{check.tool}: {check.status}")
                for issue in check.issues:
                    location = f"{issue.path}:{issue.line}" if issue.line is not None else issue.path
                    lines.append(f"  {location} [{issue.code}] {issue.message}")
            return CommandResult(True, "\n".join(lines), asdict(report))
        except asyncio.CancelledError:
            raise
        except (ValueError, ContextError, AssistantError) as exc:
            return CommandResult(False, str(exc), {"error_kind": "usage"})
        except (AnalysisError, ProcessCleanupError) as exc:
            return CommandResult(False, str(exc), {"error_kind": "execution"})

    async def explain(self, args: tuple[str, ...], *, cancel: threading.Event | None = None) -> CommandResult:
        return await self._generate("explain", args, cancel=cancel)

    async def diagnose(self, args: tuple[str, ...], *, cancel: threading.Event | None = None) -> CommandResult:
        return await self._generate("diagnose", args, cancel=cancel)

    async def _generate(self, action: str, args: tuple[str, ...], *, cancel: threading.Event | None) -> CommandResult:
        action_cancel = cancel or threading.Event()
        try:
            names = []
            traceback_path = None
            level = 0
            index = 0
            while index < len(args):
                token = args[index]
                if token in {"--traceback", "--file", "--level"}:
                    if index + 1 >= len(args):
                        raise ValueError(f"Informe um valor para {token}.")
                    value = args[index + 1]
                    if token == "--traceback":
                        traceback_path = value
                    elif token == "--file":
                        names.append(value)
                    else:
                        try:
                            level = int(value)
                        except ValueError:
                            raise ValueError("Nível deve estar entre 0 e 4.") from None
                    index += 2
                else:
                    if token.startswith("--"):
                        raise ValueError(f"Opção desconhecida: {token}.")
                    names.append(token)
                    index += 1
            if not 0 <= level <= 4:
                raise ValueError("Nível deve estar entre 0 e 4.")
            if action == "diagnose" and traceback_path is None:
                raise ValueError("Use --traceback ARQUIVO para diagnosticar.")
            snapshot = self.workspace.snapshot(self._selection(tuple(names)))
            traceback = None
            if traceback_path is not None:
                trace_snapshot = self.workspace.snapshot((Path(traceback_path),))
                traceback = trace_snapshot.sources[0].text
            mission_id = self.app.progress.current_mission_id if self.app is not None else None
            mode = self.mode
            prompt = ("Explique o código selecionado e suas causas."
                      if action == "explain" else "Diagnostique o traceback usando o código selecionado como dados.")
            request = AssistantRequest(action, prompt, mode, level, snapshot,
                                       traceback=traceback, mission_id=mission_id)
            service = self._service()
            answer = await service.execute(request, cancel=action_cancel)
            data = asdict(answer)
            sections = [answer.summary, answer.explanation, "\n".join(answer.steps)]
            references = ", ".join(
                f"{ref.path}:{ref.start_line}" +
                (f"-{ref.end_line}" if ref.end_line != ref.start_line else "")
                for ref in answer.references
            )
            sections.append(f"Referências: {references or 'nenhuma'}")
            sections.append(f"Tokens: entrada {answer.usage.input_tokens}, saída {answer.usage.output_tokens}")
            message = "\n\n".join(part for part in sections if part)
            return CommandResult(True, message, data)
        except asyncio.CancelledError:
            raise
        except (ValueError, ContextError) as exc:
            return CommandResult(False, str(exc), {"error_kind": "usage"})
        except AssistantError as exc:
            kind = "usage" if self.service is None or "Configure" in str(exc) or "Instale" in str(exc) else "execution"
            return CommandResult(False, str(exc), {"error_kind": kind})
