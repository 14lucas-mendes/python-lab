"""Shared CLI and TUI handlers for explicit, read-only assistant actions."""

import asyncio
from dataclasses import asdict
from pathlib import Path
import threading
from collections.abc import Callable

from python_lab.analysis import AnalysisCancelled, AnalysisError, AnalysisService
from python_lab.app import PythonLabApp
from python_lab.assistant.errors import AssistantError, ContextError
from python_lab.assistant.models import AssistantMode, AssistantRequest
from python_lab.assistant.service import AssistantService
from python_lab.commands import CommandResult
from python_lab.runtime.processes import ProcessCleanupError
from python_lab.workspace import Workspace


class AssistantCommands:
    def __init__(self, service: AssistantService | None, workspace: Workspace,
                 mode: AssistantMode, *, app: PythonLabApp | None = None,
                 analysis: AnalysisService | None = None,
                 service_factory: Callable[[], AssistantService] | None = None):
        self.service = service
        self.workspace = workspace
        self.mode = mode
        self.app = app
        self.analysis = analysis or AnalysisService()
        self.service_factory = service_factory

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
