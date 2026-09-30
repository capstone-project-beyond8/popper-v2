import json
from pathlib import Path

import pytest

from popper.harness.config import load_config
from popper.harness.llm import FakeLLM, LLMRequest
from popper.harness.session import BudgetExceeded, Harness
from popper.harness.store import RunStore

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "student_performance"


def _harness(tmp_path: Path, fake: FakeLLM) -> Harness:
    run = RunStore.create(tmp_path, EXAMPLE / "brief.md", EXAMPLE / "data.csv")
    return Harness(load_config(env={}), fake, run)


def test_ask_journals_each_call(tmp_path: Path) -> None:
    fake = FakeLLM(lambda req: "ok")
    h = _harness(tmp_path, fake)
    assert h.ask("code", tag="t1", system="s", prompt="p") == "ok"
    lines = h.run.path("journal.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["event"] == "llm_call"
    assert entry["tag"] == "t1"
    assert entry["role"] == "code"
    assert entry["model"] == h.config.models.code
    assert {"input_tokens", "output_tokens", "usd", "ts"} <= entry.keys()


def test_budget_blocks_further_calls(tmp_path: Path) -> None:
    fake = FakeLLM(lambda req: "ok")
    h = _harness(tmp_path, fake)
    h.config.budget.max_usd = 0
    with pytest.raises(BudgetExceeded):
        h.ask("code", tag="t", system="s", prompt="p")
    assert fake.calls == []


def test_ask_json_reads_fenced_json(tmp_path: Path) -> None:
    h = _harness(tmp_path, FakeLLM(lambda req: 'Here:\n```json\n{"a": 1}\n```'))
    assert h.ask_json("code", tag="t", system="s", prompt="p") == {"a": 1}


def test_ask_json_retries_once_on_bad_json(tmp_path: Path) -> None:
    replies = iter(["nope", '{"a": 2}'])
    fake = FakeLLM(lambda req: next(replies))
    h = _harness(tmp_path, fake)
    assert h.ask_json("code", tag="t", system="s", prompt="p") == {"a": 2}
    assert len(fake.calls) == 2
    assert isinstance(fake.calls[1], LLMRequest)


def test_store_is_write_once(tmp_path: Path) -> None:
    run = RunStore.create(tmp_path, EXAMPLE / "brief.md", EXAMPLE / "data.csv")
    run.write_json("x.json", {})
    with pytest.raises(FileExistsError):
        run.write_json("x.json", {})
