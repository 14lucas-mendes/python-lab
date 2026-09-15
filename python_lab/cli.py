from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from python_lab.app import ApplicationError, PythonLabApp
from python_lab.catalog import CatalogError, load_goal, load_missions, load_skills
from python_lab.learning import HintError, LearningError
from python_lab.progress import ProgressError, ProgressRepository


COMMANDS = (
    ("/goal", "Exibir objetivo e critérios de sucesso"),
    ("/skills", "Exibir mapa de competências e evidências"),
    ("/missions", "Listar missões e estados"),
    ("/start <id>", "Iniciar uma missão desbloqueada"),
    ("/plan", "Registrar ou revisar o planejamento"),
    ("/test", "Executar os testes da missão atual"),
    ("/hint", "Liberar a próxima pista"),
    ("/explain", "Registrar a explicação final"),
    ("/status", "Exibir estado da sessão"),
    ("/help", "Listar comandos disponíveis"),
    ("/exit", "Salvar e encerrar com segurança"),
)

SKILL_LABELS = {
    "practicing": "Em prática",
    "demonstrated": "Demonstrada",
    "consolidated": "Consolidada",
}


class PythonLabCLI:
    def __init__(self, app: PythonLabApp, console: Console | None = None) -> None:
        self.app = app
        self.console = console or Console()
        self.handlers = {
            "/goal": self.show_goal,
            "/skills": self.show_skills,
            "/missions": self.show_missions,
            "/start": self.start,
            "/plan": self.plan,
            "/test": self.test,
            "/hint": self.hint,
            "/explain": self.explain,
            "/status": self.status,
            "/help": self.help,
            "/exit": self.exit,
        }

    def execute(self, command_line: str) -> bool:
        stripped = command_line.strip()
        if not stripped:
            return True
        parts = stripped.split(maxsplit=1)
        command = parts[0].lower()
        argument = parts[1] if len(parts) > 1 else ""
        handler = self.handlers.get(command)
        if handler is None:
            self.console.print("Comando desconhecido. Digite /help para a lista.")
            return True
        try:
            return handler(argument)
        except (ApplicationError, LearningError, ProgressError) as exc:
            self.console.print(f"[red]{exc}[/red]")
            return True

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
        table = Table(title="Missions")
        table.add_column("ID")
        table.add_column("Título")
        table.add_column("Estado")
        for mission in self.app.missions:
            progress = self.app.progress.missions.get(mission.id)
            status = progress.status if progress else "available"
            table.add_row(mission.id, mission.title, status)
        self.console.print(table)
        return True

    def start(self, argument: str = "") -> bool:
        mission_id = argument.strip()
        if not mission_id:
            self.console.print("Uso: /start <id>")
            return True
        mission = self.app.start(mission_id)
        self.console.print(f"Missão {mission.id} iniciada: {mission.title}")
        self.console.print(f"Edite a solução em: {mission.solution_path}")
        return True

    def plan(self, _argument: str = "") -> bool:
        self.app.current_mission()
        plan = {
            "input": self.console.input("Entrada (input): ").strip(),
            "output": self.console.input("Saída (output): ").strip(),
            "steps": self.console.input("Etapas (steps): ").strip(),
            "risks": self.console.input("Possíveis erros (risks): ").strip(),
        }
        self.app.save_plan(plan)
        self.console.print("Planejamento registrado.")
        return True

    def test(self, _argument: str = "") -> bool:
        result = self.app.run_current_tests()
        style = "green" if result.passed else "red"
        status = "passaram" if result.passed else "falharam"
        self.console.print(f"[{style}]Testes {status} (código {result.return_code})[/{style}]")
        if result.output.strip():
            self.console.print(result.output)
        return True

    def hint(self, argument: str = "") -> bool:
        confirm = argument.strip().lower() in {"confirm", "confirmar", "sim", "yes"}
        try:
            text = self.app.next_hint(confirm_reference=confirm)
        except HintError as exc:
            self.console.print(f"[yellow]{exc}[/yellow]")
            self.console.print("Use /hint confirm para liberar a solução de referência.")
            return True
        self.console.print(Panel(text, title="Pista"))
        return True

    def explain(self, argument: str = "") -> bool:
        text = argument.strip() or self.console.input("Explicação final: ").strip()
        self.app.save_explanation(text)
        self.console.print("Explicação registrada.")
        return True

    def status(self, _argument: str = "") -> bool:
        recommended = self.app.recommended()
        current_id = self.app.progress.current_mission_id or "nenhuma"
        recommendation = f"{recommended.id} — {recommended.title}" if recommended else "Todas as missões concluídas"
        lines = [
            f"Missão atual: {current_id}",
            f"Recomendada: {recommendation}",
        ]
        try:
            progress = self.app.current_progress()
            lines.extend(
                [
                    f"Tentativas: {progress.attempts}",
                    f"Testes: {'ok' if progress.tests_passed else 'pendentes'}",
                    f"Pistas: {progress.hints_revealed}",
                    f"Plano: {'registrado' if progress.plan else 'pendente'}",
                    f"Explicação: {'registrada' if progress.explanation else 'pendente'}",
                ]
            )
        except ApplicationError:
            pass
        self.console.print(Panel("\n".join(lines), title="Sessão"))
        return True

    def help(self, _argument: str = "") -> bool:
        table = Table(title="Comandos")
        table.add_column("Comando")
        table.add_column("Responsabilidade")
        for command, description in COMMANDS:
            table.add_row(command, description)
        self.console.print(table)
        return True

    def exit(self, _argument: str = "") -> bool:
        self.app.persist()
        self.console.print("Progresso salvo. Até a próxima sessão.")
        return False


def _banner(app: PythonLabApp, console: Console) -> None:
    recommended = app.recommended()
    recommendation = (
        f"{recommended.id} — {recommended.title}" if recommended else "Nenhuma missão elegível"
    )
    current = app.progress.current_mission_id or "nenhuma"
    body = (
        f"{app.goal.title}\n\n"
        f"{app.goal.statement}\n\n"
        f"Missão atual: {current}\n"
        f"Recomendada: {recommendation}"
    )
    console.print(Panel(body, title="Python Lab"))


def build_app(project_root: Path | None = None) -> PythonLabApp:
    root = project_root or Path(__file__).resolve().parent.parent
    return PythonLabApp(
        goal=load_goal(root / "data" / "goal.json"),
        skills=load_skills(root / "data" / "skills.json"),
        missions=load_missions(root / "missions"),
        repository=ProgressRepository(root / "data" / "progress.json"),
        project_root=root,
    )


def main() -> None:
    console = Console()
    try:
        app = build_app()
    except (ProgressError, ApplicationError, CatalogError) as exc:
        console.print(f"[red]{exc}[/red]")
        return
    cli = PythonLabCLI(app=app, console=console)
    _banner(app, console)
    try:
        while True:
            line = console.input("[bold]lab>[/bold] ")
            if not cli.execute(line):
                break
    except KeyboardInterrupt:
        console.print("\nSessão encerrada. O último estado confirmado foi preservado.")
    except EOFError:
        app.persist()
        console.print("\nProgresso salvo. Até a próxima sessão.")
