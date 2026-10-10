"""Immutable assistant contracts, independent of any provider SDK."""

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, Protocol

from python_lab.assistant.errors import AssistantError


AssistantMode = Literal["assistant", "tutor"]
Action = Literal["explain", "diagnose", "review", "exercise"]

MAX_SOURCE_FILES = 20
MAX_SOURCE_BYTES = 32768
MAX_CONTEXT_BYTES = 131072
MAX_TRACEBACK_BYTES = 32768


def _text_bytes(value: object, label: str) -> bytes:
    if not isinstance(value, str):
        raise AssistantError(f"{label} deve ser texto.")
    try:
        return value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise AssistantError(f"{label} deve ser texto UTF-8 válido.") from exc


def _integer(value: object, label: str, minimum: int = 0) -> None:
    if type(value) is not int or value < minimum:
        raise AssistantError(f"{label} deve ser um inteiro maior ou igual a {minimum}.")


def _level(value: object) -> None:
    _integer(value, "Nível de assistência")
    if value > 4:
        raise AssistantError("Nível de assistência deve estar entre 0 e 4.")


def _source_path(value: object) -> None:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise AssistantError("Path deve ser relativo e POSIX.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise AssistantError("Path deve ser relativo e POSIX.")
    # A Windows drive is not a relative workspace path, even on POSIX hosts.
    if len(value) >= 2 and value[1] == ":":
        raise AssistantError("Path deve ser relativo e POSIX.")


@dataclass(frozen=True)
class SourceFile:
    path: str
    text: str
    sha256: str

    def __post_init__(self) -> None:
        _source_path(self.path)
        if len(_text_bytes(self.text, "Arquivo")) > MAX_SOURCE_BYTES:
            raise AssistantError("Arquivo excede 32768 bytes.")
        if not isinstance(self.sha256, str) or len(self.sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.sha256
        ):
            raise AssistantError("Hash SHA-256 inválido.")


@dataclass(frozen=True)
class WorkspaceSnapshot:
    root: Path
    sources: tuple[SourceFile, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            raise AssistantError("Root deve ser Path.")
        try:
            object.__setattr__(self, "root", self.root.resolve())
        except (OSError, RuntimeError) as exc:
            raise AssistantError("Não foi possível resolver root.") from exc
        if not isinstance(self.sources, tuple) or not all(isinstance(source, SourceFile) for source in self.sources):
            raise AssistantError("Sources deve ser uma tupla de SourceFile.")
        if len(self.sources) > MAX_SOURCE_FILES:
            raise AssistantError("Contexto excede 20 arquivos.")
        if len({source.path for source in self.sources}) != len(self.sources):
            raise AssistantError("Contexto contém paths duplicados.")
        if sum(len(source.text.encode("utf-8")) for source in self.sources) > MAX_CONTEXT_BYTES:
            raise AssistantError("Contexto excede 131072 bytes.")


@dataclass(frozen=True)
class CodeReference:
    path: str
    start_line: int
    end_line: int

    def __post_init__(self) -> None:
        _source_path(self.path)
        _integer(self.start_line, "Linha inicial", 1)
        _integer(self.end_line, "Linha final", 1)
        if self.end_line < self.start_line:
            raise AssistantError("Intervalo de linhas invertido.")


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        _integer(self.input_tokens, "Tokens de entrada")
        _integer(self.output_tokens, "Tokens de saída")


@dataclass(frozen=True)
class AssistantRequest:
    action: Action
    prompt: str
    mode: AssistantMode
    level: int
    snapshot: WorkspaceSnapshot
    traceback: str | None = None
    mission_id: str | None = None

    def __post_init__(self) -> None:
        if self.action not in ("explain", "diagnose", "review", "exercise"):
            raise AssistantError("Ação de assistência inválida.")
        if self.mode not in ("assistant", "tutor"):
            raise AssistantError("Modo de assistência inválido.")
        _level(self.level)
        if not isinstance(self.snapshot, WorkspaceSnapshot):
            raise AssistantError("Snapshot inválido.")
        prompt_bytes = _text_bytes(self.prompt, "Prompt")
        traceback_bytes = b"" if self.traceback is None else _text_bytes(self.traceback, "Traceback")
        if self.mission_id is not None:
            _text_bytes(self.mission_id, "Mission ID")
        if len(traceback_bytes) > MAX_TRACEBACK_BYTES:
            raise AssistantError("Traceback excede 32768 bytes.")
        source_bytes = sum(len(source.text.encode("utf-8")) for source in self.snapshot.sources)
        if len(prompt_bytes) + len(traceback_bytes) + source_bytes > MAX_CONTEXT_BYTES:
            raise AssistantError("Prompt, traceback e arquivos excedem 131072 bytes.")


@dataclass(frozen=True)
class AssistantAnswer:
    summary: str
    explanation: str
    steps: tuple[str, ...]
    references: tuple[CodeReference, ...]
    assistance_level: int
    usage: Usage

    def __post_init__(self) -> None:
        _text_bytes(self.summary, "Summary")
        _text_bytes(self.explanation, "Explanation")
        if not isinstance(self.steps, tuple):
            raise AssistantError("Steps deve ser uma tupla de textos.")
        for step in self.steps:
            _text_bytes(step, "Step")
        if not isinstance(self.references, tuple) or not all(isinstance(ref, CodeReference) for ref in self.references):
            raise AssistantError("References deve ser uma tupla de CodeReference.")
        _level(self.assistance_level)
        if not isinstance(self.usage, Usage):
            raise AssistantError("Usage inválido.")


class LLMProvider(Protocol):
    def generate(self, request: AssistantRequest) -> Awaitable[AssistantAnswer]:
        """Generate an answer; concrete providers belong to the optional adapter."""
        ...


def _mapping(value: object, keys: set[str], label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise AssistantError(f"{label} deve conter exatamente os campos esperados.")
    return value


def _array(value: object, label: str) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise AssistantError(f"{label} deve ser uma lista ou tupla.")
    return tuple(value)


def validate_answer(payload: Mapping[str, object], snapshot: WorkspaceSnapshot) -> AssistantAnswer:
    """Validate untrusted answer fields and references against captured text only."""
    if not isinstance(snapshot, WorkspaceSnapshot):
        raise AssistantError("Snapshot inválido.")
    answer = _mapping(payload, {"summary", "explanation", "steps", "references", "assistance_level", "usage"}, "Resposta")
    usage = _mapping(answer["usage"], {"input_tokens", "output_tokens"}, "Usage")
    line_counts = {source.path: len(source.text.splitlines()) for source in snapshot.sources}
    references = []
    for value in _array(answer["references"], "References"):
        reference = _mapping(value, {"path", "start_line", "end_line"}, "Reference")
        parsed = CodeReference(reference["path"], reference["start_line"], reference["end_line"])
        if parsed.path not in line_counts or parsed.end_line > line_counts[parsed.path]:
            raise AssistantError("Referência fora dos arquivos ou linhas do contexto.")
        references.append(parsed)
    return AssistantAnswer(
        summary=answer["summary"],
        explanation=answer["explanation"],
        steps=_array(answer["steps"], "Steps"),
        references=tuple(references),
        assistance_level=answer["assistance_level"],
        usage=Usage(usage["input_tokens"], usage["output_tokens"]),
    )
