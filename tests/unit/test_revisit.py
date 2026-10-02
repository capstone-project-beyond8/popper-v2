from pathlib import Path

import pytest

from popper.discover.compatibility import StudyPolicy
from popper.discover.contracts import ResearchMove
from popper.discover.policy import EligibilityError, check_move
from popper.discover.state import ResearchState
from popper.harness.config import Discovery
from popper.harness.records import ArtifactRef


def test_scheduled_attempts_bound_revisits(tmp_path: Path) -> None:
    ref = ArtifactRef(path="test.json", sha256="a"*64, producer="test", record_id="t1")
    move = ResearchMove(id="m1", snapshot=ref, action="test", objective="estimate", trigger_refs=[ref], hypothesis_id="h1", test=ref, cost_usd=0, stopping_condition="one test", discriminating_outcomes=["positive", "negative"])
    policy = StudyPolicy(5, 3, True, False)
    check_move(ResearchState(counters={"moves": 0}), move, policy, Discovery())
    with pytest.raises(EligibilityError, match="revisit"):
        check_move(ResearchState(counters={"moves": 2, "h1": 2}), move, policy, Discovery())
    with pytest.raises(EligibilityError, match="move"):
        check_move(ResearchState(counters={"moves": 4}), move, policy, Discovery())
