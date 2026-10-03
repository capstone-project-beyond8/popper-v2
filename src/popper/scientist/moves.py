"""Bounded sourced proposals, selection and immutable scheduling."""

import json

from pydantic import Field

from popper.harness.agent import Tool, agent_loop
from popper.harness.artifacts import read_artifact_tool
from popper.harness.context import fence
from popper.harness.prompts import load_prompt
from popper.harness.records import (
    ArtifactRef,
    IntegrityError,
    Record,
    reachable_refs,
    resolve_artifact,
)
from popper.harness.session import Harness
from popper.science.contracts import (
    Disposition,
    MoveProposal,
    MoveSelection,
    ResearchMove,
    RunResources,
)
from popper.science.state import (
    compact_state,
    load_snapshot,
)
from popper.science.store import ScienceStore
from popper.science.transitions import EligibilityError, validate_moves


class Proposals(Record):
    moves: list[MoveProposal]
    omitted: dict[str, str] = Field(default_factory=dict)


class SelectionProposal(Record):
    proposal_id: str
    rationale: str = Field(min_length=1)


def propose_moves(
    h: Harness, science: ScienceStore, snapshot: ArtifactRef, resources: RunResources
) -> ArtifactRef:
    key = snapshot.record_id
    existing = h.run.committed(f"science:proposals:{key}")
    if existing:
        return h.run.artifact_ref(f"science:proposals:{key}")
    if h.run.committed(f"science:disposition:{key}"):
        return science.commit(
            "proposals",
            {
                "snapshot": snapshot.model_dump(mode="json"),
                "moves": [],
                "omitted": {"all": "proposal validation exhausted"},
            },
            key=key,
        )
    state = load_snapshot(science, snapshot)
    collected: list[ResearchMove] = []

    def submit(proposal: Proposals) -> str:
        eligible = resources.eligible_hypotheses
        proposed = {m.hypothesis_id for m in proposal.moves}
        missing = set(eligible) - proposed - proposal.omitted.keys()
        if missing:
            raise ValueError(
                f"omitted eligible candidates need attributed reasons: {sorted(missing)}"
            )
        collected[:] = validate_moves(science, snapshot, proposal.moves)
        return "Validated sourced proposals."

    tools = [
        read_artifact_tool(h, reachable_refs(h.run, snapshot)),
        Tool.from_model(
            "submit_moves",
            "Submit a bounded set of sourced moves; code assigns all identities.",
            Proposals,
            submit,
            terminal=True,
        ),
    ]
    response = agent_loop(
        h,
        "theorist",
        tag="research_moves",
        system="You are a careful research scientist.",
        task=load_prompt(
            "popper.scientist",
            "research_moves.md",
            state=fence(json.dumps(compact_state(state))),
            snapshot=snapshot.model_dump_json(),
        ),
        tools=tools,
        max_turns=h.config.search.max_turns,
        max_submits=2,
    )
    if response is None:
        science.commit(
            "disposition",
            Disposition(
                kind="rejected",
                reason="Bounded scientific proposal correction exhausted",
                sources=[snapshot],
            ),
            key=key,
        )
        return science.commit(
            "proposals",
            {
                "snapshot": snapshot.model_dump(mode="json"),
                "moves": [],
                "omitted": {"all": "proposal validation exhausted"},
            },
            key=key,
        )
    return science.commit(
        "proposals",
        {
            "snapshot": snapshot.model_dump(mode="json"),
            "moves": [m.model_dump(mode="json") for m in collected],
            "omitted": response.get("omitted", {}),
        },
        key=key,
    )


def select_move(
    h: Harness, science: ScienceStore, snapshot: ArtifactRef, proposals: ArtifactRef
) -> ArtifactRef:
    key = proposals.record_id
    if h.run.committed(f"science:selection:{key}"):
        return h.run.artifact_ref(f"science:selection:{key}")
    record = json.loads(resolve_artifact(h.run, proposals).read_text("utf-8"))
    if ArtifactRef.model_validate(record["snapshot"]) != snapshot:
        raise IntegrityError("proposals cite a foreign snapshot")
    moves = [ResearchMove.model_validate(m) for m in record["moves"]]
    if not moves:
        raise EligibilityError("no executable proposals")
    choice = h.ask_model(
        "theorist",
        schema=SelectionProposal,
        tag="select_move",
        system="Select the most informative justified research move.",
        prompt=load_prompt(
            "popper.scientist", "select_move.md", proposals=fence(json.dumps(record))
        ),
    )
    if choice.proposal_id not in {m.id for m in moves}:
        raise EligibilityError("selection names an unknown retained proposal")
    return science.commit(
        "selection",
        MoveSelection(
            proposal_id=choice.proposal_id,
            snapshot=snapshot,
            proposals=proposals,
            author="theorist",
            rationale=choice.rationale,
        ),
        key=key,
    )
