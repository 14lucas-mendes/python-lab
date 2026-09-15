from pathlib import Path

import pytest

from python_lab.catalog import CatalogError, load_goal, load_missions


FIXTURES = Path(__file__).parent / "fixtures" / "catalog"


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


def test_load_missions_orders_by_id():
    missions = load_missions(FIXTURES / "missions")
    assert [mission.id for mission in missions] == ["001"]
