import argparse
import asyncio
from contextlib import redirect_stderr
from io import StringIO
import json
from dataclasses import asdict
from importlib import metadata
import sqlite3
import sys
import threading
from pathlib import Path
from typing import Sequence

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from python_lab.assistant.commands import AssistantCommands
from python_lab.assistant.errors import AssistantError, ContextError
from python_lab.assistant.history import ConversationRepository
from python_lab.assistant.openai_provider import OpenAIProvider
from python_lab.assistant.settings import load_settings
from python_lab.assistant.service import AssistantService
from python_lab.analysis.service import AnalysisService
from python_lab.workspace import Workspace
from python_lab.app import ActiveMissionError, ApplicationError, PythonLabApp
from python_lab.commands import ALIASES, COMMANDS, DEFAULT_SUMMARIES, CommandDispatcher, CommandResult, parse_command
from python_lab.catalog import CatalogError, load_goal, load_missions, load_roadmap, load_skills
from python_lab.learning import CompletionError, HintError, LearningError
from python_lab.progress import ProgressError, ProgressRepository
from python_lab.presentation import encoding_safe_console, test_feedback
from python_lab.session import SessionError, SessionLog
from python_lab.storage.codecs import decode_progress, decode_sessions
from python_lab.storage.database import connection, has_user_state
from python_lab.storage.migration import migrate_json_state
from python_lab.storage.paths import resolve_paths
from python_lab.tui.app import PythonLabTUI


SKILL_LABELS = {
    "practicing": "Em prática",
    "demonstrated": "Demonstrada",
    "consolidated": "Consolidada",
}

MISSION_STATUS_LABELS = {
    "available": "disponível",
    "started": "em andamento",
    "completed": "concluída",
    "blocked": "bloqueada",
}

EVIDENCE_RESULT_LABELS = {
    "practicing": "em prática",
    "demonstrated": "demonstrada",
    "consolidated": "consolidada",
}


class AssistantRuntime:
    """One lazy provider and output budget for one local process/session."""

    def __init__(self, data_dir: Path, app: PythonLabApp | None = None):
        self.data_dir = data_dir
        self.app = app
        self.provider = None
        self.service = None

    def get_service(self):
        if self.service is None:
            settings = load_settings(self.data_dir)
            self.provider = OpenAIProvider(settings)
            self.service = AssistantService(
                self.provider, AnalysisService(),
                ConversationRepository(self.data_dir / "lab.sqlite3"),
                on_full_solution=self.app.record_full_solution if self.app else None,
            )
        return self.service

    async def aclose(self):
        if self.provider is not None:
            await self.provider.aclose()


