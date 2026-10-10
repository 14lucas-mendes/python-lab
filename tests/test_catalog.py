import json
from pathlib import Path

import pytest

from python_lab.catalog import CatalogError, load_goal, load_missions, load_roadmap, load_skills
from python_lab.learning import recommend_mission
from python_lab.models import AppProgress, Mission, MissionProgress


FIXTURES = Path(__file__).parent / "fixtures" / "catalog"
ROOT = Path(__file__).resolve().parent.parent


def _write_mission(folder: Path, mission_id: str, **fields) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "hints.json").write_text('["hint"]', encoding="utf-8")
    payload = {
        "id": mission_id,
        "title": "M",
        "summary": "S",
        "skills": ["f"],
        "tests": "tests",
        "solution": "starter.py",
        "cycle": 1,
        "lesson_id": "lesson_01-python-core",
    }
    payload.update(fields)
    (folder / "mission.json").write_text(json.dumps(payload), encoding="utf-8")


def _roadmap_items() -> list[dict]:
    return [
        {
            "cycle": number,
            "title": f"Ciclo {number}",
            "lesson_id": f"lesson_{number:02d}",
            "milestone": f"marco {number}",
            "status": "playable" if number <= 5 else "planned",
        }
        for number in range(1, 14)
    ]


def _write_roadmap(path: Path, items: list[dict] | None = None) -> Path:
    path.write_text(json.dumps(items if items is not None else _roadmap_items()), encoding="utf-8")
    return path


def test_load_goal_returns_typed_goal(tmp_path):
    path = tmp_path / "goal.json"
    path.write_text(
        '{"title":"Python","statement":"Aprender","success_criteria":["Resolver"]}',
        encoding="utf-8",
    )
    goal = load_goal(path)
    assert goal.title == "Python"
    assert goal.success_criteria == ("Resolver",)


def test_invalid_goal_raises_actionable_error(tmp_path):
    path = tmp_path / "goal.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(CatalogError, match="JSON inválido"):
        load_goal(path)


def test_load_missions_reads_cycle_and_lesson_id():
    missions = load_missions(FIXTURES / "missions")
    assert missions[0].cycle == 1
    assert missions[0].lesson_id == "lesson_01-python-core"


def test_load_missions_orders_by_cycle_then_id(tmp_path):
    root = tmp_path / "missions"
    _write_mission(root / "002-second", "002", cycle=1)
    _write_mission(root / "001-first", "001", cycle=2, lesson_id="lesson_03-testes-git")
    assert [mission.id for mission in load_missions(root)] == ["002", "001"]


def test_real_catalog_follows_formation_cycle_order():
    missions = load_missions(ROOT / "missions")
    assert [mission.id for mission in missions] == [
        "001",
        "006",
        "004",
        "007",
        "008",
        "009",
        "002",
        "003",
        "005",
        "010",
        "011",
    ]
    by_id = {mission.id: mission for mission in missions}
    assert by_id["001"].cycle == 1
    assert by_id["006"].lesson_id == "lesson_01-python-core"
    assert by_id["004"].prerequisites == ("001",)
    assert by_id["002"].prerequisites == ("009",)
    assert by_id["010"].cycle == 5
    progress = AppProgress(missions={"001": MissionProgress(status="completed")})
    assert recommend_mission(missions, progress).id == "006"


