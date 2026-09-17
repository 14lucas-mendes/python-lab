import hashlib
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from python_lab.models import TestResult


def solution_fingerprint(solution_path: Path) -> str | None:
    """Return a stable digest for the source files used as a solution."""
    path = Path(solution_path)
    if not path.exists():
        return None

    digest = hashlib.sha256()
    if path.is_file():
        digest.update(b"file\0")
        digest.update(path.read_bytes())
        return digest.hexdigest()

    if not path.is_dir():
        return None

    for item in sorted(path.rglob("*")):
        if not item.is_file() or "__pycache__" in item.parts or item.suffix == ".pyc":
            continue
        relative = item.relative_to(path).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _pytest_report_details(report_path: Path) -> tuple[bool, str, tuple[str, ...]]:
    try:
        root = ET.parse(report_path).getroot()
    except (FileNotFoundError, ET.ParseError, OSError):
        return False, "Relatório JUnit ausente ou inválido", ()

    total = failures = errors = skipped = 0
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    try:
        for suite in suites:
            total += int(suite.attrib.get("tests", 0))
            failures += int(suite.attrib.get("failures", 0))
            errors += int(suite.attrib.get("errors", 0))
            skipped += int(suite.attrib.get("skipped", 0))
    except (TypeError, ValueError):
        return False, "Relatório JUnit inválido", ()

    diagnostics: list[str] = []
    for case in root.iter("testcase"):
        label = "::".join(
            part for part in (case.attrib.get("classname"), case.attrib.get("name")) if part
        )
        for kind in ("failure", "error"):
            problem = case.find(kind)
            if problem is None:
                continue
            message = problem.attrib.get("message") or (problem.text or "").strip()
            first_line = message.splitlines()[0] if message else "falha sem mensagem"
            diagnostics.append(f"{label or 'teste'}: {first_line}")

    passed = max(total - failures - errors - skipped, 0)
    summary = (
        f"{total} teste(s): {passed} aprovado(s), "
        f"{failures + errors} falho(s), {skipped} ignorado(s)"
    )
    complete = total > 0 and failures == 0 and errors == 0 and skipped == 0
    return complete, summary, tuple(diagnostics)


def _pytest_report_is_complete(report_path: Path) -> bool:
    return _pytest_report_details(report_path)[0]


def run_tests(
    test_path: Path,
    project_root: Path,
    solution_path: Path | None = None,
    timeout: float = 30.0,
) -> TestResult:
    env = os.environ.copy()
    if solution_path is not None:
        env["PYTHON_LAB_SOLUTION"] = str(solution_path)
    with tempfile.TemporaryDirectory(prefix="python-lab-pytest-") as report_dir:
        report_path = Path(report_dir) / "results.xml"
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    str(test_path),
                    "-q",
                    "-rA",
                    "--junitxml",
                    str(report_path),
                ],
                cwd=project_root,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                env=env,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            partial = exc.output or exc.stdout or ""
            if isinstance(partial, bytes):
                partial = partial.decode("utf-8", errors="replace")
            detail = f"\n{partial}" if partial else ""
            return TestResult(
                passed=False,
                return_code=-1,
                output=f"Tempo limite excedido após {timeout:g} segundos.{detail}",
                summary="Execução interrompida por tempo limite",
            )
        except FileNotFoundError as exc:
            return TestResult(
                passed=False,
                return_code=-1,
                output=(
                    "Não foi possível executar pytest. Instale as dependências de desenvolvimento "
                    "com `python -m pip install -e \".[dev]\"`."
                ),
                summary="pytest indisponível",
            )
        except OSError as exc:
            return TestResult(
                passed=False,
                return_code=-1,
                output=f"Não foi possível iniciar os testes: {exc}",
                summary="Falha ao iniciar pytest",
            )
        report_complete, summary, diagnostics = _pytest_report_details(report_path)
    return TestResult(
        passed=completed.returncode == 0 and report_complete,
        return_code=completed.returncode,
        output=completed.stdout or "",
        summary=summary,
        diagnostics=diagnostics,
    )
