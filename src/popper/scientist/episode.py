"""Scientific reasoning and the current bounded research playbook."""

import json
from dataclasses import dataclass
from typing import Literal

from popper.harness.records import ArtifactRef, resolve_artifact
from popper.harness.session import BudgetExceeded, Harness
from popper.science.compatibility import StudyPolicy, decode_policy
from popper.science.contracts import Disposition, MoveSelection, Program, Run, RunResources
from popper.science.descriptive import read_table
from popper.science.historical import schedule_context
from popper.science.output import StudyOutput, build_study, preparation_manifest, upstream
from popper.science.requests import CapabilityRequest
from popper.science.settings import ScientificOptions, load_options
from popper.science.state import commit_snapshot, load_snapshot, rebuild_state
from popper.science.store import ScienceStore
from popper.science.transitions import EligibilityError, selected_move
from popper.science.views import (
    exploration_view,
    foundation_view,
    latest,
    reviewed_frame,
    stage_outcome,
)
from popper.scientist.candidates import CandidateContext, generate_candidates, propose_hypothesis
from popper.scientist.feedback import challenge_candidates, interpret_result
from popper.scientist.historical import plan_robustness
from popper.scientist.moves import propose_moves, select_move


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
    newest = latest(science, "frame", "frame_reviewed")
    if newest is None:
        return CapabilityRequest("frame")
    if newest == "frame":
        return CapabilityRequest("await_review", store.artifact_ref("frame"))
    if latest(science, "foundation", "frame_reviewed") != "foundation":
        return CapabilityRequest("ground", store.artifact_ref("frame_reviewed"))
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
        return CapabilityRequest("frame", prepared.source, guidance="\n".join(lines))
    if store.committed("exploration") is None:
        return CapabilityRequest("explore", prepared.source)
    return discovery_step(h, science, context.resources)


def _current_frontier(
    science: ScienceStore, snapshot: ArtifactRef, frontier: list[ArtifactRef]
) -> bool:
    recorded = load_snapshot(science, snapshot)
    return recorded.frontier == frontier


def discovery_step(
    h: Harness, science: ScienceStore, resources: RunResources
) -> CapabilityRequest | None:
    policy = decode_policy(json.loads(science.run.path("run.json").read_text("utf-8")))
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
    reviewed = reviewed_frame(science)
    prepared = foundation_view(science)
    framing, facts = reviewed.framing, prepared.facts
    raw_columns = list(read_table(h.run.path("data", "raw.csv")).columns)
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
            schedule_context(h.config.search, load_options(h.run).robustness)
        propose_hypothesis(
            h,
            science,
            CandidateContext(
                reviewed.research, framing, facts, exploration_view(science), raw_columns
            ),
        )
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
            generate_candidates(
                h,
                science,
                CandidateContext(
                    reviewed.research, framing, facts, exploration_view(science), raw_columns
                ),
                policy,
            )
            return None
        candidates = h.run.artifact_ref("science:candidates:initial")
        while True:
            state = rebuild_state(science)
            if state.dispositions and state.dispositions[-1].ref == state.frontier[-1]:
                terminal = state.dispositions[-1].record
                if (
                    terminal.kind == "rejected"
                    and len(terminal.sources) == 1
                    and terminal.sources[0].producer == "science:snapshot"
                    and _current_frontier(science, terminal.sources[0], state.frontier[:-1])
                ):
                    return _publication(science, terminal.reason)
                if len(terminal.sources) == 1 and terminal.sources[0].producer.startswith(
                    "science:selection:"
                ):
                    move = selected_move(science, terminal.sources[0])
                    if (
                        (terminal.kind == "stopped" and move.action == "stop")
                        or (
                            terminal.kind == "deferred"
                            and move.action in {"pivot", "reframe", "acquisition"}
                        )
                    ) and _current_frontier(science, move.snapshot, state.frontier[:-1]):
                        return _publication(science, terminal.reason)
            completed = {r.record.attempt.record_id for r in state.results}
            pending = next((a for a in state.attempts if a.ref.record_id not in completed), None)
            if pending:
                return CapabilityRequest("experiment", pending.ref)
            if not any(c.record.candidates == candidates for c in state.challenges):
                if challenge_candidates(h, science, candidates) is None:
                    return _publication(
                        science, "Candidate challenge deferred; scientific feedback unavailable"
                    )
                continue
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
            selections = [
                ref for name, ref in science.commits() if name.startswith("science:selection:")
            ]
            used = {a.record.move_id for a in state.attempts}
            selection = next(
                (
                    ref
                    for ref in reversed(selections)
                    if MoveSelection.model_validate_json(
                        resolve_artifact(h.run, ref).read_text("utf-8")
                    ).proposal_id
                    not in used
                    and _current_frontier(
                        science,
                        MoveSelection.model_validate_json(
                            resolve_artifact(h.run, ref).read_text("utf-8")
                        ).snapshot,
                        state.frontier,
                    )
                ),
                None,
            )
            if selection is None:
                proposal_records = [
                    (name, ref)
                    for name, ref in science.commits()
                    if name.startswith("science:proposals:")
                ]
                pending_proposal = next(
                    (
                        ref
                        for _, ref in reversed(proposal_records)
                        if not any(
                            MoveSelection.model_validate_json(
                                resolve_artifact(h.run, s).read_text("utf-8")
                            ).proposals
                            == ref
                            for s in selections
                        )
                        and _current_frontier(
                            science,
                            ArtifactRef.model_validate(
                                json.loads(resolve_artifact(h.run, ref).read_text("utf-8"))[
                                    "snapshot"
                                ]
                            ),
                            state.frontier,
                        )
                    ),
                    None,
                )
                if pending_proposal:
                    data = json.loads(resolve_artifact(h.run, pending_proposal).read_text("utf-8"))
                    snapshot = ArtifactRef.model_validate(data["snapshot"])
                    proposals = pending_proposal
                else:
                    snapshot = commit_snapshot(science, state)
                    proposals = propose_moves(h, science, snapshot, resources)
                if h.spent_usd >= h.config.budget.max_usd:
                    raise BudgetExceeded("resource cap reached before move selection")
                selection = select_move(h, science, snapshot, proposals)
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
    except EligibilityError as exc:
        science.commit(
            "disposition",
            Disposition(kind="deferred", reason=str(exc), sources=[], resource="cap" in str(exc)),
        )
        return _publication(science, str(exc))
