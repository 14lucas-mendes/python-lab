import copy
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
import sqlite3

import pytest

from python_lab.assistant.errors import AssistantError
from python_lab.assistant.history import ConversationRepository
from python_lab.assistant.models import AssistantAnswer, AssistantRequest, Usage, WorkspaceSnapshot
from python_lab.catalog import load_missions
from python_lab.models import AppProgress, MissionProgress


ROOT = Path(__file__).resolve().parent.parent


def practice(missions, progress):
    from python_lab.recommendations import recommend_practice

    return recommend_practice(missions, progress)


def snapshot(missions, progress, **kwargs):
    from python_lab.presentation import practice_snapshot

    return practice_snapshot(missions, progress, **kwargs)


def ids(items):
    return [item.mission_id for item in items]


def test_recommendation_does_not_change_state(app):
    before = copy.deepcopy(app.progress)
    missions = copy.deepcopy(app.missions)
    items = practice(app.missions, app.progress)
    assert ids(items) == [app.recommended().id]
    assert app.progress == before
    assert app.missions == missions
    assert items[0].skills == app.missions[0].skills
    assert isinstance(items, tuple)
    with pytest.raises(FrozenInstanceError):
        items[0].reason = "alterado"


def test_started_active_mission_remains_first(app):
    active = app.missions[0]
    other = replace(active, id="002")
    app.start(active.id)
    app.progress.missions[other.id] = MissionProgress(attempts=12, hints_revealed=3)
    before = copy.deepcopy(app.progress)
    assert ids(practice([other, active], app.progress)) == [active.id, other.id]
    assert practice([active], app.progress)[0].mission_id == app.recommended().id
    assert "em andamento" in practice([active], app.progress)[0].reason
    assert app.progress == before


def test_ranking_uses_attempts_then_hints_then_cycle_and_id(app):
    base = app.missions[0]
    missions = [replace(base, id=identity, cycle=cycle) for identity, cycle in
                [("001", 1), ("002", 1), ("003", 2), ("004", 1), ("005", 2)]]
    app.missions = missions
    app.progress.missions = {
        "001": MissionProgress(attempts=1, hints_revealed=4),
        "002": MissionProgress(attempts=3, hints_revealed=1),
        "003": MissionProgress(attempts=3, hints_revealed=2),
        "004": MissionProgress(attempts=3, hints_revealed=2),
        "005": MissionProgress(attempts=3, hints_revealed=2),
    }
    before = copy.deepcopy(app.progress)
    expected = ["004", "003", "005", "002", "001"]
    assert ids(practice(missions, app.progress)) == expected
    assert ids(practice(list(reversed(missions)), app.progress)) == expected
    assert app.recommended().id == "001"  # The original method retains its semantics.
    assert app.progress == before


@pytest.mark.parametrize("current_status", ["available", "completed"])
def test_current_id_without_started_status_has_no_priority(app, current_status):
    base = app.missions[0]
    other = replace(base, id="002")
    progress = AppProgress(current_mission_id=base.id, missions={
        base.id: MissionProgress(status=current_status),
        other.id: MissionProgress(attempts=2),
    })
    expected = ["002", "001"] if current_status == "available" else ["002"]
    assert ids(practice([base, other], progress)) == expected


def test_real_catalog_respects_dependencies_even_for_started_locked_mission():
    missions = load_missions(ROOT / "missions")
    progress = AppProgress(current_mission_id="002", missions={
        "001": MissionProgress(status="completed"),
        "002": MissionProgress(status="started", attempts=20, hints_revealed=4),
        "004": MissionProgress(attempts=2, hints_revealed=1),
    })
    before = copy.deepcopy(progress)
    assert ids(practice(missions, progress)) == ["004", "006"]
    assert progress == before
    progress.missions["004"].status = "completed"
    assert ids(practice(missions, progress)) == ["006", "007", "008"]
    progress.missions["008"] = MissionProgress(status="completed")
    assert ids(practice(missions, progress)) == ["006", "007", "009"]
    progress.missions["009"] = MissionProgress(status="completed")
    assert ids(practice(missions, progress))[0] == "002"


def test_missing_prerequisite_is_locked_and_completed_is_excluded(app):
    base = app.missions[0]
    locked = replace(base, id="002", prerequisites=("missing",))
    progress = AppProgress(missions={base.id: MissionProgress(status="completed")})
    assert practice([base, locked], progress) == ()
    assert practice([], progress) == ()


def test_no_history_reason_is_neutral_and_in_portuguese():
    items = practice(load_missions(ROOT / "missions"), AppProgress())
    assert ids(items) == ["001"]
    assert items[0].reason == "Missão desbloqueada, sem tentativas ou pistas registradas."


def test_observed_reason_has_counts_without_claiming_failure_or_mastery(app):
    progress = AppProgress(missions={"001": MissionProgress(
        attempts=7, hints_revealed=2, tests_passed=True,
        attempt_history=[{"passed": True}],
    )})
    reason = practice(app.missions, progress)[0].reason
    assert reason == "Prática sugerida: 7 tentativa(s) e 2 pista(s) registradas."


def test_completed_review_is_opt_in_and_separate(app):
    progress = AppProgress(missions={"001": MissionProgress(status="completed", attempts=3)})
    ordinary = snapshot(app.missions, progress)
    assert ordinary.recommendations == ()
    assert ordinary.completed_review == ()
    review = snapshot(app.missions, progress, include_completed=True)
    assert review.recommendations == ()
    assert ids(review.completed_review) == ["001"]
    assert review.completed_review[0].reason == (
        "Revisão opcional de missão concluída: 3 tentativa(s) e 0 pista(s) registradas."
    )


