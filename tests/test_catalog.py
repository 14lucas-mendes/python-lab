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
        folder = missions / slug
        folder.mkdir(parents=True)
        (folder / "hints.json").write_text("[\"hint\"]", encoding="utf-8")
        (folder / "mission.json").write_text(
            '{"id":"001","title":"M","summary":"S","skills":["f"],'
            '"tests":"tests","solution":"starter.py"}',
            encoding="utf-8",
        )
    with pytest.raises(CatalogError, match="ID de missão duplicado"):
        load_missions(missions)


def test_catalog_rejects_unknown_prerequisite(tmp_path):
    missions = tmp_path / "missions" / "001-one"
    missions.mkdir(parents=True)
    (missions / "hints.json").write_text("[\"hint\"]", encoding="utf-8")
    (missions / "mission.json").write_text(
        '{"id":"001","title":"M","summary":"S","skills":["f"],'
        '"prerequisites":["999"],"tests":"tests","solution":"starter.py"}',
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="pré-requisito inexistente"):
        load_missions(tmp_path / "missions")


def test_catalog_rejects_prerequisite_cycle(tmp_path):
    missions = tmp_path / "missions"
    for mission_id, prerequisite in (("001", "002"), ("002", "001")):
        folder = missions / f"{mission_id}-mission"
        folder.mkdir(parents=True)
        (folder / "hints.json").write_text("[\"hint\"]", encoding="utf-8")
        (folder / "mission.json").write_text(
            '{"id":"%s","title":"M","summary":"S","skills":["f"],'
            '"prerequisites":["%s"],"tests":"tests","solution":"starter.py"}'
            % (mission_id, prerequisite),
            encoding="utf-8",
        )
    with pytest.raises(CatalogError, match="Ciclo de pré-requisitos"):
        load_missions(missions)
