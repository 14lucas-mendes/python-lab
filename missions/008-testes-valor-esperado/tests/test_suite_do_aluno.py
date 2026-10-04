import os
import subprocess
import sys
from pathlib import Path

MISSION_DIR = Path(__file__).resolve().parent.parent
CORRECT = MISSION_DIR / "implementations" / "correta.py"
BROKEN = MISSION_DIR / "implementations" / "defeituosa.py"


def _student_suite() -> Path:
    configured = os.environ.get("PYTHON_LAB_SOLUTION")
    return Path(configured) if configured else MISSION_DIR / "test_minha_solucao.py"


def _run(impl: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHON_LAB_IMPL"] = str(impl)
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(_student_suite()), "-q", "--tb=short"],
        cwd=MISSION_DIR,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def test_suite_passa_na_implementacao_correta():
    result = _run(CORRECT)
    assert result.returncode == 0, result.stdout


def test_suite_falha_na_implementacao_defeituosa():
    result = _run(BROKEN)
    assert result.returncode != 0, result.stdout
