import asyncio
from dataclasses import asdict
import json
import threading
from types import SimpleNamespace

import pytest

from python_lab.analysis import AnalysisReport, ToolCheck
from python_lab.assistant.errors import AssistantError
from python_lab.assistant.models import (
    AssistantAnswer,
    AssistantRequest,
    FileChange,
    ReviewReply,
    Usage,
)
from python_lab.assistant.patches import PatchService
from python_lab.assistant.review import ReviewService
from python_lab.assistant.openai_provider import OpenAIProvider
from python_lab.assistant.provider import UsageBudget
from python_lab.assistant.settings import AssistantSettings
from python_lab.workspace import Workspace


def request(tmp_path):
    (tmp_path / "a.py").write_text("x=1\n")
    snap = Workspace(tmp_path).snapshot([tmp_path / "a.py"])
    return AssistantRequest("review", "refactor", "assistant", 3, snap)


class Analysis:
    def inspect(self, snapshot, *, cancel=None):
        return AnalysisReport(
            (ToolCheck("ast", "passed", ()), ToolCheck("ruff", "unavailable", ()))
        )


class History:
    def __init__(self):
        self.items = []

    def append(self, request, answer, *, request_id):
        self.items.append((request, answer, request_id))


class Provider:
    def __init__(self, reply):
        self.reply = reply

    async def review(self, request):
        return self.reply


def answer():
    return AssistantAnswer("Review", "Keep the API", (), (), 2, Usage(10, 5))


def test_local_review_needs_no_provider_or_history(tmp_path):
    req = request(tmp_path)
    history = History()
    result = asyncio.run(
        ReviewService(
            Analysis(),
            None,
            PatchService(Workspace(tmp_path), tmp_path / ".state"),
            history,
        ).review(req)
    )
    assert result.analysis.checks[0].tool == "ast"
    assert result.advice is None and result.proposals == () and history.items == []


def test_review_rejects_unselected_change_without_saving_history(tmp_path):
    req = request(tmp_path)
    history = History()
    reply = ReviewReply(
        answer(), (FileChange("other.py", req.snapshot.sources[0].sha256, "x=2\n"),)
    )
    with pytest.raises(AssistantError):
        asyncio.run(
            ReviewService(
                Analysis(),
                Provider(reply),
                PatchService(Workspace(tmp_path), tmp_path / ".state"),
                history,
            ).review(req)
        )
    assert history.items == [] and not (tmp_path / "other.py").exists()


def test_review_creates_local_id_and_persists_single_file_proposal(tmp_path):
    req = request(tmp_path)
    history = History()
    change = FileChange("a.py", req.snapshot.sources[0].sha256, "x=2\n")
    patches = PatchService(Workspace(tmp_path), tmp_path / ".state")
    result = asyncio.run(
        ReviewService(
            Analysis(), Provider(ReviewReply(answer(), (change,))), patches, history
        ).review(req)
    )
    assert result.advice == answer() and len(result.proposals) == 1
    proposal = result.proposals[0]
    assert proposal.change == change and proposal.selected_paths == ("a.py",)
    assert patches.load(proposal.id) == proposal
    assert (tmp_path / "a.py").read_text() == "x=1\n"
    assert len(history.items) == 1


def test_review_provider_uses_one_budgeted_structured_sdk_call(tmp_path, monkeypatch):
    req = request(tmp_path)
    calls = []
    payload = {
        "answer": {k: v for k, v in asdict(answer()).items() if k != "usage"},
        "changes": [
            {
                "path": "a.py",
                "before_sha256": req.snapshot.sources[0].sha256,
                "after_text": "x=2\n",
            }
        ],
    }

    class Client:
        def __init__(self, **kwargs):
            self.responses = self
            assert kwargs["max_retries"] == 0

        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                status="completed",
                output_text=json.dumps(payload),
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            )

        async def close(self):
            pass

    import sys

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=Client))
    monkeypatch.setenv("LAB_API_KEY", "local-dummy")
    provider = OpenAIProvider(
        AssistantSettings("openai", "chosen-model"), budget=UsageBudget(2000)
    )
    reply = asyncio.run(provider.review(req))
    assert reply.changes[0].path == "a.py" and reply.answer.usage == Usage(10, 5)
    assert len(calls) == 1 and calls[0]["text"]["format"]["name"] == "review_reply"
    payload["changes"][0]["path"] = "../outside.py"
    with pytest.raises(AssistantError):
        asyncio.run(provider.review(req))


