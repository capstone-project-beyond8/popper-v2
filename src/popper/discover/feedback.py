"""Attributed scientific feedback over exact committed input frontiers."""

import json
from collections.abc import Callable

from popper.discover.contracts import (
    Challenge,
    ChallengeProposal,
    Disposition,
    Interpretation,
    InterpretationProposal,
    commit_record,
)
from popper.discover.state import ResearchState, compact_state, rebuild_state, validate_sources
from popper.harness.agent import Tool, agent_loop
from popper.harness.artifacts import reachable_refs, read_artifact_tool
from popper.harness.config import Role
from popper.harness.context import fence
from popper.harness.prompts import load_prompt
from popper.harness.records import ArtifactRef, Record, resolve_artifact
from popper.harness.session import Harness


def _assess[T: Record](
    h: Harness,
    snapshot: ArtifactRef,
    *,
    role: Role,
    tag: str,
    schema: type[T],
    validate: Callable[[T, list[ArtifactRef]], None],
    subject: ArtifactRef,
) -> T | None:
    deferral_key = f"{tag}:{subject.record_id}"
    if h.run.committed(f"science:disposition:{deferral_key}"):
        return None
    allowed = reachable_refs(h, snapshot)
    collected: list[T] = []

    def submit(proposal: T) -> str:
        validate_sources(h, proposal.model_dump(mode="json"))
        validate(proposal, allowed)
        collected[:] = [proposal]
        return "Sourced scientific assessment accepted; evidence standing is unchanged."

    state = ResearchState.model_validate_json(resolve_artifact(h.run, snapshot).read_text("utf-8"))
    response = agent_loop(
        h,
        role,
        tag=tag,
        system="You are a careful scientific challenger."
        if tag == "candidate_challenge"
        else "You are a careful research scientist interpreting recorded outcomes.",
        task=load_prompt(
            "popper.discover",
            f"{tag}.md",
            snapshot=snapshot.model_dump_json(),
            subject=subject.model_dump_json(),
            state=fence(json.dumps(compact_state(state))),
        ),
        tools=[
            read_artifact_tool(h, allowed),
            Tool.from_model(
                "submit_challenge" if tag == "candidate_challenge" else "submit_interpretation",
                "Submit attributed reasoning with exact sources, without changing evidence or intent.",
                schema,
                submit,
                terminal=True,
            ),
        ],
        max_turns=h.config.search.max_turns,
        max_submits=2,
    )
    if response is None:
        commit_record(
            h,
            "disposition",
            Disposition(
                kind="deferred",
                reason=f"{tag} correction allowance exhausted; scientific feedback is unavailable",
                sources=[snapshot, subject],
            ),
            key=deferral_key,
        )
        return None
    return collected[0]


def challenge_candidates(h: Harness, candidates: ArtifactRef) -> ArtifactRef | None:
    key = candidates.record_id
    name = f"science:challenge:{key}"
    if h.run.committed(name):
        return h.run.artifact_ref(name)
    state = rebuild_state(h)
    selected = {c.record.id: c.ref for c in state.candidates if c.ref == candidates}
    if not selected:
        raise ValueError("challenge requires a committed candidate set")
    snapshot = commit_record(h, "snapshot", state)

    def validate(proposal: ChallengeProposal, allowed: list[ArtifactRef]) -> None:
        ids = [a.hypothesis_id for a in proposal.assessments]
        if len(ids) != len(selected) or set(ids) != set(selected):
            raise ValueError("challenge must assess each candidate exactly once")
        for assessment in proposal.assessments:
            if selected[assessment.hypothesis_id] not in assessment.sources:
                raise ValueError("challenge must cite the assessed candidate record")
            if any(source not in allowed for source in assessment.sources):
                raise ValueError("challenge source is outside the input frontier")

    proposal = _assess(
        h, snapshot, role="judge", tag="candidate_challenge", schema=ChallengeProposal,
        validate=validate, subject=candidates,
    )
    if proposal is None:
        return None
    return commit_record(
        h, "challenge",
        Challenge(**proposal.model_dump(), snapshot=snapshot, candidates=candidates, author="judge"),
        key=key,
    )


def interpret_result(h: Harness, result: ArtifactRef) -> ArtifactRef | None:
    key = result.record_id
    name = f"science:interpretation:{key}"
    if h.run.committed(name):
        return h.run.artifact_ref(name)
    state = rebuild_state(h)
    outcome = next((r.record for r in state.results if r.ref == result), None)
    if outcome is None:
        raise ValueError("interpretation requires a committed attempt result")
    snapshot = commit_record(h, "snapshot", state)

    def validate(proposal: InterpretationProposal, allowed: list[ArtifactRef]) -> None:
        if result not in proposal.sources:
            raise ValueError("interpretation must cite its attempt result")
        if any(source not in allowed for source in proposal.sources):
            raise ValueError("interpretation source is outside the input frontier")

    proposal = _assess(
        h, snapshot, role="theorist", tag="interpret_result", schema=InterpretationProposal,
        validate=validate, subject=result,
    )
    if proposal is None:
        return None
    return commit_record(
        h, "interpretation",
        Interpretation(
            **proposal.model_dump(), hypothesis_id=outcome.hypothesis_id,
            result=result, snapshot=snapshot, author="theorist",
        ),
        key=key,
    )
