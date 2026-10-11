"""Shared test feedback and read-only learning snapshots for local interfaces."""

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from python_lab.assistant.history import ConversationReference, ConversationRepository
from python_lab.models import AppProgress, Mission, TestResult
from python_lab.recommendations import LearningRecommendation, recommend_practice, review_completed

if TYPE_CHECKING:
    from rich.console import Console


@dataclass(frozen=True)
class PracticeSnapshot:
    recommendations: tuple[LearningRecommendation, ...]
    completed_review: tuple[LearningRecommendation, ...] = ()
    error_history: tuple[ConversationReference, ...] = ()


def practice_snapshot(
    missions: list[Mission], progress: AppProgress, *, include_completed: bool = False,
    history: ConversationRepository | None = None, workspace: Path | None = None,
) -> PracticeSnapshot:
    """Expose practice and opt-in review with scoped local conversation links."""
    if history is not None and workspace is None:
        raise ValueError("Informe o workspace para consultar referências locais de erros.")
    recommendations = recommend_practice(missions, progress)
    completed = review_completed(missions, progress) if include_completed else ()
    references = tuple(
        reference
        for item in (*recommendations, *completed)
        for reference in history.error_references(workspace, mission_id=item.mission_id)
    ) if history is not None else ()
    return PracticeSnapshot(recommendations, completed, references)


def test_feedback(result: TestResult, details: bool = False) -> str:
    status = "passaram" if result.passed else "falharam"
    lines = [f"Testes {status} (código {result.return_code})"]
    if result.summary:
        lines.append(f"Resumo: {result.summary}")
    if details:
        lines.append(result.output.strip() or "A execução não produziu saída adicional.")
    else:
        if not result.passed and result.diagnostics:
            lines.append("Diagnóstico:")
            lines.extend(f"- {item}" for item in result.diagnostics[:5])
        lines.append("Saída completa: /test details")
    return "\n".join(lines)


class _EncodingSafeWriter:
    """Replace only unrepresentable output; keep the consumer's codec intact."""

    def __init__(self, stream) -> None:
        self._stream = stream

    @property
    def rich_proxied_file(self):
        # Rich unwraps file proxies; this writer must remain the final boundary.
        return self

    def write(self, text: str) -> int:
        encoding = getattr(self._stream, "encoding", None)
        if encoding:
            text = text.encode(encoding, errors="replace").decode(encoding)
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


def encoding_safe_console(console: "Console") -> "Console":
    stream = console.file
    if not isinstance(stream, _EncodingSafeWriter) and getattr(stream, "encoding", None):
        console.file = _EncodingSafeWriter(stream)
    return console
