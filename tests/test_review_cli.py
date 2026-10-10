import asyncio
import json
from pathlib import Path

import pytest

from python_lab.analysis import AnalysisService
from python_lab.assistant.history import ConversationRepository
from python_lab.assistant.models import AssistantAnswer, FileChange, PatchProposal, ReviewReply, Usage
from python_lab.assistant.patches import PatchService
from python_lab.assistant.service import AssistantService
from python_lab.assistant.verification import VerificationService, VerificationStore
from python_lab.cli import AssistantRuntime, PythonLabCLI, main
from python_lab.commands import Command
from python_lab.runtime.processes import ProcessRunner
from python_lab.workspace import Workspace


def proposal(project, state, name='bug.py', text='def add(a, b):\n    return a + b\n'):
    workspace = Workspace(project)
    snapshot = workspace.snapshot((Path(name),))
    captured = snapshot.sources[0]
    patch = PatchProposal('local-id', FileChange(captured.path, captured.sha256, text), 'fix', (captured.path,))
    PatchService(workspace, state).save(patch)
    return patch


def invoke(capsys, project, state, *args):
    code = main([*args, '--project', str(project), '--data-dir', str(state), '--json'])
    return code, json.loads(capsys.readouterr().out)


def test_cli_apply_requires_explicit_confirmation_and_displays_literal_diff(tmp_path, capsys):
    source = tmp_path / 'bug.py'
    source.write_text('def add(a, b):\n    return a - b\n')
    state = tmp_path / 'state'
    patch = proposal(tmp_path, state)
    before = source.read_bytes()
    code, payload = invoke(capsys, tmp_path, state, 'apply', patch.id)
    assert code == 2 and not payload['ok']
    assert '--yes' in payload['message']
    assert payload['data']['path'] == str(source.resolve())
    assert '-    return a - b' in payload['data']['diff']
    assert source.read_bytes() == before
    code, payload = invoke(capsys, tmp_path, state, 'apply', patch.id, '--yes')
    assert code == 0 and payload['data']['status'] == 'unverified'
    assert source.read_text() == patch.change.after_text
    assert payload['data']['event_key'].endswith(f':{patch.id}:{patch.change.before_sha256}')


def test_foreign_workspace_id_rejected(tmp_path, capsys):
    project = tmp_path / 'one'
    project.mkdir()
    other = tmp_path / 'two'
    other.mkdir()
    for root in (project, other):
        (root / 'bug.py').write_text('x=1\n')
    state = tmp_path / 'state'
    patch = proposal(project, state, text='x=2\n')
    for args in [('apply', patch.id, '--yes'), ('verify', patch.id, '--check', 'ast')]:
        code, payload = invoke(capsys, other, state, *args)
        assert code == 2 and 'workspace' in payload['message']
    assert (other / 'bug.py').read_text() == 'x=1\n'


def test_review_apply_verify_journey(tmp_path, monkeypatch, capsys):
    source = tmp_path / 'bug.py'
    source.write_text('def add(a, b):\n    return a - b\n')
    (tmp_path / 'test_bug.py').write_text('from bug import add\n\ndef test_add():\n    assert add(3, 2) == 5\n')
    state = tmp_path / 'state'
    requests = []

    class Provider:
        async def review(self, request):
            requests.append(request)
            captured = request.snapshot.sources[0]
            return ReviewReply(AssistantAnswer('fix addition', 'Use plus', (), (), 2, Usage(3, 2)),
                               (FileChange(captured.path, captured.sha256, 'def add(a, b):\n    return a + b\n'),))

    service = AssistantService(Provider(), AnalysisService(), ConversationRepository(state / 'lab.sqlite3'))
    monkeypatch.setattr(AssistantRuntime, 'get_service', lambda self: service)
    code, payload = invoke(capsys, tmp_path, state, 'review', 'bug.py')
    assert code == 0 and requests[0].action == 'review'
    preview = payload['data']['proposals'][0]
    assert '+    return a + b' in preview['diff']
    assert 'return a - b' in source.read_text()
    assert invoke(capsys, tmp_path, state, 'apply', preview['id'], '--yes')[0] == 0
    code, verified = invoke(capsys, tmp_path, state, 'verify', preview['id'], '--check', 'ast', '--check', 'pytest')
    assert code == 0 and verified['data']['status'] == 'passed'
    assert verified['data']['root'] == str(tmp_path.resolve())
    patches = PatchService(Workspace(tmp_path), state)
    verifier = VerificationService(ProcessRunner(), store=VerificationStore(state))
    assert verifier.current(patches.load(preview['id']), Workspace(tmp_path)).status == 'passed'
    source.write_text('def add(a, b):\n    return a - b\n')
    assert verifier.current(patches.load(preview['id']), Workspace(tmp_path)).status == 'unverified'
    assert invoke(capsys, tmp_path, state, 'verify', preview['id'], '--check', 'pytest')[0] == 2


