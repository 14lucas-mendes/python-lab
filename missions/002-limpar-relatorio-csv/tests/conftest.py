import importlib.util
import os
from pathlib import Path

import pytest

MISSION_DIR = Path(__file__).resolve().parent.parent


def load_solution(path: Path):
    spec = importlib.util.spec_from_file_location("mission_solution", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Não foi possível carregar {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def solution():
    configured = os.environ.get("PYTHON_LAB_SOLUTION")
    path = Path(configured) if configured else MISSION_DIR / "starter.py"
    return load_solution(path)
