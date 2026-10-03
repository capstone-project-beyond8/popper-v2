"""Scientific ideas, their critique and the sustained research direction."""

from typing import TYPE_CHECKING, Literal, Self

from pydantic import Field, model_validator

from popper.harness.storage.records import ArtifactRef, IntegrityError, Record
from popper.scientific.runtime.lifecycle.contracts import (
    Candidate,
    CandidateProposal,
    StageAdmission,
    Text,
)
from popper.scientific.runtime.store import ScienceStore

if TYPE_CHECKING:
    from popper.scientific.runtime.projections.state import ResearchState, Sourced

Maturity = Literal["observation", "question", "conjecture", "testable"]
IdeaChange = Literal["new", "continue", "split", "merge", "replace", "retire"]
NEW_IDENTITY: frozenset[IdeaChange] = frozenset({"new", "split", "merge", "replace"})
SUPERSEDING: frozenset[IdeaChange] = frozenset({"split", "merge", "replace"})
CONFLICT = "conflicting scientific record for a committed key"


def _check_parents(change: IdeaChange, parents: list[ArtifactRef]) -> None:
    if change == "new" and parents:
        raise ValueError("a new idea has no parents")
    if change == "merge" and len(parents) < 2:
        raise ValueError("a merge needs at least two parents")
    if change not in {"new", "merge"} and len(parents) != 1:
        raise ValueError(f"{change} needs exactly one parent")


def _check_maturity(idea: "IdeaProposal") -> None:
    if idea.maturity == "observation" and idea.observation is None:
        raise ValueError("an observation idea cites its observation")
    if idea.maturity == "question" and idea.question is None:
        raise ValueError("a question idea cites its question")
    if idea.maturity in {"conjecture", "testable"} and (
        idea.explanation is None or not idea.limitations
    ):
        raise ValueError("a conjecture states its explanation and at least one limitation")


class IdeaProposal(Record):
    change: IdeaChange
    maturity: Maturity
    idea_id: Text | None = None
    parents: list[ArtifactRef] = Field(default_factory=list)
    statement: Text
    rationale: Text
    meaning_changed: bool = False
    sources: list[ArtifactRef] = Field(min_length=1)
    observation: ArtifactRef | None = None
    question: ArtifactRef | None = None
    explanation: Text | None = None
    limitations: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def proposable(self) -> Self:
        if self.maturity == "testable" and self.change != "retire":
            raise ValueError("testable ideas come only from promotion")
        _check_maturity(self)
        _check_parents(self.change, self.parents)
        if (self.change in {"continue", "retire"}) != (self.idea_id is not None):
            raise ValueError("idea_id is required to continue or retire an idea and forbidden otherwise")
        return self


class IdeaRevision(IdeaProposal):
    version: Literal[1] = 1
    id: Text
    idea_id: Text
    author: Text
    admission: ArtifactRef
    status: Literal["active", "retired"]
    candidate: ArtifactRef | None = None
    candidate_id: Text | None = None
    predictions: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def proposable(self) -> Self:
        _check_maturity(self)
        _check_parents(self.change, self.parents)
        if self.maturity == "testable":
            if self.candidate is None or self.candidate_id is None or len(self.predictions) < 2:
                raise ValueError("a testable idea names its candidate and two distinguishing predictions")
        elif self.candidate is not None or self.candidate_id is not None or self.predictions:
            raise ValueError("only testable ideas carry a candidate")
        return self


class IdeaChallengeProposal(Record):
    assessment: Text
    concerns: list[Text] = Field(default_factory=list)
    rivals: list[Text] = Field(default_factory=list)
    discriminating_checks: list[Text] = Field(min_length=1)
    sources: list[ArtifactRef] = Field(min_length=1)


class IdeaChallenge(IdeaChallengeProposal):
    version: Literal[1] = 1
    revision: ArtifactRef
    author: Text
    admission: ArtifactRef


class DirectionProposal(Record):
    central_question: Text
    explanations: list[Text] = Field(min_length=1)
    uncertainties: list[Text] = Field(default_factory=list)
    evidence_sequence: list[Text] = Field(min_length=1)
    sources: list[ArtifactRef] = Field(min_length=1)


class ResearchDirection(DirectionProposal):
    version: Literal[1] = 1
    author: Text
    snapshot: ArtifactRef
    supersedes: ArtifactRef | None


class PromotionProposal(Record):
    candidate: CandidateProposal
    predictions: list[Text] = Field(min_length=2)
    rationale: Text


def _work(science: ScienceStore, admission: ArtifactRef) -> StageAdmission:
    if not admission.producer.startswith("science:admission:"):
        raise IntegrityError("not a stage admission")
    return StageAdmission.model_validate(science.read(admission))


