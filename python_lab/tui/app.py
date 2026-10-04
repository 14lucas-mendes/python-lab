from io import StringIO
from pathlib import Path

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Input, Label, RichLog

from python_lab.app import ApplicationError, PythonLabApp
from python_lab.learning import HintError, LearningError
from python_lab.models import TestResult
from python_lab.progress import ProgressError
from python_lab.session import SessionError, SessionLog
from python_lab.tui.screens import ConfirmScreen, ExplainScreen, PlanScreen
from python_lab.tui.widgets import CommandPalette, Composer, NextStepBar


APP_VERSION = "0.3.0"


class PythonLabTUI(App[None]):
    CSS_PATH = Path(__file__).with_name("lab.tcss")

    def __init__(
        self,
        lab: PythonLabApp,
        session_log: SessionLog | None = None,
    ) -> None:
        super().__init__()
        from python_lab.cli import ALIASES, COMMANDS, PythonLabCLI

        self.lab = lab
        self.session_log = session_log
        self.commands = COMMANDS
        self.aliases = ALIASES
        self._buffer = StringIO()
        self.console = Console(
            file=self._buffer,
            record=True,
            width=100,
            force_terminal=True,
        )
        self.cli = PythonLabCLI(app=lab, console=self.console, session_log=session_log)
        self.last_test_result: TestResult | None = None
        self.transcript_entries: list[str] = []
        self._testing = False
        self.title = f"Python Lab {APP_VERSION}"
        self.sub_title = self._subtitle()

    def compose(self) -> ComposeResult:
        yield RichLog(id="transcript", highlight=False, markup=False, wrap=True)
        yield CommandPalette(id="palette")
        with Vertical(id="composer-wrap"):
            with Horizontal(id="composer-row"):
                yield Label("lab ›", id="prompt-mark")
                yield Composer(placeholder="Digite / para comandos", id="composer")
        yield NextStepBar(id="next-step")

    def on_mount(self) -> None:
        self.console.print(self._opening_banner())
        self._flush_console()
        self._refresh_status()
        palette = self._palette()
        if palette is not None:
            palette.display = False
        composer = self._composer()
        if composer is not None:
            composer.focus()

    def on_unmount(self) -> None:
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

    def _transcript(self) -> RichLog | None:
        try:
            return self._shell().query_one("#transcript", RichLog)
        except NoMatches:
            return None

    def _next_step_bar(self) -> NextStepBar | None:
        try:
            return self._shell().query_one("#next-step", NextStepBar)
        except NoMatches:
            return None

    def action_quit_lab(self) -> None:
        self.lab.persist()
        self._close_session()
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
        command, argument = self._split_command(value)
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
        stripped = line.strip()
        if not stripped:
            return
        self._append_user(stripped)
        command, argument = self._split_command(stripped)
        if command in {"/plan"}:
            self._open_plan()
            return
        if command in {"/explain"} and not argument:
            self._open_explain()
            return
        if command in {"/test"}:
            self._run_tests()
            return
        if command in {"/hint"}:
            confirm = argument.lower() in {"confirm", "confirmar", "sim", "yes"}
            self._run_hint(confirm_reference=confirm)
            return
        keep = self.cli.execute(stripped)
        self._flush_console()
        self._refresh_status()
        if not keep:
            self.exit()

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
            body = (
                f"Entrada: {plan['input']}\n"
                f"Saída: {plan['output']}\n"
                f"Etapas: {plan['steps']}\n"
                f"Riscos: {plan['risks']}"
            )
            self.console.print(self._info_box("Planejamento", [
                ("Entrada", plan["input"]),
                ("Saída", plan["output"]),
                ("Etapas", plan["steps"]),
                ("Riscos", plan["risks"]),
            ]))
            self._flush_console()
            self._record("/plan", "Planejamento registrado")
            self._refresh_status()

        self.push_screen(PlanScreen(progress.plan), on_done)

    def _open_explain(self) -> None:
        try:
            self.lab.current_mission()
        except ApplicationError as exc:
            self._append_response(str(exc))
            self.notify(str(exc), severity="error")
            return

        def on_done(text: str | None) -> None:
            if text is None:
                self._append_response("Explicação cancelada.")
                return
            keep = self.cli.execute(f"/explain {text}")
            self._flush_console()
            self._refresh_status()
            if not keep:
                self.exit()

        self.push_screen(ExplainScreen(), on_done)

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
        self.run_worker(
            self._run_tests_worker,
            thread=True,
            exclusive=True,
            name="run-tests",
            exit_on_error=False,
        )

    def _run_tests_worker(self) -> None:
        try:
            result = self.lab.run_current_tests()
        except Exception as exc:
            self.call_from_thread(self._on_tests_finished, None, exc)
            return
        self.call_from_thread(self._on_tests_finished, result, None)

    def _on_tests_finished(self, result: TestResult | None, error: Exception | None) -> None:
        self._testing = False
        composer = self._composer()
        if composer is not None:
            composer.disabled = False
            composer.placeholder = "Digite / para comandos"
            composer.focus()
        if error is not None:
            self._append_response(str(error))
            self.notify(str(error), severity="error")
            self._record("/test", str(error))
            self._refresh_status()
            return
        assert result is not None
        self.last_test_result = result
        output = self._format_test_result(result)
        self._append_response(output)
        summary = "Testes passaram" if result.passed else "Testes falharam"
        self._record("/test", summary)
        self.notify(summary, severity="information" if result.passed else "error")
        self._refresh_status()

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
        self.console.print(self._info_box("Pista", [("Texto", text)]))
        self._flush_console()
        self._record("/hint", "Pista liberada")
        self._refresh_status()

    def _on_reference_confirmed(self, confirmed: bool | None) -> None:
        if not confirmed:
            self._append_response("Consulta à referência cancelada.")
            return
        self._run_hint(confirm_reference=True)

    def _split_command(self, line: str) -> tuple[str, str]:
        parts = line.strip().split(maxsplit=1)
        raw = parts[0].lower() if parts else ""
        argument = parts[1] if len(parts) > 1 else ""
        return self.aliases.get(raw, raw), argument

    def _subtitle(self) -> str:
        current = self.lab.progress.current_mission_id or "nenhuma"
        return f"{self.lab.goal.title} · missão {current}"

    def _opening_banner(self) -> Group:
        recommended = self.lab.recommended()
        current_id = self.lab.progress.current_mission_id or "nenhuma"
        recommendation = (
            f"{recommended.id} — {recommended.title}" if recommended else "Nenhuma missão elegível"
        )
        if current_id != "nenhuma":
            mission = self.lab.mission_by_id(current_id)
            mission_label = f"{mission.id} — {mission.title}"
            state = Text("RUNNING", style="bold #22c55e")
        else:
            mission_label = "nenhuma"
            state = Text("READY", style="bold #22c55e")
        prompt = Text.assemble(
            ("lab", "bold white"),
            (" ~ ", "dim"),
            (f"python-lab {APP_VERSION}", "dim"),
        )
        steps = Text()
        for done, label in (
            (True, "Goal carregado"),
            (True, "Catálogo de missões"),
            (self.session_log is not None, "Sessão iniciada"),
            (current_id != "nenhuma", f"Missão {current_id}"),
        ):
            steps.append("✓  " if done else "○  ", style="#22c55e" if done else "#8a8a8a")
            steps.append(f"{label}\n", style="white" if done else "#8a8a8a")
        return Group(
            prompt,
            Text(),
            steps,
            Text(),
            self._info_box(
                "Python Lab",
                [
                    ("Objetivo", self.lab.goal.title),
                    ("Missão", mission_label),
                    ("Estado", state),
                    ("Recomendada", recommendation),
                ],
            ),
            Text(),
            Text(f"Próximo: {self.lab.next_step()}", style="#22c55e"),
        )

    def _info_box(self, title: str, rows: list[tuple[str, object]]) -> Panel:
        table = Table(
            box=None,
            show_header=False,
            pad_edge=False,
            expand=True,
            padding=(0, 1),
        )
        table.add_column(style="#8a8a8a", min_width=14, max_width=16)
        table.add_column(overflow="fold")
        for key, value in rows:
            table.add_row(key, value if isinstance(value, Text) else str(value))
        return Panel(
            table,
            title=f" {title} ",
            title_align="left",
            box=box.SQUARE,
            border_style="#d4d4d4",
            padding=(1, 1),
        )

    def _refresh_status(self) -> None:
        next_step = self._next_step_bar()
        if next_step is not None:
            next_step.update_from(self.lab)
        self.sub_title = self._subtitle()

    def _append_user(self, line: str) -> None:
        entry = f"› {line}"
        self.transcript_entries.append(entry)
        transcript = self._transcript()
        if transcript is not None:
            transcript.write(Text.assemble(("lab › ", "bold white"), (line, "white")))

    def _append_response(self, text: str) -> None:
        cleaned = text.rstrip()
        if not cleaned:
            return
        self.transcript_entries.append(cleaned)
        transcript = self._transcript()
        if transcript is not None:
            transcript.write(Text(cleaned, style="#e8e8e8"))

    def _flush_console(self) -> None:
        text = self.console.export_text(clear=True)
        self._buffer.seek(0)
        self._buffer.truncate(0)
        if text.strip():
            self._append_response(text)

    def _format_test_result(self, result: TestResult) -> str:
        mark = "✓" if result.passed else "✗"
        status = "passaram" if result.passed else "falharam"
        lines = [f"{mark}  Testes {status} (código {result.return_code})"]
        if result.summary:
            lines.append(f"Resumo: {result.summary}")
        if result.passed:
            return "\n".join(lines)
        if result.diagnostics:
            lines.append("Diagnóstico:")
            lines.extend(f"- {item}" for item in result.diagnostics[:5])
        if result.output.strip():
            lines.append(result.output)
        return "\n".join(lines)

    def _record(self, command: str, summary: str) -> None:
        if self.session_log is None:
            return
        try:
            self.session_log.record(command, summary)
        except SessionError as exc:
            self.notify(str(exc), severity="error")

    def _close_session(self, summary: str | None = None) -> None:
        if self.session_log is None or self.session_log._current is None:
            return
        if self.session_log._current.get("ended_at") is not None:
            return
        try:
            self.session_log.close(summary)
        except SessionError:
            pass
