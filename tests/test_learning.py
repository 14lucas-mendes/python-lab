from pathlib import Path

import pytest

from python_lab.learning import (
    CompletionError,
    HintError,
    LearningError,
    complete_mission,
    recommend_mission,
    reveal_hint,
    start_mission,
)
from python_lab.models import AppProgress, Mission, MissionProgress


def mission(mid="001", prerequisites=(), skills=("debugging",), hints=("Pergunta", "Pista")):
    return Mission(
        mid,
        "example",
        "Example",
        "Summary",
        skills,
        prerequisites,
        Path("tests"),
        Path("solution.py"),
        hints,
    )


def test_recommend_started_mission_before_next_available():
    progress = AppProgress(
        current_mission_id="002",
        missions={"002": MissionProgress(status="started")},
    )
    assert recommend_mission([mission("001"), mission("002")], progress).id == "002"


def test_completion_requires_plan_tests_and_explanation():
    progress = MissionProgress(status="started", tests_passed=True)
    with pytest.raises(CompletionError, match="planejamento"):
        complete_mission(mission(), progress, [])


def test_reference_solution_prevents_demonstrated_evidence():
    progress = MissionProgress(
        status="started",
        plan={"input": "dados", "output": "relatório", "steps": "validar", "risks": "vazio"},
        tests_passed=True,
        reference_viewed=True,
        explanation="Usei validação antes do cálculo.",
    )
    evidence = complete_mission(mission(), progress, [])
    assert evidence[0]["result"] == "practicing"


def test_second_demonstration_consolidates_skill():
    progress = MissionProgress(
        status="started",
        plan={"input": "dados", "output": "relatório", "steps": "validar", "risks": "vazio"},
        tests_passed=True,
        explanation="Apliquei a mesma técnica em outro contexto.",
    )
    previous = [{"skill": "debugging", "mission": "001", "result": "demonstrated"}]
    evidence = complete_mission(mission("002"), progress, previous)
    assert evidence[0]["result"] == "consolidated"


def test_reveal_hint_requires_confirmation_for_reference():
    progress = MissionProgress(status="started", attempts=1, hints_revealed=1)
    with pytest.raises(HintError, match="(?i)confirma"):
        reveal_hint(mission(), progress, confirm_reference=False)
    hint = reveal_hint(mission(), progress, confirm_reference=True)
    assert hint == "Pista"
    assert progress.reference_viewed is True
    assert progress.hints_revealed == 2


def test_start_blocked_mission_is_rejected():
    progress = AppProgress()
    with pytest.raises(LearningError, match="bloqueada"):
        start_mission(mission("002", prerequisites=("001",)), progress, [mission("001"), mission("002")])


def test_completed_mission_can_be_started_again_without_erasing_evidence():
    progress = AppProgress(
        missions={"001": MissionProgress(status="completed", attempts=3, explanation="old")},
        evidence=[{"skill": "debugging", "mission": "001", "result": "demonstrated"}],
    )

    started = start_mission(mission(), progress, [mission()])

    assert started.status == "started"
    assert started.attempts == 3
    assert started.plan is None
    assert started.tests_passed is False
    assert started.explanation is None
    assert progress.evidence == [
        {"skill": "debugging", "mission": "001", "result": "demonstrated"}
    ]


@pytest.mark.parametrize('maximum, reference', [(4, False), (0, True), (4, True)])
def test_assisted_completion_evidence_is_practicing(maximum, reference):
    progress = MissionProgress(plan={key: 'ok' for key in ('input', 'output', 'steps', 'risks')},
                               tests_passed=True, explanation='Verifiquei o contrato',
                               max_assistance_level=maximum, reference_viewed=reference)
    evidence = complete_mission(mission(), progress, [])
    assert evidence[0]['result'] == 'practicing'
    assert evidence[0]['assistance_level'] == (4 if reference else maximum)
    assert evidence[0]['origin'] == 'mission_completion'


def test_restart_resets_assistance_and_identity_preserving_evidence():
    previous = {'skill': 'debugging', 'mission': '001', 'result': 'practicing', 'assistance_level': 4}
    old = MissionProgress(status='completed', max_assistance_level=4, reference_viewed=True)
    old_identity = old.attempt_id
    progress = AppProgress(missions={'001': old}, evidence=[previous.copy()])
    restarted = start_mission(mission(), progress, [mission()])
    assert restarted.max_assistance_level == 0
    assert not restarted.reference_viewed
    assert restarted.attempt_id != old_identity
    identity = restarted.attempt_id
    assert start_mission(mission(), progress, [mission()]).attempt_id == identity
    assert progress.evidence == [previous]
