import asyncio
from dataclasses import asdict, replace
import hashlib
import importlib
import importlib.util
import json
import sys
from types import SimpleNamespace

import pytest

from python_lab.assistant import AssistantError, SourceFile, Usage, WorkspaceSnapshot
from tests.helpers.assistant import BlockingProvider, RecordingProvider, sample_answer, sample_request


def module(name):
    assert importlib.util.find_spec("python_lab.assistant." + name) is not None, "B3 " + name + " missing"
    return importlib.import_module("python_lab.assistant." + name)


def settings(**kwargs):
    return module("settings").AssistantSettings("openai", "chosen-model", **kwargs)


@pytest.fixture
def snapshot(tmp_path):
    text = "print('source is data')\n"
    return WorkspaceSnapshot(tmp_path, (SourceFile("main.py", text, hashlib.sha256(text.encode()).hexdigest()),))


@pytest.fixture
def fake_sdk(monkeypatch, snapshot):
    state = SimpleNamespace(calls=[], clients=[], error=None, block=False, started=None,
                            response=SimpleNamespace(status="completed", output_text=json.dumps(asdict(sample_answer(snapshot))),
                                                     usage=SimpleNamespace(input_tokens=10, output_tokens=5)))

    class AsyncOpenAI:
        def __init__(self, **kwargs):
            state.clients.append(kwargs)
            self.responses = self

        async def create(self, **kwargs):
            state.calls.append(kwargs)
            if state.started:
                state.started.set()
            if state.block:
                await asyncio.Future()
            if state.error:
                raise state.error
            return state.response

        async def close(self):
            state.closed = True

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=AsyncOpenAI))
    monkeypatch.setenv("LAB_API_KEY", "SECRET-DO-NOT-ECHO")
    return state


def provider(fake_sdk, **kwargs):
    return module("openai_provider").OpenAIProvider(settings(), **kwargs)


def test_output_budget_prevents_another_request():
    budget = module("provider").UsageBudget(limit=20000)
    for _ in range(10):
        reservation = budget.reserve(2000)
        budget.settle(reservation, 2000)
    with pytest.raises(AssistantError, match="orçamento"):
        budget.reserve(2000)


@pytest.mark.parametrize("value", [-1, True, 1.5, "1", None])
def test_budget_rejects_invalid_limit(value):
    with pytest.raises(AssistantError):
        module("provider").UsageBudget(value)


@pytest.mark.parametrize("value", [-1, 0, True, 1.5, "1", None])
def test_budget_rejects_invalid_reservation(value):
    with pytest.raises(AssistantError):
        module("provider").UsageBudget(10).reserve(value)


def test_unknown_usage_retains_reservation_and_settlement_is_single():
    budget = module("provider").UsageBudget(10)
    reservation = budget.reserve(10)
    budget.settle(reservation, None)
    with pytest.raises(AssistantError, match="orçamento"):
        budget.reserve(1)
    with pytest.raises(AssistantError):
        budget.settle(reservation, 0)


@pytest.mark.parametrize("value", [-1, True, 1.5, "1"])
def test_invalid_settlement_does_not_release_reservation(value):
    budget = module("provider").UsageBudget(10)
    reservation = budget.reserve(10)
    with pytest.raises(AssistantError):
        budget.settle(reservation, value)
    with pytest.raises(AssistantError, match="orçamento"):
        budget.reserve(1)


def test_known_usage_releases_unused_tokens_and_overrun_blocks_future_reserves():
    budget = module("provider").UsageBudget(10)
    budget.settle(budget.reserve(10), 2)
    budget.settle(budget.reserve(8), 20)
    with pytest.raises(AssistantError, match="orçamento"):
        budget.reserve(1)


