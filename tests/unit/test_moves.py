from pathlib import Path

import pytest
from pydantic import ValidationError

from popper.discover.contracts import MoveProposal
from popper.discover.policy import eligible_candidates, validate_moves
from popper.discover.state import ResearchState
from popper.harness.config import Discovery, load_config
from popper.harness.llm import FakeLLM
from popper.harness.session import Harness
from popper.harness.store import RunStore


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
    assert validate_moves(h, snapshot, [move])[0].id.startswith("move-")
    foreign = snapshot.model_copy(update={"path": "foreign.json"})
    with pytest.raises(ValueError):
        validate_moves(h, snapshot, [move.model_copy(update={"trigger_refs": [foreign]})])
    assert eligible_candidates(ResearchState(counters={"moves": 4}), Discovery()) == []