class PythonLabCLI:
    def __init__(
        self,
        app: PythonLabApp,
        console: Console | None = None,
        session_log: SessionLog | None = None,
        assistant_project: Path | None = None,
        assistant_runtime: AssistantRuntime | None = None,
        assistant_mode: str = "assistant",
        mode_explicit: bool = False,
    ) -> None:
        self.app = app
        self.console = encoding_safe_console(console or Console())
        self.session_log = session_log
        self._last_summary = ""
        self.assistant_project = assistant_project.resolve() if assistant_project else None
        self.assistant_mode = assistant_mode
        self._assistant_mode_explicit = mode_explicit or assistant_mode != "assistant"
        self.assistant_runtime = assistant_runtime or AssistantRuntime(app.repository.path.parent, app)
        self._runner = None
        self._classic_loop = None
        self._classic_thread = None
        self._classic_action = None
        self.handlers = {
            "/goal": self.show_goal,
            "/skills": self.show_skills,
            "/missions": self.show_missions,
            "/start": self.start,
            "/mission": self.show_mission,
            "/concepts": self.show_concepts,
            "/plan": self.plan,
            "/test": self.test,
            "/hint": self.hint,
            "/explain": self.explain,
            "/status": self.status,
            "/history": self.history,
            "/session": self.session,
            "/evidence": self.evidence,
            "/help": self.help,
            "/exit": self.exit,
        }
        self.dispatcher = CommandDispatcher()
        for name, handler in self.handlers.items():
            self.dispatcher.register(name, self._adapt_handler(handler))

    def _adapt_handler(self, handler):
        def invoke(args: tuple[str, ...]) -> CommandResult:
            keep_running = handler(" ".join(args))
            return CommandResult(True, self._last_summary, {}, exit_requested=not keep_running)
        return invoke

    def execute(self, command_line: str) -> bool:
        if not command_line.strip():
            return True
        try:
            parsed = parse_command(command_line)
        except ValueError as exc:
            self.console.print(str(exc), style="red", markup=False)
            self._record(command_line, str(exc))
            return True
        command = parsed.name
        if command in {"/project", "/mode"}:
            return self._local_assistant_setting(command, parsed.args)
        if command in {"/explain-code", "/diagnose", "/check"}:
            return self._execute_assistant(parsed)
        if command == "/cancel":
            self.cancel_classic_action()
            return True
        self._last_summary = DEFAULT_SUMMARIES.get(command, f"{command} executado")
        display = " ".join((command, *parsed.args)).strip()
        try:
            result = self.dispatcher.dispatch(parsed)
        except (EOFError, KeyboardInterrupt):
            return self.exit()
        except (ApplicationError, LearningError, ProgressError, SessionError) as exc:
            self.console.print(str(exc), style="red", markup=False)
            self._record(display, str(exc))
            self._print_next_step()
            return True
        if not result.ok:
            self.console.print(result.message, markup=False)
            self._record(display, "Comando desconhecido")
        elif not result.exit_requested:
            self._record(display, result.message)
            if command != "/status":
                self._print_next_step()
        return not result.exit_requested

    def _local_assistant_setting(self, command: str, args: tuple[str, ...]) -> bool:
        if command == "/mode":
            if len(args) != 1 or args[0] not in {"assistant", "tutor"}:
                self.console.print("Uso: /mode assistant|tutor", markup=False)
            else:
                self.assistant_mode = args[0]
                self._assistant_mode_explicit = True
                self.console.print(f"Modo: {self.assistant_mode}", markup=False)
            return True
        if len(args) != 1:
            self.console.print("Uso: /project <diretório>|off", markup=False)
            return True
        if args[0] == "off":
            self.assistant_project = None
            self.console.print("Missões disponíveis.", markup=False)
            return True
        try:
            self.assistant_project = Workspace(Path(args[0])).root
        except ContextError as exc:
            self.console.print(str(exc), markup=False)
            return True
        self.console.print(f"Projeto: {self.assistant_project}", markup=False)
        return True

    def effective_assistant_mode(self) -> str:
        if self._assistant_mode_explicit:
            return self.assistant_mode
        return "tutor" if self.app.progress.current_mission_id else "assistant"

    def _execute_assistant(self, parsed) -> bool:
        try:
            workspace = Workspace(self.assistant_project or Path.cwd())
            handlers = AssistantCommands(None, workspace, self.effective_assistant_mode(),
                app=self.app, service_factory=self.assistant_runtime.get_service)
            if self._runner is None:
                self._runner = asyncio.Runner()
            handler = {"/check": handlers.check, "/explain-code": handlers.explain,
                "/diagnose": handlers.diagnose}[parsed.name]
            result = self._runner.run(handler(parsed.args))
            self.console.print(result.message, markup=False)
            self._record(parsed.name, result.message if result.ok else "Falha na assistência")
        except (ContextError, AssistantError) as exc:
            self.console.print(str(exc), markup=False)
        except KeyboardInterrupt:
            self.console.print("Ação cancelada.", markup=False)
        return True

    def _ensure_classic_loop(self) -> None:
        if self._classic_loop is not None:
            return
        ready = threading.Event()
        def run_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._classic_loop = loop
            ready.set()
            try:
                loop.run_forever()
                loop.run_until_complete(self.assistant_runtime.aclose())
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.run_until_complete(loop.shutdown_default_executor())
            finally:
                loop.close()
                asyncio.set_event_loop(None)
        self._classic_thread = threading.Thread(target=run_loop, name="lab-assistant-loop")
        self._classic_thread.start()
        ready.wait()

    def start_classic_assistant(self, parsed) -> None:
        if self._classic_action is not None:
            self.console.print("Ação em curso; use /cancel.", markup=False)
            return
        self._ensure_classic_loop()
        workspace = Workspace(self.assistant_project or Path.cwd())
        handlers = AssistantCommands(None, workspace, self.effective_assistant_mode(),
            app=self.app, service_factory=self.assistant_runtime.get_service)
        action = {"/check": handlers.check, "/explain-code": handlers.explain,
                  "/diagnose": handlers.diagnose}[parsed.name]
        cancel = threading.Event()
        done = threading.Event()
        scheduled = threading.Event()
        state = {"cancel": cancel, "done": done, "task": None}
        self._classic_action = state

        def schedule() -> None:
            task = self._classic_loop.create_task(action(parsed.args, cancel=cancel))
            state["task"] = task
            def finished(completed) -> None:
                try:
                    result = completed.result()
                except asyncio.CancelledError:
                    self.console.print("Ação cancelada.", markup=False)
                except Exception as exc:
                    self.console.print(str(exc), markup=False)
                else:
                    self.console.print(result.message, markup=False)
                    self._record(parsed.name, result.message if result.ok else "Falha na assistência")
                finally:
                    self._classic_action = None
                    done.set()
            task.add_done_callback(finished)
            scheduled.set()
        self._classic_loop.call_soon_threadsafe(schedule)
        scheduled.wait()
        self.console.print("Analisando projeto... Use /cancel para interromper.", markup=False)

    def cancel_classic_action(self, *, silent: bool = False) -> None:
        state = self._classic_action
        if state is None:
            if not silent:
                self.console.print("Nenhuma ação em curso.", markup=False)
            return
        state["cancel"].set()
        self._classic_loop.call_soon_threadsafe(state["task"].cancel)
        self.console.print("Cancelando; aguardando limpeza...", markup=False)
        state["done"].wait()

    def close_assistant(self) -> None:
        if self._classic_action is not None:
            self.cancel_classic_action(silent=True)
        if self._classic_loop is not None:
            self._classic_loop.call_soon_threadsafe(self._classic_loop.stop)
            self._classic_thread.join()
            self._classic_loop = None
            self._classic_thread = None
        if self._runner is not None:
            self._runner.run(self.assistant_runtime.aclose())
            self._runner.close()
            self._runner = None

    def _record(self, command: str, summary: str) -> None:
        if self.session_log is None:
            return
        failure = self.session_log.try_record(command, summary)
        if failure is not None:
            self.console.print(failure, style="red", markup=False)

    def _close_session(self, summary: str | None = None) -> None:
        if self.session_log is None:
            return
        try:
            self.session_log.close(summary)
        except SessionError as exc:
            self.console.print(str(exc), style="red", markup=False)

    def _print_next_step(self) -> None:
        try:
            step = self.app.next_step()
        except ApplicationError as exc:
            self.console.print(str(exc), style="red", markup=False)
            return
        self.console.print(f"Próximo: {step}", style="dim")

    def _printable(self, text: str) -> str:
        encoding = getattr(self.console.file, "encoding", None) or "utf-8"
        return text.encode(encoding, errors="replace").decode(encoding, errors="replace")

    def show_goal(self, _argument: str = "") -> bool:
        criteria = "\n".join(f"- {item}" for item in self.app.goal.success_criteria)
        body = f"{self.app.goal.statement}\n\nCritérios de sucesso:\n{criteria}"
        self.console.print(Panel(body, title=self.app.goal.title))
        return True

    def show_skills(self, _argument: str = "") -> bool:
        states = self.app.skill_states()
        table = Table(title="Skills")
        table.add_column("ID")
        table.add_column("Nome")
        table.add_column("Categoria")
        table.add_column("Estado")
        for skill in self.app.skills.values():
            if skill.future:
                state = "Etapa futura"
            else:
                state = SKILL_LABELS.get(states.get(skill.id, ""), "Não avaliada")
            table.add_row(skill.id, skill.name, skill.category, state)
        self.console.print(table)
        return True

    def show_missions(self, _argument: str = "") -> bool:
        by_cycle: dict[int, list] = {}
        for mission in self.app.missions:
            by_cycle.setdefault(mission.cycle, []).append(mission)
        for cycle in sorted(by_cycle):
            title = self.app.cycle_title(cycle)
            table = Table(title=f"Ciclo {cycle} — {title}")
            table.add_column("ID")
            table.add_column("Título")
            table.add_column("Lição")
            table.add_column("Estado")
            for mission in by_cycle[cycle]:
                progress = self.app.progress.missions.get(mission.id)
                if progress is not None and progress.status in {"started", "completed"}:
                    status = MISSION_STATUS_LABELS.get(progress.status, progress.status)
                else:
                    unlocked = all(
                        self.app.progress.missions.get(prerequisite) is not None
                        and self.app.progress.missions[prerequisite].status == "completed"
                        for prerequisite in mission.prerequisites
                    )
                    status = "disponível" if unlocked else "bloqueada"
                table.add_row(mission.id, mission.title, mission.lesson_id, status)
            self.console.print(table)
        planned = [item for item in self.app.roadmap if item.status == "planned"]
        if planned:
            table = Table(title="Ciclos planejados")
            table.add_column("Ciclo")
            table.add_column("Foco")
            table.add_column("Lição")
            for item in planned:
                table.add_row(str(item.cycle), item.title, item.lesson_id)
            self.console.print(table)
        return True

    def start(self, argument: str = "") -> bool:
        mission_id = argument.strip()
        if not mission_id:
            self.console.print("Uso: /start <id>")
            self._last_summary = "Uso de /start incompleto"
            return True
        mission = self.app.start(mission_id)
        self._last_summary = f"Missão {mission.id} iniciada"
        self.console.print(f"Missão {mission.id} iniciada: {mission.title}")
        self.console.print(f"Resumo: {mission.summary}")
        self.console.print(f"Leia o enunciado em: {mission.test_path.parent / 'README.md'}")
        self.console.print(f"Edite a solução em: {mission.solution_path}")
        self.console.print(Markdown(self.app.mission_content(mission)))
        return True

    def _show_content(self, argument: str, concepts: bool) -> bool:
        mission_id = argument.strip() or self.app.progress.current_mission_id
        command = "/concepts" if concepts else "/mission"
        if not mission_id:
            self.console.print(f"Nenhuma missão iniciada. Use {command} <id> ou escolha com /missions.")
            return True
        mission = self.app.mission_by_id(mission_id)
        self.console.print(f"Missão {mission.id} — {mission.title}", markup=False)
        self.console.print(f"Edite a solução em: {mission.solution_path}", markup=False)
        self.console.print(Markdown(self.app.mission_content(mission, concepts=concepts)))
        return True

    def show_mission(self, argument: str = "") -> bool:
        return self._show_content(argument, concepts=False)

    def show_concepts(self, argument: str = "") -> bool:
        return self._show_content(argument, concepts=True)

    def plan(self, _argument: str = "") -> bool:
        self.app.current_mission()
        plan = {
            "input": self.console.input("Entrada (input): ").strip(),
            "output": self.console.input("Saída (output): ").strip(),
            "steps": self.console.input("Etapas (steps): ").strip(),
            "risks": self.console.input("Possíveis erros (risks): ").strip(),
        }
        self.app.save_plan(plan)
        body = (
            f"Entrada: {plan['input']}\n"
            f"Saída: {plan['output']}\n"
            f"Etapas: {plan['steps']}\n"
            f"Riscos: {plan['risks']}"
        )
        self.console.print(Panel(body, title="Planejamento"))
        return True

    def test(self, argument: str = "") -> bool:
        argument = argument.strip().lower()
        if argument == "details":
            result = self.app.last_test_result()
            self._last_summary = "Detalhes dos testes consultados"
            if result is None:
                self.console.print("Nenhum resultado de testes nesta sessão para a missão. Execute /test.")
            else:
                self.console.print(self._printable(test_feedback(result, details=True)), markup=False)
            return True
        if argument:
            self.console.print("Uso: /test ou /test details")
            self._last_summary = "Argumento de /test inválido"
            return True
        result = self.app.run_current_tests()
        self.app.remember_test_result(result)
        self._last_summary = "Testes passaram" if result.passed else "Testes falharam"
        self.console.print(self._printable(test_feedback(result)), markup=False)
        return True

    def hint(self, argument: str = "") -> bool:
        confirm = argument.strip().lower() in {"confirm", "confirmar", "sim", "yes"}
        try:
            text = self.app.next_hint(confirm_reference=confirm)
        except HintError as exc:
            self.console.print(str(exc), style="yellow", markup=False)
            self.console.print(
                "Use /hint confirm para liberar a solução de referência.",
                markup=False,
            )
            self._last_summary = str(exc)
            return True
        self.console.print(Panel(text, title="Pista"))
        return True

    def explain(self, argument: str = "") -> bool:
        for question in self.app.current_mission().reflection_questions:
            self.console.print(f"- {question}", markup=False)
        text = argument.strip() or self.console.input("Explicação final: ").strip()
        self.app.save_explanation(text)
        try:
            evidence = self.app.complete_current_mission()
        except CompletionError as exc:
            self.console.print("Explicação registrada.")
            self.console.print(str(exc), style="yellow", markup=False)
            self._last_summary = "Explicação registrada; conclusão pendente"
            return True
        self._last_summary = "Missão concluída"
        self.console.print("[green]Missão concluída![/green]")
        table = Table(title="Evidências")
        table.add_column("Skill")
        table.add_column("Resultado")
        for item in evidence:
            table.add_row(str(item["skill"]), str(item["result"]))
        self.console.print(table)
        recommended = self.app.recommended()
        if recommended is not None:
            self.console.print(f"Próxima missão: {recommended.id} — {recommended.title}")
        else:
            self.console.print("Todas as missões concluídas.")
        return True

    def status(self, _argument: str = "") -> bool:
        snapshot = self.app.status_snapshot()
        recommended = self.app.recommended()
        current_id = snapshot.current_mission_id or "nenhuma"
        recommendation = f"{recommended.id} — {recommended.title}" if recommended else "Todas as missões concluídas"
        lines = [
            f"Missão atual: {current_id}",
            f"Recomendada: {recommendation}",
        ]
        try:
            progress = self.app.current_progress()
            if progress.tests_passed:
                tests_status = "ok" if snapshot.tests_current else "desatualizados"
            else:
                tests_status = "pendentes"
            lines.extend(
                [
                    f"Tentativas: {progress.attempts}",
                    f"Testes: {tests_status}",
                    f"Pistas: {progress.hints_revealed}",
                    f"Plano: {'registrado' if snapshot.plan_complete else 'pendente'}",
                    f"Explicação: {'registrada' if progress.explanation else 'pendente'}",
                ]
            )
        except ApplicationError:
            pass
        lines.append(f"Próximo: {snapshot.next_step}")
        self.console.print(Panel("\n".join(lines), title="Sessão"))
        return True

    def history(self, _argument: str = "") -> bool:
        progress = self.app.current_progress()
        if not progress.attempt_history:
            self.console.print("Nenhuma tentativa registrada para a missão atual.")
            return True
        self.console.print("Histórico de tentativas:")
        for index, attempt in enumerate(progress.attempt_history, start=1):
            state = "passou" if attempt.get("passed") else "falhou"
            summary = attempt.get("summary") or "sem resumo"
            self.console.print(f"{index}. {state} — {summary}")
        return True

    def session(self, argument: str = "") -> bool:
        if self.session_log is None:
            self.console.print("Histórico de sessão indisponível nesta execução.")
            return True
        if argument.strip().lower() == "all":
            previous = self.session_log.previous_sessions()
            if not previous:
                self.console.print("Nenhuma sessão anterior.")
                return True
            self.console.print("Sessões anteriores:")
            for item in previous:
                started = str(item.get("started_at", "?"))
                events = item.get("events", [])
                count = len(events) if isinstance(events, list) else 0
                self.console.print(f"- {started} ({count} evento(s))")
            return True
        events = self.session_log.current_events()
        if not events:
            self.console.print("Nenhum evento nesta sessão.")
            return True
        self.console.print("Sessão atual:")
        for index, event in enumerate(events, start=1):
            command = event.get("command", "?")
            summary = event.get("summary", "")
            self.console.print(f"{index}. {command} — {summary}")
        return True

    def evidence(self, _argument: str = "") -> bool:
        if not self.app.progress.evidence:
            self.console.print("Nenhuma evidência registrada.")
            return True
        self.console.print("Evidências:")
        for item in self.app.progress.evidence:
            self.console.print(
                f"- {item.get('mission', '?')} / {item.get('skill', '?')}: "
                f"{EVIDENCE_RESULT_LABELS.get(str(item.get('result')), item.get('result', '?'))} "
                f"(ajuda nível {item.get('help_level', '?')})"
            )
        return True

    def help(self, _argument: str = "") -> bool:
        table = Table(title="Comandos")
        table.add_column("Comando")
        table.add_column("Atalho")
        table.add_column("Responsabilidade")
        for command, shortcut, description in COMMANDS:
            table.add_row(command, shortcut, description)
        self.console.print(table)
        return True

    def exit(self, _argument: str = "") -> bool:
        self.close_assistant()
        try:
            self.app.persist()
        except ProgressError as exc:
            self.console.print(str(exc), style="red", markup=False)
            self.console.print("Sessão encerrada. O último estado confirmado foi preservado.")
        else:
            self.console.print("Progresso salvo. Até a próxima sessão.")
        self._close_session("Sessão encerrada")
        return False


