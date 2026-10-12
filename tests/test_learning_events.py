"""Assistance must bind to an attempt and commit with its progress."""

import asyncio
from datetime import datetime, timezone
import sqlite3

import pytest

from python_lab.progress import ProgressError, ProgressRepository
from python_lab.storage.database import connection


def event(mission_id='001', level=4, request_id='request', action='explain'):
    from python_lab.learning_events import AssistanceEvent
    return AssistanceEvent(mission_id, action, level, datetime.now(timezone.utc).isoformat(), request_id)


def rows(path):
    with connection(path) as db:
        return db.execute('SELECT mission_id, action, level, request_id, attempt_id FROM assistance_events').fetchall()


@pytest.mark.parametrize('level', range(5))
def test_record_all_levels_atomically_without_completing(app, level):
    app.start('001')
    before = app.repository._revision
    app.record_assistance(event(level=level), attempt_id=app.current_progress().attempt_id)
    assert app.current_progress().max_assistance_level == level
    assert app.current_progress().reference_viewed is (level == 4)
    assert app.current_progress().status == 'started'
    assert app.progress.evidence == []
    assert app.repository._revision == before + 1
    assert app.repository.load() == app.progress
    assert rows(app.repository.path)[0][:4] == ('001', 'explain', level, 'request')


def test_duplicate_is_idempotent_and_conflicting_identity_is_rejected(app):
    app.start('001')
    attempt = app.current_progress().attempt_id
    help_event = event()
    app.record_assistance(help_event, attempt_id=attempt)
    revision = app.repository._revision
    app.record_assistance(help_event, attempt_id=attempt)
    assert app.repository._revision == revision
    assert len(rows(app.repository.path)) == 1
    with pytest.raises(ProgressError, match='(?i)identidade|request'):
        app.record_assistance(event(level=1), attempt_id=attempt)
    assert app.current_progress().max_assistance_level == 4


def test_real_cas_conflict_rolls_back_event_and_local_progress(app):
    app.start('001')
    other = ProgressRepository(app.repository.path)
    fresh = other.load()
    fresh.missions['001'].explanation = 'another session'
    other.save(fresh)
    with pytest.raises(ProgressError, match='Conflito'):
        app.record_assistance(event(), attempt_id=app.current_progress().attempt_id)
    assert rows(app.repository.path) == []
    assert not app.current_progress().reference_viewed
    assert other.load().missions['001'].explanation == 'another session'


@pytest.mark.parametrize('table', ['progress', 'assistance_events'])
def test_transaction_failure_saves_neither_event_nor_maximum(app, table):
    app.start('001')
    operation = 'UPDATE' if table == 'progress' else 'INSERT'
    with connection(app.repository.path) as db:
        db.execute(f"CREATE TRIGGER reject_help BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'disk full'); END")
        db.commit()
    before = app.repository._revision
    with pytest.raises(ProgressError, match='disk full'):
        app.record_assistance(event(), attempt_id=app.current_progress().attempt_id)
    assert rows(app.repository.path) == []
    assert app.repository._revision == before
    assert not app.repository.load().missions['001'].reference_viewed
    assert not app.current_progress().reference_viewed


def test_public_recorder_and_project_only_event_do_not_attach_to_active_mission(app):
    from python_lab.learning_events import AssistanceRecorder
    app.start('001')
    AssistanceRecorder(app.repository.path).record(event(mission_id=None))
    assert rows(app.repository.path)[0][0] is None
    assert ProgressRepository(app.repository.path).load().missions['001'].max_assistance_level == 0


def test_compatibility_full_solution_call_records_help(app):
    app.start('001')
    app.record_full_solution('001')
    assert app.current_progress().max_assistance_level == 4
    assert app.current_progress().reference_viewed
    assert len(rows(app.repository.path)) == 1


def test_builtin_hints_and_reference_are_events(app):
    app.start('001')
    app.current_progress().attempts = 1
    app.persist()
    hints = app.current_mission().hints
    for index in range(len(hints)):
        app.next_hint(confirm_reference=index == len(hints) - 1)
    stored = rows(app.repository.path)
    assert len(stored) == len(hints)
    assert [row[2] for row in stored] == [min(i + 1, 3) for i in range(len(hints) - 1)] + [4]
    assert stored[-1][1] == 'reference'
    assert app.current_progress().max_assistance_level == 4
    assert app.current_progress().status == 'started'


