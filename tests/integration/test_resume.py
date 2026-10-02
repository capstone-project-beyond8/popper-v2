import json
from pathlib import Path

import pytest

from popper.coordinator.run import resume, run
from popper.harness.config import load_config
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.recovery import Journal, load_state, read_events
from popper.harness.session import Harness
from popper.harness.store import RunStore
from popper.treesearch.engine import StageSpec, load_nodes, run_stage
from tests.integration.test_run import EXAMPLE, FRAMING, _config

pytestmark = pytest.mark.integration


@pytest.fixture
def historical_stage(tmp_path: Path) -> tuple[Harness, dict[Path, bytes]]:
    """Independently encoded records from the unscoped stage format."""
    cfg = load_config(env={})
    store = RunStore.create(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv", config=cfg)
    node_dir = store.path("tree", "main", "main-000")
    payloads = {
        node_dir
        / "meta.json": b'{"id":"main-000","stage":"main","parent":null,"kind":"draft","debug_depth":0,"status":"ok","score":7.0,"goal_met":true,"analysis":"valid","figures":[],"reason":"draft 1 of 1","attempt_id":null,"seed_node":null}',
        node_dir / "analysis.md": b"valid",
        node_dir
        / "execution"
        / "code.py": b"import json; json.dump({'m': {'value': 1.5}}, open('results.json', 'w'))",
        node_dir / "execution" / "results.json": b'{"m":{"value":1.5}}',
        store.path("journal.jsonl"): (
            b'{"event":"stage_start","stage":"main","steps":2,"seed":7}\n'
            b'{"event":"node_start","stage":"main","node":"main-000","kind":"draft","parent":null,"debug_depth":0,"attempt_id":null,"seed_node":null}\n'
            b'{"event":"node_commit","stage":"main","node":"main-000"}\n'
            b'{"event":"stage_end","stage":"main","best":"main-000","steps":1}\n'
        ),
    }
    for path, content in payloads.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return Harness(
        cfg, FakeLLM(lambda _: pytest.fail("historical node must not replay")), store
    ), payloads


def test_historical_stage_records_preserve_identity(
    historical_stage: tuple[Harness, dict[Path, bytes]],
) -> None:
    h, payloads = historical_stage
    nodes = load_nodes(h, "main")
    assert len(nodes) == 1
    node = run_stage(h, StageSpec("main", "goal", "context", {}, ("results.json",)))
    assert node.id == nodes[0].id == "main-000"
    assert node.stage == "main"
    assert node.execution_dir == h.run.root / "tree/main/main-000/execution"
    assert node.results == {"m": {"value": 1.5}}
    assert node.score == 7 and node.goal_met
    assert all(path.read_bytes() == content for path, content in payloads.items())


@pytest.mark.parametrize("auto", [False, True])
def test_resume_restores_researcher_for_interactive_runs_only(tmp_path: Path, auto: bool) -> None:
    def interrupt(req: LLMRequest) -> str:
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        run(
            EXAMPLE / "research.md", EXAMPLE / "data.csv", config=_config(),
            auto=auto, llm=FakeLLM(interrupt), runs_dir=tmp_path,
        )
    root = next(tmp_path.iterdir())
    answers: list[tuple[str, str]] = []

    def researcher(question: str, proposed: str) -> str:
        answers.append((question, proposed))
        return "hours"

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        if req.tag == "steward":
            raise KeyboardInterrupt()
        if len(req.messages) == 1:
            return (ToolCall("q", "ask_researcher", {
                "question": "Unit?", "proposed_answer": "hrs", "item": "variables.sleep_hours.unit",
            }),)
        return (ToolCall("s", "submit_frame", {"framing": FRAMING}),)

    llm = FakeLLM(respond)
    if auto:
        with pytest.raises(KeyboardInterrupt):
            resume(root, llm=llm, researcher=researcher)
    else:
        assert resume(root, llm=llm, researcher=researcher).status == "awaiting_review"
    assert answers == ([] if auto else [("Unit?", "hrs")])
    feedback = llm.calls[1].messages[-1].tool_results[0].text
    assert ("unknown tool ask_researcher" in feedback) is auto
    assert ("ask_researcher" in {tool.name for tool in llm.calls[0].tools}) is not auto
    store = RunStore(root)
    frame = store.committed("frame")
    assert frame is not None
    questions = json.loads((frame.parent / "questions.json").read_text("utf-8"))
    assert questions == ([] if auto else [{
        "question": "Unit?", "proposed_answer": "hrs",
        "item": "variables.sleep_hours.unit", "answer": "hours",
    }])


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
