import importlib.util
from pathlib import Path
from types import ModuleType


def load_solution(path: Path) -> ModuleType:
    """Load a file-based student solution under an isolated module name."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    spec = importlib.util.spec_from_file_location("mission_solution", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Não foi possível carregar {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
