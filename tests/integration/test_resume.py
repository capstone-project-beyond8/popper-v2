import json
from pathlib import Path

import pytest

from popper.coordinator.run import resume, run
from popper.harness.config import load_config
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.recovery import Journal, load_state, read_events
from popper.harness.session import Harness
from popper.harness.store import RunStore
from popper.treesearch.engine import StageSpec, run_stage
from tests.integration.test_run import EXAMPLE, _config

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("cap", [0, -1, float("nan"), float("inf"), 0.1])
def test_resume_rejects_caps_that_cannot_raise_the_remaining_budget(
    tmp_path: Path, cap: float
) -> None:
    cfg = _config()
    cfg.budget.max_usd = 0.1
    store = RunStore.create(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv", config=cfg)
    Journal(store.path("journal.jsonl")).write("llm_call", usd=0.2)
    before = read_events(store.root)
    with pytest.raises(ValueError, match="cap"):
        resume(store.root, llm=FakeLLM(lambda _: pytest.fail("no calls expected")), max_usd=cap)
    assert read_events(store.root) == before


def test_raised_cap_survives_another_resume_without_overwriting_run_config(tmp_path: Path) -> None:
    cfg = _config()
    cfg.budget.max_usd = 0
    store = RunStore.create(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv", config=cfg)
    original = store.path("run.json").read_bytes()
    observed: list[float] = []

    def interrupt(req: LLMRequest) -> str:
        observed.append(1.0)
        raise KeyboardInterrupt()

    for cap in (1.0, None):
        with pytest.raises(KeyboardInterrupt):
            resume(store.root, llm=FakeLLM(interrupt), max_usd=cap)
    assert len(observed) == 2
    assert store.path("run.json").read_bytes() == original
    assert load_state(store)["max_usd"] == 1.0
    raises = [e for e in read_events(store.root) if e["event"] == "budget_raise"]
    assert len(raises) == 1 and raises[0]["old_max_usd"] == 0 and raises[0]["max_usd"] == 1
    assert json.loads(original)["config"]["budget"]["max_usd"] == 0


def test_budget_raise_survives_failure_before_its_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _config()
    cfg.budget.max_usd = 0
    store = RunStore.create(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv", config=cfg)
    Journal(store.path("journal.jsonl")).write("llm_call", usd=0.2)
    original = store.path("run.json").read_bytes()

    def fail_checkpoint(self: RunStore, state: object) -> Path:
        raise OSError("checkpoint unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(RunStore, "checkpoint", fail_checkpoint)
        with pytest.raises(OSError, match="checkpoint unavailable"):
            resume(store.root, llm=FakeLLM(lambda _: pytest.fail("no model call yet")), max_usd=1)

    def interrupt(req: LLMRequest) -> str:
        raise KeyboardInterrupt()

    llm = FakeLLM(interrupt)
    with pytest.raises(KeyboardInterrupt):
        resume(store.root, llm=llm)
    assert len(llm.calls) == 1
    assert load_state(store)["max_usd"] == 1
    assert load_state(store)["spent_usd"] == 0.2
    assert store.path("run.json").read_bytes() == original
    assert len([e for e in read_events(store.root) if e["event"] == "budget_raise"]) == 1


def test_stage_resume_after_judge_interrupt_does_not_reuse_incomplete_execution(
    tmp_path: Path,
) -> None:
    cfg = load_config(env={})
    cfg.search.steps_per_stage = 2
    cfg.search.num_drafts = 1
    script = "import json; json.dump({'m':{'value':1}}, open('results.json','w'))"

    def first(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        if req.tag.startswith("judge:"):
            raise KeyboardInterrupt()
        return (ToolCall("submit", "submit", {"code": script}),)

    store = RunStore.create(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv", config=cfg)
    spec = StageSpec("stage", "goal", "context", {}, ("results.json",))
    with pytest.raises(KeyboardInterrupt):
        run_stage(Harness(cfg, FakeLLM(first), store), spec)
    original = store.path("tree", "stage", "stage-000", "execution", "results.json").read_bytes()

    def second(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        if req.tag.startswith("judge:"):
            return '{"node_buggy":false,"goal_met":true,"node_score":7,"analysis":"valid"}'
        return (ToolCall("submit", "submit", {"code": script}),)

    best = run_stage(Harness(cfg, FakeLLM(second), store), spec)
    assert best.id == "stage-001" and best.kind == "debug"
    assert (
        store.path("tree", "stage", "stage-000", "execution", "results.json").read_bytes()
        == original
    )
    starts = [e for e in read_events(store.root) if e["event"] == "node_start"]
    assert len(starts) == 2


def test_resume_rejects_legacy_format_and_retains_budget_stop(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "run.json").write_text('{"status":"completed","format_version":2}')
    fake = FakeLLM(lambda req: pytest.fail("no model calls expected"))
    with pytest.raises(ValueError, match="format"):
        resume(legacy, llm=fake)
    cfg = _config()
    cfg.budget.max_usd = 0
    outcome = run(
        EXAMPLE / "research.md", EXAMPLE / "data.csv", config=cfg, llm=fake, runs_dir=tmp_path
    )
    assert resume(outcome.run_dir, llm=fake).status == "budget_exceeded"


def test_resume_after_node_commit_reconstructs_stage_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = _config()
    store = RunStore.create(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv", config=cfg)
    h = Harness(
        cfg,
        FakeLLM(
            lambda req: (
                '{"node_buggy":false,"goal_met":true,"node_score":7,"analysis":"valid"}'
                if req.tag.startswith("judge:")
                else (
                    ToolCall(
                        "submit",
                        "submit",
                        {
                            "code": "import json; json.dump({'m':{'value':1}}, open('results.json','w'))"
                        },
                    ),
                )
            )
        ),
        store,
    )
    original_write = h.journal.write

    def interrupted(event: str, **fields: object) -> None:
        if event == "stage_end":
            raise KeyboardInterrupt()
        original_write(event, **fields)

    monkeypatch.setattr(h.journal, "write", interrupted)
    spec = StageSpec("stage", "goal", "context", {}, ("results.json",))
    with pytest.raises(KeyboardInterrupt):
        run_stage(h, spec)
    no_calls = FakeLLM(lambda req: pytest.fail("committed node must not replay"))
    node = run_stage(Harness(cfg, no_calls, store), spec)
    assert node.id == "stage-000"
    assert len([e for e in read_events(store.root) if e["event"] == "node_start"]) == 1


def test_locked_run_cannot_be_resumed_and_journal_is_untouched(tmp_path: Path) -> None:
    cfg = _config()
    store = RunStore.create(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv", config=cfg)
    with store.lock():
        before = read_events(store.root)
        with pytest.raises(RuntimeError, match="in use"):
            resume(store.root, llm=FakeLLM(lambda req: pytest.fail("no model calls expected")))
        assert read_events(store.root) == before
    assert not store.path("run.lock").exists()
