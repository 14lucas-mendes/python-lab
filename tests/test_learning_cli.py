"""D5 exercises real adapters and local draft boundaries without remote calls."""
import asyncio
import copy
from dataclasses import replace
import importlib
import json
from pathlib import Path

import pytest
from rich.console import Console
from io import StringIO

from python_lab.cli import PythonLabCLI, build_app, main
from python_lab.commands import CommandDispatcher, parse_command
from python_lab.exercises.service import ExerciseService
from python_lab.runtime.processes import ProcessRunner
from tests.test_exercise_drafts import sample_draft

ROOT = Path(__file__).resolve().parents[1]


def learning(app, state, provider=None):
    module = importlib.import_module('python_lab.learning_commands')
    return module.LearningCommands(app, provider, ExerciseService(state, ProcessRunner(), catalog_dir=ROOT))


def dispatch(commands, line):
    dispatcher = CommandDispatcher()
    commands.register(dispatcher)
    return asyncio.run(dispatcher.dispatch_async(parse_command(line)))


def test_practice_command_does_not_unlock_missions(app, tmp_path):
    before = copy.deepcopy(app.progress)
    commands = learning(app, tmp_path / 'state')
    dispatcher = CommandDispatcher()
    commands.register(dispatcher)
    result = dispatcher.dispatch(parse_command('/practice'))
    assert result.ok and result.data['recommendations']
    assert 'registrad' in result.message
    assert app.progress == before


def test_cli_practice_json_offline_and_workspace_separate(tmp_path, capsys):
    state = tmp_path / 'state'
    project = tmp_path / 'project'
    project.mkdir()
    assert main(['practice', '--project', str(project), '--data-dir', str(state), '--json']) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload['schema_version'] == 1 and payload['action'] == 'practice'
    assert payload['data']['recommendations'][0]['mission_id'] == '001'
    assert build_app(data_dir=state).progress.current_mission_id is None


def test_classic_practice_prints_findings_literal(app, tmp_path):
    stream = StringIO()
    cli = PythonLabCLI(app, Console(file=stream))
    cli.learning = learning(app, tmp_path / 'state')
    before = copy.deepcopy(app.progress)
    assert cli.execute('/practice') is True
    assert 'registrad' in stream.getvalue()
    assert app.progress == before


def test_async_dispatch_is_actionable_without_provider(app, tmp_path):
    dispatcher = CommandDispatcher()
    learning(app, tmp_path / 'state').register(dispatcher)
    sync = dispatcher.dispatch(parse_command('/exercise funções'))
    assert not sync.ok and 'dispatch_async' in sync.message
    result = asyncio.run(dispatcher.dispatch_async(parse_command('/exercise funções')))
    assert not result.ok and result.data['error_kind'] == 'usage'
    assert not (tmp_path / 'state' / 'exercise_drafts').exists()


class DraftProvider:
    def __init__(self):
        self.requests = []
    async def draft(self, request):
        self.requests.append(request)
        return replace(sample_draft(), briefing='[red]Implemente total(values).[/red]')


def test_draft_review_validation_publication_are_distinct(app, tmp_path):
    provider = DraftProvider()
    commands = learning(app, tmp_path / 'state', provider)
    before = copy.deepcopy(app.progress)
    draft = dispatch(commands, '/exercise "somar valores"')
    assert draft.ok and draft.data['status'] == 'draft'
    assert 'return sum(values)' not in draft.message and 'reference' not in draft.data
    assert '[red]' in draft.message  # renderer must treat freeform model text literally
    assert provider.requests[0].action == 'exercise'
    commands.provider = None
    denied = dispatch(commands, '/exercise-validate custom-sum')
    assert not denied.ok and denied.data['error_kind'] == 'usage'
    assert 'privilégios' in denied.message and str(tmp_path / 'state') in denied.message
    assert not (tmp_path / 'state' / 'exercise_validations').exists()
    premature = dispatch(commands, '/exercise-publish custom-sum --yes')
    assert not premature.ok
    checked = dispatch(commands, '/exercise-validate custom-sum --yes')
    assert checked.ok and checked.data['status'] == 'validated'
    assert not (tmp_path / 'state' / 'custom_catalog').exists()
    assert not dispatch(commands, '/exercise-publish custom-sum').ok
    published = dispatch(commands, '/exercise-publish custom-sum --yes')
    assert published.ok and published.data['status'] == 'published'
    assert (tmp_path / 'state' / 'custom_catalog' / 'custom-sum' / 'mission.json').exists()
    assert app.progress == before


