"""Idea evolution: revising, challenging and promoting scientific ideas."""

import json
from pathlib import Path

from pydantic import Field

from popper.harness.agents.artifacts import ReadRequest, read_artifact_tool
from popper.harness.agents.loop import Tool, agent_loop
from popper.harness.context.prompts import load_prompt
from popper.harness.context.rendering import fence
from popper.harness.session import Harness
from popper.harness.storage.records import ArtifactRef, Record, reachable_refs
from popper.scientific.runtime.lifecycle.contracts import Disposition, StageAdmission, Text
from popper.scientific.runtime.lifecycle.ideas import (
    NEW_IDENTITY,
    IdeaChallengeProposal,
    IdeaProposal,
    PromotionProposal,
    active_ideas,
    commit_idea,
    commit_idea_challenge,
)
from popper.scientific.runtime.lifecycle.ideas import promote_idea as commit_promotion
from popper.scientific.runtime.lifecycle.transitions import (
    EligibilityError,
    bind_stage_output,
    stage_outputs,
)
from popper.scientific.runtime.projections.state import (
    compact_state,
    rebuild_state,
    validate_sources,
)
from popper.scientific.runtime.settings import load_options
from popper.scientific.runtime.store import ScienceStore
from popper.stages.discover.candidates import candidate_warnings, intent_context, processed_table


class ChallengeRequest(Record):
    revision: ArtifactRef


class PromotionRequest(Record):
    revision: ArtifactRef
    challenge: ArtifactRef
    promotion: PromotionProposal


class NeedRequest(Record):
    reason: Text
    sources: list[ArtifactRef] = Field(min_length=1)


class FinishRequest(Record):
    summary: Text


def _committed(h: Harness, work: StageAdmission) -> list[ArtifactRef]:
    """Records already committed for this admission, in commit order."""
    refs: list[ArtifactRef] = []
    index = 0
    while True:
        found = [
            h.run.artifact_ref(name) for name in (
                f"science:idea:{work.id}:{index:03d}",
                f"science:idea_challenge:{work.id}:challenge:{index:03d}",
                f"science:disposition:{work.id}:need:{index:03d}",
            ) if h.run.committed(name)
        ]
        if not found:
            return refs
        refs += found
        index += 1


