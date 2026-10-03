from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from popper.harness.storage.records import ArtifactRef, IntegrityError
from popper.harness.storage.store import RunStore
from popper.scientific.runtime.lifecycle.contracts import (
    Candidate,
    CandidateProposal,
    Question,
    StageAdmission,
)
from popper.scientific.runtime.lifecycle.ideas import (
    DirectionProposal,
    IdeaChallengeProposal,
    IdeaProposal,
    PromotionProposal,
    commit_direction,
    commit_idea,
    commit_idea_challenge,
    promote_idea,
)
from popper.scientific.runtime.lifecycle.transitions import EligibilityError
from popper.scientific.runtime.projections.state import commit_snapshot, rebuild_state
from popper.scientific.runtime.store import ScienceStore

COLUMNS = ["score", "hours"]


class World:
    def __init__(self, tmp_path: Path) -> None:
        self.science = ScienceStore(RunStore(tmp_path))
        self.intent = self.science.commit("intent", {"objective": "compare"})
        self.question = self.science.commit("question", Question(
            text="Why do scores differ?", author="theorist", sources=[self.intent],
        ))
        self.count = 0

    def admission(self) -> ArtifactRef:
        self.count += 1
        snapshot = commit_snapshot(self.science, rebuild_state(self.science))
        return self.science.commit("admission", StageAdmission(
            id=f"work{self.count}", stage="discover", move=self.intent,
            snapshot=snapshot, inputs=[self.intent],
        ), key=f"work{self.count}")

    def idea(self, change: str = "new", maturity: str = "question", **extra: Any) -> IdeaProposal:
        fields: dict[str, Any] = {
            "change": change, "maturity": maturity, "statement": "Study habits matter",
            "rationale": "Scores vary", "sources": [self.intent],
        }
        if maturity == "question":
            fields["question"] = self.question
        if maturity == "conjecture":
            fields["explanation"] = "Hours of study raise scores"
            fields["limitations"] = ["Self-reported hours"]
        return IdeaProposal.model_validate({**fields, **extra})

    def commit(self, proposal: IdeaProposal, index: int = 0) -> ArtifactRef:
        return commit_idea(self.science, proposal, self.admission(), index, "theorist")

    def conjecture(self) -> ArtifactRef:
        return self.commit(self.idea(maturity="conjecture"))

    def challenge(self, revision: ArtifactRef) -> ArtifactRef:
        return commit_idea_challenge(self.science, IdeaChallengeProposal(
            assessment="Confounded by motivation", discriminating_checks=["Adjust for motivation"],
            sources=[revision],
        ), revision, self.admission(), 0, "judge")

    def exploration(self) -> None:
        self.science.commit("candidates", {"candidates": [Candidate.model_validate({
            **self.candidate(), "id": "seed", "origins": [self.intent], "exposure": [self.intent],
        }).model_dump(mode="json")]}, key="initial")

    def candidate(self, outcome: str = "score") -> dict[str, Any]:
        return {
            "statement": "Hours raise scores", "rationale": "Dose response",
            "primary_estimand": {
                "outcome": outcome, "exposure": "hours", "contrast": "one hour",
                "comparison": "difference", "population": "students", "unit": "points",
            },
            "expected_direction": "positive", "refuting_result": "An interval spanning zero",
            "planned_test": "Regression",
            "methods": [{
                "family": "linear_regression", "description": "OLS", "inputs": ["hours"],
                "outputs": ["slope"], "effect_scale": "points",
            }],
        }

    def promote(
        self, revision: ArtifactRef, challenge: ArtifactRef, candidate: dict[str, Any] | None = None,
        admission: ArtifactRef | None = None,
    ) -> ArtifactRef:
        return promote_idea(
            self.science, revision, challenge,
            PromotionProposal(
                candidate=CandidateProposal.model_validate(candidate or self.candidate()),
                predictions=["Slope above zero", "Slope near zero"], rationale="Challenge answered",
            ),
            admission or self.admission(), 0, "theorist", columns=COLUMNS,
        )


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def test_question_idea_needs_no_estimand(world: World) -> None:
    ref = world.commit(world.idea())
    [item] = rebuild_state(world.science).ideas
    assert item.ref == ref and item.record.maturity == "question"
    assert item.record.idea_id.startswith("idea-work1-") and item.record.status == "active"
    assert ref in rebuild_state(world.science).frontier