def test_cli_saved_draft_works_without_provider_and_staleness_blocks_publish(tmp_path, capsys):
    state = tmp_path / 'state'
    service = ExerciseService(state, ProcessRunner(), catalog_dir=ROOT)
    path = service.save_draft(sample_draft())
    assert main(['exercises', 'validate', 'custom-sum', '--data-dir', str(state), '--json']) == 2
    assert json.loads(capsys.readouterr().out)['data']['error_kind'] == 'usage'
    assert main(['exercises', 'validate', 'custom-sum', '--yes', '--data-dir', str(state), '--json']) == 0
    assert json.loads(capsys.readouterr().out)['data']['status'] == 'validated'
    (path / 'README.md').write_text('Edited briefing', encoding='utf-8')
    assert main(['exercises', 'publish', 'custom-sum', '--yes', '--data-dir', str(state), '--json']) == 2
    assert 'mudou' in json.loads(capsys.readouterr().out)['message']


@pytest.mark.parametrize('identity', ['../escape', '/absolute', 'custom-sum/../other', 'bad\\path'])
def test_ids_resolve_only_inside_store(app, tmp_path, identity):
    result = dispatch(learning(app, tmp_path / 'state'), f'/exercise-validate "{identity}" --yes')
    assert not result.ok and result.data['error_kind'] == 'usage'
    assert not (tmp_path / 'state').exists()


def test_public_catalog_and_bootstrap_reject_installed_conflict(tmp_path):
    from python_lab import catalog
    state = tmp_path / 'state'
    service = ExerciseService(state, ProcessRunner(), catalog_dir=ROOT)
    path = service.save_draft(sample_draft())
    assert service.validate(path, execution_confirmed=True).passed
    service.publish(path, ROOT, approved=True)
    assert len(catalog.load_catalog(ROOT, state / 'custom_catalog')) == 12
    assert len(build_app(data_dir=state).missions) == 12
    metadata = state / 'custom_catalog' / 'custom-sum' / 'mission.json'
    payload = json.loads(metadata.read_text())
    payload['id'] = '001'
    metadata.write_text(json.dumps(payload))
    with pytest.raises(catalog.CatalogError):
        build_app(data_dir=state)


def test_explicit_reference_records_captured_attempt_and_never_completes(app, tmp_path):
    app.start('001')
    commands = learning(app, tmp_path / 'state')
    commands.exercises.save_draft(sample_draft())
    assert 'return sum' not in dispatch(commands, '/exercise-show custom-sum').message
    assert app.current_progress().max_assistance_level == 0
    result = dispatch(commands, '/exercise-show custom-sum --reference --yes')
    assert result.ok and 'return sum' in result.message
    assert result.data['assistance_level'] == 4
    assert app.current_progress().max_assistance_level == 4
    assert app.current_progress().status == 'started'


