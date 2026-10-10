"""Command contracts and registry, independent of terminal renderers."""
from dataclasses import dataclass
import shlex
from typing import Callable


COMMANDS = (
    ("/goal", "/g", "Exibir objetivo e critérios de sucesso"),
    ("/skills", "/sk", "Exibir mapa de competências e evidências"),
    ("/missions", "/ms", "Listar missões e estados"),
    ("/start <id>", "", "Iniciar ou repetir uma missão desbloqueada"),
    ("/mission [id]", "", "Consultar o enunciado sem iniciar a missão"),
    ("/concepts [id]", "", "Consultar apoio conceitual opcional"),
    ("/plan", "/p", "Registrar ou revisar o planejamento"),
    ("/test", "/t", "Executar os testes da missão atual"),
    ("/test details", "", "Consultar a saída completa sem nova tentativa"),
    ("/hint", "/h", "Liberar a próxima pista"),
    ("/explain", "/e", "Registrar a explicação final"),
    ("/status", "/st", "Exibir estado da sessão"),
    ("/history", "/hi", "Exibir histórico de tentativas da missão atual"),
    ("/session", "/se", "Exibir o histórico desta sessão"),
    ("/evidence", "/ev", "Exibir evidências de competências"),
    ("/help", "/?", "Listar comandos disponíveis"),
    ("/exit", "/q", "Salvar e encerrar com segurança"),
)

ALIASES = {
    "/g": "/goal",
    "/sk": "/skills",
    "/ms": "/missions",
    "/p": "/plan",
    "/t": "/test",
    "/h": "/hint",
    "/e": "/explain",
    "/st": "/status",
    "/hi": "/history",
    "/se": "/session",
    "/ev": "/evidence",
    "/?": "/help",
    "/q": "/exit",
}

DEFAULT_SUMMARIES = {
    "/goal": "Goal exibido",
    "/skills": "Skills exibidas",
    "/missions": "Missões listadas",
    "/mission": "Enunciado consultado",
    "/concepts": "Apoio conceitual consultado",
    "/plan": "Planejamento registrado",
    "/hint": "Pista liberada",
    "/status": "Status exibido",
    "/history": "Histórico de tentativas exibido",
    "/session": "Histórico da sessão exibido",
    "/evidence": "Evidências exibidas",
    "/help": "Ajuda exibida",
    "/exit": "Sessão encerrada",
}

@dataclass(frozen=True)
class Command:
    name: str
    args: tuple[str, ...]


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    message: str
    data: dict[str, object]
    exit_requested: bool = False


def parse_command(line: str) -> Command:
    # POSIX quote removal with escaping disabled keeps Windows paths intact,
    # including a backslash immediately before the closing quote.
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    lexer.escape = ""
    try:
        parts = list(lexer)
    except ValueError as exc:
        raise ValueError("Comando inválido: feche as aspas e tente novamente.") from exc
    raw = parts[0].lower() if parts else ""
    return Command(ALIASES.get(raw, raw), tuple(parts[1:]))


class CommandDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[tuple[str, ...]], CommandResult]] = {}

    def register(self, name: str, handler: Callable[[tuple[str, ...]], CommandResult]) -> None:
        canonical = ALIASES.get(name.lower(), name.lower())
        self._handlers[canonical] = handler

    def dispatch(self, command: Command) -> CommandResult:
        name = ALIASES.get(command.name.lower(), command.name.lower())
        handler = self._handlers.get(name)
        if handler is None:
            suggested = f"/{name}"
            message = "Comando desconhecido. Digite /help para a lista."
            if not name.startswith("/") and (suggested in self._handlers or suggested in ALIASES):
                message = f"Comando desconhecido. Use {suggested}. Digite /help para a lista."
            return CommandResult(False, message, {})
        return handler(command.args)