@pytest.mark.parametrize("action", ["explain", "review", "exercise"])
def test_structured_transport_uses_sdk_usage_and_exact_captured_context(fake_sdk, snapshot, action):
    request = replace(sample_request(snapshot, mission_id="local-mission"), action=action, traceback="captured trace")
    fake_sdk.response.output_text = json.dumps({**asdict(sample_answer(snapshot)), "usage": {"input_tokens": 999, "output_tokens": 999}})
    answer = asyncio.run(provider(fake_sdk).generate(request))
    assert answer == sample_answer(snapshot)
    assert len(fake_sdk.calls) == 1
    call = fake_sdk.calls[0]
    assert call["model"] == "chosen-model"
    assert call["max_output_tokens"] == 2000
    assert "tools" not in call
    assert call["text"]["format"]["type"] == "json_schema"
    assert call["text"]["format"]["strict"] is True
    context = json.loads(call["input"][1]["content"])
    assert context["sources"] == [asdict(snapshot.sources[0])]
    assert context["traceback"] == "captured trace"
    assert context["mission_id"] == "local-mission"
    assert context["action"] == action
    assert "data" in call["input"][0]["content"]
    assert fake_sdk.clients[0]["max_retries"] == 0
    assert fake_sdk.clients[0]["timeout"] == 30


def test_budget_is_shared_across_provider_recreation_and_new_session_is_independent(fake_sdk, snapshot):
    budget = module("provider").UsageBudget(2000)
    first = provider(fake_sdk, budget=budget)
    fake_sdk.response.usage.output_tokens = 2000
    asyncio.run(first.generate(sample_request(snapshot)))
    recreated = provider(fake_sdk, budget=budget)
    with pytest.raises(AssistantError, match="orçamento"):
        asyncio.run(recreated.generate(sample_request(snapshot)))
    assert len(fake_sdk.calls) == 1
    asyncio.run(provider(fake_sdk).generate(sample_request(snapshot)))
    assert len(fake_sdk.calls) == 2


@pytest.mark.parametrize("bad_payload", ["not json", "[]", '{"summary":"only"}', None])
def test_invalid_payload_is_charged_using_known_sdk_usage(fake_sdk, snapshot, bad_payload):
    fake_sdk.response.output_text = bad_payload
    fake_sdk.response.usage.output_tokens = 2000
    adapter = provider(fake_sdk, budget=module("provider").UsageBudget(2000))
    with pytest.raises(AssistantError):
        asyncio.run(adapter.generate(sample_request(snapshot)))
    with pytest.raises(AssistantError, match="orçamento"):
        asyncio.run(adapter.generate(sample_request(snapshot)))
    assert len(fake_sdk.calls) == 1


def test_bad_references_use_b1_validation_and_still_charge(fake_sdk, snapshot):
    data = asdict(sample_answer(snapshot))
    data["references"][0]["end_line"] = 100
    fake_sdk.response.output_text = json.dumps(data)
    with pytest.raises(AssistantError, match="Referência"):
        asyncio.run(provider(fake_sdk).generate(sample_request(snapshot)))


@pytest.mark.parametrize("usage", [None, SimpleNamespace(input_tokens=10, output_tokens=None),
    SimpleNamespace(input_tokens=-1, output_tokens=5), SimpleNamespace(input_tokens=True, output_tokens=5),
    SimpleNamespace(input_tokens=10, output_tokens=-1), SimpleNamespace(input_tokens=10, output_tokens=True)])
def test_unknown_or_invalid_sdk_usage_never_releases_reservation(fake_sdk, snapshot, usage):
    fake_sdk.response.usage = usage
    adapter = provider(fake_sdk, budget=module("provider").UsageBudget(2000))
    with pytest.raises(AssistantError):
        asyncio.run(adapter.generate(sample_request(snapshot)))
    with pytest.raises(AssistantError, match="orçamento"):
        asyncio.run(adapter.generate(sample_request(snapshot)))
    assert len(fake_sdk.calls) == 1


@pytest.mark.parametrize("code,message", [(429, "limite"), (401, "autenticação"), (403, "autenticação"), (500, "provider")])
def test_transport_errors_are_sanitized_no_retries_and_hold_reserve(fake_sdk, snapshot, caplog, code, message):
    fake_sdk.error = RuntimeError("SECRET-DO-NOT-ECHO")
    fake_sdk.error.status_code = code
    adapter = provider(fake_sdk, budget=module("provider").UsageBudget(2000))
    with pytest.raises(AssistantError, match=message) as caught:
        asyncio.run(adapter.generate(sample_request(snapshot)))
    assert "SECRET-DO-NOT-ECHO" not in str(caught.value) + caplog.text
    assert caught.value.__cause__ is None
    with pytest.raises(AssistantError, match="orçamento"):
        asyncio.run(adapter.generate(sample_request(snapshot)))
    assert len(fake_sdk.calls) == 1


