import pytest

from python_lab.models import AppProgress, MissionProgress
from python_lab.progress import ProgressError, ProgressRepository


def test_progress_round_trip(tmp_path):
    path = tmp_path / "progress.json"
    repository = ProgressRepository(path)
    expected = AppProgress(
        current_mission_id="001",
        missions={
            "001": MissionProgress(
                status="started",
                attempts=2,
                tested_solution_path="solution.py",
                tested_solution_fingerprint="abc123",
                attempt_history=[{"passed": False, "summary": "1 falho"}],
            )
        },
    )
    repository.save(expected)
    actual = repository.load()
    assert actual.current_mission_id == "001"
    assert actual.missions["001"].attempts == 2
    assert actual.missions["001"].tested_solution_path == "solution.py"
    assert actual.missions["001"].tested_solution_fingerprint == "abc123"
    assert actual.missions["001"].attempt_history == [{"passed": False, "summary": "1 falho"}]


def test_invalid_progress_is_not_overwritten(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text("{invalid", encoding="utf-8")
    repository = ProgressRepository(path)
    with pytest.raises(ProgressError, match="Progresso inválido"):
        repository.load()
    assert path.read_text(encoding="utf-8") == "{invalid"


@pytest.mark.parametrize(
    "payload",
    [
        '{"missions": []}',
        '{"missions": {"001": {"attempts": "abc"}}}',
        '{"missions": {"001": {"plan": "not-an-object"}}}',
        '{"current_mission_id": 1}',
        '{"evidence": "not-a-list"}',
    ],
)
def test_invalid_progress_schema_is_rejected(tmp_path, payload):
    path = tmp_path / "progress.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(ProgressError, match="Progresso inválido"):
        ProgressRepository(path).load()


def test_concurrent_repository_save_is_rejected_without_overwriting(tmp_path):
    path = tmp_path / "progress.json"
    first = ProgressRepository(path)
    second = ProgressRepository(path)
    first_progress = first.load()
    second_progress = second.load()

    first_progress.current_mission_id = "001"
    first_progress.missions["001"] = MissionProgress(status="started")
    first.save(first_progress)
    second_progress.current_mission_id = "002"
    second_progress.missions["002"] = MissionProgress(status="started")

    with pytest.raises(ProgressError, match="(?i)conflito"):
        second.save(second_progress)

    assert ProgressRepository(path).load().current_mission_id == "001"
