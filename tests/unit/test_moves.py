from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from popper.config import load_config
from popper.harness.llm import FakeLLM
from popper.harness.session import Harness
from popper.harness.storage.store import RunStore
from popper.scientific.runtime.lifecycle.contracts import MoveProposal
from popper.scientific.runtime.lifecycle.transitions import validate_moves
from popper.scientific.runtime.projections.state import (
    ResearchState,
    commit_snapshot,
    rebuild_state,
)
from popper.scientific.runtime.settings import Discovery, load_options
from popper.scientific.runtime.store import ScienceStore
from popper.scientific.scientist.moves import propose_moves
from popper.workflow.resources import admit_move, eligible_candidates, resource_view


def test_invalid_move_cannot_be_executable() -> None:
    base: dict[str, Any] = {"action": "stop", "objective": "stop", "trigger_refs": [{"path": "x.json", "sha256": "a"*64, "producer": "x", "record_id": "r1"}], "cost_usd": 0, "stopping_condition": "no justified action"}
    assert MoveProposal.model_validate(base).action == "stop"
    for action in ("audit", "communicate", "synthesize"):
        assert MoveProposal.model_validate({**base, "action": action}).action == action
        empirical_fields: list[dict[str, Any]] = [{"test": base["trigger_refs"][0]}, {"discriminating_outcomes": ["positive"]}, {"measurements": []}]
        for empirical in empirical_fields:
            with pytest.raises(ValidationError):
                MoveProposal.model_validate({**base, "action": action, **empirical})
    for changes in ({"cost_usd": -1}, {"cost_usd": float("inf")}, {"action": "test"}, {"stopping_condition": ""}):
        with pytest.raises(ValidationError):
            MoveProposal.model_validate({**base, **changes})


def test_source_validation_and_limits(tmp_path: Path) -> None:
    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    refpath = h.run.write_json("snapshot.json", ResearchState().model_dump(mode="json"))
    h.run.commit_artifact("snapshot", refpath)
    snapshot = h.run.artifact_ref("snapshot")
    move = MoveProposal(action="stop", objective="finish", trigger_refs=[snapshot], cost_usd=0, stopping_condition="nothing eligible")
    assert validate_moves(ScienceStore(h.run), snapshot, [move])[0].id.startswith("move-")
    foreign = snapshot.model_copy(update={"path": "foreign.json"})
    with pytest.raises(ValueError):
        validate_moves(ScienceStore(h.run), snapshot, [move.model_copy(update={"trigger_refs": [foreign]})])
    assert eligible_candidates(ResearchState(counters={"moves": 4}), Discovery()) == []


@pytest.mark.parametrize("interrupted", [False, True])
def test_permanently_incomplete_proposal_stops_after_bounded_correction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: bool) -> None:
    from popper.harness.llm import ToolCall
    fake = FakeLLM(lambda _: (ToolCall("bad", "submit_moves", {"moves": [{"action": "test"}]}),))
    h = Harness(load_config(env={}), fake, RunStore(tmp_path))
    snapshot = commit_snapshot(ScienceStore(h.run), ResearchState())
    if interrupted:
        original = RunStore.commit_artifact
        tripped = False
        def commit(store: RunStore, name: str, path: Path) -> None:
            nonlocal tripped
            original(store, name, path)
            if name.startswith("science:disposition:") and not tripped:
                tripped = True
                raise KeyboardInterrupt()
        monkeypatch.setattr(RunStore, "commit_artifact", commit)
        with pytest.raises(KeyboardInterrupt):
            propose_moves(h, ScienceStore(h.run), snapshot, resource_view(h, load_options(h.run), rebuild_state(ScienceStore(h.run))))
    ref = propose_moves(h, ScienceStore(h.run), snapshot, resource_view(h, load_options(h.run), rebuild_state(ScienceStore(h.run))))
    import json

    from popper.harness.storage.records import resolve_artifact
    assert json.loads(resolve_artifact(h.run, ref).read_text())["moves"] == []
    assert len(fake.calls) == 2
    assert h.run.committed(f"science:disposition:{snapshot.record_id}") is not None


def test_scientific_commit_rejects_conflicting_key(tmp_path: Path) -> None:
    from popper.harness.storage.records import IntegrityError
    from popper.scientific.runtime.store import ScienceStore

    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    original = ScienceStore(h.run).commit("test", {"inference": 1000}, key="test-1")
    assert ScienceStore(h.run).commit("test", {"inference": 1000}, key="test-1") == original
    with pytest.raises(IntegrityError, match="conflicting"):
        ScienceStore(h.run).commit("test", {"inference": 100}, key="test-1")


@pytest.mark.parametrize(("moves", "visits", "eligible"), [(3, 1, True), (4, 1, False), (3, 2, False)])
def test_candidate_eligibility_and_refreshed_admission_agree(
    tmp_path: Path, moves: int, visits: int, eligible: bool
) -> None:
    from popper.harness.storage.records import ArtifactRef
    from popper.scientific.runtime.lifecycle.contracts import Candidate, ResearchMove
    from popper.scientific.runtime.lifecycle.transitions import EligibilityError
    from popper.scientific.runtime.projections.state import Sourced
    from tests.unit.test_test_identity import spec_payload

    ref = ArtifactRef(path="test.json", sha256="a" * 64, producer="test", record_id="t1")
    payload = spec_payload()
    candidate = Candidate(id="h1", statement="x predicts y", rationale="association",
        primary_estimand=payload["primary_estimand"], methods=payload["methods"], expected_direction="positive",
        refuting_result="negative", planned_test="contrast", origins=[ref], exposure=[ref])
    state = ResearchState(candidates=[Sourced(ref=ref, record=candidate)], counters={"moves": moves, "h1": visits})
    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    options = load_options(h.run)
    limits = options.discovery
    resources = resource_view(h, options, state)
    move = ResearchMove(id="m1", snapshot=ref, action="test", objective="estimate", trigger_refs=[ref],
        hypothesis_id="h1", test=ref, cost_usd=0, stopping_condition="one test", discriminating_outcomes=["positive", "negative"])
    assert ("h1" in eligible_candidates(state, limits)) is eligible
    if eligible:
        admit_move(resources, state, move)
        refreshed = resources.model_copy(update={"max_moves": moves})
        with pytest.raises(EligibilityError, match="scheduled move cap"):
            admit_move(refreshed, state, move)
        with pytest.raises(EligibilityError, match="revisit"):
            admit_move(resources.model_copy(update={"max_revisits": 0}), state, move)
    else:
        with pytest.raises(EligibilityError):
            admit_move(resources, state, move)