def test_review_without_ai_reports_local_analysis_and_no_proposals(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv('LAB_API_KEY', raising=False)
    (tmp_path / 'bug.py').write_text('def broken(:\n')
    code, payload = invoke(capsys, tmp_path, tmp_path / 'state', 'review', 'bug.py')
    assert code == 0 and payload['data']['advice'] is None
    assert payload['data']['proposals'] == []
    assert 'IA indisponível' in payload['message']
    assert any(check['status'] == 'failed' for check in payload['data']['analysis']['checks'])


def test_shared_registry_and_mission_apply_association(app, tmp_path):
    app.start('001')
    source = app.current_mission().solution_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('x=1\n')
    state = tmp_path / 'assistant-state'
    patch = proposal(tmp_path, state, str(source.relative_to(tmp_path)), 'x=2\n')
    cli = PythonLabCLI(app, assistant_project=tmp_path, assistant_runtime=AssistantRuntime(state, app))
    result = asyncio.run(cli.dispatcher.dispatch_async(Command('/apply', (patch.id, '--yes'))))
    assert result.ok and app.current_progress().reference_viewed
    assert app.current_progress().status == 'started' and not app.current_progress().tests_passed
    assert not cli.dispatcher.dispatch(Command('/review', ('a.py',))).ok


@pytest.mark.parametrize('check', ['pytest', 'ast'])
def test_verify_exposes_failure_diagnostics(tmp_path, capsys, check):
    (tmp_path / 'bug.py').write_text('x=1\n')
    (tmp_path / 'test_bug.py').write_text('def test_bug():\n    assert False\n')
    state = tmp_path / 'state'
    patch = proposal(tmp_path, state, text=('x=2\n' if check == 'pytest' else 'def broken(:\n'))
    invoke(capsys, tmp_path, state, 'apply', patch.id, '--yes')
    code, payload = invoke(capsys, tmp_path, state, 'verify', patch.id, '--check', check)
    assert code == 1 and payload['data']['status'] == 'failed'
    assert payload['data']['checks'][0]['detail']


def test_apply_freezes_mission_identity_and_exact_solution_membership(app, tmp_path):
    app.start('001')
    solution = app.current_mission().solution_path
    solution.parent.mkdir(parents=True, exist_ok=True)
    solution.write_text('x=1\n')
    state = tmp_path / 'patch-state'
    patch = proposal(tmp_path, state, str(solution.relative_to(tmp_path)), 'x=2\n')
    commands = AssistantRuntime(state, app).commands(Workspace(tmp_path), 'tutor', app=app)
    recorded = []
    original = app.record_full_solution

    def record(mission_id):
        recorded.append(mission_id)
        original(mission_id)

    app.record_full_solution = record

    async def confirmed(preview):
        # Another session/navigation must not redirect the captured apply event.
        app.progress.current_mission_id = None
        return True

    result = asyncio.run(commands.apply((patch.id,), confirm=confirmed))
    assert result.ok and recorded == ['001']
    assert app.progress.missions['001'].reference_viewed
    app.progress.current_mission_id = '001'
    app.progress.missions['001'].reference_viewed = False
    unrelated = tmp_path / 'bug.py'
    unrelated.write_text('x=1\n')
    other_state = tmp_path / 'other-state'
    other = proposal(tmp_path, other_state, text='x=2\n')
    commands = AssistantRuntime(other_state, app).commands(Workspace(tmp_path), 'tutor', app=app)
    assert asyncio.run(commands.apply((other.id, '--yes'))).ok
    assert recorded == ['001'] and not app.current_progress().reference_viewed


@pytest.mark.parametrize('cleanup_failed', [False, True])
def test_verify_repeated_cancel_waits_native_cleanup(tmp_path, cleanup_failed):
    import threading
    from python_lab.runtime.processes import ProcessCleanupError
    from python_lab.assistant.verification import VerificationResult

    (tmp_path / 'bug.py').write_text('x=1\n')
    state = tmp_path / 'state'
    patch = proposal(tmp_path, state, text='x=2\n')
    started, release, finished = (threading.Event() for _ in range(3))
    commands = AssistantRuntime(state).commands(Workspace(tmp_path), 'assistant')
    assert asyncio.run(commands.apply((patch.id, '--yes'))).ok

    def run(proposal, workspace, *, checks, cancel):
        started.set()
        assert cancel.wait(5)
        assert release.wait(5)
        finished.set()
        if cleanup_failed:
            raise ProcessCleanupError('descendant still running')
        return VerificationResult('cancelled', ())

    commands.verification.run = run

    async def journey():
        task = asyncio.create_task(commands.verify((patch.id, '--check', 'ast')))
        assert await asyncio.to_thread(started.wait, 5)
        try:
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        if cleanup_failed:
            result = await task
            assert not result.ok and result.data['error_kind'] == 'execution'
            assert 'descendant still running' in result.message
        else:
            with pytest.raises(asyncio.CancelledError):
                await task
        assert finished.is_set()

    asyncio.run(journey())


def test_review_and_explain_share_one_runtime_provider(tmp_path, monkeypatch):
    from python_lab.assistant.models import CodeReference

    (tmp_path / 'bug.py').write_text('x=1\n')
    made = []
    class Provider:
        def __init__(self, settings):
            made.append(self)
            self.calls = []

        async def generate(self, request):
            self.calls.append(request.action)
            return AssistantAnswer('ok', 'ok', (), (CodeReference('bug.py', 1, 1),), 0, Usage(1, 1))

        async def review(self, request):
            self.calls.append(request.action)
            return ReviewReply(AssistantAnswer('ok', 'ok', (), (), 0, Usage(1, 1)), ())

        async def aclose(self):
            pass

    monkeypatch.setattr('python_lab.cli.OpenAIProvider', Provider)
    runtime = AssistantRuntime(tmp_path / 'state')
    async def run():
        first = runtime.commands(Workspace(tmp_path), 'assistant')
        assert (await first.explain(('bug.py',))).ok
        second = runtime.commands(Workspace(tmp_path), 'assistant')
        assert (await second.review(('bug.py',))).ok
        await runtime.aclose()
    asyncio.run(run())
    assert len(made) == 1 and made[0].calls == ['explain', 'review']


def test_verify_and_apply_never_discover_pytest_implicitly(tmp_path, capsys):
    (tmp_path / 'bug.py').write_text('x=1\n')
    sentinel = tmp_path / 'executed'
    (tmp_path / 'conftest.py').write_text(f'from pathlib import Path\nPath({str(sentinel)!r}).write_text("ran")\n')
    state = tmp_path / 'state'
    patch = proposal(tmp_path, state, text='x=2\n')
    assert invoke(capsys, tmp_path, state, 'verify', patch.id)[1]['data']['status'] == 'unverified'
    assert invoke(capsys, tmp_path, state, 'apply', patch.id, '--yes')[0] == 0
    assert invoke(capsys, tmp_path, state, 'verify', patch.id, '--check', 'ast')[0] == 0
    assert not sentinel.exists()
