from dataclasses import FrozenInstanceError
import hashlib
from pathlib import Path

import pytest

from python_lab.app import ApplicationError
from python_lab.assistant import (
    AssistantAnswer, AssistantError, AssistantRequest, CodeReference,
    SourceFile, Usage, WorkspaceSnapshot, validate_answer,
)


def source(text="one\r\ntwo\n", path="main.py"):
    return SourceFile(path=path, text=text, sha256=hashlib.sha256(text.encode()).hexdigest())


@pytest.fixture
def snapshot(tmp_path):
    return WorkspaceSnapshot(root=tmp_path, sources=(source(),))


@pytest.fixture
def answer_payload():
    return {
        "summary": "A summary", "explanation": "An explanation", "steps": ["Read", "Test"],
        "references": [{"path": "main.py", "start_line": 1, "end_line": 2}],
        "assistance_level": 2, "usage": {"input_tokens": 10, "output_tokens": 20},
    }


def test_valid_answer_is_immutable_and_preserves_exact_contract(snapshot, answer_payload):
    answer = validate_answer(answer_payload, snapshot)
    assert answer == AssistantAnswer(
        "A summary", "An explanation", ("Read", "Test"),
        (CodeReference("main.py", 1, 2),), 2, Usage(10, 20),
    )
    answer_payload["steps"].append("mutated")
    answer_payload["references"][0]["path"] = "mutated.py"
    answer_payload["usage"]["input_tokens"] = 999
    assert answer.steps == ("Read", "Test")
    assert answer.references == (CodeReference("main.py", 1, 2),)
    assert answer.usage == Usage(10, 20)
    with pytest.raises(FrozenInstanceError):
        answer.summary = "changed"


@pytest.mark.parametrize("field", ["summary", "explanation", "steps", "references", "assistance_level", "usage"])
def test_required_answer_fields_cannot_be_missing(snapshot, answer_payload, field):
    del answer_payload[field]
    with pytest.raises(AssistantError):
        validate_answer(answer_payload, snapshot)


def test_answer_rejects_extra_fields_including_model_mission_id(snapshot, answer_payload):
    answer_payload["mission_id"] = "model-selected-mission"
    with pytest.raises(AssistantError):
        validate_answer(answer_payload, snapshot)


@pytest.mark.parametrize("field,value", [
    ("summary", 3), ("summary", None), ("explanation", []),
    ("steps", "not an array"), ("steps", ["valid", 1]), ("steps", None),
    ("references", "main.py"), ("references", [1]), ("references", None),
    ("usage", None), ("usage", []),
])
def test_answer_rejects_invalid_field_types(snapshot, answer_payload, field, value):
    answer_payload[field] = value
    with pytest.raises(AssistantError):
        validate_answer(answer_payload, snapshot)


@pytest.mark.parametrize("value", [-1, 5, True, False, 2.0, "2", None])
def test_answer_level_requires_integer_in_range(snapshot, answer_payload, value):
    answer_payload["assistance_level"] = value
    with pytest.raises(AssistantError):
        validate_answer(answer_payload, snapshot)


@pytest.mark.parametrize("value", [0, 4])
def test_answer_level_includes_both_boundaries(snapshot, answer_payload, value):
    answer_payload["assistance_level"] = value
    assert validate_answer(answer_payload, snapshot).assistance_level == value


@pytest.mark.parametrize("field", ["input_tokens", "output_tokens"])
@pytest.mark.parametrize("value", [-1, True, False, 1.0, "1", None])
def test_answer_usage_rejects_negative_or_non_integer_tokens(snapshot, answer_payload, field, value):
    answer_payload["usage"][field] = value
    with pytest.raises(AssistantError):
        validate_answer(answer_payload, snapshot)


@pytest.mark.parametrize("usage", [{"input_tokens": 1}, {"output_tokens": 2}, {"input_tokens": 1, "output_tokens": 2, "cost": 1}])
def test_usage_requires_exact_fields(snapshot, answer_payload, usage):
    answer_payload["usage"] = usage
    with pytest.raises(AssistantError):
        validate_answer(answer_payload, snapshot)


def test_zero_token_usage_is_valid(snapshot, answer_payload):
    answer_payload["usage"] = {"input_tokens": 0, "output_tokens": 0}
    assert validate_answer(answer_payload, snapshot).usage == Usage(0, 0)


def test_response_reference_must_exist(snapshot, answer_payload):
    answer_payload["references"][0]["end_line"] = 3
    with pytest.raises(AssistantError):
        validate_answer(answer_payload, snapshot)


@pytest.mark.parametrize("field,value", [
    ("path", "outside.py"), ("path", "./main.py"), ("path", "../main.py"), ("path", 1),
    ("start_line", 0), ("start_line", -1), ("start_line", 3),
    ("start_line", True), ("start_line", 1.0), ("start_line", "1"),
    ("end_line", 0), ("end_line", True), ("end_line", 2.0), ("end_line", "2"),
])
def test_references_require_selected_path_and_existing_integer_line_range(snapshot, answer_payload, field, value):
    answer_payload["references"][0][field] = value
    with pytest.raises(AssistantError):
        validate_answer(answer_payload, snapshot)