@pytest.mark.parametrize('phase', ['analysis', 'provider'])
def test_response_before_restart_cannot_mark_new_attempt(app, tmp_path, phase):
    import threading
    from python_lab.assistant.history import ConversationRepository
    from python_lab.assistant.service import AssistantService
    from tests.helpers.assistant import RecordingProvider, sample_answer, sample_request
    from tests.test_assistant_service import FakeAnalysis, snapshot

    app.start('001')
    captured_attempt = app.current_progress().attempt_id
    captured = snapshot(tmp_path)
    started = threading.Event()
    release = threading.Event()

    class SlowAnalysis(FakeAnalysis):
        def inspect(self, snapshot, **kwargs):
            if phase == 'analysis':
                started.set()
                assert release.wait(5)
            return super().inspect(snapshot, **kwargs)

    class SlowProvider(RecordingProvider):
        async def generate(self, request):
            if phase == 'provider':
                started.set()
                assert await asyncio.to_thread(release.wait, 5)
            return await super().generate(request)

    service = AssistantService(SlowProvider(sample_answer(captured, level=4)), SlowAnalysis(),
                               ConversationRepository(app.repository.path),
                               on_assistance=app.record_assistance,
                               capture_attempt=app.capture_assistance_attempt)

    async def exercise():
        task = asyncio.create_task(service.execute(sample_request(captured, level=4, mission_id='001')))
        assert await asyncio.to_thread(started.wait, 5)
        try:
            app.current_progress().status = 'completed'
            app.persist()
            app.start('001')
            assert app.current_progress().attempt_id != captured_attempt
        finally:
            release.set()
        await task

    asyncio.run(exercise())
    assert app.current_progress().max_assistance_level == 0
    assert not app.current_progress().reference_viewed
    assert rows(app.repository.path)[0][-1] == captured_attempt
    assert app.progress.evidence == []


@pytest.mark.parametrize('level', [True, -1, 5, 1.0, '4'])
def test_event_rejects_malformed_levels(level):
    with pytest.raises((ValueError, ProgressError), match='(?i)level|nível'):
        event(level=level)


@pytest.mark.parametrize('level', range(5))
def test_service_all_levels_reuse_local_history_identity(app, tmp_path, level):
    from python_lab.assistant.history import ConversationRepository
    from python_lab.assistant.service import AssistantService
    from tests.helpers.assistant import RecordingProvider, sample_answer, sample_request
    from tests.test_assistant_service import FakeAnalysis, snapshot
    app.start('001')
    captured = snapshot(tmp_path)
    # The old B4 bound callback remains a supported entry point.
    service = AssistantService(RecordingProvider(sample_answer(captured, level=level)), FakeAnalysis(),
                               ConversationRepository(app.repository.path), on_full_solution=app.record_full_solution)
    asyncio.run(service.execute(sample_request(captured, level=level, mission_id='001')))
    with connection(app.repository.path) as db:
        history_id = db.execute('SELECT request_id FROM conversations').fetchone()[0]
    assert rows(app.repository.path)[0][3] == history_id
    assert app.current_progress().max_assistance_level == level
    assert app.progress.evidence == []


@pytest.mark.parametrize('related', [False, True])
def test_commands_associate_only_selected_mission_solution(app, tmp_path, related):
    from python_lab.assistant.commands import AssistantCommands
    from python_lab.assistant.history import ConversationRepository
    from python_lab.assistant.service import AssistantService
    from python_lab.workspace import Workspace
    from tests.helpers.assistant import RecordingProvider, sample_answer
    from tests.test_assistant_service import FakeAnalysis
    app.start('001')
    source = app.current_mission().solution_path if related else tmp_path / 'unrelated.py'
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('x=1\n')
    captured = Workspace(tmp_path).snapshot([source])
    service = AssistantService(RecordingProvider(sample_answer(captured, level=4)), FakeAnalysis(),
                               ConversationRepository(app.repository.path))
    commands = AssistantCommands(service, Workspace(tmp_path), 'tutor', app=app)
    result = asyncio.run(commands.explain((str(source.relative_to(tmp_path)), '--level', '4')))
    assert result.ok, result.message
    assert rows(app.repository.path)[0][0] == ('001' if related else None)
    assert app.current_progress().max_assistance_level == (4 if related else 0)


