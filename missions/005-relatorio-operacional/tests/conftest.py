import importlib
import os
import sys
from pathlib import Path

import pytest

MISSION_DIR = Path(__file__).resolve().parent.parent


def _purge_package() -> None:
    for name in list(sys.modules):
        if name == "relatorio_operacional" or name.startswith("relatorio_operacional."):
            del sys.modules[name]


@pytest.fixture
def solution():
    configured = os.environ.get("PYTHON_LAB_SOLUTION")
    root = Path(configured) if configured else MISSION_DIR / "starter"
    _purge_package()
    sys.path.insert(0, str(root))
    try:
        module = importlib.import_module("relatorio_operacional")
        return module
    finally:
        if sys.path[0] == str(root):
            sys.path.pop(0)
