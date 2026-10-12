from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static, TextArea

from python_lab.learning import PLAN_KEYS


PLAN_LABELS = {
    "input": "Entrada (input)",
    "output": "Saída (output)",
    "steps": "Etapas (steps)",
    "risks": "Possíveis erros (risks)",
}

HELP_TEXT = """\
Digite / para abrir a lista de comandos.

/start <id>  Iniciar uma missão
/mission [id] Consultar o enunciado
/concepts [id] Apoio conceitual opcional
/plan        Registrar o planejamento
/test        Executar os testes
/test details Saída completa sem nova tentativa
/hint        Liberar a próxima pista
/explain     Registrar a explicação e concluir
/project <dir>  Abrir projeto do assistente; off retorna às missões
/mode <assistant|tutor> Alternar modo
/explain-code <arquivo> Explicar código
/diagnose --traceback <arquivo> --file <fonte> Diagnosticar erro
/check <arquivo> Verificação local
/review <arquivo> Revisão local e propostas opcionais
/apply <id>  Confirmar diff e aplicar
/verify <id> --check ast|ruff|pytest Verificação explícita
/new <template> <nome> --path <pai> Criar projeto
/practice    Sugestões por observações; somente leitura
/exercise <tema> Gerar draft privado para revisão
/exercise-show <id> Consultar draft, referência oculta
/exercise-validate <id> Confirmar execução com seus privilégios
/exercise-publish <id> Aprovar revisão e publicação local
/cancel      Cancelar ação em curso
/help        Mostrar esta ajuda
/exit        Salvar e encerrar

Esc fecha o menu ou limpa o campo.
PageUp / PageDown percorrem o conteúdo sem sair do campo.
q (campo vazio) ou Ctrl+C encerra a sessão.
A pista 5 (solução de referência) pede confirmação.
"""


class PlanScreen(ModalScreen[dict[str, str] | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancelar", show=False),
    ]

    def __init__(self, plan: dict[str, str] | None = None) -> None:
        super().__init__()
        self._plan = plan or {}

    def compose(self) -> ComposeResult:
        with Vertical(id="plan-dialog"):
            yield Label("Planejamento")
            with VerticalScroll(id="plan-fields"):
                for key in PLAN_KEYS:
                    yield Label(PLAN_LABELS[key])
                    if key in {"steps", "risks"}:
                        yield TextArea(self._plan.get(key, ""), id=f"plan-{key}")
                    else:
                        yield Input(self._plan.get(key, ""), id=f"plan-{key}")
            with Horizontal(id="dialog-buttons"):
                yield Button("Salvar", variant="primary", id="plan-save")
                yield Button("Cancelar", id="plan-cancel")

    def on_mount(self) -> None:
        self.query_one("#plan-input", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "plan-save":
            self.dismiss(
                {
                    key: (
                        self.query_one(f"#plan-{key}", TextArea).text
                        if key in {"steps", "risks"}
                        else self.query_one(f"#plan-{key}", Input).value
                    )
                    for key in PLAN_KEYS
                }
            )
            return
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ExplainScreen(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancelar", show=False),
    ]

    def __init__(self, questions: tuple[str, ...] = (), explanation: str = "") -> None:
        super().__init__()
        self._questions = questions
        self._explanation = explanation

    def compose(self) -> ComposeResult:
        with Vertical(id="explain-dialog"):
            yield Label("Explicação final")
            with VerticalScroll(id="explain-fields"):
                yield Static(
                    "\n".join(f"- {question}" for question in self._questions)
                    or "Explique suas decisões e como verificou os casos extremos.",
                    id="reflection", markup=False,
                )
                yield TextArea(self._explanation, id="explain-text")
                yield Static("", id="explain-error", markup=False)
            with Horizontal(id="dialog-buttons"):
                yield Button("Concluir", variant="primary", id="explain-save")
                yield Button("Cancelar", id="explain-cancel")

    def on_mount(self) -> None:
        self.query_one("#explain-text", TextArea).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "explain-save":
            text = self.query_one("#explain-text", TextArea).text
            if not text.strip():
                self.query_one("#explain-error", Static).update("A explicação não pode ser vazia")
                self.query_one("#explain-text", TextArea).focus()
                return
            self.dismiss(text)
            return
        self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [
        Binding("y", "confirm", "Sim", show=False),
        Binding("n", "cancel", "Não", show=False),
        Binding("escape", "cancel", "Cancelar", show=False),
    ]

    def __init__(self, message: str, *, diff: str | None = None) -> None:
        super().__init__()
        self._message = message
        self._diff = diff

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(self._message, id="confirm-message", markup=False)
            if self._diff is not None:
                with VerticalScroll(id="patch-scroll"):
                    yield Static(Text(self._diff), id="patch-diff", markup=False)
            with Horizontal(id="dialog-buttons"):
                yield Button("Confirmar", variant="error", id="confirm-yes")
                yield Button("Cancelar", id="confirm-no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "dismiss_help", "Fechar", show=False),
        Binding("question_mark", "dismiss_help", "Fechar", show=False),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("Ajuda")
            yield Static(HELP_TEXT, id="help-body")
            with Horizontal(id="dialog-buttons"):
                yield Button("Fechar", variant="primary", id="help-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        del event
        self.dismiss()

    def action_dismiss_help(self) -> None:
        self.dismiss()
