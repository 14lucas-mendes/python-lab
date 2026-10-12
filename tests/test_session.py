from python_lab.session import MAX_EVENTS, MAX_SESSIONS, SessionError, SessionLog


def test_session_round_trip(tmp_path):
    path = tmp_path / "lab.sqlite3"
    log = SessionLog(path)
    log.start()
    log.record("/start 001", "Missão 001 iniciada")
    log.close("Sessão encerrada")

    reloaded = SessionLog(path)
    sessions = reloaded.load()
    assert len(sessions) == 1
    events = sessions[0]["events"]
    assert events[0]["command"] == "/start 001"
    assert events[0]["summary"] == "Missão 001 iniciada"
    assert events[-1]["summary"] == "Sessão encerrada"
    assert sessions[0]["ended_at"]


def test_invalid_session_file_is_not_overwritten(tmp_path):
    path = tmp_path / "lab.sqlite3"
    path.write_text("{invalid", encoding="utf-8")
    log = SessionLog(path)
    try:
        log.start()
    except SessionError as exc:
        assert "inválido" in str(exc).lower() or "corrompido" in str(exc).lower()
    else:
        raise AssertionError("esperava SessionError")
    assert path.read_text(encoding="utf-8") == "{invalid"


def test_session_caps_events_and_history(tmp_path):
    path = tmp_path / "lab.sqlite3"
    log = SessionLog(path)
    log.start()
    for index in range(MAX_EVENTS + 5):
        log.record("/status", f"evento {index}")
    assert len(log.current_events()) == MAX_EVENTS
    assert log.current_events()[0]["summary"] == "evento 5"
    log.close()

    for _ in range(MAX_SESSIONS + 3):
        extra = SessionLog(path)
        extra.start()
        extra.record("/help", "ajuda")
        extra.close()

    stored = SessionLog(path).load()
    assert len(stored) == MAX_SESSIONS
