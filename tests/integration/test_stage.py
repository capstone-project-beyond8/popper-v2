import random
from pathlib import Path

import pytest

from popper.harness.config import load_config
from popper.harness.llm import FakeLLM, LLMRequest
from popper.harness.session import Harness
from popper.harness.store import RunStore
from popper.treesearch.engine import StageFailed, StageSpec, run_stage

pytestmark = pytest.mark.integration

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "student_performance"
FEEDBACK = '{"is_buggy": false, "analysis": "fine", "score": 7, "goal_met": true}'
SPEC = StageSpec("stage", "goal", "ctx", {}, ("results.json", "out.txt"))


def _py(body: str) -> str:
    return f"```python\n{body}\n```"


def _harness(tmp_path: Path, code: list[str], feedback: list[str] | None = None) -> Harness:
    replies = {"code:": iter(code), "feedback:": iter(feedback or [FEEDBACK])}

    def respond(req: LLMRequest) -> str:
        return next(next(v for k, v in replies.items() if req.tag.startswith(k)))

    run = RunStore.create(tmp_path, EXAMPLE / "brief.md", EXAMPLE / "data.csv")
    h = Harness(load_config(env={}), FakeLLM(respond), run)
    h.config.search.num_drafts = 1
    h.config.search.debug_prob = 1.0
    h.config.search.max_debug_depth = 3
    h.config.search.steps_per_stage = 4
    return h


def test_recovers_through_debug(tmp_path: Path) -> None:
    h = _harness(
        tmp_path,
        [
            "no code here",
            _py("open('results.json','w').write('[]')"),
            _py(
                "import json\n"
                "json.dump({'m': {'value': 1.5}}, open('results.json','w'))\n"
                "open('out.txt','w').write('x')"
            ),
        ],
    )
    best = run_stage(h, SPEC, random.Random(0))
    assert best.results == {"m": {"value": 1.5}} and best.kind == "debug"
    analysis = h.run.path("tree", SPEC.name) / "stage-000" / "analysis.md"
    assert analysis.read_text(encoding="utf-8").startswith("no code block")


def test_all_buggy_raises_stage_failed(tmp_path: Path) -> None:
    h = _harness(tmp_path, [_py("raise RuntimeError('boom')")] * 4)
    with pytest.raises(StageFailed) as info:
        run_stage(h, SPEC, random.Random(0))
    assert info.value.stage == SPEC.name


def test_min_figures_fails_without_figure(tmp_path: Path) -> None:
    code = _py("import json\njson.dump({'m': {'value': 1}}, open('results.json','w'))")
    h = _harness(tmp_path, [code] * 4)
    spec = StageSpec("stage", "goal", "ctx", {}, ("results.json",), min_figures=1)
    with pytest.raises(StageFailed):
        run_stage(h, spec, random.Random(0))
    analysis = h.run.path("tree", spec.name) / "stage-000" / "analysis.md"
    assert "expected at least 1 figure(s)" in analysis.read_text(encoding="utf-8")


def test_bad_result_key_makes_node_buggy(tmp_path: Path) -> None:
    code = _py(
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
    code = _py(
        "import json\njson.dump({'m': {'value': 1, 'ci': None}}, open('results.json','w'))\n"
        "open('out.txt','w')"
    )
    h = _harness(tmp_path, [code])
    assert run_stage(h, SPEC, random.Random(0)).results == {"m": {"value": 1}}


def test_stage_check_rejection_makes_node_buggy(tmp_path: Path) -> None:
    code = _py(
        "import json\njson.dump({'m': {'value': 1}}, open('results.json','w'))\nopen('out.txt','w')"
    )
    h = _harness(tmp_path, [code])
    h.config.search.steps_per_stage = 1
    spec = StageSpec("stage", "goal", "ctx", {}, ("results.json",), check=lambda _: "no good")
    with pytest.raises(StageFailed):
        run_stage(h, spec, random.Random(0))
    analysis = h.run.path("tree", spec.name) / "stage-000" / "analysis.md"
    assert "no good" in analysis.read_text(encoding="utf-8")


_OK_CODE = _py(
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
    feedback = [c for c in h.llm.calls if c.tag.startswith("feedback:")]
    assert "SUMMARY-XYZ" in feedback[0].prompt
