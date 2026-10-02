import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from popper.harness.config import load_config
from popper.harness.context import UNTRUSTED_NOTE
from popper.harness.llm import Completion, FakeLLM, LLMRequest, TransientLLMError
from popper.harness.recovery import read_events
from popper.harness.session import BudgetExceeded, Harness
from popper.harness.store import RunStore

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "student_performance"


def _harness(tmp_path: Path, fake: FakeLLM) -> Harness:
    run = RunStore.create(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv")
    return Harness(load_config(env={}), fake, run)


def test_ask_journals_each_call(tmp_path: Path) -> None:
    fake = FakeLLM(lambda req: "ok")
    h = _harness(tmp_path, fake)
    assert h.ask("analyst", tag="t1", system="s", prompt="p") == "ok"
    entries = [e for e in read_events(h.run.root) if e["event"] == "llm_call"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["event"] == "llm_call"
    assert entry["tag"] == "t1"
    assert entry["role"] == "analyst"
    assert entry["model"] == h.config.models.analyst
    assert {"input_tokens", "output_tokens", "usd", "ts"} <= entry.keys()


def test_budget_blocks_further_calls(tmp_path: Path) -> None:
    fake = FakeLLM(lambda req: "ok")
    h = _harness(tmp_path, fake)
    h.config.budget.max_usd = 0
    with pytest.raises(BudgetExceeded):
        h.ask("analyst", tag="t", system="s", prompt="p")
    assert fake.calls == []


class Shape(BaseModel):
    a: int


def test_ask_model_parses_plain_json_and_sends_schema(tmp_path: Path) -> None:
    fake = FakeLLM(lambda req: '{"a": 1}')
    h = _harness(tmp_path, fake)
    assert h.ask_model("analyst", schema=Shape, tag="t", system="s", prompt="p").a == 1
    assert fake.calls[0].output_schema == Shape.model_json_schema()


def test_ask_model_retries_once_on_bad_json(tmp_path: Path) -> None:
    replies = iter(["nope", '{"a": 2}'])
    fake = FakeLLM(lambda req: next(replies))
    h = _harness(tmp_path, fake)
    assert h.ask_model("analyst", schema=Shape, tag="t", system="s", prompt="p").a == 2
    assert len(fake.calls) == 2
    assert fake.calls[1].prompt.startswith("p")
    assert "Your previous reply could not be used" in fake.calls[1].prompt


def test_store_is_write_once(tmp_path: Path) -> None:
    run = RunStore.create(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv")
    run.write_json("x.json", {})
    with pytest.raises(FileExistsError):
        run.write_json("x.json", {})


class _Failing:
    def complete(self, req: LLMRequest, max_tokens: int) -> Completion:
        raise RuntimeError("boom")


class _Costly:
    def __init__(self) -> None:
        self.n = 0

    def complete(self, req: LLMRequest, max_tokens: int) -> Completion:
        self.n += 1
        return Completion(
            "x", 1_000_000, 1_000_000, cache_read_tokens=1_000_000, cache_write_tokens=1_000_000
        )


def test_failed_call_is_journaled(tmp_path: Path) -> None:
    h = _harness(tmp_path, FakeLLM(lambda req: ""))
    h.llm = _Failing()
    with pytest.raises(RuntimeError):
        h.ask("analyst", tag="t", system="s", prompt="p")
    errors = [e for e in read_events(h.run.root) if e["event"] == "llm_error"]
    assert len(errors) == 1


def test_cost_is_accounted_and_capped(tmp_path: Path) -> None:
    stub = _Costly()
    h = _harness(tmp_path, FakeLLM(lambda req: ""))
    h.llm = stub
    h.config.budget.max_usd = 10
    h.ask("analyst", tag="t", system="s", prompt="p")
    expected = 3.0 + 15.0 + 3.0 * 1.25 + 3.0 * 0.1  # sonnet price, cache write and read
    assert h.spent_usd == pytest.approx(expected)
    entry = next(e for e in read_events(h.run.root) if e["event"] == "llm_call")
    assert entry["usd"] == pytest.approx(expected)
    assert (entry["cache_read_tokens"], entry["cache_write_tokens"]) == (1_000_000, 1_000_000)
    with pytest.raises(BudgetExceeded):
        h.ask("analyst", tag="t", system="s", prompt="p")
    assert stub.n == 1


def test_ask_model_retries_once_on_schema_mismatch(tmp_path: Path) -> None:
    replies = iter(['{"a": "x"}', '{"a": 3}'])
    fake = FakeLLM(lambda req: next(replies))
    h = _harness(tmp_path, fake)
    assert h.ask_model("analyst", schema=Shape, tag="t", system="s", prompt="p").a == 3
    assert len(fake.calls) == 2
    assert "a" in fake.calls[1].prompt


def test_schema_retry_keeps_previous_reply_and_compact_error(tmp_path: Path) -> None:
    previous = '{"a": "invalid_value", "note": "keep this detail"}'
    replies = iter([previous, '{"a": 3}'])
    fake = FakeLLM(lambda req: next(replies))
    h = _harness(tmp_path, fake)
    assert h.ask_model("analyst", schema=Shape, tag="t", system="s", prompt="p").a == 3
    prompt = fake.calls[1].prompt
    assert previous in prompt
    assert "input_value=" not in prompt and "errors.pydantic.dev" not in prompt


def test_schema_retry_keeps_partial_reply_after_token_limit(tmp_path: Path) -> None:
    class TruncatedReply(FakeLLM):
        def complete(self, req: LLMRequest, max_tokens: int) -> Completion:
            self.calls.append(req)
            if len(self.calls) == 1:
                return Completion('{"a": 123', 1, 1, "max_tokens")
            return Completion('{"a": 123}', 1, 1, "end_turn")

    fake = TruncatedReply(lambda _: "")
    h = _harness(tmp_path, fake)
    assert h.ask_model("analyst", schema=Shape, tag="t", system="s", prompt="p").a == 123
    assert '{"a": 123' in fake.calls[1].prompt
    assert "reply truncated at max_tokens" in fake.calls[1].prompt


class _Flaky:
    def __init__(self, errors: list[Exception]) -> None:
        self.errors = errors
        self.requests: list[LLMRequest] = []

    def complete(self, req: LLMRequest, max_tokens: int) -> Completion:
        self.requests.append(req)
        if self.errors:
            raise self.errors.pop(0)
        return Completion("ok", 1, 1, "end_turn")


def _flaky_harness(tmp_path: Path, llm: _Flaky) -> tuple[Harness, list[float]]:
    run = RunStore.create(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv")
    delays: list[float] = []
    return Harness(load_config(env={}), llm, run, sleep=delays.append), delays


def _events(h: Harness) -> list[str]:
    lines = h.run.path("journal.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["event"] for line in lines if json.loads(line)["event"].startswith("llm_")]


def test_retries_transient_errors_with_backoff(tmp_path: Path) -> None:
    h, delays = _flaky_harness(tmp_path, _Flaky([TransientLLMError("x"), TransientLLMError("y")]))
    assert h.ask("analyst", tag="t", system="s", prompt="p") == "ok"
    assert delays == [2.0, 4.0]
    assert _events(h) == ["llm_retry", "llm_retry", "llm_call"]


def test_gives_up_after_five_attempts(tmp_path: Path) -> None:
    h, delays = _flaky_harness(tmp_path, _Flaky([TransientLLMError("x")] * 5))
    with pytest.raises(TransientLLMError):
        h.ask("analyst", tag="t", system="s", prompt="p")
    assert delays == [2, 4, 8, 16]
    assert _events(h).count("llm_error") == 1


def test_non_transient_error_is_not_retried(tmp_path: Path) -> None:
    h, delays = _flaky_harness(tmp_path, _Flaky([RuntimeError("boom")]))
    with pytest.raises(RuntimeError):
        h.ask("analyst", tag="t", system="s", prompt="p")
    assert delays == []
    assert _events(h) == ["llm_error"]


def test_system_prompt_carries_untrusted_note(tmp_path: Path) -> None:
    llm = _Flaky([])
    h, _ = _flaky_harness(tmp_path, llm)
    h.ask("analyst", tag="t", system="s", prompt="p")
    assert llm.requests[0].system.endswith(UNTRUSTED_NOTE)


def test_schema_retry_keeps_image_attachments(tmp_path: Path) -> None:
    replies = iter(["invalid", '{"a": 3}'])
    fake = FakeLLM(lambda req: next(replies))
    h = _harness(tmp_path, fake)
    image = tmp_path / "safe.png"

    class Shape(BaseModel):
        a: int

    result = h.ask_model(
        "judge", schema=Shape, tag="judge", system="s", prompt="p", images=(image,)
    )
    assert result.a == 3
    assert all(request.messages[0].images == (image,) for request in fake.calls)
