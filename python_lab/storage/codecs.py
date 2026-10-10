"""Strict readers for the JSON state written by the original repositories."""

import json

from python_lab.models import AppProgress, MissionProgress
from python_lab.storage.errors import ProgressError, SessionError


def _json_object(raw: bytes, error_type: type[Exception], label: str) -> dict:
    try:
        text = raw.decode("utf-8")
    except (AttributeError, UnicodeDecodeError) as exc:
        raise error_type(f"{label} inválido: codificação UTF-8 inválida") from exc
    try:
        payload = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise error_type(f"{label} inválido: JSON corrompido") from exc
    if not isinstance(payload, dict):
        raise error_type(f"{label} inválido: formato inesperado")
    return payload


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _attempt_valid(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    if item.keys() - {"passed", "summary", "timestamp", "return_code", "solution_path"}:
        return False
    if not isinstance(item.get("passed"), bool) or not isinstance(item.get("summary"), str):
        return False
    optional_text = ("timestamp", "solution_path")
    if any(key in item and not isinstance(item[key], str) for key in optional_text):
        return False
    if "return_code" in item and type(item["return_code"]) is not int:
        return False
    return True


def _evidence_valid(item: object, missions: dict[str, MissionProgress]) -> bool:
    if not isinstance(item, dict):
        return False
    if item.keys() - {
        "skill", "mission", "result", "help_level", "tests_passed", "explanation", "timestamp"
    }:
        return False
    if any(not isinstance(item.get(key), str) for key in ("skill", "mission", "explanation", "timestamp")):
        return False
    if item.get("mission") not in missions:
        return False
    if item.get("result") not in ("practicing", "demonstrated", "consolidated"):
        return False
    if not _nonnegative_int(item.get("help_level")):
        return False
    if not isinstance(item.get("tests_passed"), bool):
        return False
    return True


def _mission(raw: object, mission_id: str) -> MissionProgress:
    if not isinstance(raw, dict):
        raise ProgressError(f"Progresso inválido: dados da missão {mission_id} malformados")
    try:
        mission = MissionProgress(**raw)
    except (TypeError, ValueError) as exc:
        raise ProgressError(f"Progresso inválido: dados da missão {mission_id} malformados") from exc
    if not isinstance(mission.status, str) or mission.status not in ("available", "started", "completed"):
        raise ProgressError(f"Progresso inválido: missão {mission_id} status inválido")
    for key in ("attempts", "hints_revealed"):
        if not _nonnegative_int(getattr(mission, key)):
            raise ProgressError(f"Progresso inválido: missão {mission_id} {key} inválido")
    for key in ("tests_passed", "reference_viewed"):
        if not isinstance(getattr(mission, key), bool):
            raise ProgressError(f"Progresso inválido: missão {mission_id} {key} inválido")
    for key in ("explanation", "tested_solution_path", "tested_solution_fingerprint"):
        value = getattr(mission, key)
        if value is not None and not isinstance(value, str):
            raise ProgressError(f"Progresso inválido: missão {mission_id} {key} inválido")
    if mission.plan is not None and (
        not isinstance(mission.plan, dict)
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in mission.plan.items())
    ):
        raise ProgressError(f"Progresso inválido: missão {mission_id} plan inválido")
    if not isinstance(mission.attempt_history, list):
        raise ProgressError(f"Progresso inválido: missão {mission_id} attempt_history inválido")
    for index, attempt in enumerate(mission.attempt_history):
        if not _attempt_valid(attempt):
            raise ProgressError(
                f"Progresso inválido: missão {mission_id} attempt_history[{index}] inválido"
            )
    return mission


def decode_progress(raw: bytes) -> AppProgress:
    """Decode legacy progress without replacing unknown or corrupt state with a seed."""
    payload = _json_object(raw, ProgressError, "Progresso")
    current_id = payload.get("current_mission_id")
    if current_id is not None and not isinstance(current_id, str):
        raise ProgressError("Progresso inválido: current_mission_id deve ser texto ou nulo")
    raw_missions = payload.get("missions", {})
    if not isinstance(raw_missions, dict):
        raise ProgressError("Progresso inválido: missions deve ser um objeto")
    missions = {}
    for mission_id, item in raw_missions.items():
        if not isinstance(mission_id, str):
            raise ProgressError("Progresso inválido: identificador de missão malformado")
        missions[mission_id] = _mission(item, mission_id)
    if current_id is not None and current_id not in missions:
        raise ProgressError("Progresso inválido: missão atual não encontrada")
    evidence = payload.get("evidence", [])
    if not isinstance(evidence, list):
        raise ProgressError("Progresso inválido: evidence deve ser uma lista de objetos")
    for index, item in enumerate(evidence):
        if not _evidence_valid(item, missions):
            raise ProgressError(f"Progresso inválido: evidence[{index}] malformada")
    return AppProgress(current_mission_id=current_id, missions=missions, evidence=list(evidence))


def _event_valid(item: object) -> bool:
    return isinstance(item, dict) and not (item.keys() - {"timestamp", "command", "summary"}) and all(
        isinstance(item.get(key), str) for key in ("timestamp", "command", "summary")
    )


def decode_sessions(raw: bytes) -> tuple[dict[str, object], ...]:
    """Decode legacy session history, preserving event order and data."""
    payload = _json_object(raw, SessionError, "Histórico de sessão")
    sessions = payload.get("sessions")
    if not isinstance(sessions, list):
        raise SessionError("Histórico de sessão inválido: sessions deve ser uma lista")
    for index, session in enumerate(sessions):
        if not isinstance(session, dict):
            raise SessionError(f"Histórico de sessão inválido: session[{index}] malformada")
        if not isinstance(session.get("id"), str) or not isinstance(session.get("started_at"), str):
            raise SessionError(f"Histórico de sessão inválido: session[{index}] id/started_at inválido")
        if "ended_at" not in session:
            raise SessionError(f"Histórico de sessão inválido: session[{index}] ended_at ausente")
        ended_at = session["ended_at"]
        if ended_at is not None and not isinstance(ended_at, str):
            raise SessionError(f"Histórico de sessão inválido: session[{index}] ended_at inválido")
        events = session.get("events")
        if not isinstance(events, list):
            raise SessionError(f"Histórico de sessão inválido: session[{index}] events inválidos")
        for event_index, event in enumerate(events):
            if not _event_valid(event):
                raise SessionError(
                    f"Histórico de sessão inválido: session[{index}] event[{event_index}] malformado"
                )
    return tuple(sessions)