def test_timeout_is_enforced_and_retains_reserve(fake_sdk, snapshot):
    fake_sdk.block = True
    adapter = module("openai_provider").OpenAIProvider(settings(timeout_seconds=1), budget=module("provider").UsageBudget(2000))
    with pytest.raises(AssistantError, match="tempo"):
        asyncio.run(adapter.generate(sample_request(snapshot)))
    with pytest.raises(AssistantError, match="orçamento"):
        asyncio.run(adapter.generate(sample_request(snapshot)))
    assert len(fake_sdk.calls) == 1


def test_cancellation_propagates_and_shared_budget_blocks_concurrent_send(fake_sdk, snapshot):
    async def run():
        fake_sdk.block = True
        fake_sdk.started = asyncio.Event()
        budget = module("provider").UsageBudget(2000)
        adapter = provider(fake_sdk, budget=budget)
        task = asyncio.create_task(adapter.generate(sample_request(snapshot)))
        await fake_sdk.started.wait()
        with pytest.raises(AssistantError, match="orçamento"):
            await provider(fake_sdk, budget=budget).generate(sample_request(snapshot))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(AssistantError, match="orçamento"):
            budget.reserve(1)
    asyncio.run(run())
    assert len(fake_sdk.calls) == 1


def test_missing_sdk_key_and_model_give_configuration_guidance(monkeypatch):
    adapter = module("openai_provider")
    monkeypatch.setitem(sys.modules, "openai", None)
    monkeypatch.setenv("LAB_API_KEY", "SECRET-DO-NOT-ECHO")
    with pytest.raises(AssistantError, match="assistant"):
        adapter.OpenAIProvider(settings())
    monkeypatch.delenv("LAB_API_KEY")
    with pytest.raises(AssistantError, match="LAB_API_KEY"):
        adapter.OpenAIProvider(settings())
    with pytest.raises(AssistantError, match="model"):
        adapter.OpenAIProvider(module("settings").AssistantSettings("openai", None))


def test_provider_reads_key_only_at_construction_and_can_close(fake_sdk, snapshot, monkeypatch):
    adapter = provider(fake_sdk)
    monkeypatch.delenv("LAB_API_KEY")
    assert asyncio.run(adapter.generate(sample_request(snapshot))).usage == Usage(10, 5)
    asyncio.run(adapter.aclose())
    assert fake_sdk.closed


def test_test_helpers_are_network_free_and_keep_real_reference(snapshot):
    answer = sample_answer(snapshot, level=2)
    request = sample_request(snapshot, level=2, mission_id="local")
    recording = RecordingProvider(answer)
    assert asyncio.run(recording.generate(request)) == answer
    assert recording.requests == [request]
    assert answer.references[0].path == snapshot.sources[0].path
    assert (request.action, request.prompt, request.mode, request.level, request.mission_id) == ("explain", "Explique", "tutor", 2, "local")
    async def cancel():
        started = asyncio.Event()
        task = asyncio.create_task(BlockingProvider(started).generate(request))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(cancel())


@pytest.mark.parametrize("status", ["incomplete", "failed", None])
def test_non_completed_response_is_charged_before_rejection(fake_sdk, snapshot, status):
    fake_sdk.response.status = status
    fake_sdk.response.usage.output_tokens = 2000
    adapter = provider(fake_sdk, budget=module("provider").UsageBudget(2000))
    with pytest.raises(AssistantError, match="incompleta"):
        asyncio.run(adapter.generate(sample_request(snapshot)))
    with pytest.raises(AssistantError, match="orçamento"):
        asyncio.run(adapter.generate(sample_request(snapshot)))
    assert len(fake_sdk.calls) == 1


