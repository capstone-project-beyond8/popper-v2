
import json
from pathlib import Path

import pandas as pd
import pytest

from popper.config import load_config
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.session import Harness
from popper.stages.discover.experiment import experiment, run_experiment_stage
from popper.workflow.run import create_run
from tests.unit.test_hypothesis import ESTIMAND, PROPOSAL

pytestmark = pytest.mark.integration
EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "student_performance"


def test_insufficient_repair_budget_fails_before_model_work(tmp_path: Path) -> None:
    cfg = load_config(env={})
    cfg.search.stage_steps["robustness"] = cfg.robustness.min_variants + 1
    store = create_run(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv", config=cfg)
    pd.DataFrame({"score": [1], "hours": [2]}).to_parquet(store.path("data", "processed.parquet"))

    def respond(req: LLMRequest) -> str:
        raise AssertionError(f"unexpected model call: {req.tag}")

    fake = FakeLLM(respond)
    with pytest.raises(ValueError, match="repair"):
        experiment(Harness(cfg, fake, store), {}, PROPOSAL, tmp_path)
    assert not fake.calls


@pytest.mark.slow
def test_main_seeds_from_baseline_and_judge_is_blinded(tmp_path: Path) -> None:
    invalid_reply_sent = False

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        nonlocal invalid_reply_sent
        if req.tag.startswith("judge:"):
            if not invalid_reply_sent:
                invalid_reply_sent = True
                return "invalid JSON"
            return json.dumps(
                {"node_buggy": False, "goal_met": True, "node_score": 7, "analysis": "valid"}
            )
        code = "\n".join(
            [
                "import json, os, base64",
                "signed_sentinel = -0.731",
                "os.mkdir('figures')",
                "open('figures/estimate.png','wb').write(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7XcAAAAASUVORK5CYII='))",
                "json.dump({'primary_estimate': {'value': 19.8765, 'ci': [18, 21], 'n': 50}} ,open('results.json','w'))",
                f"json.dump({ESTIMAND!r}, open('estimand.json','w'))",
            ]
        )
        return (ToolCall("submit", "submit", {"code": code}),)

    cfg = load_config(env={})
    store = create_run(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv", config=cfg)
    pd.DataFrame({"score": [1], "hours": [2]}).to_parquet(store.path("data", "processed.parquet"))
    fake = FakeLLM(respond)
    h = Harness(cfg, fake, store)
    baseline = run_experiment_stage(h, "baseline", {}, PROPOSAL, None)
    main = run_experiment_stage(h, "main", {}, PROPOSAL, baseline)
    assert main.stage == "main" and main.status == "ok"
    request = next(req for req in fake.calls if req.tag == "analyst:main")
    assert baseline.code in request.prompt
    judges = [req for req in fake.calls if req.tag.startswith("judge:")]
    assert all("19.8765" not in req.prompt and req.messages[0].images for req in judges)
    assert len(judges) == 3 and all(
        "-'<withheld>'" not in req.prompt and "0.731" not in req.prompt for req in judges
    )
    assert "Validated method reference" in judges[0].prompt and "bootstrap" in judges[-1].prompt
