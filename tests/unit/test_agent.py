import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from popper.harness.agent import Tool, agent_loop
from popper.harness.config import load_config
from popper.harness.llm import LLM, Completion, FakeLLM, LLMRequest, ToolCall, _to_converse
from popper.harness.session import BudgetExceeded, Harness
from popper.harness.store import RunStore

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "student_performance"


def _harness(tmp_path: Path, llm: LLM) -> Harness:
    run = RunStore.create(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv")
    return Harness(load_config(env={}), llm, run)


def test_integrity_failure_is_recorded_and_blocks_tool_retry(tmp_path: Path) -> None:
    from popper.harness.records import IntegrityError
    from popper.harness.recovery import read_events

    fake = FakeLLM(lambda _: (ToolCall("read", "echo", {}),))
    h = _harness(tmp_path, fake)

    def corrupted(args: dict[str, Any]) -> str:
        raise IntegrityError("committed source hash mismatch")

    with pytest.raises(IntegrityError, match="hash mismatch"):
        _run(h, corrupted)
    assert len(fake.calls) == 1
    events = [e for e in read_events(h.run.root) if e["event"] == "tool_call"]
    assert len(events) == 1 and events[0]["status"] == "integrity_error"


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


def test_each_loop_has_a_distinct_journal_session(tmp_path: Path) -> None:
    fake = FakeLLM(lambda req: (ToolCall("s", "submit", {}),))
    h = _harness(tmp_path, fake)
    _run(h)
    _run(h)
    events = [json.loads(line) for line in h.run.path("journal.jsonl").read_text().splitlines()]
    calls = [e for e in events if e["event"] == "llm_call"]
    tools = [e for e in events if e["event"] == "tool_call"]
    assert calls[0]["session"] != calls[1]["session"]
    assert [e["session"] for e in tools] == [e["session"] for e in calls]
    assert all(e["terminal"] and e["status"] == "success" for e in tools)


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
            return Completion(
                self.text, 0, 0, "max_tokens", (ToolCall("a1", "submit", {"code": "partial"}),)
            )
        return Completion("", 0, 0, "tool_use", (ToolCall("a2", "submit", {}),))


def test_truncated_turn_drops_tool_calls(tmp_path: Path) -> None:
    llm = _Truncating("partial")
    h = _harness(tmp_path, llm)
    assert _run(h) == {}
    msgs = llm.calls[1].messages
    assert [m.role for m in msgs] == ["user", "assistant", "user"]
    assert msgs[1].text == "partial"
    assert msgs[1].tool_calls == ()
    assert "cut off" in msgs[2].text
    events = [json.loads(line) for line in h.run.path("journal.jsonl").read_text().splitlines()]
    records = [e for e in events if e["event"] == "tool_call"]
    assert [e["call_id"] for e in records] == ["a1", "a2"]
    assert records[0]["status"] == "skipped"
    assert "token limit" in records[0]["result"]
    assert json.loads(records[0]["args"]) == {"code": "partial"}


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


def test_accepted_terminal_call_wins_over_earlier_rejected_one(tmp_path: Path) -> None:
    fake = _scripted((ToolCall("a1", "submit", {}), ToolCall("a2", "submit", {"ok": 2})))
    assert _validated(_harness(tmp_path, fake), 2) == {"ok": 2}


@pytest.mark.parametrize("validated", [False, True])
def test_terminal_batch_stops_effects_and_records_remaining_calls(
    tmp_path: Path, validated: bool
) -> None:
    handled: list[dict[str, Any]] = []

    def handle(args: dict[str, Any]) -> str:
        handled.append(args)
        return "accepted"

    calls = (
        ToolCall("a", "echo", {"before": 1}),
        ToolCall("b", "submit", {"ok": 1}),
        ToolCall("c", "submit", {"ok": 2}),
        ToolCall("d", "echo", {"after": 1}),
    )
    h = _harness(tmp_path, _scripted(calls))
    tools = [
        Tool("echo", "echo", {}, handle),
        Tool("submit", "submit", {}, handle if validated else None, terminal=True),
    ]
    assert agent_loop(
        h, "analyst", tag="t", system="s", task="go", tools=tools, max_turns=1
    ) == {"ok": 1}
    assert handled == ([{"before": 1}, {"ok": 1}] if validated else [{"before": 1}])
    events = [json.loads(line) for line in h.run.path("journal.jsonl").read_text().splitlines()]
    records = [e for e in events if e["event"] == "tool_call"]
    assert [json.loads(e["args"]) for e in records] == [c.input for c in calls]
    assert [e["call_id"] for e in records] == [c.id for c in calls]
    assert [e["status"] for e in records] == ["success", "success", "skipped", "skipped"]
    assert all(e["result"] for e in records)


def test_rejection_limit_counts_calls_in_a_batch(tmp_path: Path) -> None:
    calls = (
        ToolCall("a", "submit", {}),
        ToolCall("b", "submit", {}),
        ToolCall("c", "submit", {"ok": 1}),
    )
    fake = _scripted(calls)
    h = _harness(tmp_path, fake)
    assert _validated(h, 2) is None
    events = [json.loads(line) for line in h.run.path("journal.jsonl").read_text().splitlines()]
    records = [e for e in events if e["event"] == "tool_call"]
    assert [e["status"] for e in records] == ["error", "error", "skipped"]
    assert len(fake.calls) == 1


def test_typed_tool_reports_nested_errors_before_running_handler(tmp_path: Path) -> None:
    class Item(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        count: int

    class Submission(BaseModel):
        items: list[Item]

    handled: list[int] = []

    def accept(value: Submission) -> str:
        handled.extend(item.count for item in value.items)
        return "accepted"

    bad = {"items": [{"count": "wrong", "extra": "unwanted"}]}
    good = {"items": [{"count": 3}]}
    fake = _scripted((ToolCall("a", "submit", bad),), (ToolCall("b", "submit", good),))
    tool = Tool.from_model("submit", "Submit counts", Submission, accept, terminal=True)
    assert agent_loop(
        _harness(tmp_path, fake), "analyst", tag="t", system="s", task="go",
        tools=[tool], max_turns=2,
    ) == good
    assert handled == [3]
    feedback = fake.calls[1].messages[-1].tool_results[0]
    assert feedback.status == "error"
    assert "items.0.count" in feedback.text and "items.0.extra" in feedback.text
    assert "input_value=" not in feedback.text and "errors.pydantic.dev" not in feedback.text
    schema = fake.calls[0].tools[0].schema
    assert schema["properties"]["items"]["items"]["$ref"] == "#/$defs/Item"
    assert schema["$defs"]["Item"]["properties"]["count"]["type"] == "integer"
    assert schema["$defs"]["Item"]["additionalProperties"] is False


def test_long_errors_and_arguments_are_preserved_and_readable(tmp_path: Path) -> None:
    from popper.treesearch.tools import node_tools

    diagnostic = "\n".join(f"field_{i}: invalid; fix this field" for i in range(500))
    args = {"code": "x" * 4000 + "LAST_ARGUMENT"}

    def reject(value: dict[str, Any]) -> str:
        raise ValueError(diagnostic)

    fake = _scripted(
        (ToolCall("a", "echo", args),), (ToolCall("a", "echo", {}),),
        (ToolCall("b", "submit", {}),),
    )
    h = _harness(tmp_path, fake)
    _run(h, reject)
    events = [json.loads(line) for line in h.run.path("journal.jsonl").read_text("utf-8").splitlines()]
    event = next(e for e in events if e["event"] == "tool_call")
    reports = [e["diagnostic"] for e in events if "diagnostic" in e]
    assert len(reports) == 2 and len(set(reports)) == 2
    assert json.loads(event["args"]) == args
    assert event["result"] == f"error: {diagnostic}"
    report = h.run.path(event["diagnostic"])
    record = json.loads(report.read_text("utf-8"))
    assert record == {"tag": "t", "text": event["result"]}
    feedback = fake.calls[1].messages[-1].tool_results[0].text
    assert len(feedback) <= 8000 and "omitted" in feedback
    assert "read_artifact" in feedback and event["diagnostic"] in feedback
    assert "field_0: invalid; fix this field" in feedback
    kept = feedback.split("\n[", 1)[0].splitlines()
    assert all(line.endswith("invalid; fix this field") for line in kept)
    reader = next(t for t in node_tools(h, {}, h.run.path("tree", "node")) if t.name == "read_artifact")
    assert reader.handler is not None
    page = str(reader.handler({"path": event["diagnostic"], "offset": 8000}))
    assert '"offset": 16000' in page
    page = str(reader.handler({"path": event["diagnostic"], "offset": 16000}))
    assert "field_499: invalid; fix this field" in page