def test_review_does_not_reset_progress(app):
    progress = AppProgress(current_mission_id="001", missions={"001": MissionProgress(
        status="completed", attempts=4, hints_revealed=3, reference_viewed=True,
        max_assistance_level=4, plan={"input": "x"}, tests_passed=True,
        explanation="explicação preservada", attempt_history=[{"passed": False}],
    )}, evidence=[{"skill": "functions", "result": "practicing", "assistance_level": 4}])
    missions = [app.missions[0], replace(app.missions[0], id="002", prerequisites=("001",))]
    before = copy.deepcopy(progress)
    review = snapshot(missions, progress, include_completed=True)
    assert ids(review.completed_review) == ["001"]
    assert ids(review.recommendations) == ["002"]
    assert progress == before


def append_conversation(repository, workspace, identity, *, mission_id="001", action="diagnose", traceback=None):
    request = AssistantRequest(action, "PRIVATE PROMPT", "tutor", 1,
                               WorkspaceSnapshot(workspace, ()), traceback=traceback,
                               mission_id=mission_id)
    answer = AssistantAnswer("PRIVATE ANSWER", "PRIVATE SOURCE", (), (), 1, Usage(1, 1))
    repository.append(request, answer, request_id=identity)


def database_records(path):
    with sqlite3.connect(path) as db:
        return tuple(db.iterdump())


def test_error_references_are_workspace_mission_scoped_and_metadata_only(tmp_path):
    repository = ConversationRepository(tmp_path / "lab.sqlite3")
    workspace = tmp_path / "project"
    append_conversation(repository, workspace, "local-diagnose")
    append_conversation(repository, workspace, "local-trace", action="explain", traceback="PRIVATE TRACEBACK")
    append_conversation(repository, workspace, "plain-explanation", action="explain")
    append_conversation(repository, workspace, "other-mission", mission_id="002")
    append_conversation(repository, workspace, "project-only", mission_id=None)
    append_conversation(repository, tmp_path / "elsewhere", "other-workspace")
    before = database_records(repository.database_path)
    references = repository.error_references(workspace / ".", mission_id="001")
    assert [item.request_id for item in references] == ["local-diagnose", "local-trace"]
    assert all(item.workspace == workspace.resolve() and item.mission_id == "001" for item in references)
    assert set(asdict(references[0])) == {"request_id", "workspace", "mission_id", "created_at", "action"}
    assert "PRIVATE" not in repr(references)
    assert [item.request_id for item in repository.error_references(workspace, mission_id=None)] == ["project-only"]
    assert database_records(repository.database_path) == before


def test_history_order_has_request_id_tie_break(tmp_path):
    repository = ConversationRepository(tmp_path / "lab.sqlite3")
    append_conversation(repository, tmp_path, "b")
    append_conversation(repository, tmp_path, "a")
    with sqlite3.connect(repository.database_path) as db:
        db.execute("UPDATE conversations SET created_at='2026-10-11T00:00:00Z'")
    assert [item.request_id for item in repository.error_references(tmp_path, mission_id="001")] == ["a", "b"]


def test_history_read_does_not_create_database_or_parent(tmp_path):
    repository = ConversationRepository(tmp_path / "absent" / "lab.sqlite3")
    assert repository.error_references(tmp_path, mission_id="001") == ()
    assert not repository.database_path.parent.exists()


def test_history_read_does_not_initialize_or_migrate_existing_database(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE marker (value TEXT)")
        db.execute("INSERT INTO marker VALUES ('unchanged')")
    before = path.read_bytes()
    assert ConversationRepository(path).error_references(tmp_path, mission_id="001") == ()
    assert path.read_bytes() == before
    assert not (tmp_path / "backups").exists()


def test_corrupt_history_reports_error_without_replacing_file(tmp_path):
    path = tmp_path / "broken.sqlite3"
    path.write_bytes(b"invalid database")
    with pytest.raises(AssistantError, match="consultar o histórico"):
        ConversationRepository(path).error_references(tmp_path, mission_id="001")
    assert path.read_bytes() == b"invalid database"


def test_presentation_links_errors_only_for_visible_missions(app, tmp_path):
    repository = ConversationRepository(tmp_path / "history.sqlite3")
    append_conversation(repository, tmp_path, "completed")
    append_conversation(repository, tmp_path, "available", mission_id="002")
    append_conversation(repository, tmp_path, "locked", mission_id="003")
    append_conversation(repository, tmp_path, "project", mission_id=None)
    append_conversation(repository, tmp_path / "other", "foreign", mission_id="002")
    base = app.missions[0]
    missions = [base, replace(base, id="002", prerequisites=("001",)),
                replace(base, id="003", prerequisites=("002",))]
    progress = AppProgress(missions={"001": MissionProgress(status="completed")})
    before = copy.deepcopy(progress)
    stored = database_records(repository.database_path)
    ordinary = snapshot(missions, progress, history=repository, workspace=tmp_path)
    assert [item.request_id for item in ordinary.error_history] == ["available"]
    review = snapshot(missions, progress, include_completed=True, history=repository, workspace=tmp_path)
    assert [item.request_id for item in review.error_history] == ["available", "completed"]
    assert "PRIVATE" not in repr(review)
    assert progress == before
    assert database_records(repository.database_path) == stored


def test_history_requires_explicit_workspace_in_presentation(app):
    with pytest.raises(ValueError, match="workspace"):
        snapshot(app.missions, app.progress, history=ConversationRepository(Path("unused.sqlite3")))