def test_review_validates_answer_references_before_events_or_history(app, tmp_path):
    from dataclasses import replace
    from python_lab.assistant.errors import AssistantError
    from python_lab.assistant.history import ConversationRepository
    from python_lab.assistant.models import CodeReference, ReviewReply
    from python_lab.assistant.patches import PatchService
    from python_lab.assistant.review import ReviewService
    from python_lab.workspace import Workspace
    from tests.helpers.assistant import sample_answer, sample_request
    from tests.test_assistant_service import FakeAnalysis, snapshot
    from tests.test_review import Provider
    app.start('001')
    captured = snapshot(tmp_path)
    invalid = replace(sample_answer(captured, level=2), references=(CodeReference('outside.py', 1, 1),))
    service = ReviewService(FakeAnalysis(), Provider(ReviewReply(invalid, ())),
                            PatchService(Workspace(tmp_path), tmp_path / 'state'), ConversationRepository(app.repository.path),
                            on_assistance=app.record_assistance, capture_attempt=app.capture_assistance_attempt)
    with pytest.raises(AssistantError, match='Referência'):
        asyncio.run(service.review(replace(sample_request(captured, level=3, mission_id='001'), action='review')))
    assert rows(app.repository.path) == []
    with connection(app.repository.path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='conversations'").fetchone() is None


def test_review_response_before_restart_keeps_old_attempt(app, tmp_path):
    from dataclasses import replace
    import threading
    from python_lab.assistant.history import ConversationRepository
    from python_lab.assistant.models import ReviewReply
    from python_lab.assistant.patches import PatchService
    from python_lab.assistant.review import ReviewService
    from python_lab.workspace import Workspace
    from tests.helpers.assistant import sample_answer, sample_request
    from tests.test_assistant_service import FakeAnalysis, snapshot
    app.start('001')
    old = app.current_progress().attempt_id
    captured = snapshot(tmp_path)
    started, release = threading.Event(), threading.Event()

    class Provider:
        async def review(self, request):
            started.set()
            assert await asyncio.to_thread(release.wait, 5)
            return ReviewReply(sample_answer(captured, level=3), ())

    service = ReviewService(FakeAnalysis(), Provider(), PatchService(Workspace(tmp_path), tmp_path / 'state'),
                            ConversationRepository(app.repository.path), on_assistance=app.record_assistance,
                            capture_attempt=app.capture_assistance_attempt)

    async def exercise():
        task = asyncio.create_task(service.review(replace(sample_request(captured, level=3, mission_id='001'), action='review')))
        assert await asyncio.to_thread(started.wait, 5)
        try:
            app.current_progress().status = 'completed'
            app.persist()
            app.start('001')
        finally:
            release.set()
        await task

    asyncio.run(exercise())
    assert app.current_progress().max_assistance_level == 0
    assert rows(app.repository.path)[0] == ('001', 'review', 3, rows(app.repository.path)[0][3], old)


def test_patch_deduplicated_event_is_distinct_from_review(app, tmp_path):
    from python_lab.cli import AssistantRuntime
    from python_lab.workspace import Workspace
    from tests.test_review_cli import proposal
    app.start('001')
    source = app.current_mission().solution_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('x=1\n')
    app.record_assistance(event(level=3, action='review', request_id='review-id'),
                          attempt_id=app.current_progress().attempt_id)
    patch = proposal(tmp_path, tmp_path / 'patch-state', str(source.relative_to(tmp_path)), 'x=2\n')
    commands = AssistantRuntime(tmp_path / 'patch-state', app).commands(Workspace(tmp_path), 'tutor', app=app)
    result = asyncio.run(commands.apply((patch.id, '--yes')))
    assert result.ok, result.message
    assert result.data['event_key'].startswith('apply:')
    assert {row[3] for row in rows(app.repository.path)} == {'review-id', result.data['event_key']}
    assert app.current_progress().max_assistance_level == 4
    revision = app.repository._revision
    app.record_full_solution('001', request_id=result.data['event_key'], action='apply',
                             attempt_id=app.current_progress().attempt_id)
    assert len(rows(app.repository.path)) == 2
    assert app.repository._revision == revision
    assert app.current_progress().status == 'started' and app.progress.evidence == []


def test_patch_confirmation_restart_does_not_mark_new_attempt(app, tmp_path):
    from python_lab.cli import AssistantRuntime
    from python_lab.workspace import Workspace
    from tests.test_review_cli import proposal
    app.start('001')
    old = app.current_progress().attempt_id
    source = app.current_mission().solution_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('x=1\n')
    patch = proposal(tmp_path, tmp_path / 'state', str(source.relative_to(tmp_path)), 'x=2\n')
    commands = AssistantRuntime(tmp_path / 'state', app).commands(Workspace(tmp_path), 'tutor', app=app)

    async def confirm(preview):
        app.current_progress().status = 'completed'
        app.persist()
        app.start('001')
        return True

    result = asyncio.run(commands.apply((patch.id,), confirm=confirm))
    assert result.ok, result.message
    assert source.read_text() == 'x=2\n'
    assert app.current_progress().max_assistance_level == 0
    assert rows(app.repository.path)[0][-1] == old


def test_hint_failed_commit_does_not_reveal_or_save_a_hint(app):
    app.start('001')
    app.current_progress().attempts = 1
    app.persist()
    with connection(app.repository.path) as db:
        db.execute("CREATE TRIGGER reject_help BEFORE UPDATE ON progress BEGIN SELECT RAISE(ABORT, 'disk full'); END")
        db.commit()
    with pytest.raises(ProgressError, match='disk full'):
        app.next_hint()
    assert app.current_progress().hints_revealed == 0
    assert app.current_progress().max_assistance_level == 0
    assert rows(app.repository.path) == []


def test_initial_competing_recorders_save_only_winners_event(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from python_lab.learning_events import AssistanceRecorder
    from python_lab.models import AppProgress, MissionProgress
    path = tmp_path / 'lab.sqlite3'
    repos = [ProgressRepository(path), ProgressRepository(path)]
    for repo in repos:
        assert repo.load() == AppProgress()
    started = Barrier(2)

    def record(index):
        candidate = AppProgress(current_mission_id='001', missions={'001': MissionProgress(status='started')})
        started.wait(timeout=5)
        try:
            AssistanceRecorder(path).record(event(level=index + 1, request_id=str(index)), repository=repos[index],
                                            progress=candidate, attempt_id=candidate.missions['001'].attempt_id)
        except ProgressError as exc:
            assert 'Conflito' in str(exc)
            return False
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(record, range(2)))
    assert sorted(results) == [False, True]
    stored = rows(path)
    assert len(stored) == 1
    assert ProgressRepository(path).load().missions['001'].max_assistance_level == stored[0][2]


def test_cross_store_recorder_rejects_split_progress_and_event(app, tmp_path):
    from python_lab.learning_events import AssistanceRecorder
    app.start('001')
    with pytest.raises(ProgressError, match='mesmo banco'):
        AssistanceRecorder(tmp_path / 'another.sqlite3').record(event(), repository=app.repository, progress=app.progress)
    assert not (tmp_path / 'another.sqlite3').exists()
    assert not app.current_progress().reference_viewed


@pytest.mark.parametrize('same_path', [False, True])
def test_apply_local_ids_are_scoped_by_store_and_destination(tmp_path, same_path):
    from python_lab.cli import AssistantRuntime
    from python_lab.workspace import Workspace
    from tests.test_review_cli import proposal
    first = tmp_path / 'one.py'
    second = first if same_path else tmp_path / 'two.py'
    first.write_text('x=1\n')
    second.write_text('x=1\n')
    states = [tmp_path / 'state-one', tmp_path / 'state-two']
    patches = [proposal(tmp_path, states[i], source.name, 'x=2\n') for i, source in enumerate([first, second])]
    assert patches[0].id == patches[1].id
    assert patches[0].change.before_sha256 == patches[1].change.before_sha256
    keys = []
    for index, patch in enumerate(patches):
        if same_path and index == 1:
            first.write_text('x=1\n')
        commands = AssistantRuntime(states[index]).commands(Workspace(tmp_path), 'assistant')
        result = asyncio.run(commands.apply((patch.id, '--yes')))
        assert result.ok, result.message
        keys.append(result.data['event_key'])
        assert keys[-1].endswith(f':{patch.id}:{patch.change.before_sha256}')
    assert keys[0] != keys[1]
    assert [row[3] for row in rows(states[0] / 'lab.sqlite3')] == [keys[0]]
    assert [row[3] for row in rows(states[1] / 'lab.sqlite3')] == [keys[1]]


def test_builtin_hint_event_reports_its_level_after_prior_full_help(app):
    app.start('001')
    app.record_full_solution('001')
    app.current_progress().attempts = 1
    app.persist()
    app.next_hint()
    hint = rows(app.repository.path)[-1]
    assert hint[1:3] == ('hint', 1)
    assert app.current_progress().max_assistance_level == 4
    assert app.current_progress().reference_viewed


@pytest.mark.parametrize('action', ['explain', 'review'])
@pytest.mark.parametrize('requested,declared', [(4, 2), (3, 1), (2, 0), (1, 0), (0, 0)])
def test_downgraded_model_help_records_requested_level_in_active_attempt(app, tmp_path, action, requested, declared):
    from dataclasses import replace
    from python_lab.assistant.history import ConversationRepository
    from python_lab.assistant.models import ReviewReply
    from python_lab.assistant.patches import PatchService
    from python_lab.assistant.review import ReviewService
    from python_lab.assistant.service import AssistantService
    from python_lab.workspace import Workspace
    from tests.helpers.assistant import RecordingProvider, sample_answer, sample_request
    from tests.test_assistant_service import FakeAnalysis, snapshot
    from tests.test_review import Provider
    app.start('001')
    attempt = app.current_progress().attempt_id
    captured = snapshot(tmp_path)
    history = ConversationRepository(app.repository.path)
    req = replace(sample_request(captured, level=requested, mission_id='001'), action=action)
    answer = sample_answer(captured, level=declared)
    if action == 'review':
        service = ReviewService(FakeAnalysis(), Provider(ReviewReply(answer, ())),
            PatchService(Workspace(tmp_path), tmp_path / 'state'), history,
            on_assistance=app.record_assistance, capture_attempt=app.capture_assistance_attempt)
        result = asyncio.run(service.review(req)).advice
    else:
        service = AssistantService(RecordingProvider(answer), FakeAnalysis(), history,
                                   on_full_solution=app.record_full_solution)
        result = asyncio.run(service.execute(req))
    assert result.assistance_level == declared
    progress = app.current_progress()
    assert progress.max_assistance_level == requested
    assert progress.reference_viewed is (requested == 4)
    assert progress.status == 'started' and app.progress.evidence == []
    assert app.skill_states() == {}  # Help alone never approves a skill.
    assert app.repository.load().missions['001'].max_assistance_level == requested
    with connection(app.repository.path) as db:
        history_id, history_level = db.execute('SELECT request_id, level FROM conversations').fetchone()
    assert history_level == requested
    assert rows(app.repository.path) == [('001', action, requested, history_id, attempt)]
    if requested == 4:
        from copy import deepcopy
        from python_lab.learning import complete_mission
        completion = deepcopy(app.repository.load().missions['001'])
        completion.plan = {key: 'ok' for key in ('input', 'output', 'steps', 'risks')}
        completion.tests_passed = True
        completion.explanation = 'Verifiquei o contrato'
        evidence = complete_mission(app.current_mission(), completion, [])
        assert evidence and all(item['result'] == 'practicing' for item in evidence)
        assert all(item['assistance_level'] == 4 for item in evidence)
        assert app.progress.evidence == []


@pytest.mark.parametrize('action', ['explain', 'review'])
def test_above_requested_help_records_no_event_or_history(app, tmp_path, action):
    from dataclasses import replace
    from python_lab.assistant.errors import AssistantError
    from python_lab.assistant.history import ConversationRepository
    from python_lab.assistant.models import ReviewReply
    from python_lab.assistant.patches import PatchService
    from python_lab.assistant.review import ReviewService
    from python_lab.assistant.service import AssistantService
    from python_lab.workspace import Workspace
    from tests.helpers.assistant import RecordingProvider, sample_answer, sample_request
    from tests.test_assistant_service import FakeAnalysis, snapshot
    from tests.test_review import Provider
    app.start('001')
    captured = snapshot(tmp_path)
    history = ConversationRepository(app.repository.path)
    req = replace(sample_request(captured, level=1, mission_id='001'), action=action)
    answer = sample_answer(captured, level=2)
    if action == 'review':
        service = ReviewService(FakeAnalysis(), Provider(ReviewReply(answer, ())),
            PatchService(Workspace(tmp_path), tmp_path / 'state'), history,
            on_assistance=app.record_assistance, capture_attempt=app.capture_assistance_attempt)
        operation = service.review(req)
    else:
        service = AssistantService(RecordingProvider(answer), FakeAnalysis(), history,
                                   on_full_solution=app.record_full_solution)
        operation = service.execute(req)
    with pytest.raises(AssistantError, match='nível'):
        asyncio.run(operation)
    assert rows(app.repository.path) == []
    assert app.current_progress().max_assistance_level == 0
    with connection(app.repository.path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='conversations'").fetchone() is None
