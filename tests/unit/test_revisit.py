from pathlib import Path

import pytest

from popper.harness.storage.records import ArtifactRef
from popper.scientific.runtime.lifecycle.contracts import ResearchMove, RunResources
from popper.scientific.runtime.lifecycle.transitions import EligibilityError
from popper.scientific.runtime.projections.state import ResearchState
from popper.workflow.resources import admit_move


def test_scheduled_attempts_bound_revisits(tmp_path: Path) -> None:
    ref = ArtifactRef(path="test.json", sha256="a"*64, producer="test", record_id="t1")
    move = ResearchMove(id="m1", snapshot=ref, action="test", objective="estimate", trigger_refs=[ref], hypothesis_id="h1", test=ref, cost_usd=0, stopping_condition="one test", discriminating_outcomes=["positive", "negative"])
    resources = RunResources(spent_usd=0, max_usd=10, max_moves=4, max_revisits=1, max_reframes=1,
        available_routes=frozenset({"test"}), eligible_hypotheses=frozenset({"h1"}))
    admit_move(resources, ResearchState(counters={"moves": 0}), move)
    with pytest.raises(EligibilityError, match="revisit"):
        admit_move(resources, ResearchState(counters={"moves": 2, "h1": 2}), move)
    with pytest.raises(EligibilityError, match="move"):
        admit_move(resources, ResearchState(counters={"moves": 4}), move)


def test_refinement_requires_an_attributed_observation(tmp_path: Path) -> None:
    from popper.config import load_config
    from popper.harness.llm import FakeLLM
    from popper.harness.session import Harness
    from popper.harness.storage.records import resolve_artifact
    from popper.harness.storage.store import RunStore
    from popper.scientific.runtime.lifecycle.contracts import Attempt, AttemptResult
    from popper.scientific.runtime.lifecycle.contracts import ExperimentSpec as ScientificTest
    from popper.scientific.runtime.lifecycle.transitions import schedule_attempt
    from popper.scientific.runtime.projections.state import commit_snapshot, rebuild_state
    from popper.scientific.runtime.store import ScienceStore
    from tests.unit.test_test_identity import spec_payload

    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    prep = h.run.write_json("prep.json", {})
    h.run.commit_artifact("prep", prep)
    source = h.run.artifact_ref("prep")
    payload = {**spec_payload(), "preparation": source.model_dump()}
    original = ScienceStore(h.run).commit("test", ScientificTest.model_validate(payload), key="t1")
    move = ScienceStore(h.run).commit("move", {"id": "m1"})
    parent = ScienceStore(h.run).commit("attempt", Attempt(id="attempt-000", move=move, move_id="m1", hypothesis_id="h1", test=original, parent=None, diagnosis=None, changed_fields=[], stage_instances={}, move_count=1, revisit_count=0, exposure=[]))
    result = ScienceStore(h.run).commit("result", AttemptResult(attempt=parent, hypothesis_id="h1", test=original, measurements=[], stages={}, coverage={"status": "partial"}, sensitivity={}, status="partial"))
    refined = ScienceStore(h.run).commit("test", ScientificTest.model_validate({**payload, "id": "t2", "parent_test": original.model_dump(), "inference": {"bootstrap": 200, "interval_level": .95}}), key="t2")
    snapshot = commit_snapshot(ScienceStore(h.run), rebuild_state(ScienceStore(h.run)))
    proposal = ResearchMove(id="m2", snapshot=snapshot, action="refine", objective="resolve incomplete uncertainty estimate", trigger_refs=[source], hypothesis_id="h1", test=refined, cost_usd=0, stopping_condition="declared interval available", discriminating_outcomes=["adequate inference", "remaining uncertainty"])
    with pytest.raises(EligibilityError, match="attributed"):
        schedule_attempt(ScienceStore(h.run), proposal, parent)
    child = schedule_attempt(ScienceStore(h.run), proposal.model_copy(update={"trigger_refs": [result]}), parent)
    scheduled = Attempt.model_validate_json(resolve_artifact(h.run, child).read_text())
    assert scheduled.test == refined and scheduled.parent == parent and scheduled.revisit_count == 1
    assert scheduled.reuse == {}
