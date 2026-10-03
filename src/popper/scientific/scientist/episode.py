"""Scientific reasoning and the current bounded research playbook."""

import json
from dataclasses import dataclass, replace
from typing import Literal

from popper.harness.session import BudgetExceeded, Harness
from popper.harness.storage.records import ArtifactRef, IntegrityError, resolve_artifact
from popper.scientific.runtime.compatibility import StudyPolicy
from popper.scientific.runtime.evidence.historical import schedule_context
from popper.scientific.runtime.lifecycle.contracts import (
    Action,
    Disposition,
    MoveSelection,
    Program,
    ResearchMove,
    Run,
    RunResources,
)
from popper.scientific.runtime.lifecycle.requests import CapabilityRequest
from popper.scientific.runtime.lifecycle.transitions import EligibilityError, selected_move
from popper.scientific.runtime.projections.output import (
    StudyOutput,
    build_study,
    preparation_manifest,
    upstream,
)
from popper.scientific.runtime.projections.state import (
    commit_snapshot,
    current_frontier,
    load_snapshot,
    pending_proposal,
    pending_selection,
    rebuild_state,
)
from popper.scientific.runtime.projections.views import (
    foundation_view,
    latest,
    reviewed_frame,
    stage_outcome,
    validate_intent_inputs,
)
from popper.scientific.runtime.settings import ScientificOptions
from popper.scientific.runtime.store import ScienceStore
from popper.scientific.scientist.feedback import interpret_result
from popper.scientific.scientist.historical import plan_robustness
from popper.scientific.scientist.moves import propose_moves, select_move


@dataclass(frozen=True)
class EpisodeContext:
    program: Program
    run: Run
    resources: RunResources
    policy: StudyPolicy
    options: ScientificOptions


def _publication(
    science: ScienceStore,
    reason: str,
    status: Literal["completed", "failed", "budget_exceeded"] = "completed",
) -> CapabilityRequest:
    build_study(science, reason, status)
    return CapabilityRequest("publish", science.run.artifact_ref("study"))


def next_step(
    h: Harness, science: ScienceStore, context: EpisodeContext
) -> CapabilityRequest | None:
    store = science.run
    if context.policy.stage_aware:
        state = rebuild_state(science)
        if state.pending_admissions:
            admission = state.pending_admissions[0]
            selection = next(ref for ref in admission.record.inputs if ref.producer.startswith("science:selection:"))
            return replace(request_move(science, selection), admission=admission.ref)
        if state.dispositions and state.frontier and state.dispositions[-1].ref == state.frontier[-1]:
            disposition = state.dispositions[-1]
            if disposition.record.kind == "stopped" or disposition.record.resource and h.spent_usd >= h.config.budget.max_usd:
                return finish_episode(science, disposition.record.reason, "budget_exceeded" if disposition.record.resource else "completed", key=f"finish:{disposition.ref.record_id}")
        if state.stage_history:
            terminal = state.stage_history[-1].record
            admitted = next(a.record for a in state.stage_admissions if a.ref == terminal.admission)
            if admitted.stage == "communicate" and terminal.status == "completed":
                move = ResearchMove.model_validate(science.read(admitted.move))
                return finish_episode(science, move.stopping_condition, key=f"finish:{terminal.admission.record_id}")
        pending_choice = pending_selection(science, state)
        if pending_choice:
            return request_move(science, pending_choice)
        if not store.committed("science:intent:bootstrap"):
            science.commit("intent", {"research": context.run.initial_intent.model_dump(mode="json"), "inputs": context.run.inputs.model_dump(mode="json")}, key="bootstrap")
    newest = latest(science, "frame", "frame_reviewed")
    if newest is None:
        request = CapabilityRequest("frame")
        return _bootstrap(science, request, context.run.initial_intent) if context.policy.stage_aware else request
    if newest == "frame":
        return CapabilityRequest("await_review", store.artifact_ref("frame"))
    if latest(science, "foundation", "frame_reviewed") != "foundation":
        request = CapabilityRequest("ground", store.artifact_ref("frame_reviewed"))
        return _bootstrap(science, request, request.subject) if context.policy.stage_aware else request
    prepared = foundation_view(science)
    concerns = [c for c in prepared.facts["concerns"] if c["kind"] == "frame"]
    reframes = max(sum(name == "frame" for name, _ in science.commits()) - 1, 0)
    if concerns and reframes < context.resources.max_reframes:
        frame = reviewed_frame(science)
        lines = ["The data steward found that the data cannot represent the current frame:"]
        lines += [
            f"- {c['type']}: {c['description']} (evidence: {', '.join(c['evidence'])})"
            for c in concerns
        ]
        lines.append(
            "Revise the frame so the study stays answerable with this data: narrow the scope, "
            "reword questions or concepts, or state what is unmeasured."
        )
        lines.append(f"Current framing:\n{json.dumps(frame.framing, indent=2)}")
        request = CapabilityRequest("frame", prepared.source, guidance="\n".join(lines))
        return _bootstrap(science, request, prepared.source) if context.policy.stage_aware else request
    if store.committed("exploration") is None:
        request = CapabilityRequest("explore", prepared.source)
        return _bootstrap(science, request, prepared.source) if context.policy.stage_aware else request
    return discovery_step(h, science, context.resources, context.policy, context.options)


