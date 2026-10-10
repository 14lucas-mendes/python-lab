from pathlib import Path
from shutil import copytree, copyfile

import pytest

from python_lab.app import PythonLabApp
from python_lab.catalog import load_goal, load_missions, load_roadmap, load_skills
from python_lab.progress import ProgressRepository


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "catalog"


@pytest.fixture
def app(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    copyfile(ROOT / "data" / "goal.json", data_dir / "goal.json")
    copyfile(ROOT / "data" / "skills.json", data_dir / "skills.json")
    copyfile(ROOT / "data" / "roadmap.json", data_dir / "roadmap.json")
    missions_root = tmp_path / "missions"
    copytree(FIXTURES / "missions", missions_root)
    repository = ProgressRepository(tmp_path / "lab.sqlite3")
    repository.save(repository.load())
    missions = load_missions(missions_root)
    return PythonLabApp(
        goal=load_goal(data_dir / "goal.json"),
        skills=load_skills(data_dir / "skills.json"),
        missions=missions,
        repository=repository,
        project_root=tmp_path,
        roadmap=load_roadmap(data_dir / "roadmap.json", missions),
    )
