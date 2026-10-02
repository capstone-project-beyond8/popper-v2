import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from popper.discover.contracts import Attempt, AttemptResult, commit_record
from popper.discover.contracts import TestSpec as ScientificTest
from popper.discover.experiment import ExperimentRequest, experiment
from popper.harness.config import load_config
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.records import resolve_measurement
from popper.harness.session import Harness
from popper.harness.store import RunStore
from tests.unit.test_test_identity import spec_payload

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.mark.parametrize("failed_variant", [False, True])
def test_scoped_negative_measurements_and_resume(tmp_path: Path, failed_variant: bool) -> None:
    cfg = load_config(env={})
    h = Harness(cfg, FakeLLM(lambda _: ""), RunStore(tmp_path))
    pd.DataFrame({"x": [1, 2], "y": [2, 3]}).to_parquet(h.run.path("processed.parquet"))
    prep = h.run.write_json("preparation/changes.json", {})
    h.run.commit_artifact("prep", prep)
    h.run.path("data").mkdir()
    h.run.copy_once(h.run.path("processed.parquet"), "data/processed.parquet")
    results: list[AttemptResult] = []
    for index in (1, 2):
        payload = spec_payload()
        payload.update(id=f"t{index}", hypothesis_id=f"h{index}", preparation=h.run.artifact_ref("prep").model_dump())
        payload["support_rule"] = {"kind": "directional_ci", "result_key": "primary_estimate", "interval_level": .95, "null": 0, "direction": "positive"}
        if failed_variant:
            payload["requested_coverage"] = {"seeds": [7], "alternatives": [{"selection": {"slice": "x > 1", "assumptions": ["same target population"]}}]}
        test = commit_record(h, "test", ScientificTest.model_validate(payload), key=f"t{index}")
        move = commit_record(h, "move", {"id": f"m{index}"})
        attempt = commit_record(h, "attempt", Attempt(id=f"a{index}", move=move, move_id=f"m{index}", hypothesis_id=f"h{index}", test=test, parent=None, diagnosis=None, changed_fields=[], stage_instances={role: f"h{index}-a{index}-{role}" for role in ("baseline", "main", "robustness")}, move_count=index, revisit_count=0, exposure=[]), key=f"m{index}")

        def respond(req: LLMRequest, payload: dict[str, Any] = payload) -> str | tuple[ToolCall, ...]:
            if req.tag.startswith("judge:"):
                return json.dumps({"node_buggy": False, "goal_met": True, "node_score": 7, "analysis": "valid", "fidelity_status": "consistent", "fidelity_reason": "Code computes declared contrast and reports required outputs", "fidelity_requirements": ["contrast", "scale"], "fidelity_evidence": ["code: means", "output: declared scale"]})
            code = "raise RuntimeError('variant failure')" if "robustness" in req.tag else (
                "import json\n"
                "json.dump({'primary_estimate': {'value': -2., 'ci': [-3., -1.], 'n': 2}}, open('results.json','w'))\n"
                f"json.dump({payload['primary_estimand']!r}, open('estimand.json','w'))\n"
                "json.dump({'seeds':[7], 'interval_level':.95, 'effect_scale':'points'}, open('coverage.json','w'))"
            )
            return (ToolCall("submit", "submit", {"code": code}),)

        h.llm = FakeLLM(respond)
        hypothesis: dict[str, Any] = {"primary_estimand": payload["primary_estimand"], "methods": payload["methods"], "planned_test": "compare"}
        request = ExperimentRequest(test=test, attempt=attempt)
        path = experiment(h, {}, hypothesis, prep.parent, request=request)
        result = AttemptResult.model_validate_json(path.read_text("utf-8"))
        assert result.status == ("partial" if failed_variant else "complete")
        assert len(result.variant_tests) == int(failed_variant)
        main = next(m for m in result.measurements if m.role == "main")
        assert main.support == "not_supported"
        assert resolve_measurement(h.run, main.ref).value == -2.
        h.llm = FakeLLM(lambda req: (_ for _ in ()).throw(AssertionError(req.tag)))
        assert experiment(h, {}, hypothesis, prep.parent, request=request) == path
        results.append(result)
    assert results[0].stages["main"] != results[1].stages["main"]
    assert results[0].measurements[1].ref.test_id == "t1"
    assert results[1].measurements[1].ref.test_id == "t2"