@pytest.mark.parametrize("fields", [
    {"maturity": "testable"},
    {"maturity": "observation"},
    {"maturity": "question", "question": None},
    {"maturity": "conjecture", "limitations": []},
    {"change": "continue"},
    {"idea_id": "idea-x"},
    {"sources": []},
])
def test_unfit_proposal_is_rejected(world: World, fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        world.idea(**fields)


def test_question_must_be_a_projected_question(world: World) -> None:
    with pytest.raises(IntegrityError, match="question"):
        world.commit(world.idea(question=world.intent))


def test_split_and_merge_preserve_lineage(world: World) -> None:
    parent = world.commit(world.idea())
    left = world.commit(world.idea("split", parents=[parent]))
    right = world.commit(world.idea("split", parents=[parent]))
    assert left != right
    ideas = rebuild_state(world.science).ideas
    assert len({i.record.idea_id for i in ideas}) == 3
    assert [i.record.parents for i in ideas[1:]] == [[parent], [parent]]
    merged = world.commit(world.idea("merge", parents=[left, right]))
    assert rebuild_state(world.science).ideas[-1].ref == merged
    with pytest.raises(ValueError, match="distinct"):
        world.commit(world.idea("merge", parents=[left, left]))


def test_retirement_keeps_measurements_visible(world: World) -> None:
    parent = world.commit(world.idea())
    before = rebuild_state(world.science)
    idea_id = before.ideas[0].record.idea_id
    retired = world.commit(world.idea("retire", idea_id=idea_id, parents=[parent]))
    after = rebuild_state(world.science)
    assert after.ideas[-1].ref == retired and after.ideas[-1].record.status == "retired"
    assert after.history == before.history and after.observations == before.observations
    with pytest.raises(IntegrityError):
        world.commit(world.idea("continue", idea_id=idea_id, parents=[retired]))
    with pytest.raises(IntegrityError):
        world.commit(world.idea("continue", idea_id=idea_id, parents=[parent]))


def test_retirement_keeps_maturity(world: World) -> None:
    parent = world.commit(world.idea())
    idea_id = rebuild_state(world.science).ideas[0].record.idea_id
    with pytest.raises(ValueError, match="maturity"):
        world.commit(world.idea("retire", "conjecture", idea_id=idea_id, parents=[parent]))


def test_identity_changes_only_with_replacement(world: World) -> None:
    parent = world.conjecture()
    idea_id = rebuild_state(world.science).ideas[0].record.idea_id
    with pytest.raises(ValueError, match="replacement"):
        world.commit(world.idea("continue", "conjecture", idea_id=idea_id, parents=[parent], meaning_changed=True))
    world.commit(world.idea("continue", "conjecture", idea_id=idea_id, parents=[parent]))
    with pytest.raises(IntegrityError):  # the first revision is no longer the latest
        world.commit(world.idea("continue", "conjecture", idea_id=idea_id, parents=[parent]))
    latest = rebuild_state(world.science).ideas[-1].ref
    other = world.commit(world.idea("new", "conjecture"))
    with pytest.raises(ValueError, match="different idea"):
        world.commit(world.idea("continue", "conjecture", idea_id=idea_id, parents=[other]))
    replaced = world.commit(world.idea("replace", "conjecture", parents=[latest]))
    ideas = rebuild_state(world.science).ideas
    assert ideas[-1].ref == replaced and ideas[-1].record.idea_id != idea_id

    world.exploration()
    first = world.promote(other, world.challenge(other))
    second = world.promote(replaced, world.challenge(replaced))
    state = rebuild_state(world.science)
    by_ref = {i.ref: i.record for i in state.ideas}
    by_id = {c.record.id: c.record for c in state.candidates}
    assert by_ref[first].candidate_id != by_ref[second].candidate_id
    assert by_id[str(by_ref[first].candidate_id)].primary_estimand == by_id[str(by_ref[second].candidate_id)].primary_estimand


def test_promotion_projects_a_candidate_with_lineage(world: World) -> None:
    world.exploration()
    revision = world.conjecture()
    challenge = world.challenge(revision)
    testable = world.promote(revision, challenge)
    state = rebuild_state(world.science)
    idea = state.ideas[-1]
    assert idea.ref == testable and idea.record.maturity == "testable"
    assert idea.record.parents == [revision] and len(idea.record.predictions) == 2
    candidate = state.candidates[-1]
    assert candidate.record.id == f"hypothesis-{idea.record.idea_id}"
    assert candidate.record.origins == [revision, challenge]
    assert idea.record.candidate == candidate.ref and idea.record.candidate_id == candidate.record.id
    assert candidate.record.exposure == state.exposure == [world.intent]


def test_exposure_is_the_union_of_candidate_sets(world: World) -> None:
    world.exploration()
    extra = world.science.commit("intent", {"objective": "second"})
    candidate = Candidate.model_validate({
        **world.candidate(), "id": "later", "origins": [extra], "exposure": [extra, world.intent],
    })
    world.science.commit("candidates", {"candidates": [candidate.model_dump(mode="json")]}, key="later")
    assert rebuild_state(world.science).exposure == [world.intent, extra]


def test_promotion_rejections(world: World) -> None:
    world.exploration()
    question = world.commit(world.idea())
    conjecture = world.conjecture()
    other = world.commit(world.idea("new", "conjecture"))
    challenge = world.challenge(conjecture)
    with pytest.raises(ValueError, match="conjecture"):
        world.promote(question, world.challenge(question))
    with pytest.raises(IntegrityError, match="challenge"):
        world.promote(other, challenge)
    with pytest.raises(ValidationError, match="processed columns"):
        world.promote(conjecture, challenge, world.candidate(outcome="missing"))
    tampered = conjecture.model_copy(update={"sha256": "a" * 64})
    with pytest.raises(IntegrityError):
        world.promote(tampered, challenge)
    with pytest.raises(IntegrityError):
        world.promote(world.question, challenge)
    with pytest.raises(IntegrityError):
        world.promote(conjecture, challenge, admission=world.intent)
    admission = world.admission()
    before = len(world.science.commits())
    testable = world.promote(conjecture, challenge, admission=admission)
    assert len(world.science.commits()) == before + 2
    with pytest.raises(ValueError):
        world.promote(conjecture, challenge)
    with pytest.raises(ValueError):
        world.promote(testable, challenge)
    assert len(rebuild_state(world.science).candidates) == 2


def test_promotion_requires_exposure(world: World) -> None:
    revision = world.conjecture()
    with pytest.raises(EligibilityError):
        world.promote(revision, world.challenge(revision))


def test_interrupted_promotion_resumes_once(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.exploration()
    revision = world.conjecture()
    challenge = world.challenge(revision)
    admission = world.admission()
    original = ScienceStore.commit

    def interrupt(store: ScienceStore, kind: str, record: Any, *, key: str | None = None) -> ArtifactRef:
        if kind == "idea" and key and key.startswith("work"):
            raise KeyboardInterrupt
        return original(store, kind, record, key=key)

    with monkeypatch.context() as patch:
        patch.setattr(ScienceStore, "commit", interrupt)
        with pytest.raises(KeyboardInterrupt):
            world.promote(revision, challenge, admission=admission)
    assert len(rebuild_state(world.science).candidates) == 2
    done = world.promote(revision, challenge, admission=admission)
    assert world.promote(revision, challenge, admission=admission) == done
    state = rebuild_state(world.science)
    assert len(state.candidates) == 2
    assert [i.record.maturity for i in state.ideas] == ["conjecture", "testable"]


def test_commit_idea_is_idempotent_and_never_overwrites(world: World) -> None:
    admission = world.admission()
    proposal = world.idea()
    first = commit_idea(world.science, proposal, admission, 0, "theorist")
    assert commit_idea(world.science, proposal, admission, 0, "theorist") == first
    with pytest.raises(IntegrityError, match="conflicting"):
        commit_idea(world.science, world.idea(statement="Something else"), admission, 0, "theorist")
    with pytest.raises(IntegrityError, match="conflicting"):
        commit_idea(world.science, proposal, admission, 0, "someone else")
    assert len(rebuild_state(world.science).ideas) == 1


def test_idea_challenge_needs_an_active_committed_revision(world: World) -> None:
    revision = world.conjecture()
    challenge = world.challenge(revision)
    assert rebuild_state(world.science).idea_challenges[0].ref == challenge
    idea_id = rebuild_state(world.science).ideas[0].record.idea_id
    world.commit(world.idea("retire", "conjecture", idea_id=idea_id, parents=[revision]))
    with pytest.raises(IntegrityError):
        world.challenge(revision)
    with pytest.raises(IntegrityError):
        world.challenge(world.question)


def test_direction_supersedes_the_latest(world: World) -> None:
    def propose(text: str) -> DirectionProposal:
        return DirectionProposal(
            central_question=text, explanations=["Study habits"], evidence_sequence=["Measure hours"],
            sources=[world.intent],
        )

    first_snapshot = commit_snapshot(world.science, rebuild_state(world.science))
    first = commit_direction(world.science, propose("Why do scores differ?"), first_snapshot, "scientist")
    assert commit_direction(world.science, propose("Why do scores differ?"), first_snapshot, "scientist") == first
    with pytest.raises(IntegrityError, match="conflicting"):
        commit_direction(world.science, propose("Other"), first_snapshot, "scientist")
    second_snapshot = commit_snapshot(world.science, rebuild_state(world.science))
    second = commit_direction(world.science, propose("What about hours?"), second_snapshot, "scientist")
    directions = rebuild_state(world.science).directions
    assert [d.ref for d in directions] == [first, second]
    assert [d.record.supersedes for d in directions] == [None, first]


def test_retiring_a_tested_idea_keeps_its_candidate(world: World) -> None:
    world.exploration()
    revision = world.conjecture()
    testable = world.promote(revision, world.challenge(revision))
    before = rebuild_state(world.science)
    parent = before.ideas[-1].record
    retired = world.commit(world.idea(
        "retire", "testable", idea_id=parent.idea_id, parents=[testable],
        explanation="Hours of study raise scores", limitations=["Self-reported hours"],
    ))
    after = rebuild_state(world.science)
    record = after.ideas[-1].record
    assert after.ideas[-1].ref == retired and record.status == "retired" and record.maturity == "testable"
    assert (record.candidate, record.candidate_id, record.predictions) == (
        parent.candidate, parent.candidate_id, parent.predictions,
    )
    assert after.candidates == before.candidates and after.history == before.history
    with pytest.raises(IntegrityError):
        world.commit(world.idea(
            "retire", "testable", idea_id=parent.idea_id, parents=[retired],
            explanation="Hours of study raise scores", limitations=["Self-reported hours"],
        ))
    with pytest.raises(ValidationError):
        world.idea("continue", "testable", idea_id=parent.idea_id, parents=[retired])
