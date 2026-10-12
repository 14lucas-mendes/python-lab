"""Deterministic practice suggestions from recorded progress, without writes."""

from dataclasses import dataclass

from python_lab.learning import _is_completed, _is_unlocked
from python_lab.models import AppProgress, Mission, MissionProgress


@dataclass(frozen=True)
class LearningRecommendation:
    mission_id: str
    reason: str
    skills: tuple[str, ...]


def _recorded_counts(state: MissionProgress | None) -> str:
    attempts = state.attempts if state is not None else 0
    hints = state.hints_revealed if state is not None else 0
    return f"{attempts} tentativa(s) e {hints} pista(s) registradas."


def _practice_order(mission: Mission, progress: AppProgress) -> tuple[int, int, int, int, str]:
    state = progress.missions.get(mission.id)
    active = (mission.id == progress.current_mission_id
              and state is not None and state.status == "started")
    return (
        0 if active else 1,
        -state.attempts if state is not None else 0,
        -state.hints_revealed if state is not None else 0,
        mission.cycle,
        mission.id,
    )


def recommend_practice(missions: list[Mission], progress: AppProgress) -> tuple[LearningRecommendation, ...]:
    """Prioritize active, unlocked practice, then recorded attempts and hints.

    Counts describe activity only; neither passing tests nor missing records
    imply a level of mastery or a diagnosis of difficulty.
    """
    eligible = [mission for mission in missions
                if not _is_completed(progress, mission.id) and _is_unlocked(mission, progress)]
    items = []
    for mission in sorted(eligible, key=lambda item: _practice_order(item, progress)):
        state = progress.missions.get(mission.id)
        if mission.id == progress.current_mission_id and state is not None and state.status == "started":
            reason = "Continue a missão em andamento: " + _recorded_counts(state)
        elif state is not None and (state.attempts or state.hints_revealed):
            reason = "Prática sugerida: " + _recorded_counts(state)
        else:
            reason = "Missão desbloqueada, sem tentativas ou pistas registradas."
        items.append(LearningRecommendation(mission.id, reason, mission.skills))
    return tuple(items)


def review_completed(missions: list[Mission], progress: AppProgress) -> tuple[LearningRecommendation, ...]:
    """Return a separate optional review list without restarting any mission."""
    completed = [mission for mission in missions if _is_completed(progress, mission.id)]
    return tuple(
        LearningRecommendation(
            mission.id,
            "Revisão opcional de missão concluída: " + _recorded_counts(progress.missions[mission.id]),
            mission.skills,
        )
        for mission in sorted(completed, key=lambda item: _practice_order(item, progress))
    )