def _same(existing: Record, expected: Record, ignore: frozenset[str] = frozenset()) -> None:
    fields = set(type(expected).model_fields) - ignore
    if existing.model_dump(mode="json", include=fields) != expected.model_dump(mode="json", include=fields):
        raise IntegrityError(CONFLICT)


def _superseded(state: "ResearchState") -> dict[str, IdeaChange]:
    """Revision record ids that a split, merge or replacement superseded, with that change."""
    return {
        parent.record_id: item.record.change
        for item in state.ideas
        if item.record.change in SUPERSEDING
        for parent in item.record.parents
    }


def _heads(state: "ResearchState", *, splitting: bool = False) -> dict[str, "Sourced[IdeaRevision]"]:
    """Latest revision of every idea that is still active, by idea identity.

    A split parent stays available to further split children.
    """
    superseded = _superseded(state)
    latest = {item.record.idea_id: item for item in state.ideas}
    return {
        k: v
        for k, v in latest.items()
        if v.record.status == "active"
        and (
            v.ref.record_id not in superseded
            or splitting and superseded[v.ref.record_id] == "split"
        )
    }


def inactive_candidates(state: "ResearchState") -> set[str]:
    """Candidate ids whose owning idea is retired or superseded."""
    heads = _heads(state)
    return {
        item.record.candidate_id
        for item in state.ideas
        if item.record.candidate_id and item.record.idea_id not in heads
    }


def active_ideas(state: "ResearchState") -> int:
    """Number of ideas whose latest revision is active."""
    return len(_heads(state))


def _head(heads: dict[str, "Sourced[IdeaRevision]"], ref: ArtifactRef) -> "Sourced[IdeaRevision]":
    found = next((item for item in heads.values() if item.ref == ref), None)
    if found is None:
        raise ValueError("parent must be the latest revision of an active idea")
    return found


def commit_idea(
    science: ScienceStore,
    proposal: IdeaProposal,
    admission: ArtifactRef,
    index: int,
    author: str,
) -> ArtifactRef:
    from popper.scientific.runtime.projections.state import rebuild_state, validate_sources

    work = _work(science, admission)
    validate_sources(science, proposal.model_dump(mode="json"))
    key = f"{work.id}:{index:03d}"
    if science.run.committed(f"science:idea:{key}"):
        ref = science.run.artifact_ref(f"science:idea:{key}")
        existing = IdeaRevision.model_validate(science.read(ref))
        _same(existing, proposal, frozenset() if proposal.idea_id else frozenset({"idea_id"}))
        if existing.author != author or existing.admission != admission:
            raise IntegrityError(CONFLICT)
        return ref
    state = rebuild_state(science)
    heads = _heads(state, splitting=proposal.change == "split")
    parents = [_head(heads, ref) for ref in proposal.parents]
    if proposal.change in NEW_IDENTITY:
        idea_id = f"idea-{work.id}-{index:03d}"
    else:
        idea_id = str(proposal.idea_id)
        if parents[0].record.idea_id != idea_id:
            raise ValueError("parent belongs to a different idea")
    if proposal.change == "merge" and len({p.record.idea_id for p in parents}) != len(parents):
        raise ValueError("a merge needs parents from distinct ideas")
    if proposal.change == "continue" and proposal.meaning_changed:
        raise ValueError("a changed explanation needs a replacement idea")
    if proposal.change == "continue" and parents[0].record.maturity == "testable":
        raise ValueError("a testable idea changes only by retirement or replacement")
    if proposal.change == "retire" and proposal.maturity != parents[0].record.maturity:
        raise ValueError("a retired idea keeps its maturity")
    if proposal.question is not None and proposal.question not in {q.ref for q in state.questions}:
        raise ValueError("question is not a projected research question")
    inherited = (
        {k: parents[0].record.model_dump()[k] for k in ("candidate", "candidate_id", "predictions")}
        if proposal.change == "retire"
        else {}
    )
    revision = IdeaRevision.model_validate({
        **proposal.model_dump(),
        **inherited,
        "id": f"rev-{work.id}-{index:03d}",
        "idea_id": idea_id,
        "author": author,
        "admission": admission,
        "status": "retired" if proposal.change == "retire" else "active",
    })
    return science.commit("idea", revision, key=key)


