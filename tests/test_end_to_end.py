from pathlib import Path
from shutil import copyfile, copytree

import pytest

from python_lab.app import ApplicationError, PythonLabApp
from python_lab.catalog import load_goal, load_missions, load_skills
from python_lab.learning import CompletionError
from python_lab.progress import ProgressRepository
from python_lab.progress import ProgressError


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def test_app(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    copyfile(ROOT / "data" / "goal.json", data_dir / "goal.json")
    copyfile(ROOT / "data" / "skills.json", data_dir / "skills.json")
    copytree(ROOT / "missions" / "001-consolidar-falhas", tmp_path / "missions" / "001-consolidar-falhas")
    repository = ProgressRepository(tmp_path / "lab.sqlite3")
    return PythonLabApp(
        goal=load_goal(data_dir / "goal.json"),
        skills=load_skills(data_dir / "skills.json"),
        missions=load_missions(tmp_path / "missions"),
        repository=repository,
        project_root=tmp_path,
    )


@pytest.fixture
def solved_mission_001():
    return ROOT / "missions" / "001-consolidar-falhas" / "reference_solution.py"


def test_complete_first_mission_updates_progress(test_app, solved_mission_001):
    test_app.start("001")
    test_app.save_plan(
        {
            "input": "registros",
            "output": "totais",
            "steps": "acumular e comparar",
            "risks": "lista vazia",
        }
    )
    result = test_app.run_current_tests(solution_path=solved_mission_001)
    assert result.passed
    assert test_app.current_progress().attempt_history[-1]["passed"] is True
    assert test_app.current_progress().attempt_history[-1]["summary"]
    test_app.save_explanation("Usei um dicionário para acumular minutos por equipamento.")
    test_app.complete_current_mission()
    reloaded = test_app.repository.load()
    assert reloaded.missions["001"].status == "completed"
    assert any(item["skill"] == "collections" for item in reloaded.evidence)


def test_completion_rejected_without_explanation(test_app, solved_mission_001):
    test_app.start("001")
    test_app.save_plan(
        {
            "input": "registros",
            "output": "totais",
            "steps": "acumular e comparar",
            "risks": "lista vazia",
        }
    )
    test_app.run_current_tests(solution_path=solved_mission_001)
    with pytest.raises(CompletionError, match="explicação"):
        test_app.complete_current_mission()


def test_empty_explanation_is_rejected(test_app):
    test_app.start("001")
    with pytest.raises(ApplicationError, match="vazia"):
        test_app.save_explanation("   ")


def test_completion_rejected_when_tested_solution_changes(test_app, tmp_path, solved_mission_001):
    test_app.start("001")
    test_app.save_plan(
        {
            "input": "registros",
            "output": "totais",
            "steps": "acumular e comparar",
            "risks": "lista vazia",
        }
    )
    solution = tmp_path / "solution.py"
    solution.write_bytes(solved_mission_001.read_bytes())
    assert test_app.run_current_tests(solution_path=solution).passed
    test_app.save_explanation("A solução foi validada antes da alteração.")
    solution.write_text("def consolidar_falhas(:\n", encoding="utf-8")

    with pytest.raises(CompletionError, match="novamente"):
        test_app.complete_current_mission()


def test_retry_completed_mission_preserves_previous_evidence(test_app, solved_mission_001):
    test_app.start("001")
    test_app.save_plan(
        {
            "input": "registros",
            "output": "totais",
            "steps": "acumular e comparar",
            "risks": "lista vazia",
        }
    )
    assert test_app.run_current_tests(solution_path=solved_mission_001).passed
    test_app.save_explanation("Primeira tentativa concluída.")
    test_app.complete_current_mission()
    previous_evidence = list(test_app.progress.evidence)

    test_app.start("001")

    assert test_app.current_progress().status == "started"
    assert test_app.current_progress().tests_passed is False
    assert test_app.progress.evidence == previous_evidence


def test_app_rolls_back_memory_when_progress_save_fails(test_app, monkeypatch):
    test_app.start("001")
    before = test_app.repository.load()
    monkeypatch.setattr(
        test_app.repository,
        "save",
        lambda progress: (_ for _ in ()).throw(ProgressError("falha de disco")),
    )

    with pytest.raises(ProgressError, match="falha de disco"):
        test_app.save_plan({"input": "x", "output": "y", "steps": "z", "risks": "w"})

    assert test_app.progress == before