def discovery_step(
    h: Harness,
    science: ScienceStore,
    resources: RunResources,
    policy: StudyPolicy,
    options: ScientificOptions,
) -> CapabilityRequest | None:
    if policy.stage_aware:
        return _stage_decision(h, science, resources)
    if policy.adaptive and h.run.committed("science:intent:initial"):
        validate_intent_inputs(science, h.run.artifact_ref("science:intent:initial"))
    if policy.adaptive and (completed_study := h.run.committed("science:study")):
        output = StudyOutput.model_validate_json(completed_study.read_text("utf-8"))
        if (
            output.operational_status == "completed"
            and output.frontier == rebuild_state(science).frontier
            and output.frame == upstream(science, "frame_reviewed")
            and output.foundation == upstream(science, "foundation")
        ):
            if h.run.committed("study") != completed_study:
                h.run.commit_artifact("study", completed_study)
            return CapabilityRequest("publish", h.run.artifact_ref("study"))
    prepared = foundation_view(science)
    if not policy.adaptive:
        if h.run.committed("evidence"):
            build_study(
                science,
                "Historical analysis completed",
                adaptive=False,
                evidence=h.run.artifact_ref("evidence"),
            )
            return CapabilityRequest("publish", h.run.artifact_ref("study"))
        if not h.run.committed("robustness_plan"):
            schedule_context(h.config.search, options.robustness)
        if h.run.committed("hypothesis") is None:
            return CapabilityRequest("candidates", h.run.artifact_ref("exploration"), strategy="historical")
        hypothesis = h.run.artifact_ref("hypothesis")
        main = stage_outcome(science, "main")
        if main is None:
            return CapabilityRequest(
                "experiment", hypothesis, strategy="historical", implementation_only=True
            )
        plan_robustness(
            h,
            json.loads(resolve_artifact(h.run, hypothesis).read_text("utf-8"))[0],
            main,
            prepared.preparation,
        )
        return CapabilityRequest(
            "experiment",
            hypothesis,
            strategy="historical",
            schedule=h.run.artifact_ref("robustness_plan"),
        )
    preparation = preparation_manifest(science, prepared.preparation)
    if h.run.committed("science:intent:initial") is None:
        science.commit(
            "intent",
            {
                "frame": h.run.artifact_ref("frame_reviewed").model_dump(mode="json"),
                "foundation": h.run.artifact_ref("foundation").model_dump(mode="json"),
                "preparation": preparation.model_dump(mode="json"),
                "exploration": h.run.artifact_ref("exploration").model_dump(mode="json"),
            },
            key="initial",
        )
    try:
        if h.run.committed("science:candidates:initial") is None:
            return CapabilityRequest("candidates", h.run.artifact_ref("science:intent:initial"))
        candidates = h.run.artifact_ref("science:candidates:initial")
        while True:
            state = rebuild_state(science)
            if state.dispositions and state.dispositions[-1].ref == state.frontier[-1]:
                terminal = state.dispositions[-1].record
                if (
                    terminal.kind == "rejected"
                    and len(terminal.sources) == 1
                    and terminal.sources[0].producer == "science:snapshot"
                    and current_frontier(science, terminal.sources[0], state.frontier[:-1])
                ):
                    return _publication(science, terminal.reason)
                if (
                    terminal.kind == "deferred"
                    and len(terminal.sources) == 1
                    and terminal.sources[0].producer.startswith("science:proposals:")
                ):
                    proposal = science.read(terminal.sources[0])
                    if current_frontier(
                        science,
                        ArtifactRef.model_validate(proposal["snapshot"]),
                        state.frontier[:-1],
                    ):
                        return _publication(science, terminal.reason)
                if len(terminal.sources) == 1 and terminal.sources[0].producer.startswith(
                    "science:selection:"
                ):
                    move = selected_move(science, terminal.sources[0])
                    if (
                        (
                            terminal.kind == "deferred"
                            and state.dispositions[-1].ref.producer.startswith(
                                "science:disposition:admission:"
                            )
                        )
                        or (terminal.kind == "stopped" and move.action == "stop")
                        or (
                            terminal.kind == "deferred"
                            and move.action in {"pivot", "reframe", "acquisition"}
                        )
                    ) and current_frontier(science, move.snapshot, state.frontier[:-1]):
                        return _publication(science, terminal.reason)
            completed = {r.record.attempt.record_id for r in state.results}
            pending = next((a for a in state.attempts if a.ref.record_id not in completed), None)
            if pending:
                return CapabilityRequest("experiment", pending.ref)
            if not any(c.record.candidates == candidates for c in state.challenges):
                deferral = f"science:disposition:candidate_challenge:{candidates.record_id}"
                if h.run.committed(deferral):
                    disposition = Disposition.model_validate(science.read(h.run.artifact_ref(deferral)))
                    if candidates not in disposition.sources:
                        raise IntegrityError("challenge disposition cites a different subject")
                    return _publication(science, "Candidate challenge deferred; scientific feedback unavailable")
                snapshot = next((
                    ref for name, ref in reversed(science.commits())
                    if name == "science:snapshot"
                    and current_frontier(science, ref, state.frontier)
                    and any(c.ref == candidates for c in load_snapshot(science, ref).candidates)
                ), None)
                if snapshot is None:
                    snapshot = commit_snapshot(science, state)
                return CapabilityRequest("challenge", candidates, snapshot=snapshot)
            uninterpreted = next(
                (
                    r
                    for r in state.results
                    if not any(i.record.result == r.ref for i in state.interpretations)
                ),
                None,
            )
            if uninterpreted:
                if interpret_result(h, science, uninterpreted.ref) is None:
                    return _publication(
                        science, "Result interpretation deferred; scientific feedback unavailable"
                    )
                continue
            if h.spent_usd >= h.config.budget.max_usd:
                raise BudgetExceeded("discovery resource cap reached")
            if not resources.eligible_hypotheses:
                return _publication(
                    science,
                    "Scheduled move or revisit limit reached; no eligible candidate remains",
                )
            selection = pending_selection(science, state)
            if selection is None:
                pending_decision = pending_proposal(science, state)
                if pending_decision:
                    proposals, decision_snapshot = pending_decision
                else:
                    decision_snapshot = commit_snapshot(science, state)
                    proposals = propose_moves(h, science, decision_snapshot, resources)
                if h.spent_usd >= h.config.budget.max_usd:
                    raise BudgetExceeded("resource cap reached before move selection")
                try:
                    selection = select_move(h, science, decision_snapshot, proposals)
                except EligibilityError as exc:
                    science.commit(
                        "disposition",
                        Disposition(kind="deferred", reason=str(exc), sources=[proposals]),
                        key=f"decision:{proposals.record_id}",
                    )
                    return _publication(science, str(exc))
            move = selected_move(science, selection)
            if move.action == "stop":
                science.commit(
                    "disposition",
                    Disposition(
                        kind="stopped", reason=move.stopping_condition, sources=[selection]
                    ),
                    key=move.id,
                )
                return _publication(science, move.stopping_condition)
            if move.action in {"pivot", "reframe", "acquisition"}:
                science.commit(
                    "disposition",
                    Disposition(
                        kind="deferred",
                        reason=f"{move.action} is unavailable in this execution policy",
                        sources=[selection],
                        hypothesis_id=move.hypothesis_id,
                    ),
                    key=move.id,
                )
                return _publication(science, f"Selected {move.action} route deferred")
            if h.spent_usd >= h.config.budget.max_usd:
                raise BudgetExceeded("resource cap reached before scheduling selected move")
            assert move.test is not None
            return CapabilityRequest("experiment", move.test, selection=selection)
    except BudgetExceeded as exc:
        return _publication(science, str(exc), "budget_exceeded")


