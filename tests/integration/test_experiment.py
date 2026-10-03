
import json
from pathlib import Path

import pandas as pd
import pytest

from popper.config import load_config
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.session import Harness
from popper.scientific.runtime.lifecycle.contracts import ExperimentSpec
from popper.scientific.runtime.store import ScienceStore
from popper.stages.discover.experiment import run_experiment_stage
from popper.workflow.run import create_run
from tests.unit.test_test_identity import spec_payload

pytestmark = pytest.mark.integration
EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "student_performance"


@pytest.mark.slow
def test_main_seeds_from_baseline_and_judge_is_blinded(tmp_path: Path) -> None:
    invalid_reply_sent = False

    estimand = spec_payload()["primary_estimand"]

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        nonlocal invalid_reply_sent
        if req.tag.startswith("judge:"):
            if not invalid_reply_sent:
                invalid_reply_sent = True
                return "invalid JSON"
            return json.dumps(
                {
                    "node_buggy": False, "goal_met": True, "node_score": 7, "analysis": "valid",
                    "fidelity_status": "consistent", "fidelity_reason": "Code computes declared contrast",
                    "fidelity_requirements": ["contrast"], "fidelity_evidence": ["code: means"],
                }
            )
        code = "\n".join(
            [
                "import json, os, base64",
                "signed_sentinel = -0.731",
                "os.mkdir('figures')",
                "open('figures/estimate.png','wb').write(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7XcAAAAASUVORK5CYII='))",
                "json.dump({'primary_estimate': {'value': 19.8765, 'ci': [18, 21], 'n': 50}} ,open('results.json','w'))",
                f"json.dump({estimand!r}, open('estimand.json','w'))",
                "json.dump({'seeds':[7], 'interval_level':.95, 'effect_scale':'points'}, open('coverage.json','w'))",
            ]
        )
        return (ToolCall("submit", "submit", {"code": code}),)

    cfg = load_config(env={})
    store = create_run(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv", config=cfg)
    pd.DataFrame({"y": [1], "x": [2]}).to_parquet(store.path("data", "processed.parquet"))
    store.commit_artifact("prep", store.write_json("preparation/changes.json", {}))
    payload = {**spec_payload(), "preparation": store.artifact_ref("prep").model_dump()}
    test = ScienceStore(store).commit("test", ExperimentSpec.model_validate(payload), key="t1")
    fake = FakeLLM(respond)
    h = Harness(cfg, fake, store)
    hypothesis: dict[str, object] = {}
    baseline = run_experiment_stage(h, "baseline", {}, hypothesis, None, test=test)
    main = run_experiment_stage(h, "main", {}, hypothesis, baseline, test=test)
    assert main.stage == "main" and main.status == "ok"
    request = next(req for req in fake.calls if req.tag == "analyst:main")
    assert baseline.code in request.prompt
    judges = [req for req in fake.calls if req.tag.startswith("judge:")]
    assert all("19.8765" not in req.prompt and req.messages[0].images for req in judges)
    assert len(judges) == 3 and all(
        "-'<withheld>'" not in req.prompt and "0.731" not in req.prompt for req in judges
    )
    assert "Declared estimand" in judges[0].prompt
