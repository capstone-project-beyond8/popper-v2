import json
from pathlib import Path

import pytest

from popper.discover.experiment import run_experiment_stage
from popper.harness.config import load_config
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.session import Harness
from popper.harness.store import RunStore
from tests.unit.test_hypothesis import ESTIMAND, PROPOSAL

pytestmark = pytest.mark.integration
EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "student_performance"


def test_main_seeds_from_baseline_and_judge_is_blinded(tmp_path: Path) -> None:
    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        if req.tag.startswith("judge:"):
            return json.dumps(
                {"node_buggy": False, "goal_met": True, "node_score": 7, "analysis": "valid"}
            )
        code = "\n".join(
            [
                "import json, os, base64",
                "os.mkdir('figures')",
                "open('figures/estimate.png','wb').write(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7XcAAAAASUVORK5CYII='))",
                "json.dump({'primary_estimate': {'value': 19.8765, 'ci': [18, 21], 'n': 50}} ,open('results.json','w'))",
                f"json.dump({ESTIMAND!r}, open('estimand.json','w'))",
            ]
        )
        return (ToolCall("submit", "submit", {"code": code}),)

    cfg = load_config(env={})
    store = RunStore.create(tmp_path, EXAMPLE / "brief.md", EXAMPLE / "data.csv", config=cfg)
    fake = FakeLLM(respond)
    h = Harness(cfg, fake, store)
    baseline = run_experiment_stage(h, "baseline", {}, PROPOSAL, None)
    main = run_experiment_stage(h, "main", {}, PROPOSAL, baseline)
    assert main.stage == "main" and main.status == "ok"
    request = next(req for req in fake.calls if req.tag == "analyst:main")
    assert baseline.code in request.prompt
    judges = [req for req in fake.calls if req.tag.startswith("judge:")]
    assert all("19.8765" not in req.prompt and req.messages[0].images for req in judges)