def unavailable(
    science: ScienceStore, request: CapabilityRequest, reason: str
) -> CapabilityRequest:
    """The current playbook records an unavailable selected move and concludes the episode."""
    assert request.selection is not None
    science.commit(
        "disposition",
        Disposition(
            kind="deferred", reason=reason, sources=[request.selection], resource="cap" in reason
        ),
        key=f"admission:{request.selection.record_id}",
    )
    return _publication(science, reason)


def finish_episode(
    science: ScienceStore, reason: str,
    status: Literal["completed", "failed", "budget_exceeded"] = "completed",
    *, key: str | None = None,
) -> CapabilityRequest:
    build_study(science, reason, status, key=key)
    return CapabilityRequest("finish", science.run.artifact_ref("study"), outcome=status)


def request_move(science: ScienceStore, selection: ArtifactRef) -> CapabilityRequest:
    move = selected_move(science, selection)
    if move.action in {"audit", "synthesize", "communicate", "stop"}:
        kind: Literal["audit", "synthesize", "publish", "finish"] = "publish" if move.action == "communicate" else "finish" if move.action == "stop" else move.action
        return CapabilityRequest(kind, move.snapshot, selection=selection, snapshot=move.snapshot)
    if move.action in {"frame", "ground", "explore", "candidates", "challenge"}:
        return CapabilityRequest(move.action, move.trigger_refs[0], selection=selection, snapshot=move.snapshot,
                                 guidance=move.objective if move.action == "frame" and "foundation" in move.trigger_refs[0].producer else "")
    if move.test is None:
        return CapabilityRequest("finish", move.snapshot, selection=selection, snapshot=move.snapshot)
    return CapabilityRequest("experiment", move.test, selection=selection, snapshot=move.snapshot)