def _banner(app: PythonLabApp, console: Console) -> None:
    from rich import box
    from rich.table import Table

    recommended = app.recommended()
    recommendation = (
        f"{recommended.id} — {recommended.title}" if recommended else "Nenhuma missão elegível"
    )
    current = app.progress.current_mission_id or "nenhuma"
    table = Table(box=None, show_header=False, pad_edge=False, expand=True, padding=(0, 1))
    table.add_column(style="dim", min_width=14, max_width=16)
    table.add_column()
    table.add_row("Objetivo", app.goal.title)
    table.add_row("Missão", current)
    table.add_row("Estado", "Em andamento" if current != "nenhuma" else "Pronto para iniciar")
    table.add_row("Recomendada", recommendation)
    console.print("lab ~ python-lab")
    console.print("✓  Goal carregado")
    console.print("✓  Catálogo de missões")
    console.print(
        Panel(table, title=" Python Lab ", title_align="left", box=box.SQUARE, padding=(1, 1))
    )
    try:
        step = app.next_step()
    except ApplicationError as exc:
        console.print(str(exc), style="red", markup=False)
    else:
        console.print(f"Próximo: {step}", style="green")


def build_app(project_root: Path | None = None, *, data_dir: Path | None = None) -> PythonLabApp:
    root = project_root or Path(__file__).resolve().parent.parent
    paths = resolve_paths(root, data_dir)
    legacy = root / "data"
    old_progress = legacy / "progress.json"
    old_sessions = legacy / "sessions.json"
    database_path = paths.data_dir / "lab.sqlite3"
    needs_migration = not database_path.exists()
    if not needs_migration:
        try:
            with connection(database_path) as db:
                needs_migration = not has_user_state(db) and db.execute("SELECT 1 FROM migrations LIMIT 1").fetchone() is None
        except (sqlite3.Error, OSError, ValueError) as exc:
            raise ProgressError(f"Banco de progresso inválido: {exc}") from exc
    if needs_migration:
        real_progress = False
        real_sessions = False
        if old_progress.exists():
            try:
                raw_progress = old_progress.read_bytes()
            except OSError as exc:
                raise ProgressError(f"Não foi possível ler o progresso legado: {old_progress}: {exc}") from exc
            state = decode_progress(raw_progress)
            real_progress = bool(state.current_mission_id or state.missions or state.evidence)
        if old_sessions.exists():
            try:
                raw_sessions = old_sessions.read_bytes()
            except OSError as exc:
                raise SessionError(f"Não foi possível ler o histórico legado: {old_sessions}: {exc}") from exc
            real_sessions = bool(decode_sessions(raw_sessions))
        if real_progress or real_sessions:
            raise ProgressError(
                f"Estado JSON legado encontrado. Execute lab migrate --from-dir {legacy} --data-dir {paths.data_dir}"
            )
    missions = load_missions(root / "missions")
    try:
        app = PythonLabApp(
            goal=load_goal(root / "data" / "goal.json"),
            skills=load_skills(root / "data" / "skills.json"),
            missions=missions,
            repository=ProgressRepository(paths.data_dir / "lab.sqlite3"),
            project_root=root,
            roadmap=load_roadmap(root / "data" / "roadmap.json", missions),
        )
    except ActiveMissionError as exc:
        raise ProgressError(str(exc)) from exc
    return app


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: erro: argumento inválido: {message}\n")