def test_known_output_is_charged_even_if_input_usage_is_invalid(fake_sdk, snapshot):
    budget = module("provider").UsageBudget(2000)
    fake_sdk.response.usage.input_tokens = -1
    fake_sdk.response.usage.output_tokens = 5
    with pytest.raises(AssistantError):
        asyncio.run(provider(fake_sdk, budget=budget).generate(sample_request(snapshot)))
    budget.reserve(1995)
    with pytest.raises(AssistantError, match="orçamento"):
        budget.reserve(1)


def test_reported_over_budget_output_blocks_next_send(fake_sdk, snapshot):
    fake_sdk.response.usage.output_tokens = 2001
    adapter = provider(fake_sdk, budget=module("provider").UsageBudget(2000))
    assert asyncio.run(adapter.generate(sample_request(snapshot))).usage.output_tokens == 2001
    with pytest.raises(AssistantError, match="orçamento"):
        asyncio.run(adapter.generate(sample_request(snapshot)))
    assert len(fake_sdk.calls) == 1


def test_sdk_timeout_type_is_sanitized_and_not_retried(fake_sdk, snapshot):
    fake_sdk.error = type("APITimeoutError", (Exception,), {})("SECRET-DO-NOT-ECHO")
    with pytest.raises(AssistantError, match="tempo") as caught:
        asyncio.run(provider(fake_sdk).generate(sample_request(snapshot)))
    assert "SECRET-DO-NOT-ECHO" not in str(caught.value)
    assert len(fake_sdk.calls) == 1


def test_sdk_constructor_errors_do_not_expose_key(fake_sdk, monkeypatch):
    def fail(**kwargs):
        raise RuntimeError(kwargs["api_key"])
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=fail))
    with pytest.raises(AssistantError) as caught:
        provider(fake_sdk)
    assert "SECRET-DO-NOT-ECHO" not in str(caught.value)
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("action", ["explain", "review", "exercise"])
def test_future_adapters_reuse_budgeted_transport_with_their_own_validator(fake_sdk, snapshot, action):
    adapter = provider(fake_sdk, budget=module("provider").UsageBudget(2000))
    fake_sdk.response.output_text = '{"item":"local result"}'
    fake_sdk.response.usage.output_tokens = 2000
    schema = {"type": "object", "properties": {"item": {"type": "string"}}, "required": ["item"], "additionalProperties": False}
    def validate(payload, selected, usage):
        assert selected is snapshot
        return (payload["item"], usage)
    request = replace(sample_request(snapshot), action=action)
    result = asyncio.run(adapter.transport.generate(request, schema=schema, schema_name="future_result", validate=validate))
    assert result == ("local result", Usage(10, 2000))
    assert fake_sdk.calls[0]["text"]["format"]["schema"] == schema
    with pytest.raises(AssistantError, match="orçamento"):
        asyncio.run(adapter.generate(sample_request(snapshot)))
    assert len(fake_sdk.calls) == 1


def test_official_sdk_serializes_structured_request_using_only_local_http(snapshot, monkeypatch):
    """Optional integration: the actual pinned SDK sends to a local mock only."""
    sdk = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx2")
    real_client = sdk.AsyncOpenAI
    captured = []
    payload = asdict(sample_answer(snapshot))
    del payload["usage"]

    def local_response(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "resp_local", "object": "response", "created_at": 0,
            "status": "completed", "model": "chosen-model", "error": None,
            "incomplete_details": None, "instructions": None, "metadata": {},
            "parallel_tool_calls": False, "tool_choice": "auto", "tools": [],
            "output": [{"id": "msg_local", "type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": json.dumps(payload), "annotations": []}]}],
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                      "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}},
        })

    def local_client(**kwargs):
        return real_client(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(local_response)))

    monkeypatch.setattr(sdk, "AsyncOpenAI", local_client)
    monkeypatch.setenv("LAB_API_KEY", "local-no-network-dummy-key")
    async def run():
        adapter = module("openai_provider").OpenAIProvider(settings())
        try:
            return await adapter.generate(sample_request(snapshot))
        finally:
            await adapter.aclose()
    assert asyncio.run(run()) == sample_answer(snapshot)
    assert len(captured) == 1
    assert captured[0]["text"]["format"]["schema"] == module("openai_provider").ANSWER_SCHEMA
    assert captured[0]["max_output_tokens"] == 2000
    assert "tools" not in captured[0]
