"""Shared adapters retain their command-entry identity across worker awaits."""

import asyncio
from dataclasses import replace
import threading

import pytest

from python_lab.assistant.commands import AssistantCommands
from python_lab.assistant.history import ConversationRepository
from python_lab.assistant.models import ReviewReply
from python_lab.assistant.patches import PatchService
from python_lab.assistant.review import ReviewService
from python_lab.workspace import Workspace
from tests.helpers.assistant import sample_answer
from tests.test_assistant_service import FakeAnalysis
from tests.test_learning_events import rows
from tests.test_review_cli import proposal


@pytest.mark.parametrize('phase', ['review_snapshot', 'apply_load', 'apply_preview'])
@pytest.mark.parametrize('change', ['restart', 'navigate', 'unrelated_navigation', 'project_to_mission', 'solution_change'])
def test_shared_command_freezes_identity_before_first_worker(app, tmp_path, monkeypatch, phase, change):
    original_mission = app.mission_by_id('001')
    original_solution = original_mission.solution_path
    original_solution.parent.mkdir(parents=True, exist_ok=True)
    original_solution.write_text('x=1\n')
    unrelated = tmp_path / 'project.py'
    unrelated.write_text('x=1\n')
    selected = unrelated if change == 'unrelated_navigation' else original_solution
    second_solution = unrelated if change == 'unrelated_navigation' else tmp_path / 'second.py'
    second_solution.write_text('x=1\n')
    app.missions.append(replace(original_mission, id='002', prerequisites=(), solution_path=second_solution))
    if change != 'project_to_mission':
        app.start('001')
    old_attempt = app.current_progress().attempt_id if change != 'project_to_mission' else None
    workspace = Workspace(tmp_path)
    patches = PatchService(workspace, tmp_path / 'patch-state')
    started, release = threading.Event(), threading.Event()

    class Provider:
        async def review(self, request):
            return ReviewReply(sample_answer(request.snapshot, level=3), ())

    def review_service():
        return ReviewService(FakeAnalysis(), Provider(), patches, ConversationRepository(app.repository.path),
                             on_assistance=app.record_assistance, capture_attempt=app.capture_assistance_attempt)

    commands = AssistantCommands(None, workspace, 'tutor', app=app, patches=patches, review_factory=review_service)
    if phase == 'review_snapshot':
        original_worker = workspace.snapshot
        args = (str(selected.relative_to(tmp_path)),)
        operation = commands.review
        worker_owner, worker_name = workspace, 'snapshot'
    else:
        patch = proposal(tmp_path, patches.data_dir, str(selected.relative_to(tmp_path)), 'x=2\n')
        worker_name = 'load' if phase == 'apply_load' else 'preview'
        original_worker = getattr(patches, worker_name)
        args = (patch.id, '--yes')
        operation = commands.apply
        worker_owner = patches

    def paused_worker(*args, **kwargs):
        captured = original_worker(*args, **kwargs)
        started.set()
        assert release.wait(5), 'command worker was not released'
        return captured

    monkeypatch.setattr(worker_owner, worker_name, paused_worker)

    async def exercise():
        task = asyncio.create_task(operation(args))
        assert await asyncio.to_thread(started.wait, 5), 'command did not reach worker boundary'
        try:
            if change == 'restart':
                app.current_progress().status = 'completed'
                app.persist()
                app.start('001')
                assert app.current_progress().attempt_id != old_attempt
            elif change in {'navigate', 'unrelated_navigation'}:
                app.start('002')
            elif change == 'project_to_mission':
                app.start('001')
            else:
                # Association must use the solution captured before the worker,
                # even if the current catalog changes while the command awaits.
                app.missions[0] = replace(original_mission, solution_path=second_solution)
        finally:
            release.set()
        result = await task
        assert result.ok, result.message

    asyncio.run(exercise())
    stored = rows(app.repository.path)
    assert len(stored) == 1
    project_only = change in {'unrelated_navigation', 'project_to_mission'}
    assert stored[0][0] == (None if project_only else '001')
    assert stored[0][-1] == (None if project_only else old_attempt)
    assert stored[0][1:3] == (('review', 3) if phase == 'review_snapshot' else ('apply', 4))
    expected_current_level = (3 if phase == 'review_snapshot' else 4) if change == 'solution_change' else 0
    assert app.current_progress().max_assistance_level == expected_current_level
    assert app.current_progress().reference_viewed is (expected_current_level == 4)
    assert app.repository.load() == app.progress
    assert app.progress.evidence == []
    if phase != 'review_snapshot':
        assert selected.read_text() == 'x=2\n'
