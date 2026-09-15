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
]


@pytest.mark.parametrize("slug, solution", REFERENCES)
def test_reference_solution_passes_mission_suite(slug, solution):
    mission_dir = ROOT / "missions" / slug
    result = run_tests(mission_dir / "tests", ROOT, mission_dir / solution)
    assert result.passed, result.output