def _argument_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
        prog="python-lab",
        description="Ambiente de prática deliberada em Python.",
    )
    parser.add_argument("--version", action="version", version=f"python-lab {metadata.version('python-lab')}")
    parser.add_argument(
        "--classic",
        action="store_true",
        help="Usar o prompt lab> em vez da TUI em tela cheia.",
    )
    parser.add_argument("--data-dir", type=Path, help="Diretório de dados do usuário")
    parser.add_argument("--project", type=Path, help="Projeto do assistente; mantém o catálogo de missões separado")
    parser.add_argument("--mode", choices=("assistant", "tutor"), default="assistant")
    parser.add_argument("--level", type=int, choices=range(5), default=0)
    parser.add_argument("--json", action="store_true", help="Resultado estruturado schema_version=1")
    parser.add_argument("--traceback", type=Path)
    parser.add_argument("--file", action="append", type=Path, default=[])
    parser.add_argument("command", nargs="?", choices=("migrate", "explain", "diagnose", "check"))
    parser.add_argument("files", nargs="*")
    parser.add_argument("--from-dir", type=Path, help="Diretório com JSON legado")
    return parser


def _run_classic(app: PythonLabApp, session_log: SessionLog | None, console: Console,
                 assistant_project: Path | None = None, assistant_mode: str = "assistant",
                 mode_explicit: bool = False) -> int:
    cli = PythonLabCLI(app=app, console=console, session_log=session_log,
                       assistant_project=assistant_project, assistant_mode=assistant_mode,
                       mode_explicit=mode_explicit)
    if assistant_project is None:
        _banner(app, console)
    else:
        console.print(f"Projeto: {assistant_project.resolve()} · modo {assistant_mode}", markup=False)
        console.print("Use /explain-code, /diagnose ou /check; /project off volta às missões.", markup=False)
    try:
        while True:
            line = console.input("[bold]lab>[/bold] ")
            try:
                parsed = parse_command(line)
            except ValueError:
                cli.execute(line)
                continue
            if cli._classic_action is not None:
                if parsed.name == "/cancel":
                    cli.cancel_classic_action()
                elif parsed.name == "/exit":
                    cli.cancel_classic_action()
                    cli.execute(line)
                    break
                else:
                    console.print("Ação em curso; use /cancel.", markup=False)
                continue
            if parsed.name in {"/check", "/explain-code", "/diagnose"}:
                try:
                    cli.start_classic_assistant(parsed)
                except (ContextError, AssistantError) as exc:
                    console.print(str(exc), markup=False)
                continue
            if not cli.execute(line):
                break
    except KeyboardInterrupt:
        cli.cancel_classic_action(silent=True)
        cli._close_session("Sessão interrompida")
        console.print("\nSessão encerrada. O último estado confirmado foi preservado.")
    except EOFError:
        cli.cancel_classic_action(silent=True)
        cli.exit()
    finally:
        cli.close_assistant()
    return 0


