import os
import sqlite3
from pathlib import Path

import pytest

from python_lab.solution_loader import load_solution

MISSION_DIR = Path(__file__).resolve().parent.parent
SEED = (MISSION_DIR / "data" / "falhas.sql").read_text(encoding="utf-8")


@pytest.fixture
def solution():
    configured = os.environ.get("PYTHON_LAB_SOLUTION")
    path = Path(configured) if configured else MISSION_DIR / "starter.py"
    return load_solution(path)


@pytest.fixture
def conexao():
    conexao = sqlite3.connect(":memory:")
    conexao.executescript(SEED)
    yield conexao
    conexao.close()
