import json
from pathlib import Path

import pandas as pd
import pytest

from popper.discover.contracts import Attempt, ResearchMove, commit_record
from popper.discover.contracts import TestSpec as ScientificTest
from popper.discover.experiment import ExperimentRequest, experiment
from popper.discover.policy import make_attempt
from popper.discover.state import commit_snapshot, rebuild_state
from popper.harness.config import load_config
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.records import resolve_artifact, resolve_measurement
from popper.harness.session import Harness
from popper.harness.store import RunStore
from tests.unit.test_test_identity import spec_payload

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def test_measurement_repair_retains_parent_and_reuses_unaffected_baseline(tmp_path: Path) -> None:
    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    h.run.path("data").mkdir()
    pd.DataFrame({"x": [1, 2], "y": [2, 3]}).to_parquet(h.run.path("data/processed.parquet"))
    prep = h.run.write_json("prep.json", {})
    h.run.commit_artifact("prep", prep)
    payload = spec_payload()
    payload["preparation"] = h.run.artifact_ref("prep").model_dump()
    intended = commit_record(h, "test", ScientificTest.model_validate(payload), key="t1")
    move = commit_record(h, "move", {"id": "m1"})
    parent_ref = commit_record(h, "attempt", Attempt(id="attempt-000", move=move, move_id="m1", hypothesis_id="h1", test=intended, parent=None, diagnosis=None, changed_fields=[], stage_instances={role: f"h1-attempt-000-{role}" for role in ("baseline", "main", "robustness")}, move_count=1, revisit_count=0, exposure=[]), key="m1")
    repairing = False

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        if req.tag.startswith("judge:"):
            defect = "main" in req.tag and not repairing
            return json.dumps({"node_buggy": False, "goal_met": True, "node_score": 7, "analysis": "computes output",
                              "fidelity_status": "defect" if defect else "consistent",
                              "fidelity_reason": "Code multiplies estimate by 100, violating declared points" if defect else "Declared points restored",
                              "fidelity_requirements": ["original points scale"], "fidelity_evidence": ["code: multiplication", "output: primary_estimate"]})
        value = 2 if repairing or "baseline" in req.tag else 200
        code = ("import json\n" + f"json.dump({{'primary_estimate':{{'value':{value},'ci':[{value-1},{value+1}],'n':2}}}},open('results.json','w'))\n" +
                f"json.dump({payload['primary_estimand']!r},open('estimand.json','w'))\n" +
                "json.dump({'seeds':[7],'interval_level':.95,'effect_scale':'points'},open('coverage.json','w'))")
        return (ToolCall("submit", "submit", {"code": code}),)

    h.llm = FakeLLM(respond)
    hypothesis = {"primary_estimand": payload["primary_estimand"], "methods": payload["methods"], "planned_test": "contrast"}
    experiment(h, {}, hypothesis, tmp_path, request=ExperimentRequest(intended, parent_ref))
    state = rebuild_state(h)
    bad = next(m.record.ref for m in state.history if m.record.role == "main")
    assert resolve_measurement(h.run, bad).value == 200
    assert len(state.observations) == 1
    diagnosis = state.diagnoses[-1].ref
    snapshot = commit_snapshot(h, state)
    child_move = ResearchMove(id="m2", snapshot=snapshot, action="measurement_repair", objective="restore scale", trigger_refs=[diagnosis], hypothesis_id="h1", test=intended, diagnosis=diagnosis, cost_usd=0, discriminating_outcomes=["correct points", "unresolved scaling"], stopping_condition="corrected declared scale", changed_fields=["implementation"])
    child_ref = make_attempt(h, child_move, parent_ref)
    child = Attempt.model_validate_json(resolve_artifact(h.run, child_ref).read_text())
    parent_bytes = {p: p.read_bytes() for p in h.run.path("tree/h1-attempt-000-main").rglob("*") if p.is_file()}
    assert child.revisit_count == 1 and child.reuse["baseline"] == state.results[0].record.stages["baseline"]
    repairing = True
    experiment(h, {}, hypothesis, tmp_path, request=ExperimentRequest(intended, child_ref))
    final = rebuild_state(h)
    assert len(final.observations) == 2
    assert len(final.history) == 3
    assert resolve_measurement(h.run, bad).value == 200
    good = next(m.record.ref for m in final.observations if m.record.role == "main")
    assert resolve_measurement(h.run, good).value == 2
    assert good.test_id == bad.test_id and good.execution_id != bad.execution_id
    assert all(p.read_bytes() == content for p, content in parent_bytes.items())