def test_assisted_learning_journey(app, tmp_path):
    from python_lab.analysis.service import AnalysisService
    from python_lab.assistant.commands import AssistantCommands
    from python_lab.assistant.history import ConversationRepository
    from python_lab.assistant.models import AssistantAnswer, CodeReference, Usage
    from python_lab.assistant.service import AssistantService
    from python_lab.workspace import Workspace
    from tests.helpers.assistant import RecordingProvider
    source = tmp_path / 'student.py'
    source.write_text('def solve():\n    return 0\n', encoding='utf-8')
    suite = tmp_path / 'test_student.py'
    suite.write_text("import os, runpy\ndef test_solution():\n    assert runpy.run_path(os.environ['PYTHON_LAB_SOLUTION'])['solve']() == 2\n", encoding='utf-8')
    app.missions[0] = replace(app.missions[0], test_path=suite, solution_path=source)
    app.start('001')
    app.save_plan(dict(input='number', output='two', steps='return result', risks='wrong constant'))
    assert not app.run_current_tests().passed
    provider = RecordingProvider(AssistantAnswer('[red]Try a constant[/red]', 'Check the required result.', (),
        (CodeReference('student.py', 1, 2),), 1, Usage(4, 2)))
    service = AssistantService(provider, AnalysisService(), ConversationRepository(tmp_path / 'history.sqlite3'),
        on_assistance=app.record_assistance, capture_attempt=app.capture_assistance_attempt)
    commands = AssistantCommands(service, Workspace(tmp_path), 'tutor', app=app)
    hinted = asyncio.run(commands.explain(('student.py', '--level', '1')))
    assert hinted.ok and 'nível 1' in hinted.message
    assert app.current_progress().max_assistance_level == 1
    assert app.current_progress().explanation is None
    source.write_text('def solve():\n    return 2\n', encoding='utf-8')
    assert app.run_current_tests().passed
    assert app.current_progress().status == 'started'
    app.save_explanation('I returned two and checked the function contract with the test.')
    evidence = app.complete_current_mission()
    assert all(item['result'] == 'demonstrated' for item in evidence)
    app.start('001')
    app.save_plan(dict(input='number', output='two', steps='return result', risks='wrong constant'))
    provider.answer = AssistantAnswer('Solution', 'Return two.', (), (CodeReference('student.py', 1, 2),), 4, Usage(4, 2))
    solution = asyncio.run(commands.explain(('student.py', '--level', '4')))
    assert solution.ok and 'nível 4' in solution.message
    assert app.current_progress().status == 'started'
    assert app.current_progress().max_assistance_level == 4
    assert app.run_current_tests().passed
    app.save_explanation('I used the complete solution and checked the same function contract.')
    assert all(item['result'] == 'practicing' for item in app.complete_current_mission())


