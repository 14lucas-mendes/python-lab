from importlib import metadata
import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from io import StringIO
import shlex
from pathlib import Path
from threading import Event

from rich.console import Console
from rich.text import Text

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.widgets import Button, Input, Label, Markdown, Static
from textual.worker import Worker, WorkerCancelled, WorkerFailed, get_current_worker

from python_lab.app import ApplicationError, PythonLabApp
from python_lab.assistant.commands import AssistantCommands
from python_lab.assistant.errors import ContextError
from python_lab.assistant.service import AssistantService
from python_lab.workspace import Workspace
from python_lab.commands import ALIASES, COMMANDS, parse_command
from python_lab.learning import HintError, LearningError
from python_lab.models import TestResult
from python_lab.presentation import encoding_safe_console, test_feedback
from python_lab.progress import ProgressError
from python_lab.session import SessionError, SessionLog
from python_lab.tui.screens import ConfirmScreen, ExplainScreen, PlanScreen
from python_lab.tui.widgets import CommandPalette, Composer, NextStepBar


APP_VERSION = metadata.version("python-lab")


class PythonLabTUI(App[None]):
    CSS_PATH = Path(__file__).with_name("lab.tcss")
    BINDINGS = [Binding("ctrl+c", "quit_lab", "Cancelar / sair", show=False)]

    def __init__(
        self,
        lab: PythonLabApp,
        session_log: SessionLog | None = None,
        assistant_project: Path | None = None,
        assistant_service: AssistantService | None = None,
        assistant_mode: str = "assistant",
        mode_explicit: bool = False,
    ) -> None:
        super().__init__()
        from python_lab.cli import PythonLabCLI

        self.lab = lab
        self.session_log = session_log
        self.commands = COMMANDS
        self.aliases = ALIASES
        self._buffer = StringIO()
        self.output_console = Console(
            file=self._buffer,
            record=True,
            force_terminal=False,
            legacy_windows=False,
        )
        self.cli = PythonLabCLI(app=lab, console=self.output_console, session_log=session_log,
                                assistant_project=assistant_project, assistant_mode=assistant_mode,
                                mode_explicit=mode_explicit)
        self.assistant_project = Workspace(assistant_project).root if assistant_project else None
        self.assistant_mode = assistant_mode
        self.assistant_service = assistant_service
        self._assistant_task: asyncio.Task | None = None
        self._assistant_cancel: Event | None = None
        self._assistant_exiting = False
        self.last_test_result: TestResult | None = None
        self.transcript_entries: list[str] = []
        self._testing = False
        self._test_worker = None
        self._test_executor: ThreadPoolExecutor | None = None
        self._test_future: Future | None = None
        self._test_started = Event()
        self._test_cleanup_done = Event()
        self._test_exiting = False
        self._status_timer = None
        self.title = f"Python Lab {APP_VERSION}"
        self.sub_title = self._subtitle()

    def compose(self) -> ComposeResult:
        yield Static(id="mission-header", markup=False)
        yield Static(id="stages", markup=False)
        with VerticalScroll(id="content"):
            yield Markdown(id="document")
            yield Static(id="response", markup=False)
        yield Static(id="last-result", markup=False)
        yield Static(id="actions", markup=False)
        yield CommandPalette(id="palette")
        yield Button("Cancelar ação (/cancel)", id="assistant-cancel")
        with Vertical(id="composer-wrap"):
            with Horizontal(id="composer-row"):
                yield Label("lab ›", id="prompt-mark")
                yield Composer(placeholder="Digite / para comandos", id="composer")
        yield NextStepBar(id="next-step")

    def on_mount(self) -> None:
        self.output_console.size = (max(20, self.size.width - 4), max(1, self.size.height))
        current = self.lab.progress.current_mission_id
        if current:
            try:
                self._show_document(current)
            except ApplicationError as exc:
                self._append_response(str(exc))
        elif self.assistant_project is not None:
            self._append_response(f"Projeto: {self.assistant_project}\nUse /explain-code, /diagnose ou /check.")
        else:
            self._append_response(
                "Python Lab\n\nEscolha uma missão com /missions. "
                "Consulte o enunciado com /mission <id> antes de iniciar."
            )
        self._refresh_status()
        self._status_timer = self.set_interval(1.0, self._refresh_status)
        palette = self._palette()
        if palette is not None:
            palette.display = False
        self.query_one("#assistant-cancel", Button).display = False
        composer = self._composer()
        if composer is not None:
            composer.focus()

    async def on_unmount(self) -> None:
        if self._testing and self._test_worker is not None:
            self._test_worker.cancel()
            await asyncio.to_thread(self._test_cleanup_done.wait)
        if self._assistant_task is not None:
            self._assistant_exiting = False
            self._assistant_cancel.set()
            task = self._assistant_task
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await self.cli.assistant_runtime.aclose()
        if self._status_timer is not None:
            self._status_timer.stop()
        self._close_session("Sessão encerrada")

    def _shell(self):
        return self.screen_stack[0] if self.screen_stack else self.screen

    def _palette(self) -> CommandPalette | None:
        try:
            return self._shell().query_one("#palette", CommandPalette)
        except NoMatches:
            return None

    def _composer(self) -> Composer | None:
        try:
            return self._shell().query_one("#composer", Composer)
        except NoMatches:
            return None

    def _cancel_button(self) -> Button | None:
        try:
            return self._shell().query_one("#assistant-cancel", Button)
        except NoMatches:
            return None

    def _next_step_bar(self) -> NextStepBar | None:
        try:
            return self._shell().query_one("#next-step", NextStepBar)
        except NoMatches:
            return None

    def action_quit_lab(self) -> None:
        if self._testing and self._test_worker is not None:
            self._test_exiting = True
            self._test_worker.cancel()
            self._append_response("Cancelando testes; aguardando limpeza antes de sair...")
            return
        if self._assistant_task is not None:
            self._assistant_exiting = True
            self._cancel_assistant()
            return
        self.cli.exit()
        self._flush_console()
        self.exit()

    def action_composer_escape(self) -> None:
        palette = self._palette()
        composer = self._composer()
        if palette is not None and palette.display:
            palette.display = False
            palette.clear_options()
            return
        if composer is not None:
            composer.value = ""

    def action_palette_up(self) -> None:
        palette = self._palette()
        if palette is not None and palette.display:
            palette.action_cursor_up()

    def action_palette_down(self) -> None:
        palette = self._palette()
        if palette is not None and palette.display:
            palette.action_cursor_down()

    def scroll_content(self, down: bool) -> None:
        content = self._shell().query_one("#content", VerticalScroll)
        if down:
            content.scroll_page_down(animate=False)
        else:
            content.scroll_page_up(animate=False)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "composer":
            return
        palette = self._palette()
        if palette is not None:
            palette.update_from(self.commands, event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "composer":
            return
        if self._testing:
            return
        value = event.value
        palette = self._palette()
        if palette is not None and palette.display and self._should_complete_from_palette(value):
            if self._apply_palette_selection():
                return
        event.input.value = ""
        if palette is not None:
            palette.display = False
            palette.clear_options()
        self._submit(value)

    def on_option_list_option_selected(self, event: CommandPalette.OptionSelected) -> None:
        del event
        self._apply_palette_selection()

    def _should_complete_from_palette(self, value: str) -> bool:
        try:
            command, argument = self._split_command(value)
        except ValueError:
            return False
        if command in self.cli.handlers:
            return command == "/start" and not argument
        return True

    def _apply_palette_selection(self) -> bool:
        palette = self._palette()
        composer = self._composer()
        if palette is None or composer is None:
            return False
        selected = palette.selected_insert()
        if selected is None:
            return False
        command, needs_arg = selected
        if needs_arg:
            composer.value = f"{command} "
            composer.cursor_position = len(composer.value)
            palette.display = False
            palette.clear_options()
            composer.focus()
            return True
        composer.value = ""
        palette.display = False
        palette.clear_options()
        composer.focus()
        self._submit(command)
        return True

    def _submit(self, line: str) -> None:
        self.output_console.size = (max(20, self.size.width - 4), max(1, self.size.height))
        stripped = line.strip()
        if not stripped:
            return
        self._append_user(stripped)
        try:
            command, argument = self._split_command(stripped)
        except ValueError as exc:
            self._append_response(str(exc))
            self._record(stripped, str(exc))
            return
        if command == "/cancel":
            self._cancel_assistant()
            return
        if self._assistant_task is not None:
            self._append_response("Ação em curso; use /cancel.")
            return
        if command == "/project":
            self.cli._local_assistant_setting(command, parse_command(stripped).args)
            self.assistant_project = self.cli.assistant_project
            self._flush_console()
            self._refresh_status()
            return
        if command == "/mode":
            self.cli._local_assistant_setting(command, parse_command(stripped).args)
            self.assistant_mode = self.cli.assistant_mode
            self._flush_console()
            self._refresh_status()
            return
        if command in {"/explain-code", "/diagnose", "/check"}:
            self._start_assistant(command, parse_command(stripped).args)
            return
        if command in {"/mission", "/concepts"}:
            mission_id = argument.strip() or self.lab.progress.current_mission_id
            if not mission_id:
                self._append_response(f"Nenhuma missão iniciada. Use {command} <id> ou escolha com /missions.")
            else:
                try:
                    self._show_document(mission_id, concepts=command == "/concepts")
                except ApplicationError as exc:
                    self._append_response(str(exc))
            self._record(stripped, "Apoio conceitual consultado" if command == "/concepts" else "Enunciado consultado")
            self._refresh_status()
            return
        if command in {"/plan"}:
            self._open_plan()
            return
        if command in {"/explain"} and not argument:
            self._open_explain()
            return
        if command == "/test" and not argument:
            self._run_tests()
            return
        if command in {"/hint"}:
            confirm = argument.lower() in {"confirm", "confirmar", "sim", "yes"}
            self._run_hint(confirm_reference=confirm)
            return
        keep = self.cli.execute(stripped)
        self._flush_console()
        if command == "/start" and self.lab.progress.current_mission_id == argument.strip():
            try:
                self._show_document(argument.strip())
            except ApplicationError as exc:
                self._append_response(str(exc))
        self._refresh_status()
        if not keep:
            self.exit()

    def _start_assistant(self, command: str, args: tuple[str, ...]) -> None:
        try:
            workspace = Workspace(self.assistant_project or Path.cwd())
        except ContextError as exc:
            self._append_response(str(exc))
            return
        handlers = AssistantCommands(self.assistant_service, workspace, self.cli.effective_assistant_mode(),
            app=self.lab, service_factory=self.cli.assistant_runtime.get_service)
        action = {"/explain-code": handlers.explain, "/diagnose": handlers.diagnose,
                  "/check": handlers.check}[command]
        cancel = self._assistant_cancel = Event()
        composer = self._composer()
        if composer is not None:
            composer.placeholder = "Ação em curso; digite /cancel ou Ctrl+C"
        button = self._cancel_button()
        if button is not None:
            button.display = True
        self._append_response("Analisando projeto... Use /cancel para interromper.")

        async def run():
            result = None
            try:
                result = await action(args, cancel=cancel)
            except asyncio.CancelledError:
                # AssistantService and local analysis return only after cleanup.
                pass
            except Exception as exc:
                self._append_response(str(exc))
            finally:
                if cancel is self._assistant_cancel:
                    self._assistant_task = None
                    self._assistant_cancel = None
                    button = self._cancel_button()
                    if button is not None:
                        button.display = False
                    if result is not None and not cancel.is_set():
                        self._append_response(result.message)
                        if result.ok:
                            self._record(command, "Assistência concluída")
                    elif cancel.is_set():
                        self._append_response("Ação cancelada.")
                    composer = self._composer()
                    if composer is not None:
                        composer.disabled = False
                        composer.placeholder = "Digite / para comandos"
                        composer.focus()
                    self._refresh_status()
                    if self._assistant_exiting:
                        self._assistant_exiting = False
                        self.action_quit_lab()
        task = self._assistant_task = asyncio.create_task(run())
        def pending_cancelled(done):
            if done.cancelled() and self._assistant_task is done:
                self._assistant_task = None
                self._assistant_cancel = None
                button = self._cancel_button()
                if button is not None:
                    button.display = False
                composer = self._composer()
                if composer is not None:
                    composer.disabled = False
                    composer.placeholder = "Digite / para comandos"
                    composer.focus()
                self._append_response("Ação cancelada.")
                self._refresh_status()
                if self._assistant_exiting:
                    self._assistant_exiting = False
                    self.action_quit_lab()
        task.add_done_callback(pending_cancelled)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "assistant-cancel":
            self._cancel_assistant()

    def _cancel_assistant(self) -> None:
        if self._assistant_task is None:
            self._append_response("Nenhuma ação em curso.")
            return
        assert self._assistant_cancel is not None
        self._assistant_cancel.set()
        self._assistant_task.cancel()
        self._append_response("Cancelando; aguardando limpeza...")

    def _open_plan(self) -> None:
        try:
            progress = self.lab.current_progress()
        except ApplicationError as exc:
            self._append_response(str(exc))
            self.notify(str(exc), severity="error")
            return

        def on_done(plan: dict[str, str] | None) -> None:
            if plan is None:
                self._append_response("Planejamento cancelado.")
                return
            try:
                self.lab.save_plan(plan)
            except (ApplicationError, ProgressError) as exc:
                self._append_response(str(exc))
                self.notify(str(exc), severity="error")
                return
            self._append_response("Planejamento registrado\n\n" + "\n".join(
                f"{label}: {plan[key]}" for key, label in (
                    ("input", "Entrada"), ("output", "Saída"),
                    ("steps", "Etapas"), ("risks", "Riscos"),
                )
            ))
            self._record("/plan", "Planejamento registrado")
            self._refresh_status()

        self.push_screen(PlanScreen(progress.plan), on_done)

    def _open_explain(self) -> None:
        try:
            mission = self.lab.current_mission()
            progress = self.lab.current_progress()
        except ApplicationError as exc:
            self._append_response(str(exc))
            self.notify(str(exc), severity="error")
            return

        def on_done(text: str | None) -> None:
            if text is None:
                self._append_response("Explicação cancelada.")
                return
            keep = self.cli.execute(f"/explain {shlex.quote(text)}")
            self._flush_console()
            self._refresh_status()
            if not keep:
                self.exit()

        self.push_screen(ExplainScreen(mission.reflection_questions, progress.explanation or ""), on_done)

    def _run_tests(self) -> None:
        if self._testing:
            self._append_response("Testes já em execução.")
            return
        try:
            self.lab.current_mission()
        except ApplicationError as exc:
            self._append_response(str(exc))
            self.notify(str(exc), severity="error")
            return
        self._testing = True
        composer = self._composer()
        if composer is not None:
            composer.disabled = True
            composer.placeholder = "Executando testes..."
        self._append_response("Executando testes...")
        next_step = self._next_step_bar()
        if next_step is not None:
            next_step.update("Próximo: executando testes...")
        self._test_started = Event()
        self._test_cleanup_done = Event()
        self._test_future = None
        self._test_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lab-tests")
        self._test_worker = self.run_worker(
            self._run_tests_async,
            exclusive=True,
            name="run-tests",
            exit_on_error=False,
        )
        asyncio.create_task(self._watch_test_worker(self._test_worker))

    async def _run_tests_async(self) -> None:
        worker = get_current_worker()
        assert self._test_executor is not None
        future = self._test_executor.submit(self._run_tests_worker, self._test_started, worker)
        self._test_future = future
        await asyncio.wrap_future(future)

    async def _watch_test_worker(self, worker: Worker) -> None:
        try:
            await worker.wait()
        except (WorkerCancelled, WorkerFailed):
            pass
        if worker is not self._test_worker:
            return
        future = self._test_future
        # A cancelled concurrent Future cannot subsequently enter its callable.
        # A running Future may not have set _test_started yet, so its callback
        # remains the only proof that runner cleanup has finished.
        if future is None:
            error = worker.error if isinstance(worker.error, Exception) and not worker.is_cancelled else None
            self._test_cleanup_done.set()
            self._on_tests_finished(None, error, worker.cancelled_event)
        elif future.cancel():
            self._test_cleanup_done.set()
            self._on_tests_finished(None, None, worker.cancelled_event)
        elif future.done():
            error = future.exception()
            if error is not None:
                self._test_cleanup_done.set()
                self._on_tests_finished(None, error, worker.cancelled_event)

    def _run_tests_worker(self, started: Event, worker: Worker) -> None:
        started.set()
        if worker.is_cancelled:
            self._test_cleanup_done.set()
            self.call_from_thread(self._on_tests_finished, None, None, worker.cancelled_event)
            return
        result = error = None
        try:
            result = self.lab.run_current_tests(cancel=worker.cancelled_event)
        except Exception as exc:
            error = exc
        finally:
            # Future cancellation is not process cleanup. This event follows
            # the real runner/service return and precedes the UI callback.
            self._test_cleanup_done.set()
        # Worker.cancel() sets the same Event even though cancelling Textual's
        # executor future cannot stop this thread. The runner returns only after
        # process-tree cleanup; only then may the UI release its action slot.
        self.call_from_thread(
            self._on_tests_finished, result, error, worker.cancelled_event
        )

    def _on_tests_finished(self, result: TestResult | None, error: Exception | None, cancel=None) -> None:
        if cancel is not None and (
            self._test_worker is None or cancel is not self._test_worker.cancelled_event
        ):
            return
        executor = self._test_executor
        self._test_executor = None
        self._test_future = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        self._test_worker = None
        self._testing = False
        composer = self._composer()
        if composer is not None:
            composer.disabled = False
            composer.placeholder = "Digite / para comandos"
            composer.focus()
        # The service accepted completion before saving. A late Worker.cancel
        # cannot turn a committed result (or save error) into cancellation.
        if (result is not None and result.cancelled) or (
            result is None and error is None and cancel is not None and cancel.is_set()
        ):
            self._append_response("Execução cancelada.")
            self._refresh_status()
            self._finish_test_exit()
            return
        if error is not None:
            self._append_response(str(error))
            self.notify(str(error), severity="error")
            self._record("/test", str(error))
            self._refresh_status()
            self._finish_test_exit()
            return
        assert result is not None
        self.last_test_result = result
        self.lab.remember_test_result(result)
        output = self._format_test_result(result)
        self._append_response(output)
        summary = "Testes passaram" if result.passed else "Testes falharam"
        self._record("/test", summary)
        self.notify(summary, severity="information" if result.passed else "error")
        self._refresh_status()
        self._finish_test_exit()

    def _finish_test_exit(self) -> None:
        if self._test_exiting:
            self._test_exiting = False
            self.cli.exit()
            self._flush_console()
            self.exit()

    def _run_hint(self, confirm_reference: bool = False) -> None:
        try:
            text = self.lab.next_hint(confirm_reference=confirm_reference)
        except HintError as exc:
            if "confirma" in str(exc).lower() and not confirm_reference:
                self.push_screen(
                    ConfirmScreen("Consultar a solução de referência?"),
                    self._on_reference_confirmed,
                )
                return
            self._append_response(str(exc))
            self.notify(str(exc), severity="warning")
            return
        except (ApplicationError, LearningError, ProgressError) as exc:
            self._append_response(str(exc))
            self.notify(str(exc), severity="error")
            return
        self._append_response(f"Pista\n\n{text}")
        self._record("/hint", "Pista liberada")
        self._refresh_status()

    def _on_reference_confirmed(self, confirmed: bool | None) -> None:
        if not confirmed:
            self._append_response("Consulta à referência cancelada.")
            return
        self._run_hint(confirm_reference=True)

    def _split_command(self, line: str) -> tuple[str, str]:
        command = parse_command(line)
        return command.name, " ".join(command.args)

    def _subtitle(self) -> str:
        current = self.lab.progress.current_mission_id or "nenhuma"
        return f"{self.lab.goal.title} · missão {current}"

    def _refresh_status(self) -> None:
        try:
            self._update_status()
        except ApplicationError as exc:
            message = str(exc)
            if not self.transcript_entries or self.transcript_entries[-1] != message:
                self._append_response(message)
                self.notify(message, severity="error")

    def _update_status(self) -> None:
        self.output_console.size = (max(20, self.size.width - 4), max(1, self.size.height))
        if self._testing or self._assistant_task is not None:
            return
        next_step = self._next_step_bar()
        if next_step is None:
            return
        snapshot = self.lab.status_snapshot()
        next_step.update_from(self.lab, snapshot)
        self.sub_title = self._subtitle()
        shell = self._shell()
        current = self.lab.progress.current_mission_id
        mission = self.lab.mission_by_id(current) if current else self.lab.recommended()
        header = "PYTHON LAB"
        if mission:
            header += f" · Ciclo {mission.cycle} — {self.lab.cycle_title(mission.cycle)}"
            header += f"\n{mission.id} — {mission.title} · " + ("Em andamento" if current else "Pronto para iniciar")
            if mission.learning_objectives:
                header += "\nObjetivo: " + " ".join(mission.learning_objectives)
        else:
            header += " · Todas as missões concluídas"
        shell.query_one("#mission-header", Static).update(header)
        if current:
            progress = self.lab.current_progress()
            plan_done = snapshot.plan_complete
            current_tests = snapshot.tests_current
            stages = "   ".join(
                f"[{'x' if done else ' '}] {label}" for done, label in (
                    (plan_done, "Plano"), (current_tests, "Testes atuais"),
                    (bool(progress.explanation), "Explicação"),
                )
            )
            actions = ["/mission", "/concepts", "/plan"]
            actions.append("/explain" if current_tests else "/test")
            if progress.attempts:
                actions.append("/hint")
        else:
            stages = "Consulte uma missão antes de iniciar."
            actions = ["/missions"]
            if mission:
                actions += [f"/mission {mission.id}", f"/start {mission.id}"]
        shell.query_one("#stages", Static).update(stages)
        if self.assistant_project is not None:
            actions += ["/explain-code", "/diagnose", "/check", "/mode", "/project off"]
        else:
            actions += ["/project"]
        shell.query_one("#actions", Static).update("Ações: " + "  ".join(actions) + "  · / para todos")
        result = snapshot.last_result
        if result:
            label = result.summary or ("Testes passaram" if result.passed else "Testes falharam")
            if current and self.lab.current_progress().tests_passed and not snapshot.tests_current:
                label = "Desatualizado: execute /test novamente. " + label
            result_mission = current or self.lab.last_test_mission_id
            text = f"Último resultado (missão {result_mission}): " + label
        else:
            text = "Último resultado: nenhum teste executado nesta sessão."
        shell.query_one("#last-result", Static).update(text)

    def _show_document(self, mission_id: str, concepts: bool = False) -> None:
        mission = self.lab.mission_by_id(mission_id)
        content = self.lab.mission_content(mission, concepts=concepts)
        title = "Apoio conceitual" if concepts else "Enunciado"
        try:
            solution = mission.solution_path.relative_to(self.lab.project_root)
        except ValueError:
            solution = mission.solution_path
        document = (
            f"**{title} · {mission.id} — {mission.title}**\n\n"
            f"{mission.summary}\n\n**Arquivo editável:** `{solution}`\n\n{content}"
        )
        self.transcript_entries.append(document)
        shell = self._shell()
        shell.query_one("#document", Markdown).update(document)
        shell.query_one("#document").display = True
        shell.query_one("#response").display = False
        shell.query_one("#content", VerticalScroll).scroll_home(animate=False)

    def _append_user(self, line: str) -> None:
        entry = f"› {line}"
        self.transcript_entries.append(entry)

    def _append_response(self, text: str) -> None:
        cleaned = text.rstrip()
        if not cleaned:
            return
        self.transcript_entries.append(cleaned)
        if not self.screen_stack:
            return
        shell = self._shell()
        shell.query_one("#response", Static).update(Text(cleaned))
        shell.query_one("#response").display = True
        shell.query_one("#document").display = False
        shell.query_one("#content", VerticalScroll).scroll_home(animate=False)

    def _flush_console(self) -> None:
        text = self.output_console.export_text(clear=True)
        self._buffer.seek(0)
        self._buffer.truncate(0)
        if text.strip():
            self._append_response(text)

    def _format_test_result(self, result: TestResult) -> str:
        return test_feedback(result)

    def _record(self, command: str, summary: str) -> None:
        if self.session_log is None:
            return
        failure = self.session_log.try_record(command, summary)
        if failure is not None:
            self._append_response(failure)
            self.notify(failure, severity="error")

    def _close_session(self, summary: str | None = None) -> None:
        if self.session_log is None or not self.session_log.is_open:
            return
        try:
            self.session_log.close(summary)
        except SessionError as exc:
            self._append_response(str(exc))
            if self.screen_stack:
                self.notify(str(exc), severity="error")
            else:
                encoding_safe_console(Console()).print(str(exc), style="red", markup=False)
