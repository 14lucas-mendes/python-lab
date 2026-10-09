"""Shared, literal test feedback for the classic CLI and terminal UI."""

from python_lab.models import TestResult


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
