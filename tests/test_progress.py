import pytest

from python_lab.models import AppProgress, MissionProgress
from python_lab.progress import ProgressError, ProgressRepository


def test_progress_round_trip(tmp_path):
    path = tmp_path / "progress.json"
    repository = ProgressRepository(path)
    expected = AppProgress(
        current_mission_id="001",
        missions={"001": MissionProgress(status="started", attempts=2)},
    )
    repository.save(expected)
    actual = repository.load()
    assert actual.current_mission_id == "001"
    assert actual.missions["001"].attempts == 2


def test_invalid_progress_is_not_overwritten(tmp_path):
    path = tmp_path / "progress.json"
    path.write_text("{invalid", encoding="utf-8")
    repository = ProgressRepository(path)
    with pytest.raises(ProgressError, match="Progresso inválido"):
        repository.load()
    assert path.read_text(encoding="utf-8") == "{invalid"
