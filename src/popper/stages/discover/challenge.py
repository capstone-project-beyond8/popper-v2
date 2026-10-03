"""Independent candidate challenge over a caller's committed scientific snapshot."""

import json

from popper.harness.agents.artifacts import read_artifact_tool
from popper.harness.agents.loop import Tool, agent_loop
from popper.harness.context.prompts import load_prompt
from popper.harness.context.rendering import fence
from popper.harness.session import Harness
from popper.harness.storage.records import ArtifactRef, IntegrityError, reachable_refs
from popper.scientific.runtime.lifecycle.contracts import Challenge, ChallengeProposal, Disposition
from popper.scientific.runtime.projections.state import (
    compact_state,
    current_frontier,
    load_snapshot,
    rebuild_state,
    validate_sources,
)
from popper.scientific.runtime.store import ScienceStore


def challenge_candidates(
    h: Harness, science: ScienceStore, candidates: ArtifactRef, snapshot: ArtifactRef
) -> ArtifactRef | None:
    science.read(candidates)
    state = load_snapshot(science, snapshot)
    selected = {c.record.id: c.ref for c in state.candidates if c.ref == candidates}
    if not selected:
        raise IntegrityError("challenge snapshot does not contain its candidate subject")
    name = f"science:challenge:{candidates.record_id}"
    if h.run.committed(name):
        return h.run.artifact_ref(name)
    deferral_key = f"candidate_challenge:{candidates.record_id}"
    if h.run.committed(f"science:disposition:{deferral_key}"):
        deferred = Disposition.model_validate(science.read(h.run.artifact_ref(f"science:disposition:{deferral_key}")))
        if candidates not in deferred.sources:
            raise IntegrityError("challenge disposition cites a different subject")
        return None
    if not current_frontier(science, snapshot, rebuild_state(science).frontier):
        raise IntegrityError("challenge snapshot has a stale frontier")
    allowed = reachable_refs(h.run, snapshot)
    collected: list[ChallengeProposal] = []

    def submit(proposal: ChallengeProposal) -> str:
        validate_sources(science, proposal.model_dump(mode="json"))
        ids = [a.hypothesis_id for a in proposal.assessments]
        if len(ids) != len(selected) or set(ids) != set(selected):
            raise ValueError("challenge must assess each candidate exactly once")
        for assessment in proposal.assessments:
            if selected[assessment.hypothesis_id] not in assessment.sources:
                raise ValueError("challenge must cite the assessed candidate record")
            if any(source not in allowed for source in assessment.sources):
                raise ValueError("challenge source is outside the input frontier")
        collected[:] = [proposal]
        return "Sourced scientific assessment accepted; evidence standing is unchanged."

    response = agent_loop(
        h, "judge", tag="candidate_challenge", system="You are a careful scientific challenger.",
        task=load_prompt(
            "popper.stages.discover", "candidate_challenge.md",
            snapshot=snapshot.model_dump_json(), subject=candidates.model_dump_json(),
            state=fence(json.dumps(compact_state(state))),
        ),
        tools=[read_artifact_tool(h, allowed), Tool.from_model(
            "submit_challenge",
            "Submit attributed reasoning with exact sources, without changing evidence or intent.",
            ChallengeProposal, submit, terminal=True,
        )],
        max_turns=h.config.search.max_turns, max_submits=2,
    )
    if response is None:
        science.commit("disposition", Disposition(
            kind="deferred",
            reason="candidate_challenge correction allowance exhausted; scientific feedback is unavailable",
            sources=[snapshot, candidates],
        ), key=deferral_key)
        return None
    return science.commit("challenge", Challenge(
        **collected[0].model_dump(), snapshot=snapshot, candidates=candidates, author="judge",
    ), key=candidates.record_id)
