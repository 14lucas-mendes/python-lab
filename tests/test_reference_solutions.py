from pathlib import Path

import pytest

from python_lab.test_runner import run_tests


ROOT = Path(__file__).resolve().parent.parent

REFERENCES = [
    ("001-consolidar-falhas", "reference_solution.py"),
    ("002-limpar-relatorio-csv", "reference_solution.py"),
    ("003-validar-inventario-json", "reference_solution.py"),
    ("004-recuperar-script", "reference_solution.py"),
    ("005-relatorio-operacional", "reference_solution"),
    ("006-classificar-ordens", "reference_solution.py"),
    ("007-erros-tempo", "reference_solution"),
    ("008-testes-valor-esperado", "reference_solution.py"),
    ("009-historico-git", "reference_solution.py"),
    ("010-consultar-falhas-sql", "reference_solution.py"),
    ("011-reincidencias-sql", "reference_solution.py"),
]


@pytest.mark.parametrize("slug, solution", REFERENCES)
def test_reference_solution_passes_mission_suite(slug, solution):
    mission_dir = ROOT / "missions" / slug
    result = run_tests(mission_dir / "tests", ROOT, mission_dir / solution)
    assert result.passed, result.output


def test_mission_008_reference_suite_passes_correct_and_fails_broken():
    import os
    import subprocess
    import sys

    mission = ROOT / "missions" / "008-testes-valor-esperado"
    suite = mission / "reference_solution.py"

    def _run(impl: Path) -> int:
        env = os.environ.copy()
        env["PYTHON_LAB_IMPL"] = str(impl)
        completed = subprocess.run(
            [sys.executable, "-m", "pytest", str(suite), "-q"],
            cwd=ROOT,
            env=env,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return completed.returncode

    assert _run(mission / "implementations" / "correta.py") == 0
    assert _run(mission / "implementations" / "defeituosa.py") != 0