def _bootstrap(science: ScienceStore, request: CapabilityRequest, source: ArtifactRef | None) -> CapabilityRequest:
    assert source is not None
    state = rebuild_state(science)
    snapshot = commit_snapshot(science, state)
    actions: dict[str, Action] = {"frame": "frame", "ground": "ground", "explore": "explore", "candidates": "candidates", "challenge": "challenge"}
    action = actions[request.kind]
    key = f"bootstrap:{request.kind}:{source.record_id}:{len(state.frontier)}"
    if science.run.committed(f"science:proposals:{key}"):
        original = science.read(science.run.artifact_ref(f"science:proposals:{key}"))
        snapshot = ArtifactRef.model_validate(original["snapshot"])
    move = ResearchMove(action=action, id=key, snapshot=snapshot, objective=request.guidance or f"Required {request.kind} prerequisite",
                        trigger_refs=[source], cost_usd=0, execution_effort=0, stopping_condition=f"Accepted {request.kind} output")
    proposals = science.commit("proposals", {"snapshot": snapshot.model_dump(mode="json"), "moves": [move.model_dump(mode="json")]}, key=key)
    selection = science.commit("selection", MoveSelection(proposal_id=move.id, snapshot=snapshot, proposals=proposals,
                                                         author="scientist:bootstrap", rationale=move.objective), key=key)
    return replace(request, selection=selection, snapshot=snapshot)


