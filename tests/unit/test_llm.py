from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

from popper.harness.llm import (
    BedrockLLM,
    FakeLLM,
    LLMRequest,
    Message,
    ToolCall,
    ToolResult,
    TransientLLMError,
    _from_converse,
    _to_converse,
)


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
        {"toolResult": {"toolUseId": "t1", "content": [{"text": "cols"}]}}
    ]
    assert wire[3]["content"] == [
        {
            "toolResult": {
                "toolUseId": "t1",
                "content": [{"image": {"format": "png", "source": {"bytes": b"PNG"}}}],
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
    with pytest.raises(TransientLLMError if transient else ClientError):
        llm.complete(req, 10)


def test_fake_llm_replays_tool_calls() -> None:
    fake = FakeLLM(lambda req: (ToolCall("a", "submit", {"code": "x"}),))
    done = fake.complete(LLMRequest("m", "t", "s", (Message("user", "p"),)), 10)
    assert done.stop_reason == "tool_use"
    assert done.tool_calls[0].name == "submit"
