from pathlib import Path
from typing import Any, Literal

import pytest
from botocore.exceptions import ClientError
from pydantic import BaseModel, ConfigDict, Field, JsonValue

from popper.config import load_config
from popper.harness.llm import (
    BedrockLLM,
    FakeLLM,
    LLMError,
    LLMRequest,
    Message,
    ToolCall,
    ToolResult,
    ToolSpec,
    TransientLLMError,
    _from_converse,
    _to_converse,
)
from popper.harness.session import Harness
from popper.harness.storage.recovery import read_events
from popper.harness.storage.store import RunStore


def test_structured_reply_preserves_open_maps() -> None:
    class Shape(BaseModel):
        model_config = ConfigDict(extra="forbid")
        score: float = Field(ge=1, le=10)
        name: str = Field(min_length=1)
        reasons: dict[Literal["cleaning", "model"], str]
        parameters: dict[str, JsonValue]

    original = Shape.model_json_schema()
    payload = {
        "score": 5,
        "name": "analysis",
        "reasons": {"model": "comparison"},
        "parameters": {"custom": {"levels": [1, False, None], "label": "new"}},
    }
    capture = _Capture()
    capture.content = [
        {"text": "Here is the result."},
        {"toolUse": {"toolUseId": "output", "name": "structured_reply", "input": payload}},
    ]
    llm = BedrockLLM.__new__(BedrockLLM)
    llm._client = capture
    result = llm.complete(
        LLMRequest("anthropic.m", "t", "s", (Message("user", "p"),), output_schema=original), 10
    )
    assert Shape.model_validate_json(result.text).model_dump() == payload
    sent = capture.kwargs
    assert sent["toolConfig"]["tools"][0]["toolSpec"]["inputSchema"]["json"] == original
    assert sent["toolConfig"]["toolChoice"] == {"tool": {"name": "structured_reply"}}
    assert "outputConfig" not in sent
    assert result.tool_calls == ()
    assert (result.input_tokens, result.output_tokens) == (1, 1)


@pytest.mark.parametrize(
    "failure", ["missing", "wrong_name", "duplicate", "truncated", "invalid_value"]
)
def test_structured_reply_rejection_retries_and_bills_both_responses(
    tmp_path: Path, failure: str
) -> None:
    class Shape(BaseModel):
        a: int = Field(ge=1)

    reply = {"toolUse": {"toolUseId": "reply", "name": "structured_reply", "input": {"a": 2}}}
    content = {
        "missing": [{"text": '{"a": 2}'}],
        "wrong_name": [{"toolUse": {"toolUseId": "wrong", "name": "other", "input": {"a": 2}}}],
        "duplicate": [
            reply,
            {"toolUse": {"toolUseId": "extra", "name": "structured_reply", "input": {"a": 3}}},
        ],
        "truncated": [reply],
        "invalid_value": [
            {"toolUse": {"toolUseId": "invalid", "name": "structured_reply", "input": {"a": 0}}}
        ],
    }[failure]
    responses = iter(
        [
            {
                "output": {"message": {"content": content}},
                "usage": {"inputTokens": 1, "outputTokens": 1},
                "stopReason": "max_tokens" if failure == "truncated" else "tool_use",
            },
            {
                "output": {"message": {"content": [reply]}},
                "usage": {"inputTokens": 1, "outputTokens": 1},
                "stopReason": "tool_use",
            },
        ]
    )

    class Client:
        def converse(self, **_: Any) -> Any:
            return next(responses)

    llm = BedrockLLM.__new__(BedrockLLM)
    llm._client = Client()
    h = Harness(load_config(env={}), llm, RunStore(tmp_path))
    assert h.ask_model("analyst", schema=Shape, tag="response", system="s", prompt="p").a == 2
    events = read_events(tmp_path)
    assert sum(e["event"] == "schema_rejection" for e in events) == 1
    calls = [e for e in events if e["event"] == "llm_call"]
    assert len(calls) == 2
    assert all(e["usd"] > 0 for e in calls)
    assert h.spent_usd == pytest.approx(sum(e["usd"] for e in calls))


def test_tool_round_trip_wire_format(tmp_path: Path) -> None:
    png = tmp_path / "f.png"
    png.write_bytes(b"PNG")
    call = ToolCall("t1", "inspect_data", {"name": "data"})
    wire = _to_converse(
        [
            Message("user", "hi"),
            Message("assistant", tool_calls=(call,)),
            Message("user", tool_results=(ToolResult("t1", text="cols"),)),
            Message("user", tool_results=(ToolResult("t1", image=png),)),
        ]
    )
    assert wire[0]["content"] == [{"text": "hi"}]
    assert wire[1]["content"] == [
        {"toolUse": {"toolUseId": "t1", "name": "inspect_data", "input": {"name": "data"}}}
    ]
    assert wire[2]["content"] == [
        {"toolResult": {"toolUseId": "t1", "content": [{"text": "cols"}], "status": "success"}}
    ]
    assert wire[3]["content"] == [
        {
            "toolResult": {
                "toolUseId": "t1",
                "content": [{"image": {"format": "png", "source": {"bytes": b"PNG"}}}],
                "status": "success",
            }
        }
    ]