def _stage_decision(h: Harness, science: ScienceStore, resources: RunResources) -> CapabilityRequest:
    store = science.run
    state = rebuild_state(science)
    if state.pending_admissions:
        admission = state.pending_admissions[0]
        selection = next(r for r in admission.record.inputs if r.producer.startswith("science:selection:"))
        return replace(request_move(science, selection), admission=admission.ref)
    if store.committed("science:intent:initial") is None:
        prepared = foundation_view(science)
        preparation = preparation_manifest(science, prepared.preparation)
        science.commit("intent", {"frame": store.artifact_ref("frame_reviewed").model_dump(mode="json"), "foundation": prepared.source.model_dump(mode="json"),
                                  "preparation": preparation.model_dump(mode="json"), "exploration": store.artifact_ref("exploration").model_dump(mode="json")}, key="initial")
    if store.committed("science:candidates:initial") is None:
        return _bootstrap(science, CapabilityRequest("candidates", store.artifact_ref("science:intent:initial")), store.artifact_ref("science:intent:initial"))
    state = rebuild_state(science)
    candidates = store.artifact_ref("science:candidates:initial")
    if not any(c.record.candidates == candidates for c in state.challenges):
        if store.committed(f"science:disposition:candidate_challenge:{candidates.record_id}"):
            return finish_episode(science, "Candidate challenge deferred; scientific feedback unavailable")
        snapshot = commit_snapshot(science, state)
        return _bootstrap(science, CapabilityRequest("challenge", candidates, snapshot=snapshot), candidates)
    if state.dispositions and state.frontier and state.dispositions[-1].ref == state.frontier[-1]:
        disposition = state.dispositions[-1]
        if disposition.record.kind == "stopped":
            return finish_episode(science, disposition.record.reason, key=f"finish:{disposition.ref.record_id}")
        if disposition.record.resource and h.spent_usd >= h.config.budget.max_usd:
            return finish_episode(science, disposition.record.reason, "budget_exceeded", key=f"finish:{disposition.ref.record_id}")
    pending_choice = pending_selection(science, state)
    if pending_choice:
        return request_move(science, pending_choice)
    try:
        if h.spent_usd >= h.config.budget.max_usd:
            raise BudgetExceeded("resource cap reached before scientific decision")
        uninterpreted = next((r for r in state.results if not any(i.record.result == r.ref for i in state.interpretations)), None)
        if uninterpreted:
            if interpret_result(h, science, uninterpreted.ref) is None:
                return finish_episode(science, "Result interpretation deferred; scientific feedback unavailable")
            state = rebuild_state(science)
        pending = pending_proposal(science, state)
        if pending:
            proposals, snapshot = pending
        else:
            snapshot = commit_snapshot(science, state)
            proposals = propose_moves(h, science, snapshot, resources)
        if h.spent_usd >= h.config.budget.max_usd:
            raise BudgetExceeded("resource cap reached before move selection")
        selection = select_move(h, science, snapshot, proposals)
        return request_move(science, selection)
    except (BudgetExceeded, EligibilityError) as exc:
        return finish_episode(science, str(exc), "budget_exceeded" if isinstance(exc, BudgetExceeded) else "completed")