def test_cli_bad_learning_usage_json_and_no_fabricated_draft(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv('LAB_API_KEY', raising=False)
    assert main(['exercises', 'draft', '--topic', 'sum', '--data-dir', str(tmp_path / 'state'), '--json']) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload['schema_version'] == 1 and not payload['ok']
    assert not (tmp_path / 'state' / 'exercise_drafts').exists()
    assert main(['exercises', 'draft', '--topic', 'sum', '--level', '9', '--json']) == 2
    assert json.loads(capsys.readouterr().out)['data']['error_kind'] == 'usage'


def test_real_cli_fake_provider_draft_and_shared_runtime(app, tmp_path, capsys, monkeypatch):
    import python_lab.cli as cli_module
    provider = DraftProvider()
    class Runtime:
        instances = []
        def __init__(self, data_dir, app=None):
            self.data_dir = data_dir
            self.app = app
            self.provider = provider
            self.calls = 0
            self.closed = False
            self.instances.append(self)
        def get_service(self):
            self.calls += 1
            return self
        async def aclose(self):
            self.closed = True
    monkeypatch.setattr(cli_module, 'AssistantRuntime', Runtime)
    state = tmp_path / 'state'
    assert main(['exercises', 'draft', '--topic', '[red]soma[/red]', '--data-dir', str(state), '--json']) == 0
    generated = json.loads(capsys.readouterr().out)
    assert generated['ok'] and generated['data']['status'] == 'draft'
    assert '[red]' in generated['message'] and 'return sum' not in generated['message']
    assert Runtime.instances[0].closed and Runtime.instances[0].calls == 1
    assert main(['exercises', 'show', 'custom-sum', '--data-dir', str(state), '--json']) == 0
    assert 'return sum' not in json.loads(capsys.readouterr().out)['message']
    assert Runtime.instances[1].calls == 0 and Runtime.instances[1].closed


def test_classic_learning_uses_persistent_action_loop(app, tmp_path):
    import threading
    from types import SimpleNamespace
    class LoopProvider(DraftProvider):
        async def draft(self, request):
            self.loop = asyncio.get_running_loop()
            return await super().draft(request)
    provider = LoopProvider()
    class Runtime:
        data_dir = tmp_path / 'state'
        async def aclose(self):
            self.closed_loop = asyncio.get_running_loop()
        def get_service(self):
            return SimpleNamespace(provider=provider)
    runtime = Runtime()
    cli = PythonLabCLI(app, Console(file=StringIO()), assistant_runtime=runtime)
    cli.learning = learning(app, runtime.data_dir, provider)
    try:
        cli.start_classic_assistant(parse_command('/exercise soma'))
        action = cli._classic_action
        if action is not None:
            assert action['done'].wait(5)
        assert provider.loop is cli._classic_loop
        assert (runtime.data_dir / 'exercise_drafts' / 'custom-sum').exists()
        cli.start_classic_assistant(parse_command('/exercise-show custom-sum'))
        action = cli._classic_action
        if action is not None:
            assert action['done'].wait(5)
        assert provider.loop is cli._classic_loop
    finally:
        cli.close_assistant()
    assert runtime.closed_loop is provider.loop


@pytest.mark.parametrize('source,assertion,diagnostic', [
    ('def value(:\n', 'assert solution.value() == 2', 'SyntaxError'),
    ('def value():\n    return missing_name\n', 'assert solution.value() == 2', 'NameError'),
    ('def value():\n    return "2" + 1\n', 'assert solution.value() == 2', 'TypeError'),
    ('import unavailable_tutor_evaluation_module\n', 'assert solution.value() == 2', 'ModuleNotFoundError'),
    ('def value():\n    return 3\n', 'assert solution.value() == 2', 'AssertionError'),
    ('def value():\n    return 2\n', 'assert solution.value() == 999', 'AssertionError'),
], ids=['syntax', 'names', 'types', 'import', 'logic', 'pytest'])
def test_deterministic_tutor_scenarios(tmp_path, source, assertion, diagnostic):
    from python_lab.test_runner import run_tests
    student = tmp_path / 'student.py'
    student.write_text(source, encoding='utf-8')
    suite = tmp_path / 'tests'
    suite.mkdir()
    (suite / 'conftest.py').write_text('import os, pytest\nfrom pathlib import Path\nfrom python_lab.solution_loader import load_solution\n@pytest.fixture\ndef solution():\n    return load_solution(Path(os.environ["PYTHON_LAB_SOLUTION"]))\n', encoding='utf-8')
    (suite / 'test_contract.py').write_text(f'def test_contract(solution):\n    {assertion}\n', encoding='utf-8')
    result = run_tests(suite, tmp_path, student)
    assert not result.passed and not result.cancelled
    assert result.return_code == 1 and diagnostic in result.output


def test_catalog_override_is_distinct_from_assistant_workspace(tmp_path):
    from shutil import copytree
    catalog = tmp_path / 'catalog'
    copytree(ROOT / 'data', catalog / 'data')
    copytree(ROOT / 'missions', catalog / 'missions')
    state = tmp_path / 'state'
    project = tmp_path / 'assistant-workspace'
    project.mkdir()
    app = build_app(catalog, data_dir=state)
    cli = PythonLabCLI(app, Console(file=StringIO()), assistant_project=project)
    provider = DraftProvider()
    commands = cli.learning_handlers()
    commands.provider = provider
    assert commands.exercises.catalog_dir == catalog.resolve()
    assert dispatch(commands, '/exercise soma').ok
    assert provider.requests[0].snapshot.root == project.resolve()
    assert (state / 'exercise_drafts' / 'custom-sum').exists()
    assert not (project / 'exercise_drafts').exists()
    assert len(app.missions) == 11
    assert all(mission.test_path.is_relative_to(catalog) for mission in app.missions)


def test_practice_links_only_local_scoped_error_metadata(app, tmp_path):
    from python_lab.assistant.history import ConversationRepository
    from python_lab.assistant.models import AssistantAnswer, AssistantRequest, Usage, WorkspaceSnapshot
    state = tmp_path / 'state'
    state.mkdir()
    history = ConversationRepository(state / 'lab.sqlite3')
    workspace = tmp_path / 'project'
    workspace.mkdir()
    request = AssistantRequest('diagnose', 'Inspect error', 'tutor', 0, WorkspaceSnapshot(workspace, ()),
                               traceback='ValueError', mission_id='001')
    history.append(request, AssistantAnswer('Check inputs', 'Inspect the value.', (), (), 0, Usage(1, 1)),
                   request_id='local-request')
    commands = learning(app, state)
    commands.workspace = workspace
    before = (state / 'lab.sqlite3').read_bytes()
    result = commands.practice(())
    assert result.ok
    assert result.data['error_history'][0]['request_id'] == 'local-request'
    assert 'local-request' in result.message
    assert (state / 'lab.sqlite3').read_bytes() == before
    commands.workspace = tmp_path / 'other'
    assert not commands.practice(()).data['error_history']