def test_reference_range_cannot_be_reversed(snapshot, answer_payload):
    answer_payload["references"] = [{"path": "main.py", "start_line": 2, "end_line": 1}]
    with pytest.raises(AssistantError):
        validate_answer(answer_payload, snapshot)


@pytest.mark.parametrize("reference", [
    {"path": "main.py", "start_line": 1},
    {"path": "main.py", "start_line": 1, "end_line": 1, "verified": True},
])
def test_reference_requires_exact_fields(snapshot, answer_payload, reference):
    answer_payload["references"] = [reference]
    with pytest.raises(AssistantError):
        validate_answer(answer_payload, snapshot)


def test_zero_line_file_cannot_be_referenced(tmp_path, answer_payload):
    empty = WorkspaceSnapshot(tmp_path, (source(text=""),))
    answer_payload["references"] = [{"path": "main.py", "start_line": 1, "end_line": 1}]
    with pytest.raises(AssistantError):
        validate_answer(answer_payload, empty)


def test_answer_may_have_no_references(snapshot, answer_payload):
    answer_payload["references"] = []
    assert validate_answer(answer_payload, snapshot).references == ()


def test_reference_validation_uses_captured_text_after_disk_changes(snapshot, answer_payload):
    (snapshot.root / "main.py").write_text("only one line\n", encoding="utf-8")
    assert validate_answer(answer_payload, snapshot).references == (CodeReference("main.py", 1, 2),)


@pytest.mark.parametrize("payload", [None, [], "answer", True])
def test_answer_payload_must_be_mapping(snapshot, payload):
    with pytest.raises(AssistantError):
        validate_answer(payload, snapshot)


def test_answer_validation_requires_snapshot(answer_payload):
    with pytest.raises(AssistantError):
        validate_answer(answer_payload, None)


def test_request_preserves_local_session_mission(snapshot):
    request = AssistantRequest("review", "Help", "tutor", 4, snapshot, "trace", "011")
    assert request.action == "review"
    assert request.mode == "tutor"
    assert request.level == 4
    assert request.mission_id == "011"
    assert request.traceback == "trace"
    assert request.snapshot is snapshot
    with pytest.raises(FrozenInstanceError):
        request.mission_id = "changed"


@pytest.mark.parametrize("field,value", [
    ("action", "execute"), ("action", True), ("mode", "teacher"),
    ("level", -1), ("level", 5), ("level", True), ("level", 2.0),
    ("prompt", 1), ("traceback", []), ("mission_id", 11), ("snapshot", None),
])
def test_request_rejects_invalid_contract_values(snapshot, field, value):
    values = dict(action="explain", prompt="Help", mode="assistant", level=0, snapshot=snapshot)
    values[field] = value
    with pytest.raises(AssistantError):
        AssistantRequest(**values)


@pytest.mark.parametrize("action", ["explain", "diagnose", "review", "exercise"])
@pytest.mark.parametrize("mode", ["assistant", "tutor"])
def test_request_supports_all_spec_actions_and_modes(snapshot, action, mode):
    request = AssistantRequest(action, "Help", mode, 0, snapshot)
    assert request.traceback is None
    assert request.mission_id is None


@pytest.mark.parametrize("size,allowed", [(32768, True), (32769, False)])
def test_request_traceback_byte_boundary(tmp_path, size, allowed):
    empty = WorkspaceSnapshot(tmp_path, ())
    if allowed:
        assert AssistantRequest("diagnose", "", "assistant", 0, empty, "a" * size).traceback == "a" * size
    else:
        with pytest.raises(AssistantError):
            AssistantRequest("diagnose", "", "assistant", 0, empty, "a" * size)


@pytest.mark.parametrize("extra,allowed", [(0, True), (1, False)])
def test_request_combines_prompt_traceback_and_source_byte_limits(tmp_path, extra, allowed):
    selected = WorkspaceSnapshot(tmp_path, (source("a" * 32768),))
    prompt = "á" * 32768 + "a" * extra
    if allowed:
        request = AssistantRequest("explain", prompt, "assistant", 0, selected, "a" * 32768)
        assert request.prompt == prompt
    else:
        with pytest.raises(AssistantError):
            AssistantRequest("explain", prompt, "assistant", 0, selected, "a" * 32768)


@pytest.mark.parametrize("field", ["prompt", "traceback"])
def test_request_rejects_unencodable_surrogate_text(snapshot, field):
    values = dict(action="explain", prompt="Help", mode="assistant", level=0, snapshot=snapshot)
    values[field] = "\ud800"
    with pytest.raises(AssistantError):
        AssistantRequest(**values)


@pytest.mark.parametrize("factory", [
    lambda snapshot: snapshot,
    lambda snapshot: snapshot.sources[0],
    lambda snapshot: CodeReference("main.py", 1, 1),
    lambda snapshot: Usage(0, 0),
])
def test_shared_types_are_frozen(snapshot, factory):
    value = factory(snapshot)
    field = next(iter(value.__dataclass_fields__))
    with pytest.raises(FrozenInstanceError):
        setattr(value, field, None)


def test_snapshot_requires_immutable_source_tuple(tmp_path):
    with pytest.raises(AssistantError):
        WorkspaceSnapshot(tmp_path, [source()])


def test_public_assistant_error_is_application_error():
    assert issubclass(AssistantError, ApplicationError)
