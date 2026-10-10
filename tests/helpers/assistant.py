"""Network-free providers and real-reference B1 fixtures."""

import asyncio

from python_lab.assistant.models import (
    AssistantAnswer, AssistantRequest, CodeReference, Usage, WorkspaceSnapshot,
)


class RecordingProvider:
    def __init__(self, answer: AssistantAnswer):
        self.answer = answer
        self.requests: list[AssistantRequest] = []

    async def generate(self, request: AssistantRequest) -> AssistantAnswer:
        self.requests.append(request)
        return self.answer


class BlockingProvider:
    def __init__(self, started: asyncio.Event):
        self.started = started

    async def generate(self, request: AssistantRequest) -> AssistantAnswer:
        self.started.set()
        await asyncio.Future()
        raise AssertionError("Unreachable")


def sample_request(snapshot: WorkspaceSnapshot, *, level: int = 0, mission_id: str | None = None) -> AssistantRequest:
    return AssistantRequest("explain", "Explique", "tutor", level, snapshot, mission_id=mission_id)


def sample_answer(snapshot: WorkspaceSnapshot, *, level: int = 0) -> AssistantAnswer:
    return AssistantAnswer(
        "Resumo", "Explicação", ("Leia a linha",),
        (CodeReference(snapshot.sources[0].path, 1, 1),), level, Usage(10, 5),
    )
