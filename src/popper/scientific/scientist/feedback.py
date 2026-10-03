"""Attributed scientific feedback over exact committed input frontiers."""

import json

from popper.harness.agents.artifacts import read_artifact_tool
from popper.harness.agents.loop import Tool, agent_loop
from popper.harness.context.prompts import load_prompt
from popper.harness.context.rendering import fence
from popper.harness.session import Harness
from popper.harness.storage.records import ArtifactRef, reachable_refs
from popper.scientific.runtime.lifecycle.contracts import (
    Disposition,
    Interpretation,
    InterpretationProposal,
)
from popper.scientific.runtime.projections.state import (
    compact_state,
    load_snapshot,
    rebuild_state,
    validate_sources,
)
from popper.scientific.runtime.store import ScienceStore


def interpret_result(h: Harness, science: ScienceStore, result: ArtifactRef) -> ArtifactRef | None:
    key = result.record_id
    name = f"science:interpretation:{key}"
    if h.run.committed(name):
        return h.run.artifact_ref(name)
    state = rebuild_state(science)
    outcome = next((r.record for r in state.results if r.ref == result), None)
    if outcome is None:
        raise ValueError("interpretation requires a committed attempt result")
    deferral_key = f"interpret_result:{result.record_id}"
    if h.run.committed(f"science:disposition:{deferral_key}"):
        return None
    snapshot = science.commit("snapshot", state)

    def validate(proposal: InterpretationProposal, allowed: list[ArtifactRef]) -> None:
        if result not in proposal.sources:
            raise ValueError("interpretation must cite its attempt result")
        if any(source not in allowed for source in proposal.sources):
            raise ValueError("interpretation source is outside the input frontier")

    allowed = reachable_refs(h.run, snapshot)
    collected: list[InterpretationProposal] = []

    def submit(proposal: InterpretationProposal) -> str:
        validate_sources(science, proposal.model_dump(mode="json"))
        validate(proposal, allowed)
        collected[:] = [proposal]
        return "Sourced scientific assessment accepted; evidence standing is unchanged."

    response = agent_loop(
        h, "theorist", tag="interpret_result",
        system="You are a careful research scientist interpreting recorded outcomes.",
        task=load_prompt(
            "popper.scientific.scientist", "interpret_result.md",
            snapshot=snapshot.model_dump_json(), subject=result.model_dump_json(),
            state=fence(json.dumps(compact_state(load_snapshot(science, snapshot)))),
        ),
        tools=[read_artifact_tool(h, allowed), Tool.from_model(
            "submit_interpretation",
            "Submit attributed reasoning with exact sources, without changing evidence or intent.",
            InterpretationProposal, submit, terminal=True,
        )],
        max_turns=h.config.search.max_turns, max_submits=2,
    )
    if response is None:
        science.commit("disposition", Disposition(
            kind="deferred",
            reason="interpret_result correction allowance exhausted; scientific feedback is unavailable",
            sources=[snapshot, result],
        ), key=deferral_key)
        return None
    proposal = collected[0]
    return science.commit(
        "interpretation",
        Interpretation(
            **proposal.model_dump(),
            hypothesis_id=outcome.hypothesis_id,
            result=result,
            snapshot=snapshot,
            author="theorist",
        ),
        key=key,
    )
