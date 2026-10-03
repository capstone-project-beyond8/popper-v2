from pathlib import Path

import pytest
from pydantic import ValidationError

from popper.config import load_config
from popper.discover.policy import eligible_candidates, propose_moves
from popper.harness.llm import FakeLLM
from popper.harness.session import Harness
from popper.harness.store import RunStore
from popper.science.contracts import MoveProposal
from popper.science.settings import Discovery
from popper.science.state import ResearchState, commit_snapshot
from popper.science.store import ScienceStore
from popper.science.transitions import validate_moves


def test_invalid_move_cannot_be_executable() -> None:
    base = {"action": "stop", "objective": "stop", "trigger_refs": [{"path": "x.json", "sha256": "a"*64, "producer": "x", "record_id": "r1"}], "cost_usd": 0, "stopping_condition": "no justified action"}
    assert MoveProposal.model_validate(base).action == "stop"
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


def test_permanently_incomplete_proposal_stops_after_bounded_correction(tmp_path: Path) -> None:
    from popper.harness.llm import ToolCall
    fake = FakeLLM(lambda _: (ToolCall("bad", "submit_moves", {"moves": [{"action": "test"}]}),))
    h = Harness(load_config(env={}), fake, RunStore(tmp_path))
    snapshot = commit_snapshot(ScienceStore(h.run), ResearchState())
    ref = propose_moves(h, snapshot)
    import json

    from popper.harness.records import resolve_artifact
    assert json.loads(resolve_artifact(h.run, ref).read_text())["moves"] == []
    assert len(fake.calls) == 2
    assert h.run.committed(f"science:disposition:{snapshot.record_id}") is not None


def test_scientific_commit_rejects_conflicting_key(tmp_path: Path) -> None:
    from popper.harness.records import IntegrityError
    from popper.science.store import ScienceStore

    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    original = ScienceStore(h.run).commit("test", {"inference": 1000}, key="test-1")
    assert ScienceStore(h.run).commit("test", {"inference": 1000}, key="test-1") == original
    with pytest.raises(IntegrityError, match="conflicting"):
        ScienceStore(h.run).commit("test", {"inference": 100}, key="test-1")
