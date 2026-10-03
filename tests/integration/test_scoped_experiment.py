import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from popper.config import load_config
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.session import Harness
from popper.harness.storage.store import RunStore
from popper.scientific.runtime.evidence.references import resolve_measurement
from popper.scientific.runtime.lifecycle.contracts import Attempt, AttemptResult
from popper.scientific.runtime.lifecycle.contracts import ExperimentSpec as ScientificTest
from popper.scientific.runtime.lifecycle.requests import ExperimentRequest
from popper.scientific.runtime.projections.state import rebuild_state
from popper.scientific.runtime.store import ScienceStore
from popper.scientific.scientist.feedback import interpret_result
from popper.stages.discover.experiment import experiment
from tests.unit.test_test_identity import spec_payload

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@pytest.mark.parametrize(("failed_variant", "overflow"), [(False, False), (True, False), (False, True)])
def test_scoped_negative_measurements_and_resume(tmp_path: Path, failed_variant: bool, overflow: bool) -> None:
    cfg = load_config(env={})
    if overflow:
        cfg.search.stage_steps["robustness"] = 1
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
        if overflow:
            payload["requested_coverage"]["alternatives"] = [{"inference": {"bootstrap": count, "interval_level": .95}} for count in (100, 200, 300)]
        test = ScienceStore(h.run).commit("test", ScientificTest.model_validate(payload), key=f"t{index}")
        move = ScienceStore(h.run).commit("move", {"id": f"m{index}"})
        attempt = ScienceStore(h.run).commit("attempt", Attempt(id=f"a{index}", move=move, move_id=f"m{index}", hypothesis_id=f"h{index}", test=test, parent=None, diagnosis=None, changed_fields=[], stage_instances={role: f"h{index}-a{index}-{role}" for role in ("baseline", "main", "robustness")}, move_count=index, revisit_count=0, exposure=[]), key=f"m{index}")

        def respond(req: LLMRequest, payload: dict[str, Any] = payload) -> str | tuple[ToolCall, ...]:
            if req.tag == "interpret_result":
                outcome = rebuild_state(ScienceStore(h.run)).results[-1]
                return (ToolCall("interpret", "submit_interpretation", {
                    "summary": "The usable negative interval contradicts the positive prediction.",
                    "rivals": ["The opposing association"],
                    "limitations": ["Sensitivity coverage is partial" if outcome.record.status == "partial" else "Association does not establish mechanism"],
                    "questions": ["What explains the opposing association?"],
                    "sources": [outcome.ref.model_dump(mode="json")],
                }),)
            if req.tag.startswith("judge:"):
                return json.dumps({"node_buggy": False, "goal_met": True, "node_score": 7, "analysis": "valid", "fidelity_status": "consistent", "fidelity_reason": "Code computes declared contrast and reports required outputs", "fidelity_requirements": ["contrast", "scale"], "fidelity_evidence": ["code: means", "output: declared scale"]})
            code = "raise RuntimeError('variant failure')" if failed_variant and "robustness" in req.tag else (
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
        assert result.status == ("partial" if failed_variant or overflow else "complete")
        assert len(result.variant_tests) == (3 if overflow else int(failed_variant))
        if overflow:
            assert result.coverage["requested"] == 3 and result.coverage["completed"] == 1
            from popper.harness.storage.records import resolve_artifact
            from popper.scientific.runtime.lifecycle.contracts import Diagnosis
            assert any(Diagnosis.model_validate_json(resolve_artifact(h.run, ref).read_text()).category == "resource" for ref in result.diagnoses)
        main = next(m for m in result.measurements if m.role == "main")
        assert main.support == "not_supported"
        assert resolve_measurement(h.run, main.ref).value == -2.
        original_result = path.read_bytes()
        interpretation = interpret_result(h, ScienceStore(h.run), rebuild_state(ScienceStore(h.run)).results[-1].ref)
        state = rebuild_state(ScienceStore(h.run))
        assert interpretation is not None and path.read_bytes() == original_result
        assert state.interpretations[-1].record.result == state.results[-1].ref
        assert state.results[-1].record.status == result.status
        assert any(m.record.role == "main" and m.record.support == "not_supported" for m in state.observations)
        assert state.questions[-1].record.text == "What explains the opposing association?"
        assert not state.stale_interpretations
        h.llm = FakeLLM(lambda req: (_ for _ in ()).throw(AssertionError(req.tag)))
        assert experiment(h, {}, hypothesis, prep.parent, request=request) == path
        results.append(result)
    assert results[0].stages["main"] != results[1].stages["main"]
    assert results[0].measurements[1].ref.test_id == "t1"
    assert results[1].measurements[1].ref.test_id == "t2"


def test_failed_main_retains_declared_missing_coverage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    from popper.strategies.treesearch.engine import StageFailed

    module = importlib.import_module("popper.stages.discover.experiment")
    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    prep = h.run.write_json("prep.json", {})
    h.run.commit_artifact("prep", prep)
    payload = spec_payload()
    payload["preparation"] = h.run.artifact_ref("prep").model_dump()
    payload["requested_coverage"]["alternatives"] = [
        {"inference": {"bootstrap": 100, "interval_level": .95}},
        {"inference": {"bootstrap": 200, "interval_level": .95}},
    ]
    test = ScienceStore(h.run).commit("test", ScientificTest.model_validate(payload), key="t1")
    move = ScienceStore(h.run).commit("move", {"id": "m1"})
    attempt = ScienceStore(h.run).commit("attempt", Attempt(id="a1", move=move, move_id="m1", hypothesis_id="h1", test=test, parent=None, diagnosis=None, changed_fields=[], stage_instances={role: f"h1-a1-{role}" for role in ("baseline", "main", "robustness")}, move_count=1, revisit_count=0, exposure=[]))

    def fail(*args: object, **kwargs: object) -> None:
        raise StageFailed("main")

    monkeypatch.setattr(module, "run_experiment_stage", fail)
    # No execution can satisfy either alternative once a prerequisite fails.
    monkeypatch.setattr(module.pd, "read_parquet", lambda _: pd.DataFrame(columns=["x", "y"]))
    path = experiment(h, {}, {}, tmp_path, request=ExperimentRequest(test, attempt))
    result = AttemptResult.model_validate_json(path.read_text())
    assert result.status == "failed"
    assert result.coverage["requested"] == 2 and result.coverage["completed"] == 0
    missing = result.coverage["missing"]
    assert result.coverage["status"] == "partial" and isinstance(missing, list) and len(missing) == 2
    assert len(result.variant_tests) == 2


def _run_scoped(tmp_path: Path, **declared: Any) -> tuple[AttemptResult, list[str]]:
    """Execute one scoped test; returns its result and the stage roles that asked for code."""
    cfg = load_config(env={})
    cfg.search.stage_steps["robustness"] = declared.pop("capacity", 6)
    h = Harness(cfg, FakeLLM(lambda _: ""), RunStore(tmp_path))
    pd.DataFrame({"x": [1, 2], "y": [2, 3]}).to_parquet(h.run.path("processed.parquet"))
    prep = h.run.write_json("preparation/changes.json", {})
    h.run.commit_artifact("prep", prep)
    h.run.path("data").mkdir()
    h.run.copy_once(h.run.path("processed.parquet"), "data/processed.parquet")
    payload = {**spec_payload(), "preparation": h.run.artifact_ref("prep").model_dump(), **declared}
    test = ScienceStore(h.run).commit("test", ScientificTest.model_validate(payload), key="t1")
    move = ScienceStore(h.run).commit("move", {"id": "m1"})
    attempt = ScienceStore(h.run).commit("attempt", Attempt(id="a1", move=move, move_id="m1", hypothesis_id="h1", test=test, parent=None, diagnosis=None, changed_fields=[], stage_instances={role: f"h1-a1-{role}" for role in ("baseline", "main", "robustness")}, move_count=1, revisit_count=0, exposure=[]), key="m1")
    roles: list[str] = []

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        if req.tag.startswith("judge:"):
            return json.dumps({"node_buggy": False, "goal_met": True, "node_score": 7, "analysis": "valid", "fidelity_status": "consistent", "fidelity_reason": "Code computes declared contrast", "fidelity_requirements": ["contrast"], "fidelity_evidence": ["code: means"]})
        roles.append(req.tag.rsplit("-", 1)[-1])
        code = (
            "import json\n"
            "json.dump({'primary_estimate': {'value': 1., 'ci': [.5, 1.5], 'n': 2}}, open('results.json','w'))\n"
            f"json.dump({payload['primary_estimand']!r}, open('estimand.json','w'))\n"
            "json.dump({'seeds':[7], 'interval_level':.95, 'effect_scale':'points'}, open('coverage.json','w'))"
        )
        return (ToolCall("submit", "submit", {"code": code}),)

    h.llm = FakeLLM(respond)
    hypothesis: dict[str, Any] = {"primary_estimand": payload["primary_estimand"], "methods": payload["methods"], "planned_test": "compare"}
    path = experiment(h, {}, hypothesis, prep.parent, request=ExperimentRequest(test=test, attempt=attempt))
    return AttemptResult.model_validate_json(path.read_text("utf-8")), roles


@pytest.mark.parametrize("descriptive", [False, True])
def test_main_only_test_runs_and_records_only_main(tmp_path: Path, descriptive: bool) -> None:
    declared: dict[str, Any] = {"components": ["main"]}
    if descriptive:
        declared["support_rule"] = {"kind": "descriptive", "result_key": "primary_estimate", "interval_level": .95, "description": "Report the estimate without a directional claim"}
    result, roles = _run_scoped(tmp_path, **declared)
    assert set(roles) == {"main"}
    assert set(result.stages) == {"main"} and {m.role for m in result.measurements} == {"main"}
    assert result.status == "complete" and result.variant_tests == []
    assert result.coverage["requested"] == 0 and result.coverage["missing"] == []


def test_declared_variants_beyond_stage_capacity_are_reported_missing(tmp_path: Path) -> None:
    alternatives = [{"inference": {"bootstrap": count, "interval_level": .95}} for count in (100, 200, 300)]
    result, roles = _run_scoped(
        tmp_path,
        components=["main", "robustness"],
        requested_coverage={"seeds": [7], "alternatives": alternatives},
        capacity=1,
    )
    assert "baseline" not in roles and "baseline" not in result.stages
    assert len(result.variant_tests) == 3
    missing = result.coverage["missing"]
    assert isinstance(missing, list) and len(missing) == 2
    assert result.coverage["completed"] == 1 and result.status == "partial"
    assert set(missing) < {ref.path for ref in result.variant_tests}
