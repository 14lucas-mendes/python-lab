import json
from pathlib import Path
from typing import Any

from python_lab.models import Goal, Mission, Skill


class CatalogError(Exception):
    pass


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"Arquivo não encontrado: {path}") from exc
    except UnicodeDecodeError as exc:
        raise CatalogError(f"Codificação inválida em {path}; use UTF-8") from exc
    except OSError as exc:
        raise CatalogError(f"Não foi possível ler {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(f"JSON inválido em {path}: {exc.msg}") from exc


def _require(payload: dict[str, Any], field: str, path: Path) -> Any:
    if field not in payload:
        raise CatalogError(f"Campo obrigatório ausente em {path}: {field}")
    return payload[field]


def _text(value: Any, field: str, path: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"Campo {field} deve ser texto não vazio em {path}")
    return value


def _as_tuple(value: Any, field: str, path: Path) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CatalogError(f"Campo {field} deve ser uma lista de strings em {path}")
    return tuple(value)


def load_goal(path: Path) -> Goal:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise CatalogError(f"Goal deve ser um objeto JSON em {path}")
    criteria = _require(payload, "success_criteria", path)
    return Goal(
        title=_text(_require(payload, "title", path), "title", path),
        statement=_text(_require(payload, "statement", path), "statement", path),
        success_criteria=_as_tuple(criteria, "success_criteria", path),
    )


def load_skills(path: Path) -> dict[str, Skill]:
    payload = _read_json(path)
    if not isinstance(payload, list):
        raise CatalogError(f"Skills devem ser uma lista JSON em {path}")
    skills: dict[str, Skill] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise CatalogError(f"Cada skill deve ser um objeto JSON em {path}")
        skill_id = _text(_require(item, "id", path), "id", path)
        skills[skill_id] = Skill(
            id=skill_id,
            name=_text(_require(item, "name", path), "name", path),
            category=_text(_require(item, "category", path), "category", path),
            future=bool(item.get("future", False)),
        )
    return skills


def _hint_text(item: Any, path: Path) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        if item.get("type") == "reference":
            reference = item.get("path", "reference_solution.py")
            return f"Solução de referência: {reference}"
        text = item.get("text")
        if isinstance(text, str):
            return text
    raise CatalogError(f"Pista inválida em {path}")


def _load_hints(mission_dir: Path) -> tuple[str, ...]:
    hints_path = mission_dir / "hints.json"
    payload = _read_json(hints_path)
    if not isinstance(payload, list):
        raise CatalogError(f"hints.json deve ser uma lista em {hints_path}")
    return tuple(_hint_text(item, hints_path) for item in payload)


def _load_mission(mission_path: Path) -> Mission:
    payload = _read_json(mission_path)
    if not isinstance(payload, dict):
        raise CatalogError(f"Missão deve ser um objeto JSON em {mission_path}")
    mission_dir = mission_path.parent
    folder_slug = mission_dir.name.split("-", 1)[1] if "-" in mission_dir.name else mission_dir.name
    tests = _text(_require(payload, "tests", mission_path), "tests", mission_path)
    solution = _text(_require(payload, "solution", mission_path), "solution", mission_path)
    return Mission(
        id=_text(_require(payload, "id", mission_path), "id", mission_path),
        slug=_text(payload.get("slug", folder_slug), "slug", mission_path),
        title=_text(_require(payload, "title", mission_path), "title", mission_path),
        summary=_text(_require(payload, "summary", mission_path), "summary", mission_path),
        skills=_as_tuple(_require(payload, "skills", mission_path), "skills", mission_path),
        prerequisites=_as_tuple(payload.get("prerequisites", []), "prerequisites", mission_path),
        test_path=(mission_dir / tests).resolve(),
        solution_path=(mission_dir / solution).resolve(),
        hints=_load_hints(mission_dir),
    )


def load_missions(root: Path) -> list[Mission]:
    root = Path(root)
    if not root.exists():
        raise CatalogError(f"Diretório de missões não encontrado: {root}")
    if not root.is_dir():
        raise CatalogError(f"Catálogo de missões não é um diretório: {root}")
    mission_files = sorted(root.glob("*/mission.json"))
    if not mission_files:
        raise CatalogError(f"Nenhuma missão encontrada em: {root}")
    missions = [_load_mission(path) for path in mission_files]
    missions.sort(key=lambda mission: mission.id)
    ids = [mission.id for mission in missions]
    if len(ids) != len(set(ids)):
        duplicate = next(item for item in ids if ids.count(item) > 1)
        raise CatalogError(f"ID de missão duplicado no catálogo: {duplicate}")
    known_ids = set(ids)
    for mission in missions:
        missing = [item for item in mission.prerequisites if item not in known_ids]
        if missing:
            raise CatalogError(
                f"Missão {mission.id} referencia pré-requisito inexistente: {missing[0]}"
            )
    graph = {mission.id: set(mission.prerequisites) for mission in missions}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(mission_id: str) -> None:
        if mission_id in visiting:
            raise CatalogError(f"Ciclo de pré-requisitos detectado envolvendo: {mission_id}")
        if mission_id in visited:
            return
        visiting.add(mission_id)
        for prerequisite in graph[mission_id]:
            visit(prerequisite)
        visiting.remove(mission_id)
        visited.add(mission_id)

    for mission_id in graph:
        visit(mission_id)
    return missions