def test_official_sdk_review_uses_local_mock_only(tmp_path, monkeypatch):
    sdk = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx2")
    req = request(tmp_path)
    captured = []
    payload = {
        "answer": {k: v for k, v in asdict(answer()).items() if k != "usage"},
        "changes": [
            {
                "path": "a.py",
                "before_sha256": req.snapshot.sources[0].sha256,
                "after_text": "x=2\n",
            }
        ],
    }
    real_client = sdk.AsyncOpenAI

    def local_response(http_request):
        captured.append(json.loads(http_request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp_local",
                "object": "response",
                "created_at": 0,
                "status": "completed",
                "model": "chosen-model",
                "error": None,
                "incomplete_details": None,
                "instructions": None,
                "metadata": {},
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
                "output": [
                    {
                        "id": "msg_local",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(payload),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    monkeypatch.setattr(
        sdk,
        "AsyncOpenAI",
        lambda **kwargs: real_client(
            **kwargs,
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(local_response)
            ),
        ),
    )
    monkeypatch.setenv("LAB_API_KEY", "local-no-network-dummy-key")

    async def run():
        provider = OpenAIProvider(AssistantSettings("openai", "chosen-model"))
        try:
            return await provider.review(req)
        finally:
            await provider.aclose()

    reply = asyncio.run(run())
    assert reply.changes[0].path == "a.py" and reply.answer.usage == Usage(10, 5)
    assert (
        len(captured) == 1
        and captured[0]["text"]["format"]["schema"]["properties"]["changes"]
    )
    assert "tools" not in captured[0]


def test_review_rejects_patch_service_bound_to_other_workspace(tmp_path):
    selected = tmp_path / "selected"
    other = tmp_path / "other"
    selected.mkdir()
    other.mkdir()
    req = request(selected)
    (other / "a.py").write_text("x=1\n")
    changes = (FileChange("a.py", req.snapshot.sources[0].sha256, "x=2\n"),)
    history = History()
    with pytest.raises(AssistantError, match="workspace"):
        asyncio.run(
            ReviewService(
                Analysis(),
                Provider(ReviewReply(answer(), changes)),
                PatchService(Workspace(other), other / ".state"),
                history,
            ).review(req)
        )
    assert history.items == [] and not (other / ".state").exists()


def test_review_contracts_are_exported_from_public_modules():
    from python_lab.assistant import ReviewProvider as PublicReviewProvider
    from python_lab.assistant import ReviewReply as PublicReviewReply
    from python_lab.assistant.provider import ReviewProvider as ProviderReviewProvider

    assert PublicReviewProvider is ProviderReviewProvider
    assert PublicReviewReply is ReviewReply


def test_review_without_provider_reports_real_local_ruff_finding(tmp_path):
    from python_lab.analysis import AnalysisService

    (tmp_path / 'a.py').write_text('import os\n')
    snapshot = Workspace(tmp_path).snapshot([tmp_path / 'a.py'])
    req = AssistantRequest('review', 'Review', 'assistant', 2, snapshot)
    result = asyncio.run(ReviewService(AnalysisService(), None,
        PatchService(Workspace(tmp_path), tmp_path / '.state'), History()).review(req))
    assert result.advice is None and result.proposals == ()
    assert any(check.tool == 'ruff' and check.status == 'failed' and
               any(issue.code == 'F401' for issue in check.issues) for check in result.analysis.checks)


@pytest.mark.parametrize("cleanup_failed", [False, True])
def test_repeated_review_cancellation_waits_for_cleanup(tmp_path, cleanup_failed):
    from python_lab.analysis import AnalysisCancelled
    from python_lab.runtime.processes import ProcessCleanupError

    req = request(tmp_path)
    started, release, finished = (threading.Event() for _ in range(3))
    history = History()

    class SlowAnalysis:
        def inspect(self, snapshot, *, cancel=None):
            started.set()
            assert cancel.wait(5)
            assert release.wait(5)
            finished.set()
            if cleanup_failed:
                raise ProcessCleanupError("descendant still running")
            raise AnalysisCancelled("cancelled")

    class NeverProvider:
        async def review(self, request):
            pytest.fail("Cancelled review must not send a provider request")

    service = ReviewService(
        SlowAnalysis(), NeverProvider(),
        PatchService(Workspace(tmp_path), tmp_path / ".state"), history,
    )

    async def run():
        task = asyncio.create_task(service.review(req))
        assert await asyncio.to_thread(started.wait, 5)
        try:
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        expected = AssistantError if cleanup_failed else asyncio.CancelledError
        with pytest.raises(expected):
            await task
        assert finished.is_set()

    asyncio.run(run())
    assert history.items == [] and not (tmp_path / ".state").exists()
