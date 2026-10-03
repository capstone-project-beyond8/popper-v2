from pathlib import Path

import pytest

from popper.discover.policy import EligibilityError, check_move
from popper.discover.state import ResearchState
from popper.harness.config import Discovery
from popper.harness.records import ArtifactRef
from popper.science.contracts import ResearchMove


def test_scheduled_attempts_bound_revisits(tmp_path: Path) -> None:
    ref = ArtifactRef(path="test.json", sha256="a"*64, producer="test", record_id="t1")
    move = ResearchMove(id="m1", snapshot=ref, action="test", objective="estimate", trigger_refs=[ref], hypothesis_id="h1", test=ref, cost_usd=0, stopping_condition="one test", discriminating_outcomes=["positive", "negative"])
    check_move(ResearchState(counters={"moves": 0}), move, Discovery())
    with pytest.raises(EligibilityError, match="revisit"):
        check_move(ResearchState(counters={"moves": 2, "h1": 2}), move, Discovery())
    with pytest.raises(EligibilityError, match="move"):
        check_move(ResearchState(counters={"moves": 4}), move, Discovery())


def test_refinement_requires_an_attributed_observation(tmp_path: Path) -> None:
    from popper.discover.policy import make_attempt
    from popper.discover.state import commit_snapshot, rebuild_state
    from popper.harness.config import load_config
    from popper.harness.llm import FakeLLM
    from popper.harness.records import resolve_artifact
    from popper.harness.session import Harness
    from popper.harness.store import RunStore
    from popper.science.contracts import Attempt, AttemptResult
    from popper.science.contracts import ExperimentSpec as ScientificTest
    from popper.science.store import ScienceStore
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
    snapshot = commit_snapshot(h, rebuild_state(h))
    proposal = ResearchMove(id="m2", snapshot=snapshot, action="refine", objective="resolve incomplete uncertainty estimate", trigger_refs=[source], hypothesis_id="h1", test=refined, cost_usd=0, stopping_condition="declared interval available", discriminating_outcomes=["adequate inference", "remaining uncertainty"])
    with pytest.raises(EligibilityError, match="attributed"):
        make_attempt(h, proposal, parent)
    child = make_attempt(h, proposal.model_copy(update={"trigger_refs": [result]}), parent)
    scheduled = Attempt.model_validate_json(resolve_artifact(h.run, child).read_text())
    assert scheduled.test == refined and scheduled.parent == parent and scheduled.revisit_count == 1
    assert scheduled.reuse == {}
