"""Scientific identity and transition contracts."""

import json
from typing import Any

from popper.harness.storage.records import (
    ArtifactRef,
    IntegrityError,
    reachable_refs,
    resolve_artifact,
)
from popper.scientific.runtime.lifecycle.contracts import (
    STAGE_OF,
    Attempt,
    Diagnosis,
    Disposition,
    ExperimentSpec,
    Invalidation,
    MoveProposal,
    MoveSelection,
    ResearchMove,
    StageAdmission,
    StageWork,
    WorkStatus,
    classify_change,
)
from popper.scientific.runtime.projections.state import (
    load_snapshot,
    rebuild_state,
    validate_sources,
)
from popper.scientific.runtime.store import ScienceStore


class EligibilityError(ValueError):
    pass


def selected_move(science: ScienceStore, selection: ArtifactRef) -> ResearchMove:
    choice = MoveSelection.model_validate_json(
        resolve_artifact(science.run, selection).read_text("utf-8")
    )
    data = json.loads(resolve_artifact(science.run, choice.proposals).read_text("utf-8"))
    return next(
        ResearchMove.model_validate(m) for m in data["moves"] if m["id"] == choice.proposal_id
    )


def admit_stage(science: ScienceStore, selection: ArtifactRef) -> ArtifactRef:
    move = selected_move(science, selection)
    validate_sources(science, move.model_dump(mode="json"))
    name = f"science:admission:{selection.record_id}"
    if science.run.committed(name):
        ref = science.run.artifact_ref(name)
        validate_sources(science, science.read(ref))
        return ref
    state = rebuild_state(science)
    if load_snapshot(science, move.snapshot).frontier != state.frontier:
        raise EligibilityError("stale scientific frontier")
    stage = STAGE_OF[move.action]
    if stage is None:
        raise EligibilityError("selected move has no executable stage")
    move_ref = science.commit("move", move, key=move.id)
    return science.commit("admission", StageAdmission(
        id=move.id, stage=stage, move=move_ref, snapshot=move.snapshot,
        inputs=list(dict.fromkeys([selection, *move.trigger_refs, *([move.test] if move.test else [])])),
    ), key=selection.record_id)


def defer_stage(science: ScienceStore, selection: ArtifactRef, reason: str) -> ArtifactRef:
    selected_move(science, selection)
    return science.commit("disposition", Disposition(
        kind="deferred", reason=reason, sources=[selection], resource="cap" in reason,
    ), key=f"admission:{selection.record_id}")


def complete_stage(
    science: ScienceStore, admission: ArtifactRef, status: WorkStatus,
    outputs: list[ArtifactRef], reason: str,
) -> ArtifactRef:
    StageAdmission.model_validate(science.read(admission))
    record = StageWork(admission=admission, status=status, outputs=outputs, reason=reason)
    validate_sources(science, record.model_dump(mode="json"))
    return science.commit("work", record, key=admission.record_id)


def bind_stage_output(science: ScienceStore, admission: ArtifactRef, outputs: list[ArtifactRef]) -> ArtifactRef:
    work = StageAdmission.model_validate(science.read(admission))
    payload = {"admission": admission.model_dump(mode="json"), "outputs": [r.model_dump(mode="json") for r in outputs]}
    validate_sources(science, payload)
    return science.commit("stage_output", payload, key=work.id)


def stage_outputs(science: ScienceStore, admission: ArtifactRef) -> list[ArtifactRef] | None:
    work = StageAdmission.model_validate(science.read(admission))
    name = f"science:stage_output:{work.id}"
    if science.run.committed(name) is None:
        return None
    payload = science.read(science.run.artifact_ref(name))
    if ArtifactRef.model_validate(payload["admission"]) != admission:
        raise IntegrityError("stage output belongs to a different admission")
    validate_sources(science, payload)
    return [ArtifactRef.model_validate(r) for r in payload["outputs"]]


