from datetime import datetime, timezone

from python_lab.models import AppProgress, Mission, MissionProgress


PLAN_KEYS = ("input", "output", "steps", "risks")


class LearningError(Exception):
    pass


class CompletionError(LearningError):
    pass


class HintError(LearningError):
    pass


def _is_completed(progress: AppProgress, mission_id: str) -> bool:
    mission_progress = progress.missions.get(mission_id)
    return mission_progress is not None and mission_progress.status == "completed"


def _is_unlocked(mission: Mission, progress: AppProgress) -> bool:
    return all(_is_completed(progress, prerequisite) for prerequisite in mission.prerequisites)


def recommend_mission(missions: list[Mission], progress: AppProgress) -> Mission | None:
    by_id = {item.id: item for item in missions}
    current_id = progress.current_mission_id
    if current_id and current_id in by_id:
        current_progress = progress.missions.get(current_id)
        if current_progress is not None and current_progress.status == "started":
            return by_id[current_id]
    for item in missions:
        if _is_completed(progress, item.id):
            continue
        if _is_unlocked(item, progress):
            return item
    return None


def start_mission(mission: Mission, progress: AppProgress, missions: list[Mission]) -> MissionProgress:
    if not _is_unlocked(mission, progress):
        raise LearningError(f"Missão {mission.id} bloqueada: conclua os pré-requisitos primeiro")
    mission_progress = progress.missions.get(mission.id)
    if mission_progress is None:
        mission_progress = MissionProgress()
        progress.missions[mission.id] = mission_progress
    elif mission_progress.status == "completed":
        mission_progress.status = "started"
        mission_progress.plan = None
        mission_progress.tests_passed = False
        mission_progress.hints_revealed = 0
        mission_progress.reference_viewed = False
        mission_progress.explanation = None
        mission_progress.tested_solution_path = None
        mission_progress.tested_solution_fingerprint = None
    mission_progress.status = "started"
    progress.current_mission_id = mission.id
    return mission_progress


def reveal_hint(mission: Mission, progress: MissionProgress, confirm_reference: bool = False) -> str:
    if not mission.hints:
        raise HintError("Esta missão não possui pistas")
    if progress.hints_revealed >= len(mission.hints):
        return mission.hints[-1]
    next_index = progress.hints_revealed
    is_reference = next_index == len(mission.hints) - 1
    if is_reference and not confirm_reference:
            raise HintError("Confirmação necessária para consultar a solução de referência")
    progress.hints_revealed += 1
    if is_reference:
        progress.reference_viewed = True
    return mission.hints[next_index]


def plan_is_complete(plan: dict[str, str] | None) -> bool:
    if not plan:
        return False
    return all(key in plan and str(plan[key]).strip() for key in PLAN_KEYS)


def _skill_result(skill: str, mission_id: str, reference_viewed: bool, existing_evidence: list[dict[str, object]]) -> str:
    if reference_viewed:
        return "practicing"
    demonstrated_elsewhere = any(
        item.get("skill") == skill
        and item.get("mission") != mission_id
        and item.get("result") in {"demonstrated", "consolidated"}
        for item in existing_evidence
    )
    return "consolidated" if demonstrated_elsewhere else "demonstrated"


def complete_mission(
    mission: Mission,
    progress: MissionProgress,
    existing_evidence: list[dict[str, object]],
) -> list[dict[str, object]]:
    if not plan_is_complete(progress.plan):
        raise CompletionError("Conclusão rejeitada: planejamento incompleto")
    if not progress.tests_passed:
        raise CompletionError("Conclusão rejeitada: testes pendentes")
    if not progress.explanation or not progress.explanation.strip():
        raise CompletionError("Conclusão rejeitada: explicação pendente")
    timestamp = datetime.now(timezone.utc).isoformat()
    evidence = []
    for skill in mission.skills:
        evidence.append(
            {
                "skill": skill,
                "mission": mission.id,
                "result": _skill_result(skill, mission.id, progress.reference_viewed, existing_evidence),
                "help_level": progress.hints_revealed,
                "tests_passed": progress.tests_passed,
                "explanation": progress.explanation,
                "timestamp": timestamp,
            }
        )
    progress.status = "completed"
    return evidence
