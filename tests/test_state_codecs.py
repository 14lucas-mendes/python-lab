import json

import pytest

from python_lab.models import AppProgress, MissionProgress
from python_lab.storage.codecs import decode_progress, decode_sessions
from python_lab.storage.errors import ProgressError, SessionError


def encoded(payload):
    return json.dumps(payload).encode("utf-8")


def valid_progress():
    return {
        "current_mission_id": "001",
        "missions": {"001": {"status": "started"}},
        "evidence": [],
    }


def valid_session():
    return {
        "id": "20260101T120000000000",
        "started_at": "2026-01-01T12:00:00+00:00",
        "ended_at": None,
        "events": [{"timestamp": "2026-01-01T12:00:01+00:00", "command": "/help", "summary": "ajuda"}],
    }


def test_seed_progress_preserves_defaults():
    actual = decode_progress(encoded({"current_mission_id": None, "missions": {}, "evidence": []}))
    assert actual == AppProgress()


def test_legacy_partial_attempt_preserves_defaults_and_content():
    payload = valid_progress()
    payload["missions"]["001"] = {
        "status": "started",
        "attempts": 2,
        "attempt_history": [{"passed": False, "summary": "1 falho"}],
    }
    actual = decode_progress(encoded(payload))
    assert actual.missions["001"] == MissionProgress(
        status="started",
        attempts=2,
        attempt_history=[{"passed": False, "summary": "1 falho"}],
    )


def test_full_attempt_and_evidence_are_preserved():
    attempt = {
        "timestamp": "2026-01-01T12:00:00+00:00",
        "passed": True,
        "return_code": 0,
        "summary": "ok",
        "solution_path": "/tmp/solution.py",
    }
    evidence = {
        "skill": "python",
        "mission": "001",
        "result": "demonstrated",
        "help_level": 0,
        "tests_passed": True,
        "explanation": "resolvido",
        "timestamp": "2026-01-01T12:00:00+00:00",
    }
    payload = valid_progress()
    payload["missions"]["001"]["attempt_history"] = [attempt]
    payload["evidence"] = [evidence]
    actual = decode_progress(encoded(payload))
    assert actual.missions["001"].attempt_history == [attempt]
    assert actual.evidence == [evidence]


def test_unknown_attempt_field_is_rejected():
    payload = valid_progress()
    payload["missions"]["001"]["attempt_history"] = [
        {"passed": True, "summary": "ok", "unexpected": {"broken": []}}
    ]
    with pytest.raises(ProgressError, match="attempt_history"):
        decode_progress(encoded(payload))


def test_evidence_cannot_reference_an_unknown_mission():
    payload = valid_progress()
    payload["evidence"] = [{
        "skill": "python", "mission": "missing", "result": "demonstrated",
        "help_level": 0, "tests_passed": True, "explanation": "ok", "timestamp": "now",
    }]
    with pytest.raises(ProgressError, match="evidence"):
        decode_progress(encoded(payload))


def test_unknown_evidence_field_is_rejected():
    payload = valid_progress()
    payload["evidence"] = [{
        "skill": "python", "mission": "001", "result": "demonstrated",
        "help_level": 0, "tests_passed": True, "explanation": "ok", "timestamp": "now",
        "unexpected": {"broken": []},
    }]
    with pytest.raises(ProgressError, match="evidence"):
        decode_progress(encoded(payload))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", [], "status"),
        ("status", "alien", "status"),
        ("attempts", True, "attempts"),
        ("hints_revealed", True, "hints_revealed"),
        ("tests_passed", 1, "tests_passed"),
        ("plan", {"input": 1}, "plan"),
        ("attempt_history", "bad", "attempt_history"),
        ("attempt_history", [{"passed": "no", "summary": "bad"}], "attempt_history"),
        ("attempt_history", [{"passed": True, "summary": 42}], "attempt_history"),
        ("attempt_history", [{"passed": True, "summary": "ok", "return_code": True}], "attempt_history"),
    ],
)
def test_invalid_mission_fields_are_domain_errors(field, value, message):
    payload = valid_progress()
    payload["missions"]["001"][field] = value
    with pytest.raises(ProgressError, match=message):
        decode_progress(encoded(payload))


@pytest.mark.parametrize(
    ("evidence", "message"),
    [
        ("bad", "evidence"),
        ([42], "evidence"),
        ([{"skill": "python"}], "evidence"),
        ([{"skill": 1, "mission": "001", "result": "demonstrated", "help_level": 0, "tests_passed": True, "explanation": "ok", "timestamp": "now"}], "evidence"),
        ([{"skill": "python", "mission": "001", "result": "unknown", "help_level": 0, "tests_passed": True, "explanation": "ok", "timestamp": "now"}], "evidence"),
    ],
)
def test_invalid_evidence_is_domain_error(evidence, message):
    payload = valid_progress()
    payload["evidence"] = evidence
    with pytest.raises(ProgressError, match=message):
        decode_progress(encoded(payload))


def test_unknown_active_mission_is_rejected():
    payload = valid_progress()
    payload["current_mission_id"] = "missing"
    with pytest.raises(ProgressError, match="missão atual"):
        decode_progress(encoded(payload))


def test_invalid_utf8_is_a_domain_error():
    with pytest.raises(ProgressError, match="UTF-8"):
        decode_progress(b"\xff")


def test_invalid_json_is_a_domain_error():
    with pytest.raises(ProgressError, match="JSON"):
        decode_progress(b"{")


def test_valid_sessions_decode_to_tuple():
    session = valid_session()
    assert decode_sessions(encoded({"sessions": [session]})) == (session,)


def test_unknown_event_field_is_rejected():
    session = valid_session()
    session["events"][0]["unexpected"] = {"broken": []}
    with pytest.raises(SessionError, match="event"):
        decode_sessions(encoded({"sessions": [session]}))


def test_session_requires_ended_at_field():
    session = valid_session()
    del session["ended_at"]
    with pytest.raises(SessionError, match="ended_at"):
        decode_sessions(encoded({"sessions": [session]}))


@pytest.mark.parametrize(
    ("sessions", "message"),
    [
        ("bad", "sessions"),
        ([42], "session"),
        ([{"id": "a", "started_at": "now", "ended_at": None, "events": "bad"}], "events"),
        ([{"id": "a", "started_at": "now", "ended_at": None, "events": [42]}], "event"),
        ([{"id": "a", "started_at": "now", "ended_at": None, "events": [{"timestamp": "now", "command": 3, "summary": "ok"}]}], "event"),
    ],
)
def test_invalid_session_shape_is_domain_error(sessions, message):
    with pytest.raises(SessionError, match=message):
        decode_sessions(encoded({"sessions": sessions}))


def test_invalid_session_utf8_and_json_are_domain_errors():
    with pytest.raises(SessionError, match="UTF-8"):
        decode_sessions(b"\xff")
    with pytest.raises(SessionError, match="JSON"):
        decode_sessions(b"{")
