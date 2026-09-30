import json
import random
from pathlib import Path

import pytest

from popper.harness.config import load_config
from popper.harness.llm import FakeLLM, LLMError, LLMRequest, ToolCall
from popper.harness.session import Harness
from popper.harness.store import RunStore
from popper.treesearch.engine import StageFailed, StageSpec, run_stage

pytestmark = pytest.mark.integration

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "student_performance"
FEEDBACK = '{"node_buggy": false, "goal_met": true, "node_score": 7, "analysis": "fine"}'
Reply = str | tuple[ToolCall, ...] | LLMError
SPEC = StageSpec("stage", "goal", "ctx", {}, ("results.json", "out.txt"))


def _tool(name: str, **args: object) -> tuple[ToolCall, ...]:
    return (ToolCall(f"id-{name}", name, dict(args)),)


def _submit(code: str) -> tuple[ToolCall, ...]:
    return _tool("submit", code=code)


def _harness(tmp_path: Path, analyst: list[Reply], judge: list[str] | None = None) -> Harness:
    replies = {"analyst:": iter(analyst), "judge:": iter(judge or [FEEDBACK])}

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        reply = next(next(v for k, v in replies.items() if req.tag.startswith(k)))
        if isinstance(reply, LLMError):
            raise reply
        return reply

    run = RunStore.create(tmp_path, EXAMPLE / "brief.md", EXAMPLE / "data.csv")
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