def evolve_ideas(h: Harness, science: ScienceStore, admission: ArtifactRef) -> list[ArtifactRef]:
    """Run one admitted idea round and return the committed idea records it produced."""
    work = StageAdmission.model_validate(science.read(admission))
    snapshot = work.snapshot
    bound = stage_outputs(science, admission)
    if bound is not None:
        return bound
    deferral_key = f"evolve_ideas:{work.id}"
    deferral_name = f"science:disposition:{deferral_key}"
    if h.run.committed(deferral_name):
        deferred = Disposition.model_validate(science.read(h.run.artifact_ref(deferral_name)))
        validate_sources(science, deferred.model_dump(mode="json"))
        raise EligibilityError(deferred.reason)

    outputs = _committed(h, work)
    allowed = [*reachable_refs(h.run, snapshot), *outputs]
    capacity = load_options(h.run).discovery.hypotheses

    def record(ref: ArtifactRef) -> str:
        outputs.append(ref)
        allowed.append(ref)
        return ref.model_dump_json()

    def checked(sources: list[ArtifactRef]) -> None:
        if any(source not in allowed for source in sources):
            raise ValueError("source is not a reachable committed record")

    def read(request: ReadRequest) -> str | Path:
        handler = read_artifact_tool(h, allowed).handler
        assert handler is not None
        return handler(request.model_dump())

    def submit_idea(proposal: IdeaProposal) -> str:
        checked(proposal.sources)
        if proposal.change in NEW_IDENTITY and active_ideas(rebuild_state(science)) >= capacity:
            raise ValueError("retire an idea before adding another")
        return record(commit_idea(science, proposal, admission, len(outputs), "theorist"))

    def challenge_idea(request: ChallengeRequest) -> str:
        checked([request.revision])
        collected: list[IdeaChallengeProposal] = []

        def submit(proposal: IdeaChallengeProposal) -> str:
            validate_sources(science, proposal.model_dump(mode="json"))
            checked(proposal.sources)
            if request.revision not in proposal.sources:
                raise ValueError("challenge must cite the revision it assesses")
            collected[:] = [proposal]
            return "Sourced critique accepted; evidence standing is unchanged."

        response = agent_loop(
            h, "judge", tag="idea_challenge", system="You are a careful scientific challenger.",
            task=load_prompt(
                "popper.stages.discover", "idea_challenge.md",
                snapshot=snapshot.model_dump_json(), subject=request.revision.model_dump_json(),
                state=fence(json.dumps(compact_state(rebuild_state(science)))),
            ),
            tools=[
                Tool.from_model("read_artifact", "Read exact cited records.", ReadRequest, read),
                Tool.from_model(
                    "submit_idea_challenge",
                    "Submit attributed critique with exact sources, without changing evidence.",
                    IdeaChallengeProposal, submit, terminal=True,
                ),
            ],
            max_turns=h.config.search.max_turns, max_submits=2,
        )
        if response is None:
            return "Challenge unavailable: the judge produced no accepted critique; nothing was committed."
        proposal = collected[0]
        ref = commit_idea_challenge(science, proposal, request.revision, admission, len(outputs), "judge")
        return json.dumps({
            "challenge": json.loads(record(ref)), "assessment": proposal.assessment,
            "rivals": proposal.rivals, "discriminating_checks": proposal.discriminating_checks,
        })

    def promote_idea(request: PromotionRequest) -> str:
        checked([request.revision, request.challenge])
        if not h.run.committed("science:intent:initial"):
            raise ValueError("promotion needs the committed discovery inputs")
        context, refs = intent_context(h, science, h.run.artifact_ref("science:intent:initial"))
        processed = processed_table(h, science, refs["preparation"])
        return record(commit_promotion(
            science, request.revision, request.challenge, request.promotion, admission, len(outputs), "theorist",
            columns=processed.columns.tolist(),
            warnings=candidate_warnings(request.promotion.candidate, context, processed),
        ))

    def record_need(request: NeedRequest) -> str:
        checked(request.sources)
        disposition = Disposition(kind="deferred", reason=request.reason, sources=request.sources)
        return record(science.commit("disposition", disposition, key=f"{work.id}:need:{len(outputs):03d}"))

    def finish(request: FinishRequest) -> str:
        return "Idea round finished."

    agent_loop(
        h, "theorist", tag="evolve_ideas", system="You evolve sourced scientific ideas without selecting moves.",
        task=load_prompt(
            "popper.stages.discover", "evolve_ideas.md",
            snapshot=snapshot.model_dump_json(), capacity=str(capacity),
            prior=json.dumps([ref.model_dump(mode="json") for ref in outputs]),
            state=fence(json.dumps(compact_state(rebuild_state(science)))),
        ),
        tools=[
            Tool.from_model("read_artifact", "Read exact cited records.", ReadRequest, read),
            Tool.from_model("submit_idea", "Commit one sourced idea revision.", IdeaProposal, submit_idea),
            Tool.from_model("challenge_idea", "Obtain an independent critique of one idea revision.", ChallengeRequest, challenge_idea),
            Tool.from_model("promote_idea", "Promote a challenged conjecture to a testable idea with a quantitative candidate.", PromotionRequest, promote_idea),
            Tool.from_model("record_need", "Record a sourced missing data, literature or measurement prerequisite.", NeedRequest, record_need),
            Tool.from_model("finish_ideas", "End the idea round.", FinishRequest, finish, terminal=True),
        ],
        max_turns=h.config.search.max_turns, max_submits=2,
    )
    if not outputs:
        reason = "Idea round produced no committed work; scientific feedback unavailable"
        science.commit("disposition", Disposition(kind="deferred", reason=reason, sources=[snapshot]), key=deferral_key)
        raise EligibilityError(reason)
    bind_stage_output(science, admission, outputs)
    return outputs