def test_catalog_requires_cycle_and_lesson_id(tmp_path):
    folder = tmp_path / "missions" / "001-one"
    _write_mission(folder, "001")
    payload = json.loads((folder / "mission.json").read_text(encoding="utf-8"))
    del payload["cycle"]
    (folder / "mission.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CatalogError, match="cycle"):
        load_missions(tmp_path / "missions")


def test_catalog_rejects_cycle_outside_range(tmp_path):
    folder = tmp_path / "missions" / "001-one"
    _write_mission(folder, "001", cycle=14)
    with pytest.raises(CatalogError, match="cycle"):
        load_missions(tmp_path / "missions")


def test_catalog_rejects_boolean_cycle(tmp_path):
    folder = tmp_path / "missions" / "001-one"
    _write_mission(folder, "001", cycle=True)
    with pytest.raises(CatalogError, match="cycle"):
        load_missions(tmp_path / "missions")


def test_missing_missions_directory_raises_actionable_error(tmp_path):
    with pytest.raises(CatalogError, match="Diretório de missões não encontrado"):
        load_missions(tmp_path / "missing")


def test_empty_missions_directory_raises_actionable_error(tmp_path):
    missions = tmp_path / "missions"
    missions.mkdir()
    with pytest.raises(CatalogError, match="Nenhuma missão encontrada"):
        load_missions(missions)


def test_catalog_reports_invalid_encoding(tmp_path):
    path = tmp_path / "goal.json"
    path.write_bytes(b"{\xff")
    with pytest.raises(CatalogError, match="UTF-8"):
        load_goal(path)


def test_catalog_rejects_duplicate_mission_ids(tmp_path):
    missions = tmp_path / "missions"
    for slug in ("001-first", "002-second"):
        _write_mission(missions / slug, "001")
    with pytest.raises(CatalogError, match="ID de missão duplicado"):
        load_missions(missions)


def test_catalog_rejects_unknown_prerequisite(tmp_path):
    _write_mission(
        tmp_path / "missions" / "001-one",
        "001",
        prerequisites=["999"],
    )
    with pytest.raises(CatalogError, match="pré-requisito inexistente"):
        load_missions(tmp_path / "missions")


def test_catalog_rejects_prerequisite_cycle(tmp_path):
    missions = tmp_path / "missions"
    _write_mission(missions / "001-mission", "001", prerequisites=["002"])
    _write_mission(missions / "002-mission", "002", prerequisites=["001"])
    with pytest.raises(CatalogError, match="Ciclo de pré-requisitos"):
        load_missions(missions)


def test_load_roadmap_validates_cycles_and_catalog():
    missions = load_missions(ROOT / "missions")
    roadmap = load_roadmap(ROOT / "data" / "roadmap.json", missions)
    assert [item.cycle for item in roadmap] == list(range(1, 14))
    assert roadmap[0].status == "playable"
    assert roadmap[5].status == "planned"
    assert roadmap[0].lesson_id == "lesson_01-python-core"


def test_roadmap_rejects_duplicate_cycle(tmp_path):
    items = _roadmap_items()
    items[1]["cycle"] = 1
    path = _write_roadmap(tmp_path / "roadmap.json", items)
    with pytest.raises(CatalogError, match="duplicado"):
        load_roadmap(path)


def test_roadmap_rejects_missing_cycle(tmp_path):
    items = [item for item in _roadmap_items() if item["cycle"] != 13]
    path = _write_roadmap(tmp_path / "roadmap.json", items)
    with pytest.raises(CatalogError, match="1 a 13"):
        load_roadmap(path)


def test_roadmap_rejects_mission_with_unknown_cycle(tmp_path):
    path = _write_roadmap(tmp_path / "roadmap.json")
    orphan = Mission(
        "099",
        "orphan",
        "Orphan",
        "S",
        ("functions",),
        (),
        tmp_path / "tests",
        tmp_path / "starter.py",
        ("hint",),
        99,
        "lesson_99",
    )
    with pytest.raises(CatalogError, match="ciclo inexistente"):
        load_roadmap(path, [orphan])


def test_duplicate_skill_is_rejected(tmp_path):
    path = tmp_path / "skills.json"
    row = {"id": "x", "name": "X", "category": "core", "future": False}
    path.write_text(json.dumps([row, row]), encoding="utf-8")
    with pytest.raises(CatalogError, match="duplicad"):
        load_skills(path)


@pytest.mark.parametrize("future", ["false", 0, None])
def test_skill_future_requires_boolean(tmp_path, future):
    path = tmp_path / "skills.json"
    path.write_text(json.dumps([{"id": "x", "name": "X", "category": "core", "future": future}]), encoding="utf-8")
    with pytest.raises(CatalogError, match="future"):
        load_skills(path)


def test_unknown_mission_skill_is_rejected_before_loading_state(app):
    from python_lab.app import PythonLabApp
    from python_lab.progress import ProgressRepository

    repository = ProgressRepository(app.repository.path.parent / "uninitialized.sqlite3")
    with pytest.raises(CatalogError, match="skill.*inexistente"):
        PythonLabApp(app.goal, {}, app.missions, repository, app.project_root)
    assert not repository.path.exists()