def test_from_converse_reads_tool_calls() -> None:
    resp = {
        "output": {
            "message": {
                "content": [
                    {"text": "thinking"},
                    {"toolUse": {"toolUseId": "a", "name": "submit", "input": {"code": "x"}}},
                ]
            }
        },
        "usage": {"inputTokens": 3, "outputTokens": 4},
        "stopReason": "tool_use",
    }
    done = _from_converse(resp)
    assert done.text == "thinking"
    assert done.tool_calls == (ToolCall("a", "submit", {"code": "x"}),)
    assert (done.stop_reason, done.input_tokens, done.output_tokens) == ("tool_use", 3, 4)


class _Raises:
    def __init__(self, code: str, status: int) -> None:
        self._err = ClientError(
            {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}, "Converse"
        )

    def converse(self, **_: Any) -> Any:
        raise self._err


@pytest.mark.parametrize(
    ("code", "status", "transient"),
    [("ThrottlingException", 400, True), ("Oops", 503, True), ("ValidationException", 400, False)],
)
def test_transient_errors_are_classified(code: str, status: int, transient: bool) -> None:
    llm = BedrockLLM.__new__(BedrockLLM)
    llm._client = _Raises(code, status)
    req = LLMRequest("m", "t", "s", (Message("user", "p"),))
    with pytest.raises(LLMError) as err:
        llm.complete(req, 10)
    assert isinstance(err.value, TransientLLMError) == transient


def test_fake_llm_replays_tool_calls() -> None:
    fake = FakeLLM(lambda req: (ToolCall("a", "submit", {"code": "x"}),))
    done = fake.complete(LLMRequest("m", "t", "s", (Message("user", "p"),)), 10)
    assert done.stop_reason == "tool_use"
    assert done.tool_calls[0].name == "submit"


def test_tool_results_precede_text_and_blank_text_is_dropped() -> None:
    result = (ToolResult("t1", text="out"),)
    wire = _to_converse(
        [Message("user", "note", tool_results=result), Message("user", "\n\n", tool_results=result)]
    )
    assert [next(iter(b)) for b in wire[0]["content"]] == ["toolResult", "text"]
    assert [next(iter(b)) for b in wire[1]["content"]] == ["toolResult"]


class _Capture:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] = {}
        self.content: list[dict[str, Any]] = [{"text": "ok"}]

    def converse(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        usage = {"inputTokens": 1, "outputTokens": 1}
        return {"output": {"message": {"content": self.content}}, "usage": usage}


def test_cache_points_follow_the_conversation_tail() -> None:
    llm = BedrockLLM.__new__(BedrockLLM)
    llm._client = capture = _Capture()
    msgs = (Message("user", "task"), Message("assistant", "a"), Message("user", "more"))
    llm.complete(LLMRequest("anthropic.m", "t", "s", msgs, (ToolSpec("x", "d", {}),)), 10)
    point = {"cachePoint": {"type": "default"}}
    sent = capture.kwargs
    assert sent["system"][-1] == point
    assert sent["toolConfig"]["tools"][-1] == point
    assert sent["messages"][-1]["content"] == [{"text": "more"}, point]
    assert all(point not in m["content"] for m in sent["messages"][:-1])
    llm.complete(LLMRequest("amazon.nova", "t", "s", msgs, (ToolSpec("x", "d", {}),)), 10)
    assert point not in capture.kwargs["toolConfig"]["tools"]
    assert all(point not in m["content"] for m in capture.kwargs["messages"])
    llm.complete(LLMRequest("anthropic.m", "t", "s", (Message("user", "task"),)), 10)
    assert capture.kwargs["system"] == [{"text": "s"}]
    assert capture.kwargs["messages"][0]["content"] == [{"text": "task"}]


def test_from_converse_reads_cache_counts() -> None:
    resp: dict[str, Any] = {
        "output": {"message": {"content": [{"text": "x"}]}},
        "usage": {"inputTokens": 1, "outputTokens": 2},
    }
    assert (_from_converse(resp).cache_read_tokens, _from_converse(resp).cache_write_tokens) == (
        0,
        0,
    )
    resp["usage"] |= {"cacheReadInputTokens": 5, "cacheWriteInputTokens": 7}
    done = _from_converse(resp)
    assert (done.cache_read_tokens, done.cache_write_tokens) == (5, 7)