def _run_tui(app: PythonLabApp, session_log: SessionLog | None, assistant_project: Path | None = None, assistant_mode: str = "assistant", mode_explicit: bool = False) -> int:
    try:
        if assistant_project is None and assistant_mode == "assistant" and not mode_explicit:
            PythonLabTUI(lab=app, session_log=session_log).run()
        else:
            PythonLabTUI(lab=app, session_log=session_log, assistant_project=assistant_project, assistant_mode=assistant_mode, mode_explicit=mode_explicit).run()
    finally:
        if session_log is not None and session_log.is_open:
            try:
                session_log.close("Sessão encerrada")
            except SessionError as exc:
                encoding_safe_console(Console()).print(str(exc), style="red", markup=False)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    external = next((item for item in raw if item in {"explain", "diagnose", "check"}), None)
    if "--json" in raw and external is not None:
        diagnostic = StringIO()
        try:
            with redirect_stderr(diagnostic):
                args = _argument_parser().parse_intermixed_args(raw)
        except SystemExit as exc:
            if exc.code != 2:
                raise
            message = diagnostic.getvalue().strip().splitlines()[-1]
            print(json.dumps({"schema_version": 1, "action": external, "ok": False,
                              "message": message, "data": {"error_kind": "usage"}}, ensure_ascii=False))
            return 2
    else:
        args = _argument_parser().parse_intermixed_args(raw)
    if args.command in {"explain", "diagnose", "check"}:
        return _run_external_assistant(args)
    console = encoding_safe_console(Console())
    if sys.version_info < (3, 11):
        console.print(
            "Python Lab requer Python 3.11 ou mais recente.", style="red", markup=False
        )
        return 2
    if args.project is not None:
        try:
            Workspace(args.project)
        except ContextError as exc:
            console.print(str(exc), style="red", markup=False)
            return 2
    session_log: SessionLog | None = None
    try:
        if args.command == "migrate":
            if args.from_dir is None:
                console.print("Informe --from-dir para migrar.", style="red")
                return 2
            paths = resolve_paths(Path(__file__).resolve().parent.parent, args.data_dir)
            report = migrate_json_state(args.from_dir, paths.data_dir / "lab.sqlite3")
            console.print("Estado importado." if report.imported else "Estado já importado.")
            return 0
        app = build_app(data_dir=args.data_dir) if args.data_dir is not None else build_app()
        session_log = SessionLog(app.repository.path)
        try:
            session_log.start()
        except SessionError as exc:
            console.print(str(exc), style="red", markup=False)
    except ValueError as exc:
        console.print(str(exc), style="red", markup=False)
        return 2
    except (ProgressError, ApplicationError, CatalogError, SessionError) as exc:
        console.print(str(exc), style="red", markup=False)
        return 1
    mode_explicit = any(value == "--mode" or value.startswith("--mode=") for value in raw)
    if args.classic:
        return _run_classic(app, session_log, console, args.project, args.mode, mode_explicit)
    return _run_tui(app, session_log, args.project, args.mode, mode_explicit)


