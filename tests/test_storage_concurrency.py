import multiprocessing as mp
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError

from python_lab.storage.migration import migrate_json_state
from python_lab.storage import database as database_module

from python_lab.models import MissionProgress
from python_lab.progress import ProgressError, ProgressRepository
from python_lab.session import MAX_EVENTS, MAX_SESSIONS, SessionLog


def _writer(path, ready, go, result, mission):
    repo = ProgressRepository(path)
    progress = repo.load()
    ready.put(True)
    go.wait()
    progress.missions[mission] = MissionProgress(status="started")
    progress.current_mission_id = mission
    try:
        repo.save(progress)
    except ProgressError:
        result.put("conflict")
    else:
        result.put("saved")


def test_simultaneous_progress_writers(tmp_path):
    path = tmp_path / "lab.sqlite3"
    ctx = mp.get_context("spawn")
    ready, result, go = ctx.Queue(), ctx.Queue(), ctx.Event()
    children = [ctx.Process(target=_writer, args=(path, ready, go, result, mission)) for mission in ("001", "002")]
    for child in children:
        child.start()
    try:
        for _ in children:
            assert ready.get(timeout=10)
        go.set()
        assert sorted(result.get(timeout=10) for _ in children) == ["conflict", "saved"]
    finally:
        go.set()
        for child in children:
            child.join(timeout=10)
            if child.is_alive():
                child.terminate()
                child.join()
    assert all(child.exitcode == 0 for child in children)
    assert len(ProgressRepository(path).load().missions) == 1


def test_session_interleaving_preserves_both(tmp_path):
    path = tmp_path / "lab.sqlite3"
    first, second = SessionLog(path), SessionLog(path)
    first.start()
    second.start()
    first.record("/status", "A")
    second.record("/help", "B")
    first.close()
    second.close()
    sessions = SessionLog(path).load()
    assert len({session["id"] for session in sessions}) == 2
    assert {session["events"][0]["summary"] for session in sessions} == {"A", "B"}


def test_open_sessions_survive_closed_retention(tmp_path):
    path = tmp_path / "lab.sqlite3"
    open_logs = [SessionLog(path) for _ in range(MAX_SESSIONS + 2)]
    for log in open_logs:
        log.start()
    for _ in range(MAX_SESSIONS + 3):
        closed = SessionLog(path)
        closed.start()
        closed.close()
    sessions = SessionLog(path).load()
    assert sum(session["ended_at"] is None for session in sessions) == len(open_logs)
    assert sum(session["ended_at"] is not None for session in sessions) == MAX_SESSIONS
    open_logs[0].record("/status", "still open")
    assert open_logs[0].current_events()[0]["summary"] == "still open"


def test_close_is_idempotent_and_events_are_capped(tmp_path):
    log = SessionLog(tmp_path / "lab.sqlite3")
    log.start()
    for index in range(MAX_EVENTS + 2):
        log.record("/status", str(index))
    log.close("done")
    log.close("duplicate")
    events = log.load()[0]["events"]
    assert len(events) == MAX_EVENTS
    assert events[-1]["summary"] == "done"
    assert sum(item["command"] == "/exit" for item in events) == 1


def test_simultaneous_importers_recognize_initially_absent_marker(tmp_path, monkeypatch):
    import json
    from dataclasses import asdict

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    progress = {"current_mission_id": "001", "missions": {"001": asdict(MissionProgress(status="started"))}, "evidence": []}
    (legacy / "progress.json").write_text(json.dumps(progress))
    target = tmp_path / "state" / "lab.sqlite3"
    ProgressRepository(target).load()  # Build schema before forcing the marker interleaving.

    marker_reads = Barrier(2)
    original_connect = sqlite3.connect

    class MarkerCursor:
        def __init__(self, cursor):
            self.cursor = cursor

        def fetchone(self):
            row = self.cursor.fetchone()
            try:
                marker_reads.wait(timeout=1)
            except BrokenBarrierError:
                pass
            return row

    class MarkerConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            cursor = super().execute(sql, parameters)
            return MarkerCursor(cursor) if sql.startswith("SELECT digest FROM migrations") else cursor

    def traced_connect(*args, **kwargs):
        return original_connect(*args, **kwargs, factory=MarkerConnection)

    monkeypatch.setattr(database_module.sqlite3, "connect", traced_connect)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(migrate_json_state, legacy, target) for _ in range(2)]
        reports = [future.result(timeout=10) for future in futures]

    assert sorted(report.imported for report in reports) == [False, True]
    assert ProgressRepository(target).load().current_mission_id == "001"
    assert all(path.read_bytes() == (legacy / "progress.json").read_bytes() for report in reports for path in report.backup_paths)
