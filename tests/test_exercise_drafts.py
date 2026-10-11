"""D3 draft boundaries: local review only, bounded content, no SDK imports."""
import asyncio
from dataclasses import asdict, replace
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from python_lab.assistant import AssistantError
from tests.helpers.assistant import sample_request
from tests import test_assistant_provider as provider_fixtures

fake_sdk = provider_fixtures.fake_sdk
snapshot = provider_fixtures.snapshot
settings = provider_fixtures.settings

ROOT = Path(__file__).resolve().parents[1]


def models():
    assert importlib.util.find_spec('python_lab.exercises') is not None, 'D3 exercises missing'
    return importlib.import_module('python_lab.exercises.models')


def sample_draft(id='custom-sum'):
    return models().ExerciseDraft(id, {
        'id': id, 'slug': id, 'title': 'Somar valores', 'summary': 'Implementar soma',
        'skills': ['functions'], 'prerequisites': ['001'], 'cycle': 1,
        'lesson_id': 'lesson_01-python-core', 'success_criteria': ['Soma lista e lista vazia'],
        'tests': 'tests', 'solution': 'starter.py',
        'learning_objectives': [], 'reflection_questions': [],
    }, 'Implemente total(values).', 'def total(values):\n    return None\n',
        'def total(values):\n    return sum(values)\n',
        'def test_total(solution):\n    assert solution.total([2, 3]) == 5\n\ndef test_empty(solution):\n    assert solution.total([]) == 0\n')


def service(tmp_path, runner=None):
    from python_lab.runtime.processes import ProcessRunner
    module = importlib.import_module('python_lab.exercises.service')
    return module.ExerciseService(tmp_path / 'state', runner or ProcessRunner(), catalog_dir=ROOT)


def test_schema_and_save_are_local_and_reference_is_private(tmp_path, monkeypatch):
    draft = sample_draft()
    from python_lab.runtime.processes import ProcessRunner
    monkeypatch.setattr(ProcessRunner, 'run', lambda *a, **kw: pytest.fail('save executed code'))
    path = service(tmp_path).save_draft(draft)
    assert path.is_relative_to(tmp_path / 'state' / 'exercise_drafts')
    assert (path / 'starter.py').read_text() == draft.starter
    assert (path / 'reference_solution.py').read_text() == draft.reference
    assert draft.reference not in repr(draft)
    assert (path / 'criteria.json').exists()
    with pytest.raises(AssistantError):
        service(tmp_path).save_draft(draft)


@pytest.mark.parametrize('id', ['../escape', '/absolute', '.', '', 'a/b', 'a\\b'])
def test_ids_cannot_escape(tmp_path, id):
    with pytest.raises(AssistantError):
        service(tmp_path).save_draft(sample_draft(id))
    assert not (tmp_path / 'escape').exists()


@pytest.mark.parametrize('field,value', [
    ('skills', ['unknown']), ('skills', 'functions'), ('prerequisites', ['unknown']),
    ('prerequisites', ['custom-sum']), ('cycle', True), ('cycle', 14),
    ('lesson_id', 'unknown'), ('lesson_id', 'lesson_03-testes-git'),
    ('tests', '../outside'), ('solution', 'package/main.py'), ('id', 'other'),
    ('title', ''), ('success_criteria', []), ('learning_objectives', [5]),
])
def test_invalid_mission_never_saves(tmp_path, field, value):
    draft = sample_draft()
    draft.mission[field] = value
    with pytest.raises(AssistantError):
        service(tmp_path).save_draft(draft)
    assert not (tmp_path / 'state' / 'exercise_drafts' / draft.id).exists()


@pytest.mark.parametrize('field,value', [('briefing', '\ud800'), ('tests', ''), ('starter', 'x' * 262145)])
def test_text_is_strict_utf8_and_bounded(tmp_path, field, value):
    with pytest.raises(AssistantError):
        service(tmp_path).save_draft(replace(sample_draft(), **{field: value}))


def test_protocol_is_independent_of_sdk_and_draft_reuses_shared_budget(fake_sdk, snapshot):
    models()
    from python_lab.assistant.openai_provider import OpenAIProvider
    from python_lab.assistant.provider import UsageBudget
    budget = UsageBudget(2000)
    adapter = OpenAIProvider(settings(), budget=budget)
    fake_sdk.response.output_text = json.dumps(asdict(sample_draft()))
    fake_sdk.response.usage.output_tokens = 2000
    result = asyncio.run(adapter.draft(replace(sample_request(snapshot), action='exercise')))
    assert result == sample_draft()
    assert len(fake_sdk.calls) == 1
    assert fake_sdk.calls[0]['text']['format']['name'] == 'exercise_draft'
    with pytest.raises(AssistantError, match='orçamento'):
        asyncio.run(adapter.generate(sample_request(snapshot)))
    assert len(fake_sdk.calls) == 1


