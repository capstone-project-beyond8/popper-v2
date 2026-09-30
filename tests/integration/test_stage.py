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


def _harness(tmp_path: Path, code: list[str]) -> Harness:
    replies = {"code:": iter(code), "feedback:": iter([FEEDBACK])}

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
    assert analysis.read_text().startswith("no code block")


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
    assert "expected at least 1 figure(s)" in analysis.read_text()
