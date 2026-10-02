import json
from pathlib import Path

import pytest

from popper.discover.contracts import Candidate, commit_record
from popper.discover.policy import make_attempt, propose_moves, select_move, selected_move
from popper.discover.state import commit_snapshot, rebuild_state
from popper.harness.config import load_config
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.records import resolve_artifact
from popper.harness.session import Harness
from popper.harness.store import RunStore
from tests.unit.test_test_identity import spec_payload

pytestmark = pytest.mark.integration


def test_sourced_tool_proposals_and_idempotent_schedule(tmp_path: Path) -> None:
    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    source = h.run.write_json("explore.json", {"question": "What explains variance?"})
    h.run.commit_artifact("exploration", source)
    ref = h.run.artifact_ref("exploration")
    payload = spec_payload()
    candidate = Candidate(
        id="hypothesis-001", statement="x predicts y", rationale="exploration",
        primary_estimand=payload["primary_estimand"], expected_direction="positive",
        refuting_result="negative interval", planned_test="trimmed contrast",
        methods=payload["methods"], origins=[ref], exposure=[ref],
    )
    commit_record(h, "candidates", {"candidates": [candidate.model_dump(mode="json")]})
    snapshot = commit_snapshot(h, rebuild_state(h))
    prep = h.run.write_json("prep.json", {})
    h.run.commit_artifact("prep", prep)
    payload["preparation"] = h.run.artifact_ref("prep").model_dump(mode="json")
    proposal = {k: v for k, v in payload.items() if k not in {"id", "hypothesis_id"}}

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        if req.tag == "research_moves":
            if len(req.messages) == 1:
                return (ToolCall("read", "read_artifact", {"path": ref.path}),)
            return (ToolCall("submit", "submit_moves", {
                "moves": [{"action": "test", "objective": "resolve exploration question",
                "hypothesis_id": candidate.id, "trigger_refs": [ref.model_dump(mode="json")],
                "test_proposal": proposal, "discriminating_outcomes": ["positive", "negative"],
                "cost_usd": .1, "stopping_condition": "one accepted analysis"}],
            }),)
        data = json.loads(resolve_artifact(h.run, h.run.artifact_ref(f"science:proposals:{snapshot.record_id}")).read_text())
        return json.dumps({"proposal_id": data["moves"][0]["id"], "rationale": "resolve sourced uncertainty"})

    h.llm = FakeLLM(respond)
    proposals = propose_moves(h, snapshot)
    selection = select_move(h, snapshot, proposals)
    move = selected_move(h, selection)
    first = make_attempt(h, move, None)
    assert make_attempt(h, move, None) == first
    assert rebuild_state(h).counters == {"moves": 1, "hypothesis-001": 1}
    assert move.test is not None
    assert resolve_artifact(h.run, move.test).is_file()
    assert len(json.loads(resolve_artifact(h.run, proposals).read_text())["moves"]) == 1