def test_invalid_draft_is_charged_before_validation(fake_sdk, snapshot):
    models()
    from python_lab.assistant.openai_provider import OpenAIProvider
    from python_lab.assistant.provider import UsageBudget
    adapter = OpenAIProvider(settings(), budget=UsageBudget(2000))
    fake_sdk.response.output_text = '{"id":"../escape"}'
    fake_sdk.response.usage.output_tokens = 2000
    with pytest.raises(AssistantError):
        asyncio.run(adapter.draft(replace(sample_request(snapshot), action='exercise')))
    with pytest.raises(AssistantError, match='orçamento'):
        asyncio.run(adapter.review(replace(sample_request(snapshot), action='review')))
    assert len(fake_sdk.calls) == 1


def test_three_real_adapters_share_trusted_usage_across_provider_recreation(fake_sdk, snapshot):
    from tests.helpers.assistant import sample_answer
    from python_lab.assistant.openai_provider import OpenAIProvider
    from python_lab.assistant.provider import UsageBudget
    budget = UsageBudget(6000)
    request = sample_request(snapshot)
    fake_sdk.response.usage.output_tokens = 2000
    adapter = OpenAIProvider(settings(), budget=budget)
    asyncio.run(adapter.generate(request))
    answer_payload = asdict(sample_answer(snapshot))
    del answer_payload['usage']
    fake_sdk.response.output_text = json.dumps({'answer': answer_payload, 'changes': []})
    asyncio.run(adapter.review(replace(request, action='review')))
    fake_sdk.response.output_text = json.dumps(asdict(sample_draft()))
    asyncio.run(adapter.draft(replace(request, action='exercise')))
    assert len(fake_sdk.calls) == 3
    with pytest.raises(AssistantError, match='orçamento'):
        asyncio.run(OpenAIProvider(settings(), budget=budget).draft(replace(request, action='exercise')))
    assert len(fake_sdk.calls) == 3
    asyncio.run(OpenAIProvider(settings()).draft(replace(request, action='exercise')))
    assert len(fake_sdk.calls) == 4


def test_wrong_draft_action_rejected_before_send(fake_sdk, snapshot):
    from python_lab.assistant.openai_provider import OpenAIProvider
    with pytest.raises(AssistantError, match='exercício'):
        asyncio.run(OpenAIProvider(settings()).draft(sample_request(snapshot)))
    assert fake_sdk.calls == []


def test_exercise_provider_import_does_not_import_sdk():
    import subprocess
    import sys
    completed = subprocess.run([sys.executable, '-c',
        'import sys; from python_lab.exercises.models import ExerciseProvider; assert "openai" not in sys.modules'],
        cwd=ROOT, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


def test_official_sdk_draft_uses_local_http_only(snapshot, monkeypatch):
    sdk = pytest.importorskip('openai')
    httpx = pytest.importorskip('httpx2')
    from python_lab.assistant.openai_provider import OpenAIProvider, EXERCISE_SCHEMA
    real_client = sdk.AsyncOpenAI
    captured = []
    def response(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={
            'id': 'resp_exercise', 'object': 'response', 'created_at': 0, 'status': 'completed',
            'model': 'chosen-model', 'error': None, 'incomplete_details': None,
            'instructions': None, 'metadata': {}, 'parallel_tool_calls': False,
            'tool_choice': 'auto', 'tools': [],
            'output': [{'id': 'msg_exercise', 'type': 'message', 'role': 'assistant',
                'status': 'completed', 'content': [{'type': 'output_text',
                    'text': json.dumps(asdict(sample_draft())), 'annotations': []}]}],
            'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15,
                'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': {'reasoning_tokens': 0}},
        })
    monkeypatch.setattr(sdk, 'AsyncOpenAI', lambda **kw: real_client(**kw,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(response))))
    monkeypatch.setenv('LAB_API_KEY', 'offline-dummy-exercise-key')
    async def run():
        adapter = OpenAIProvider(settings())
        try:
            return await adapter.draft(replace(sample_request(snapshot), action='exercise'))
        finally:
            await adapter.aclose()
    assert asyncio.run(run()) == sample_draft()
    assert len(captured) == 1 and 'tools' not in captured[0]
    assert captured[0]['text']['format']['schema'] == EXERCISE_SCHEMA


def test_draft_cancellation_keeps_shared_session_reservation(fake_sdk, snapshot):
    from python_lab.assistant.openai_provider import OpenAIProvider
    from python_lab.assistant.provider import UsageBudget
    async def run():
        fake_sdk.block = True
        fake_sdk.started = asyncio.Event()
        budget = UsageBudget(2000)
        adapter = OpenAIProvider(settings(), budget=budget)
        pending = asyncio.create_task(adapter.draft(replace(sample_request(snapshot), action='exercise')))
        await fake_sdk.started.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        with pytest.raises(AssistantError, match='orçamento'):
            await adapter.generate(sample_request(snapshot))
    asyncio.run(run())
    assert len(fake_sdk.calls) == 1


def test_required_positional_constructor_uses_installed_context(tmp_path):
    from python_lab.exercises import ExerciseService
    from python_lab.runtime.processes import ProcessRunner
    svc = ExerciseService(tmp_path / 'user-data', ProcessRunner())
    path = svc.save_draft(sample_draft())
    assert path.parent == tmp_path / 'user-data' / 'exercise_drafts'
    assert svc.catalog_dir == ROOT