def commit_idea_challenge(
    science: ScienceStore,
    proposal: IdeaChallengeProposal,
    revision: ArtifactRef,
    admission: ArtifactRef,
    index: int,
    author: str,
) -> ArtifactRef:
    from popper.scientific.runtime.projections.state import rebuild_state, validate_sources

    work = _work(science, admission)
    validate_sources(science, proposal.model_dump(mode="json"))
    key = f"{work.id}:challenge:{index:03d}"
    if science.run.committed(f"science:idea_challenge:{key}"):
        ref = science.run.artifact_ref(f"science:idea_challenge:{key}")
        existing = IdeaChallenge.model_validate(science.read(ref))
        _same(existing, proposal)
        if (existing.revision, existing.author, existing.admission) != (revision, author, admission):
            raise IntegrityError(CONFLICT)
        return ref
    state = rebuild_state(science)
    target = next((item for item in state.ideas if item.ref == revision), None)
    if target is None or target.record.idea_id not in _heads(state):
        raise ValueError("challenge needs a committed revision of an active idea")
    return science.commit("idea_challenge", IdeaChallenge(
        **proposal.model_dump(), revision=revision, author=author, admission=admission,
    ), key=key)


def commit_direction(
    science: ScienceStore, proposal: DirectionProposal, snapshot: ArtifactRef, author: str
) -> ArtifactRef:
    from popper.scientific.runtime.projections.state import rebuild_state, validate_sources

    validate_sources(science, [proposal.model_dump(mode="json"), snapshot.model_dump(mode="json")])
    name = f"science:direction:{snapshot.record_id}"
    if science.run.committed(name):
        ref = science.run.artifact_ref(name)
        existing = ResearchDirection.model_validate(science.read(ref))
        _same(existing, proposal)
        if (existing.author, existing.snapshot) != (author, snapshot):
            raise IntegrityError(CONFLICT)
        return ref
    directions = rebuild_state(science).directions
    return science.commit("direction", ResearchDirection(
        **proposal.model_dump(), author=author, snapshot=snapshot,
        supersedes=directions[-1].ref if directions else None,
    ), key=snapshot.record_id)


def promote_idea(
    science: ScienceStore,
    revision: ArtifactRef,
    challenge: ArtifactRef,
    proposal: PromotionProposal,
    admission: ArtifactRef,
    index: int,
    author: str,
    *,
    columns: list[str],
    warnings: list[str] | None = None,
) -> ArtifactRef:
    from popper.scientific.runtime.lifecycle.transitions import EligibilityError
    from popper.scientific.runtime.projections.state import rebuild_state, validate_sources

    work = _work(science, admission)
    validate_sources(science, [proposal.model_dump(mode="json"), revision.model_dump(mode="json")])
    key = f"{work.id}:{index:03d}"
    if science.run.committed(f"science:idea:{key}"):
        ref = science.run.artifact_ref(f"science:idea:{key}")
        existing = IdeaRevision.model_validate(science.read(ref))
        if (existing.parents, existing.predictions, existing.admission, existing.author) != (
            [revision], proposal.predictions, admission, author,
        ):
            raise IntegrityError(CONFLICT)
        return ref
    state = rebuild_state(science)
    parent = _head(_heads(state), revision)
    if parent.record.maturity != "conjecture":
        raise ValueError("only a conjecture can be promoted")
    challenged = next((c for c in state.idea_challenges if c.ref == challenge), None)
    if challenged is None or challenged.record.revision != revision:
        raise ValueError("promotion needs the challenge of this exact revision")
    checked = CandidateProposal.model_validate(
        proposal.candidate.model_dump(), context={"columns": columns}
    )
    candidate_id = f"hypothesis-{parent.record.idea_id}"
    promotion = f"promotion:{revision.record_id}"
    if not science.run.committed(f"science:candidates:{promotion}"):
        if any(c.record.id == candidate_id for c in state.candidates):
            raise ValueError("an idea is promoted once")
        if not state.exposure:
            raise EligibilityError("promotion needs committed exploration exposure")
    candidates = science.commit("candidates", {
        "version": 1,
        "candidates": [Candidate(
            **checked.model_dump(), id=candidate_id, origins=[revision, challenge],
            exposure=state.exposure, warnings=warnings or [],
        ).model_dump(mode="json")],
        "admission": admission.model_dump(mode="json"),
    }, key=promotion)
    return science.commit("idea", IdeaRevision.model_validate({
        **parent.record.model_dump(),
        "change": "continue",
        "maturity": "testable",
        "parents": [revision],
        "rationale": proposal.rationale,
        "meaning_changed": False,
        "sources": [revision, challenge],
        "id": f"rev-{work.id}-{index:03d}",
        "author": author,
        "admission": admission,
        "status": "active",
        "candidate": candidates,
        "candidate_id": candidate_id,
        "predictions": proposal.predictions,
    }), key=key)