def validate_moves(
    science: ScienceStore, snapshot: ArtifactRef, proposals: list[MoveProposal]
) -> list[ResearchMove]:
    state = load_snapshot(science, snapshot)
    allowed = {r.model_dump_json() for r in reachable_refs(science.run, snapshot)}
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
        validate_sources(science, proposal.model_dump(mode="json"))
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
                resolve_artifact(
                    science.run, ArtifactRef.model_validate(payload["test"])
                ).read_text("utf-8")
            )
            if existing_test.hypothesis_id != proposal.hypothesis_id:
                raise IntegrityError("move test belongs to another hypothesis")
        validated.append((payload, test))
    moves: list[ResearchMove] = []
    for index, (payload, test) in enumerate(validated):
        if test:
            test_ref = science.commit("test", test, key=test.id)
            payload["test"] = test_ref.model_dump(mode="json")
        moves.append(
            ResearchMove(
                **payload,
                id=f"move-{snapshot.record_id.removeprefix('artifact-')}-{index:03d}",
                snapshot=snapshot,
            )
        )
    return moves


def schedule_attempt(
    science: ScienceStore, move: ResearchMove, parent: ArtifactRef | None
) -> ArtifactRef:
    name = f"science:attempt:{move.id}"
    if science.run.committed(name):
        existing = science.run.artifact_ref(name)
        ensure_invalidation(science, existing)
        return existing
    state = rebuild_state(science)
    snapshot = load_snapshot(science, move.snapshot)
    if snapshot.frontier != state.frontier:
        raise EligibilityError("stale scientific frontier")
    if any(d.record.category == "integrity" for d in state.diagnoses):
        raise IntegrityError("integrity diagnosis blocks scheduling")
    if move.action in {"technical_repair", "measurement_repair"} and not move.diagnosis:
        raise EligibilityError("repair requires sourced defect diagnosis")
    if move.test is None or move.hypothesis_id is None:
        raise EligibilityError("move cannot schedule an execution")
    test = ExperimentSpec.model_validate_json(
        resolve_artifact(science.run, move.test).read_text("utf-8")
    )
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
            resolve_artifact(science.run, previous.record.test).read_text("utf-8")
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
                resolve_artifact(science.run, move.diagnosis).read_text("utf-8")
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
            attributed = {
                r.ref for r in state.results if r.record.hypothesis_id == move.hypothesis_id
            }
            attributed.update(
                q.ref
                for q in state.questions
                if q.record.hypothesis_id == move.hypothesis_id and not q.record.resolved
            )
            attributed.update(
                d.ref
                for d in state.diagnoses
                if previous.record.test in d.record.affected_refs
                or previous.ref in d.record.observation_refs
            )
            if not any(ref in attributed for ref in move.trigger_refs):
                raise EligibilityError(
                    "refinement requires an attributed question or diagnostic observation"
                )
    elif move.action != "test":
        raise EligibilityError("first hypothesis execution must be a test")
    move_ref = science.commit("move", move, key=move.id)
    index = state.counters.get("moves", 0)
    attempt_id = f"attempt-{index:03d}"
    ref = science.commit(
        "attempt",
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
    ensure_invalidation(science, ref)
    return ref


def ensure_invalidation(science: ScienceStore, attempt_ref: ArtifactRef) -> None:
    attempt = Attempt.model_validate_json(
        resolve_artifact(science.run, attempt_ref).read_text("utf-8")
    )
    if attempt.diagnosis is None or attempt.parent is None:
        return
    diagnosis = Diagnosis.model_validate_json(
        resolve_artifact(science.run, attempt.diagnosis).read_text("utf-8")
    )
    if diagnosis.category != "measurement":
        return
    state = rebuild_state(science)
    prior = next((r.record for r in state.results if r.record.attempt == attempt.parent), None)
    invalid = [m.ref for m in prior.measurements if m.role not in attempt.reuse] if prior else []
    if invalid:
        science.commit(
            "invalidation",
            Invalidation(
                measurements=invalid, diagnosis=attempt.diagnosis, superseded_by=attempt_ref
            ),
            key=attempt.move_id,
        )
