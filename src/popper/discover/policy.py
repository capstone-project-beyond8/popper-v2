"""Bounded sourced proposals, selection and immutable scheduling."""

import json
from typing import Any

from pydantic import Field

from popper.discover.state import (
    ResearchState,
    compact_state,
    rebuild_state,
    validate_sources,
)
from popper.harness.agent import Tool, agent_loop
from popper.harness.artifacts import reachable_refs, read_artifact_tool
from popper.harness.config import Discovery
from popper.harness.context import fence
from popper.harness.prompts import load_prompt
from popper.harness.records import ArtifactRef, IntegrityError, Record, resolve_artifact
from popper.harness.session import Harness
from popper.science.contracts import (
    Attempt,
    Diagnosis,
    Disposition,
    ExperimentSpec,
    Invalidation,
    MoveProposal,
    MoveSelection,
    ResearchMove,
    classify_change,
)
from popper.science.store import ScienceStore


class EligibilityError(ValueError):
    pass


class Proposals(Record):
    moves: list[MoveProposal]
    omitted: dict[str, str] = Field(default_factory=dict)


class SelectionProposal(Record):
    proposal_id: str
    rationale: str = Field(min_length=1)


def eligible_candidates(state: ResearchState, limits: Discovery) -> list[str]:
    if state.counters.get("moves", 0) >= limits.max_moves:
        return []
    return [
        c.record.id
        for c in state.candidates
        if state.counters.get(c.record.id, 0) <= limits.max_revisits
    ]


def check_move(
    state: ResearchState, move: ResearchMove, limits: Discovery
) -> None:
    if move.action == "stop":
        return
    if move.action in {"pivot", "reframe", "acquisition"}:
        raise EligibilityError(f"{move.action} route is deferred")
    if state.counters.get("moves", 0) >= limits.max_moves:
        raise EligibilityError("scheduled move cap reached")
    if state.counters.get(move.hypothesis_id or "", 0) > limits.max_revisits:
        raise EligibilityError("hypothesis revisit cap reached")
    if any(d.record.category == "integrity" for d in state.diagnoses):
        raise IntegrityError("integrity diagnosis blocks scheduling")
    if state.budget and state.budget["spent_usd"] >= state.budget["max_usd"]:
        raise EligibilityError("resource cap reached")
    if move.action in {"technical_repair", "measurement_repair"} and not move.diagnosis:
        raise EligibilityError("repair requires sourced defect diagnosis")


def validate_moves(
    h: Harness, snapshot: ArtifactRef, proposals: list[MoveProposal]
) -> list[ResearchMove]:
    state = ResearchState.model_validate_json(resolve_artifact(h.run, snapshot).read_text("utf-8"))
    allowed = {r.model_dump_json() for r in reachable_refs(h, snapshot)}
    candidates = {c.record.id for c in state.candidates}
    seen: set[str] = set()
    validated: list[tuple[dict[str, Any], ExperimentSpec | None]] = []
    for index, proposal in enumerate(proposals):
        for ref in proposal.trigger_refs:
            if ref.model_dump_json() not in allowed:
                raise IntegrityError("unresolved trigger or foreign snapshot")
        if proposal.hypothesis_id:
            if proposal.hypothesis_id in seen:
                raise ValueError("duplicate per-candidate proposal")
            if proposal.hypothesis_id not in candidates:
                raise ValueError("proposal names unknown hypothesis")
            seen.add(proposal.hypothesis_id)
        validate_sources(h, proposal.model_dump(mode="json"))
        payload = proposal.model_dump(mode="json")
        test = None
        if proposal.test_proposal:
            if not proposal.hypothesis_id:
                raise ValueError("test proposal requires owning hypothesis")
            candidate = next(
                c.record for c in state.candidates if c.record.id == proposal.hypothesis_id
            )
            if proposal.test_proposal.primary_estimand != candidate.primary_estimand:
                raise EligibilityError("changed target requires deferred pivot")
            previous = next(
                (
                    a.record.test
                    for a in reversed(state.attempts)
                    if a.record.hypothesis_id == proposal.hypothesis_id
                ),
                None,
            )
            test_id = f"test-{snapshot.record_id.removeprefix('artifact-')}-{index:03d}"
            test = ExperimentSpec(
                **proposal.test_proposal.model_dump(),
                id=test_id,
                hypothesis_id=proposal.hypothesis_id,
                parent_test=previous,
            )
        if payload.get("test"):
            existing_test = ExperimentSpec.model_validate_json(
                resolve_artifact(h.run, ArtifactRef.model_validate(payload["test"])).read_text(
                    "utf-8"
                )
            )
            if existing_test.hypothesis_id != proposal.hypothesis_id:
                raise IntegrityError("move test belongs to another hypothesis")
        validated.append((payload, test))
    moves: list[ResearchMove] = []
    for index, (payload, test) in enumerate(validated):
        if test:
            test_ref = ScienceStore(h.run).commit("test", test, key=test.id)
            payload["test"] = test_ref.model_dump(mode="json")
        moves.append(
            ResearchMove(
                **payload,
                id=f"move-{snapshot.record_id.removeprefix('artifact-')}-{index:03d}",
                snapshot=snapshot,
            )
        )
    return moves


