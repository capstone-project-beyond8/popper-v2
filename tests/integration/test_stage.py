import json
import random
from pathlib import Path

import pytest

from popper.harness.config import load_config
from popper.harness.llm import FakeLLM, LLMError, LLMRequest, ToolCall
from popper.harness.recovery import read_events
from popper.harness.session import Harness
from popper.harness.store import RunStore
from popper.treesearch.engine import AttemptSpec, StageFailed, StageSpec, load_nodes, run_stage

pytestmark = pytest.mark.integration

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "student_performance"
FEEDBACK = '{"node_buggy": false, "goal_met": true, "node_score": 7, "analysis": "fine"}'
Reply = str | tuple[ToolCall, ...] | LLMError
SPEC = StageSpec("stage", "goal", "ctx", {}, ("results.json", "out.txt"))


def _tool(name: str, **args: object) -> tuple[ToolCall, ...]:
    return (ToolCall(f"id-{name}", name, dict(args)),)


def _submit(code: str) -> tuple[ToolCall, ...]:
    return _tool("submit", code=code)


def _harness(tmp_path: Path, analyst: list[Reply], judge: list[Reply] | None = None) -> Harness:
    replies = {"analyst:": iter(analyst), "judge:": iter(judge or [FEEDBACK])}

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        reply = next(next(v for k, v in replies.items() if req.tag.startswith(k)))
        if isinstance(reply, LLMError):
            raise reply
        return reply

    run = RunStore.create(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv")
    h = Harness(load_config(env={}), FakeLLM(respond), run)
    h.config.search.num_drafts = 1
    h.config.search.debug_prob = 1.0
    h.config.search.max_debug_depth = 3
    h.config.search.steps_per_stage = 4
    h.config.search.max_turns = 3
    return h


def test_recovers_through_debug(tmp_path: Path) -> None:
    good = (
        "import json\n"
        "json.dump({'m': {'value': 1.5}}, open('results.json','w'))\n"
        "open('out.txt','w').write('x')"
    )
    h = _harness(
        tmp_path,
        [
            "thinking",
            "still thinking",
            "no tool",
            _tool("run_python", code="print(1)"),
            _submit("open('results.json','w').write('[]')"),
            _submit(good),
        ],
    )
    best = run_stage(h, SPEC, random.Random(0))
    assert best.results == {"m": {"value": 1.5}} and best.kind == "debug"
    stage = h.run.path("tree", SPEC.name)
    analysis = stage / "stage-000" / "analysis.md"
    assert analysis.read_text(encoding="utf-8").startswith("no submit within 3 turns")
    assert (stage / "stage-001" / "scratch" / "00" / "code.py").exists()
    meta = json.loads((stage / "stage-001" / "meta.json").read_text(encoding="utf-8"))
    assert meta["reason"].startswith("debug stage-000")


def test_judge_llm_error_marks_node_buggy_and_stage_continues(tmp_path: Path) -> None:
    good = (
        "import json\n"
        "json.dump({'m': {'value': 1.5}}, open('results.json','w'))\n"
        "open('out.txt','w').write('x')"
    )
    h = _harness(tmp_path, [_submit(good), _submit(good)], [LLMError("judge down"), FEEDBACK])
    best = run_stage(h, SPEC, random.Random(0))
    assert best.id == "stage-001" and best.status == "ok"
    first = h.run.path("tree", SPEC.name) / "stage-000"
    assert (first / "analysis.md").read_text(encoding="utf-8") == "judge call failed: judge down"
    assert json.loads((first / "meta.json").read_text(encoding="utf-8"))["status"] == "buggy"


def test_submit_without_code_is_buggy(tmp_path: Path) -> None:
    h = _harness(tmp_path, [_tool("submit")])
    h.config.search.steps_per_stage = 1
    with pytest.raises(StageFailed):
        run_stage(h, SPEC, random.Random(0))
    analysis = h.run.path("tree", SPEC.name) / "stage-000" / "analysis.md"
    assert analysis.read_text(encoding="utf-8") == "submit without code"


def test_all_buggy_raises_stage_failed(tmp_path: Path) -> None:
    h = _harness(tmp_path, [_submit("raise RuntimeError('boom')")] * 4)
    with pytest.raises(StageFailed) as info:
        run_stage(h, SPEC, random.Random(0))
    assert info.value.stage == SPEC.name


@pytest.mark.parametrize("stderr_length", [0, 12000])
def test_failed_fit_diagnostics_reach_debug_node(tmp_path: Path, stderr_length: int) -> None:
    h = _harness(
        tmp_path,
        [
            _submit(
                "import sys\nprint('fit failed:' + ' parameter dimension mismatch')\n"
                f"sys.stderr.write('x' * {stderr_length})\nraise RuntimeError('empty fits')"
            ),
            _submit(
                "import json\njson.dump({'m': {'value': 1}}, open('results.json','w'))\n"
                "open('out.txt','w').write('x')"
            ),
        ],
    )
    h.config.search.steps_per_stage = 2
    best = run_stage(h, SPEC, random.Random(0))
    assert best.kind == "debug"
    assert isinstance(h.llm, FakeLLM)
    requests = [req for req in h.llm.calls if req.tag == "analyst:stage"]
    assert "fit failed: parameter dimension mismatch" in requests[-1].prompt
    assert "RuntimeError: empty fits" in requests[-1].prompt


def test_min_figures_fails_without_figure(tmp_path: Path) -> None:
    code = _submit("import json\njson.dump({'m': {'value': 1}}, open('results.json','w'))")
    h = _harness(tmp_path, [code] * 4)
    spec = StageSpec("stage", "goal", "ctx", {}, ("results.json",), min_figures=1)
    with pytest.raises(StageFailed):
        run_stage(h, spec, random.Random(0))
    analysis = h.run.path("tree", spec.name) / "stage-000" / "analysis.md"
    assert "expected at least 1 figure(s)" in analysis.read_text(encoding="utf-8")


def test_bad_result_key_makes_node_buggy(tmp_path: Path) -> None:
    code = _submit(
        "import json\njson.dump({'r2.adj': {'value': 1}}, open('results.json','w'))\n"
        "open('out.txt','w')"
    )
    h = _harness(tmp_path, [code])
    h.config.search.steps_per_stage = 1
    with pytest.raises(StageFailed):
        run_stage(h, SPEC, random.Random(0))
    analysis = h.run.path("tree", SPEC.name) / "stage-000" / "analysis.md"
    assert "'r2.adj'" in analysis.read_text(encoding="utf-8")


def test_null_ci_is_dropped_from_results(tmp_path: Path) -> None:
    code = _submit(
        "import json\njson.dump({'m': {'value': 1, 'ci': None}}, open('results.json','w'))\n"
        "open('out.txt','w')"
    )
    h = _harness(tmp_path, [code])
    assert run_stage(h, SPEC, random.Random(0)).results == {"m": {"value": 1}}


def test_stage_check_rejection_makes_node_buggy(tmp_path: Path) -> None:
    code = _submit(
        "import json\njson.dump({'m': {'value': 1}}, open('results.json','w'))\nopen('out.txt','w')"
    )
    h = _harness(tmp_path, [code])
    h.config.search.steps_per_stage = 1
    spec = StageSpec("stage", "goal", "ctx", {}, ("results.json",), check=lambda _: "no good")
    with pytest.raises(StageFailed):
        run_stage(h, spec, random.Random(0))
    analysis = h.run.path("tree", spec.name) / "stage-000" / "analysis.md"
    assert "no good" in analysis.read_text(encoding="utf-8")


_OK_CODE = _submit(
    "import json\njson.dump({'m': {'value': 1}}, open('results.json','w'))\nopen('out.txt','w')"
)


def test_same_role_instances_are_isolated(tmp_path: Path) -> None:
    h = _harness(tmp_path, [_OK_CODE, _OK_CODE], [FEEDBACK, FEEDBACK])
    specs = [
        StageSpec("main", "goal", "ctx", {}, ("results.json",), instance_id=identity)
        for identity in ("h001-s001-main", "h002-s001-main")
    ]
    for spec in specs:
        best = run_stage(h, spec)
        assert best.id == f"{spec.instance_id}-000"
        assert best.stage == "main" and best.stage_instance == spec.instance_id
        assert best.dir == h.run.root / "tree" / str(spec.instance_id) / best.id
        assert [n.id for n in load_nodes(h, str(spec.instance_id))] == [best.id]
        metadata = json.loads((best.dir / "meta.json").read_bytes())
        assert metadata["stage"] == "main" and metadata["stage_instance"] == spec.instance_id
    assert load_nodes(h, "main") == []
    no_calls = Harness(
        h.config, FakeLLM(lambda _: pytest.fail("completed instance must not replay")), h.run
    )
    for spec in specs:
        assert run_stage(no_calls, spec).id == f"{spec.instance_id}-000"


def test_scoped_stage_uses_role_budget(tmp_path: Path) -> None:
    nonterminal = FEEDBACK.replace('"goal_met": true', '"goal_met": false')
    terminal = FEEDBACK.replace('"node_score": 7', '"node_score": 8')
    h = _harness(tmp_path, [_OK_CODE] * 4, [nonterminal, terminal] * 2)
    h.config.search.steps_per_stage = 1
    h.config.search.stage_steps["main"] = 2
    for identity in ("h001-s001-main", "h002-s001-main"):
        best = run_stage(
            h, StageSpec("main", "goal", "ctx", {}, ("results.json",), instance_id=identity)
        )
        assert best.id == f"{identity}-001" and best.parent == f"{identity}-000"
        assert len(load_nodes(h, identity)) == 2
    starts = [e for e in read_events(h.run.root) if e["event"] == "stage_start"]
    assert [e["steps"] for e in starts] == [2, 2]
    assert [e["stage"] for e in starts] == ["main", "main"]
    assert [e["stage_instance"] for e in starts] == ["h001-s001-main", "h002-s001-main"]


@pytest.mark.parametrize("instance_id", [None, "h001-s001-main"])
def test_stage_instance_cannot_change_role(tmp_path: Path, instance_id: str | None) -> None:
    h = _harness(tmp_path, [_OK_CODE])
    spec = StageSpec("main", "goal", "ctx", {}, ("results.json",), instance_id=instance_id)
    run_stage(h, spec)
    before = {p: p.read_bytes() for p in h.run.root.rglob("*") if p.is_file()}
    h.llm = FakeLLM(lambda _: pytest.fail("role mismatch must fail before model calls"))
    with pytest.raises(ValueError, match="role"):
        run_stage(h, StageSpec("baseline", "goal", "ctx", {}, (), instance_id=spec.execution_id))
    assert {p: p.read_bytes() for p in h.run.root.rglob("*") if p.is_file()} == before


def test_stage_stops_when_good_score_stops_improving(tmp_path: Path) -> None:
    steady = FEEDBACK.replace("true", "false")
    h = _harness(tmp_path, [_OK_CODE] * 6, [steady] * 6)
    h.config.search.steps_per_stage = 6
    h.config.search.good_score = 7
    h.config.search.patience = 2
    run_stage(h, SPEC, random.Random(0))
    assert len(list(h.run.path("tree", SPEC.name).glob("stage-*"))) == 3


def test_describe_text_reaches_feedback_prompt(tmp_path: Path) -> None:
    h = _harness(tmp_path, [_OK_CODE])
    spec = StageSpec(
        "stage", "goal", "ctx", {}, ("results.json",), describe=lambda _: "SUMMARY-XYZ"
    )
    run_stage(h, spec, random.Random(0))
    assert isinstance(h.llm, FakeLLM)
    judged = [c for c in h.llm.calls if c.tag.startswith("judge:")]
    assert "SUMMARY-XYZ" in judged[0].prompt


def test_provider_error_marks_node_buggy(tmp_path: Path) -> None:
    good = (
        "import json\n"
        "json.dump({'m': {'value': 1.5}}, open('results.json','w'))\n"
        "open('out.txt','w').write('x')"
    )
    h = _harness(tmp_path, [LLMError("ValidationException"), _submit(good)])
    best = run_stage(h, SPEC, random.Random(0))
    assert best.status == "ok"
    analysis = h.run.path("tree", SPEC.name) / "stage-000" / "analysis.md"
    assert analysis.read_text(encoding="utf-8").startswith("model call failed")


@pytest.mark.slow
def test_judge_receives_figures_and_persists_quality_reason(tmp_path: Path) -> None:
    code = _submit("""
import json, os
import matplotlib.pyplot as plt
os.mkdir('figures')
plt.plot([0, 1], [0, 1]); plt.savefig('figures/result.png')
json.dump({'m': {'value': 1}}, open('results.json', 'w'))
open('out.txt','w').write('x')
""")
    verdict = '{"node_buggy":false,"goal_met":true,"node_score":4,"analysis":"unreadable axis","figure_issues":["unreadable axis"]}'
    h = _harness(tmp_path, [code], [verdict])
    best = run_stage(h, SPEC)
    assert best.score == 4 and "unreadable axis" in best.analysis
    assert isinstance(h.llm, FakeLLM)
    request = next(req for req in h.llm.calls if req.tag.startswith("judge:"))
    assert request.messages[0].images == (best.execution_dir / "figures" / "result.png",)


def test_scheduled_attempts_run_before_debug_and_ignore_early_goal(tmp_path: Path) -> None:
    h = _harness(tmp_path, [_submit("raise ValueError('bad')"), *[_OK_CODE] * 5], [FEEDBACK] * 5)
    h.config.search.steps_per_stage = 6
    attempts = tuple(AttemptSpec(f"v{i}", "variant", f"check {i}", "ctx") for i in range(5))
    spec = StageSpec("stage", "goal", "ctx", {}, ("results.json", "out.txt"), attempts=attempts)
    run_stage(h, spec)
    nodes = [
        json.loads(p.read_text()) for p in sorted(h.run.path("tree", "stage").glob("*/meta.json"))
    ]
    assert [n["attempt_id"] for n in nodes] == ["v0", "v1", "v2", "v3", "v4", "v0"]
    assert [n["kind"] for n in nodes] == ["variant"] * 5 + ["debug"]