def _run_external_assistant(args) -> int:
    """One-shot action; each invocation has a fresh in-memory token budget."""
    action = args.command
    runtime = None
    try:
        catalog = Path(__file__).resolve().parent.parent
        data_dir = resolve_paths(catalog, args.data_dir).data_dir
        workspace = Workspace(args.project or Path.cwd())
        runtime = AssistantRuntime(data_dir)
        handlers = AssistantCommands(None, workspace, args.mode, service_factory=runtime.get_service)
        names = tuple(args.files) + tuple(str(path) for path in args.file)
        if action == "check":
            if args.traceback or args.level:
                raise ValueError("check aceita apenas arquivos selecionados.")
            coro = handlers.check(names)
        else:
            arguments = names + (('--level', str(args.level)) if args.level else ())
            if args.traceback is not None:
                arguments += ('--traceback', str(args.traceback))
            coro = (handlers.explain if action == 'explain' else handlers.diagnose)(arguments)
        async def run():
            try:
                return await coro
            finally:
                await runtime.aclose()
        result = asyncio.run(run())
    except (ValueError, ContextError, AssistantError) as exc:
        result = CommandResult(False, str(exc), {"error_kind": "usage"})
    code = 0 if result.ok else (2 if result.data.get("error_kind") == "usage" else 1)
    if args.json:
        print(json.dumps({"schema_version": 1, "action": action, "ok": result.ok,
                          "message": result.message, "data": result.data}, ensure_ascii=False))
    else:
        encoding_safe_console(Console()).print(result.message, markup=False)
    return code