def propose_moves(h: Harness, snapshot: ArtifactRef) -> ArtifactRef:
    key = snapshot.record_id
    existing = h.run.committed(f"science:proposals:{key}")
    if existing:
        return h.run.artifact_ref(f"science:proposals:{key}")
    state = ResearchState.model_validate_json(resolve_artifact(h.run, snapshot).read_text("utf-8"))
    collected: list[ResearchMove] = []

    def submit(proposal: Proposals) -> str:
        eligible = eligible_candidates(state, h.config.discovery)
        proposed = {m.hypothesis_id for m in proposal.moves}
        missing = set(eligible) - proposed - proposal.omitted.keys()
        if missing:
            raise ValueError(
                f"omitted eligible candidates need attributed reasons: {sorted(missing)}"
            )
        collected[:] = validate_moves(h, snapshot, proposal.moves)
        return "Validated sourced proposals."

    tools = [
        read_artifact_tool(h, reachable_refs(h, snapshot)),
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
            "popper.discover",
            "research_moves.md",
            state=fence(json.dumps(compact_state(state))),
            snapshot=snapshot.model_dump_json(),
        ),
        tools=tools,
        max_turns=h.config.search.max_turns,
        max_submits=2,
    )
    if response is None:
        ScienceStore(h.run).commit("disposition",
            Disposition(
                kind="rejected",
                reason="Bounded scientific proposal correction exhausted",
                sources=[snapshot],
            ),
            key=key,
        )
        return ScienceStore(h.run).commit("proposals",
            {
                "snapshot": snapshot.model_dump(mode="json"),
                "moves": [],
                "omitted": {"all": "proposal validation exhausted"},
            },
            key=key,
        )
    return ScienceStore(h.run).commit("proposals",
        {
            "snapshot": snapshot.model_dump(mode="json"),
            "moves": [m.model_dump(mode="json") for m in collected],
            "omitted": response.get("omitted", {}),
        },
        key=key,
    )


def select_move(h: Harness, snapshot: ArtifactRef, proposals: ArtifactRef) -> ArtifactRef:
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
        prompt=load_prompt("popper.discover", "select_move.md", proposals=fence(json.dumps(record))),
    )
    if choice.proposal_id not in {m.id for m in moves}:
        raise EligibilityError("selection names an unknown retained proposal")
    return ScienceStore(h.run).commit("selection",
        MoveSelection(
            proposal_id=choice.proposal_id,
            snapshot=snapshot,
            proposals=proposals,
            author="theorist",
            rationale=choice.rationale,
        ),
        key=key,
    )


def selected_move(h: Harness, selection: ArtifactRef) -> ResearchMove:
    choice = MoveSelection.model_validate_json(
        resolve_artifact(h.run, selection).read_text("utf-8")
    )
    data = json.loads(resolve_artifact(h.run, choice.proposals).read_text("utf-8"))
    return next(
        ResearchMove.model_validate(m) for m in data["moves"] if m["id"] == choice.proposal_id
    )


