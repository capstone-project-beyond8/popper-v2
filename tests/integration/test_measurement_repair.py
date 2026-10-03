import json
from pathlib import Path

import pandas as pd
import pytest

from popper.config import load_config
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.session import Harness
from popper.harness.storage.records import resolve_artifact
from popper.harness.storage.store import RunStore
from popper.scientific.runtime.evidence.references import resolve_measurement
from popper.scientific.runtime.lifecycle.contracts import (
    Attempt,
    Diagnosis,
    Invalidation,
    ResearchMove,
)
from popper.scientific.runtime.lifecycle.contracts import ExperimentSpec as ScientificTest
from popper.scientific.runtime.lifecycle.requests import ExperimentRequest
from popper.scientific.runtime.lifecycle.transitions import schedule_attempt
from popper.scientific.runtime.projections.state import commit_snapshot, rebuild_state
from popper.scientific.runtime.store import ScienceStore
from popper.scientific.scientist.feedback import interpret_result
from popper.stages.discover.experiment import experiment
from tests.unit.test_test_identity import spec_payload

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.mark.parametrize(("affected_role", "other_defect"), [("main", False), ("baseline", False), ("main", True)])
def test_measurement_repair_retains_parent_and_reuses_unaffected_baseline(tmp_path: Path, affected_role: str, other_defect: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    h.run.path("data").mkdir()
    pd.DataFrame({"x": [1, 2], "y": [2, 3]}).to_parquet(h.run.path("data/processed.parquet"))
    prep = h.run.write_json("prep.json", {})
    h.run.commit_artifact("prep", prep)
    payload = spec_payload()
    payload["preparation"] = h.run.artifact_ref("prep").model_dump()
    intended = ScienceStore(h.run).commit("test", ScientificTest.model_validate(payload), key="t1")
    move = ScienceStore(h.run).commit("move", {"id": "m1"})
    parent_ref = ScienceStore(h.run).commit("attempt",
        Attempt(
            id="attempt-000",
            move=move,
            move_id="m1",
            hypothesis_id="h1",
            test=intended,
            parent=None,
            diagnosis=None,
            changed_fields=[],
            stage_instances={
                role: f"h1-attempt-000-{role}" for role in ("baseline", "main", "robustness")
            },
            move_count=1,
            revisit_count=0,
            exposure=[],
        ),
        key="m1",
    )
    repairing = False

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        if req.tag == "interpret_result":
            current = rebuild_state(ScienceStore(h.run)).results[-1]
            return (ToolCall("interpret", "submit_interpretation", {
                "summary": "Corrected measurement restores the intended scale." if repairing else "Scaling defects leave the intended contrast unresolved.",
                "rivals": ["Selection"], "limitations": ["Observational design"],
                "questions": ["Does the faithful contrast discriminate the surviving explanation?"],
                "sources": [current.ref.model_dump(mode="json")],
            }),)
        if req.tag.startswith("judge:"):
            defect = (affected_role in req.tag or other_defect) and not repairing
            return json.dumps(
                {
                    "node_buggy": False,
                    "goal_met": True,
                    "node_score": 7,
                    "analysis": "computes output",
                    "fidelity_status": "defect" if defect else "consistent",
                    "fidelity_reason": "Code multiplies estimate by 100, violating declared points"
                    if defect
                    else "Declared points restored",
                    "fidelity_requirements": ["original points scale"],
                    "fidelity_evidence": ["code: multiplication", "output: primary_estimate"],
                }
            )
        value = 2 if repairing or "baseline" in req.tag else 200
        code = (
            "import json\n"
            + f"json.dump({{'primary_estimate':{{'value':{value},'ci':[{value - 1},{value + 1}],'n':2}}}},open('results.json','w'))\n"
            + f"json.dump({payload['primary_estimand']!r},open('estimand.json','w'))\n"
            + "json.dump({'seeds':[7],'interval_level':.95,'effect_scale':'points'},open('coverage.json','w'))"
        )
        return (ToolCall("submit", "submit", {"code": code}),)

    h.llm = FakeLLM(respond)
    hypothesis = {
        "primary_estimand": payload["primary_estimand"],
        "methods": payload["methods"],
        "planned_test": "contrast",
    }
    experiment(h, {}, hypothesis, request=ExperimentRequest(intended, parent_ref))
    state = rebuild_state(ScienceStore(h.run))
    bad = next(m.record.ref for m in state.history if m.record.role == affected_role)
    assert resolve_measurement(h.run, bad).value == (200 if affected_role == "main" else 2)
    assert len(state.observations) == (0 if other_defect else 1)
    from popper.scientific.runtime.projections.output import build_study
    from popper.stages.communicate.paper import write_study

    h.config.budget.max_usd = 0
    old_source = write_study(h, build_study(ScienceStore(h.run), "measurement defect", "budget_exceeded"))[0]
    original_report = old_source.read_bytes()
    h.config.budget.max_usd = 5
    interpretation = interpret_result(h, ScienceStore(h.run), state.results[-1].ref)
    assert interpretation is not None
    interpretation_bytes = resolve_artifact(h.run, interpretation).read_bytes()
    state = rebuild_state(ScienceStore(h.run))
    diagnosis = state.diagnoses[-1].ref
    snapshot = commit_snapshot(ScienceStore(h.run), state)
    child_move = ResearchMove(
        id="m2",
        snapshot=snapshot,
        action="measurement_repair",
        objective="restore scale",
        trigger_refs=[diagnosis],
        hypothesis_id="h1",
        test=intended,
        diagnosis=diagnosis,
        cost_usd=0,
        discriminating_outcomes=["correct points", "unresolved scaling"],
        stopping_condition="corrected declared scale",
        changed_fields=["implementation"],
    )
    original_commit = RunStore.commit_artifact
    interrupted = False

    def commit(store: RunStore, name: str, path: Path) -> None:
        nonlocal interrupted
        original_commit(store, name, path)
        if name == "science:attempt:m2" and not interrupted:
            interrupted = True
            raise KeyboardInterrupt()

    monkeypatch.setattr(RunStore, "commit_artifact", commit)
    with pytest.raises(KeyboardInterrupt):
        schedule_attempt(ScienceStore(h.run), child_move, parent_ref)
    child_ref = schedule_attempt(ScienceStore(h.run), child_move, parent_ref)
    assert len(rebuild_state(ScienceStore(h.run)).attempts) == 2
    assert interpretation in rebuild_state(ScienceStore(h.run)).stale_interpretations
    assert resolve_artifact(h.run, interpretation).read_bytes() == interpretation_bytes
    child = Attempt.model_validate_json(resolve_artifact(h.run, child_ref).read_text())
    parent_bytes = {
        p: p.read_bytes() for p in h.run.path("tree/h1-attempt-000-main").rglob("*") if p.is_file()
    }
    assert child.revisit_count == 1
    if affected_role == "main":
        assert child.reuse["baseline"] == state.results[0].record.stages["baseline"]
    else:
        assert child.reuse == {}
    repairing = True
    experiment(h, {}, hypothesis, request=ExperimentRequest(intended, child_ref))
    final = rebuild_state(ScienceStore(h.run))
    assert len(final.observations) == (1 if other_defect else 2)
    assert len(final.history) == (3 if affected_role == "main" else 4)
    assert resolve_measurement(h.run, bad).value == (200 if affected_role == "main" else 2)
    good = next(m.record.ref for m in final.observations if m.record.role == affected_role)
    assert resolve_measurement(h.run, good).value == 2
    assert good.test_id == bad.test_id and good.execution_id != bad.execution_id
    assert all(p.read_bytes() == content for p, content in parent_bytes.items())
    current_interpretation = interpret_result(h, ScienceStore(h.run), final.results[-1].ref)
    assert current_interpretation is not None
    updated = rebuild_state(ScienceStore(h.run))
    assert updated.stale_interpretations == [interpretation]
    assert current_interpretation not in updated.stale_interpretations
    assert len(updated.interpretations) == 2
    h.config.budget.max_usd = 0
    new_source = write_study(h, build_study(ScienceStore(h.run), "scale corrected"))[0]
    assert new_source != old_source and old_source.read_bytes() == original_report
    contents = new_source.read_text("utf-8")
    assert "excluded from active claims" in contents
    assert "Computed stability" not in contents
    if affected_role == "main":
        reused = next(m.record.ref for m in final.history if m.record.role == "baseline")
        late_defect = ScienceStore(h.run).commit("diagnosis", Diagnosis(
                category="measurement", observation_refs=[child_ref], author="reviewer",
                reason="The reused baseline also had a measurement defect",
                affected_refs=[intended], affected_roles=["baseline"],
            ),
        )
        ScienceStore(h.run).commit("invalidation", Invalidation(measurements=[reused], diagnosis=late_defect))
        assert rebuild_state(ScienceStore(h.run)).stale_interpretations == [interpretation, current_interpretation]
