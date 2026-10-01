import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from popper.harness.agent import Tool, agent_loop
from popper.harness.config import load_config
from popper.harness.llm import LLM, Completion, FakeLLM, LLMRequest, ToolCall, _to_converse
from popper.harness.session import BudgetExceeded, Harness
from popper.harness.store import RunStore

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "student_performance"


def _harness(tmp_path: Path, llm: LLM) -> Harness:
    run = RunStore.create(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv")
    return Harness(load_config(env={}), llm, run)


def _run(
    h: Harness,
    handler: Callable[[dict[str, Any]], str | Path] = lambda args: "echoed",
    max_turns: int = 5,
) -> dict[str, Any] | None:
    tools = [Tool("echo", "echo", {}, handler), Tool("submit", "submit", {}, None, terminal=True)]
    return agent_loop(
        h, "analyst", tag="t", system="s", task="go", tools=tools, max_turns=max_turns
    )


def _scripted(*turns: tuple[ToolCall, ...]) -> FakeLLM:
    replies = iter(turns)
    return FakeLLM(lambda req: next(replies))


def test_returns_submitted_input(tmp_path: Path) -> None:
    fake = _scripted((ToolCall("a1", "echo", {}),), (ToolCall("a2", "submit", {"code": "x"}),))
    assert _run(_harness(tmp_path, fake)) == {"code": "x"}
    last = fake.calls[1].messages[-1]
    assert last.role == "user"
    assert last.tool_results[0].call_id == "a1"
    assert last.tool_results[0].text == "echoed"
    assert [t.name for t in fake.calls[0].tools] == ["echo", "submit"]


def test_stops_at_max_turns(tmp_path: Path) -> None:
    fake = FakeLLM(lambda req: "thinking")
    assert _run(_harness(tmp_path, fake), max_turns=3) is None
    assert len(fake.calls) == 3
    roles = [m.role for m in fake.calls[2].messages]
    assert roles == ["user", "assistant", "user", "assistant", "user"]


def test_handler_error_becomes_result(tmp_path: Path) -> None:
    def boom(args: dict[str, Any]) -> str:
        raise KeyError("code")

    fake = _scripted((ToolCall("a1", "echo", {}),), (ToolCall("a2", "submit", {"k": 1}),))
    assert _run(_harness(tmp_path, fake), boom) == {"k": 1}
    assert fake.calls[1].messages[-1].tool_results[0].text.startswith("error:")
    assert fake.calls[1].messages[-1].tool_results[0].status == "error"


def test_unknown_tool_and_image_results(tmp_path: Path) -> None:
    png = tmp_path / "f.png"
    fake = _scripted(
        (ToolCall("a1", "nope", {}), ToolCall("a2", "echo", {})), (ToolCall("a3", "submit", {}),)
    )
    _run(_harness(tmp_path, fake), lambda args: png)
    r1, r2 = fake.calls[1].messages[-1].tool_results
    assert r1.text == "error: unknown tool nope; available: echo, submit"
    assert r2.image == png
    assert r1.status == "error" and r2.status == "success"


class _Truncating:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[LLMRequest] = []

    def complete(self, req: LLMRequest, max_tokens: int) -> Completion:
        self.calls.append(req)
        if len(self.calls) == 1:
            return Completion(self.text, 0, 0, "max_tokens", (ToolCall("a1", "echo", {}),))
        return Completion("", 0, 0, "tool_use", (ToolCall("a2", "submit", {}),))


def test_truncated_turn_drops_tool_calls(tmp_path: Path) -> None:
    llm = _Truncating("partial")
    assert _run(_harness(tmp_path, llm)) == {}
    msgs = llm.calls[1].messages
    assert [m.role for m in msgs] == ["user", "assistant", "user"]
    assert msgs[1].text == "partial"
    assert msgs[1].tool_calls == ()
    assert "cut off" in msgs[2].text


def test_truncated_empty_text_merges_nudge(tmp_path: Path) -> None:
    llm = _Truncating("")
    assert _run(_harness(tmp_path, llm)) == {}
    msgs = llm.calls[1].messages
    assert [m.role for m in msgs] == ["user"]
    assert msgs[0].text.startswith("go")
    assert "cut off" in msgs[0].text


def test_budget_exceeded_propagates(tmp_path: Path) -> None:
    h = _harness(tmp_path, FakeLLM(lambda req: "x"))
    h.config.budget.max_usd = 0
    with pytest.raises(BudgetExceeded):
        _run(h)


def test_tool_calls_are_journaled(tmp_path: Path) -> None:
    fake = _scripted((ToolCall("a1", "echo", {"q": 1}),), (ToolCall("a2", "submit", {}),))
    h = _harness(tmp_path, fake)
    _run(h)
    lines = h.run.path("journal.jsonl").read_text(encoding="utf-8").splitlines()
    calls = [e for e in map(json.loads, lines) if e["event"] == "tool_call"]
    assert [c["tool"] for c in calls] == ["echo", "submit"]
    assert calls[0]["result"] == "echoed"


def test_truncation_after_tool_results_keeps_results_first(tmp_path: Path) -> None:
    turns = iter(
        [
            Completion("", 0, 0, "tool_use", (ToolCall("a1", "echo", {}),)),
            Completion("", 0, 0, "max_tokens", (ToolCall("a2", "submit", {}),)),
            Completion("", 0, 0, "tool_use", (ToolCall("a3", "submit", {}),)),
        ]
    )
    calls: list[LLMRequest] = []

    class _LLM:
        def complete(self, req: LLMRequest, max_tokens: int) -> Completion:
            calls.append(req)
            return next(turns)

    assert _run(_harness(tmp_path, _LLM())) == {}
    last = _to_converse(calls[2].messages)[-1]["content"]
    assert [next(iter(b)) for b in last] == ["toolResult", "text"]


def _validated(h: Harness, max_submits: int | None) -> dict[str, Any] | None:
    def check(args: dict[str, Any]) -> str:
        if "ok" not in args:
            raise ValueError("missing ok")
        return "accepted"

    tools = [Tool("submit", "submit", {}, check, terminal=True)]
    return agent_loop(
        h, "steward", tag="t", system="s", task="go", tools=tools, max_turns=6,
        max_submits=max_submits,
    )  # fmt: skip


def test_rejected_terminal_submit_returns_error_and_retry_succeeds(tmp_path: Path) -> None:
    fake = _scripted((ToolCall("a1", "submit", {}),), (ToolCall("a2", "submit", {"ok": 1}),))
    assert _validated(_harness(tmp_path, fake), 3) == {"ok": 1}
    result = fake.calls[1].messages[-1].tool_results[0]
    assert result.text == "error: missing ok"
    assert result.status == "error"


def test_rejected_submits_stop_at_max_submits(tmp_path: Path) -> None:
    fake = FakeLLM(lambda req: (ToolCall("a", "submit", {}),))
    assert _validated(_harness(tmp_path, fake), 3) is None
    assert len(fake.calls) == 3
