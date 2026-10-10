"""Shared, literal test feedback for the classic CLI and terminal UI."""

from typing import TYPE_CHECKING

from python_lab.models import TestResult

if TYPE_CHECKING:
    from rich.console import Console


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