def make_attempt(h: Harness, move: ResearchMove, parent: ArtifactRef | None) -> ArtifactRef:
    name = f"science:attempt:{move.id}"
    if h.run.committed(name):
        return h.run.artifact_ref(name)
    state = rebuild_state(h)
    snapshot = ResearchState.model_validate_json(
        resolve_artifact(h.run, move.snapshot).read_text("utf-8")
    )
    if snapshot.frontier != state.frontier:
        raise EligibilityError("stale scientific frontier")
    check_move(state, move, h.config.discovery)
    if move.test is None or move.hypothesis_id is None:
        raise EligibilityError("move cannot schedule an execution")
    test = ExperimentSpec.model_validate_json(resolve_artifact(h.run, move.test).read_text("utf-8"))
    if test.hypothesis_id != move.hypothesis_id:
        raise IntegrityError("move test belongs to another hypothesis")
    previous = next(
        (a for a in reversed(state.attempts) if a.record.hypothesis_id == move.hypothesis_id), None
    )
    reuse: dict[str, ArtifactRef] = {}
    if previous:
        if parent != previous.ref:
            raise EligibilityError("revisit must cite its latest parent attempt")
        old_test = ExperimentSpec.model_validate_json(
            resolve_artifact(h.run, previous.record.test).read_text("utf-8")
        )
        change = classify_change(old_test, test)
        if change == "pivot":
            raise EligibilityError("changed target requires pivot")
        if move.action == "test":
            raise EligibilityError("repeat test requires a sourced repair or refinement")
        if move.action in {"technical_repair", "measurement_repair"}:
            if change != "same_test" or test.id != old_test.id:
                raise EligibilityError("repair must preserve exact intended test")
            assert move.diagnosis is not None
            diagnosis = Diagnosis.model_validate_json(
                resolve_artifact(h.run, move.diagnosis).read_text("utf-8")
            )
            required = "technical" if move.action == "technical_repair" else "measurement"
            if (
                diagnosis.category != required
                or previous.ref not in diagnosis.observation_refs
                and previous.record.test not in diagnosis.affected_refs
            ):
                raise EligibilityError("repair requires a defect attributed to this test")
            prior_result = next(
                (r.record for r in state.results if r.record.attempt == previous.ref), None
            )
            if prior_result:
                affected = set(diagnosis.affected_roles)
                if not affected:
                    raise EligibilityError("repair diagnosis must identify affected stages")
                reuse = {
                    role: ref
                    for role, ref in prior_result.stages.items()
                    if role in {"baseline", "main"}
                    and role not in affected
                    and not (role == "main" and "baseline" in affected)
                }
        elif move.action == "refine":
            if change != "refine":
                raise EligibilityError("refinement must change the operational procedure")
            attributed = {r.ref for r in state.results if r.record.hypothesis_id == move.hypothesis_id}
            attributed.update(q.ref for q in state.questions if q.record.hypothesis_id == move.hypothesis_id and not q.record.resolved)
            attributed.update(d.ref for d in state.diagnoses if previous.record.test in d.record.affected_refs or previous.ref in d.record.observation_refs)
            if not any(ref in attributed for ref in move.trigger_refs):
                raise EligibilityError("refinement requires an attributed question or diagnostic observation")
    elif move.action != "test":
        raise EligibilityError("first hypothesis execution must be a test")
    move_ref = ScienceStore(h.run).commit("move", move, key=move.id)
    index = state.counters.get("moves", 0)
    attempt_id = f"attempt-{index:03d}"
    ref = ScienceStore(h.run).commit("attempt",
        Attempt(
            id=attempt_id,
            move=move_ref,
            move_id=move.id,
            hypothesis_id=move.hypothesis_id,
            test=move.test,
            parent=parent,
            diagnosis=move.diagnosis,
            changed_fields=move.changed_fields,
            stage_instances={
                role: f"{move.hypothesis_id}-{attempt_id}-{role}"
                for role in ("baseline", "main", "robustness")
            },
            reuse=reuse,
            move_count=index + 1,
            revisit_count=state.counters.get(move.hypothesis_id, 0),
            exposure=state.exposure,
        ),
        key=move.id,
    )
    ensure_invalidation(h, ref)
    return ref


def ensure_invalidation(h: Harness, attempt_ref: ArtifactRef) -> None:
    attempt = Attempt.model_validate_json(resolve_artifact(h.run, attempt_ref).read_text("utf-8"))
    if attempt.diagnosis is None or attempt.parent is None:
        return
    diagnosis = Diagnosis.model_validate_json(resolve_artifact(h.run, attempt.diagnosis).read_text("utf-8"))
    if diagnosis.category != "measurement":
        return
    state = rebuild_state(h)
    prior = next((r.record for r in state.results if r.record.attempt == attempt.parent), None)
    invalid = [m.ref for m in prior.measurements if m.role not in attempt.reuse] if prior else []
    if invalid:
        ScienceStore(h.run).commit("invalidation", Invalidation(measurements=invalid, diagnosis=attempt.diagnosis, superseded_by=attempt_ref), key=attempt.move_id)
