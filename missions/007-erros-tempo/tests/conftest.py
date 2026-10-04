import os
from pathlib import Path

import pytest

from python_lab.solution_loader import load_solution

MISSION_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def solution_dir() -> Path:
    configured = os.environ.get("PYTHON_LAB_SOLUTION")
    return Path(configured) if configured else MISSION_DIR / "starter"


@pytest.fixture
def load_module():
    def _load(root: Path, name: str):
        return load_solution(root / name)

    return _load
