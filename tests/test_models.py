from python_lab.models import MissionProgress


def test_new_mission_progress_starts_available():
    progress = MissionProgress()
    assert progress.status == "available"
    assert progress.attempts == 0
    assert progress.tests_passed is False
    assert progress.reference_viewed is False
    assert progress.tested_solution_path is None
    assert progress.tested_solution_fingerprint is None
