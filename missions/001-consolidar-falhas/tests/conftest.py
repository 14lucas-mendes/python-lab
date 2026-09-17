import os
from pathlib import Path

import pytest

from python_lab.solution_loader import load_solution

MISSION_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def solution():
    configured = os.environ.get("PYTHON_LAB_SOLUTION")
    path = Path(configured) if configured else MISSION_DIR / "starter.py"
    return load_solution(path)
