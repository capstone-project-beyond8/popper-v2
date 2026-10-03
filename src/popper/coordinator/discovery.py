"""One sequential scheduler over Discover-owned scientific decisions."""

import json
from pathlib import Path

from popper.discover.experiment import ExperimentRequest, experiment
from popper.discover.explore import generate_candidates, propose_hypothesis
from popper.discover.feedback import challenge_candidates, interpret_result
from popper.discover.policy import (
    EligibilityError,
    eligible_candidates,
    make_attempt,
    propose_moves,
    select_move,
)
from popper.ground.steward import load_foundation
from popper.harness.descriptive import read_table
from popper.harness.records import ArtifactRef, resolve_artifact
from popper.harness.research import render_fields
from popper.harness.session import BudgetExceeded, Harness
from popper.harness.store import file_hash
from popper.science.compatibility import decode_policy
from popper.science.contracts import Disposition, MoveSelection
from popper.science.output import StudyOutput, build_study, preparation_manifest, upstream
from popper.science.state import commit_snapshot, load_snapshot, rebuild_state
from popper.science.store import ScienceStore
from popper.science.transitions import selected_move
from popper.treesearch.engine import Node
from popper.understand.frame import load_frame


def _current_frontier(h: Harness, snapshot: ArtifactRef, frontier: list[ArtifactRef]) -> bool:
    recorded = load_snapshot(ScienceStore(h.run), snapshot)
    return recorded.frontier == frontier


def advance_discovery(h: Harness, *, frame: Path, foundation: Path, exploration: Node) -> Path:
    metadata = json.loads(h.run.path("run.json").read_text("utf-8"))
    policy = decode_policy(metadata)
    if policy.adaptive and (completed_study := h.run.committed("science:study")):
        output = StudyOutput.model_validate_json(completed_study.read_text("utf-8"))
        if (
            output.operational_status == "completed"
            and output.frontier == rebuild_state(ScienceStore(h.run)).frontier
            and output.frame == upstream(ScienceStore(h.run), "frame_reviewed")
            and output.foundation == upstream(ScienceStore(h.run), "foundation")
        ):
            if h.run.committed("study") != completed_study:
                h.run.commit_artifact("study", completed_study)
            return completed_study
    reviewed = load_frame(frame)
    prepared = load_foundation(h)
    assert prepared is not None
    framing = reviewed.framing.model_dump()
    facts = prepared.as_dict()
    raw_columns = list(read_table(h.run.path("data", "raw.csv")).columns)
    if not policy.adaptive:
        hypothesis = propose_hypothesis(
            h, reviewed.research, framing, facts, exploration, raw_columns
        )
        path = experiment(
            h,
            framing,
            hypothesis,
            prepared.preparation,
            reviewed.research.notes.get("experiment", ""),
            render_fields(reviewed.research, "design"),
        )
        return build_study(
            ScienceStore(h.run),
            "Historical analysis completed",
            adaptive=False,
            evidence=h.run.artifact_ref("evidence"),
        )
    if h.run.committed("exploration") is None:
        path = h.run.write_json(
            "inputs/exploration.json",
            {
                "files": {
                    p.relative_to(h.run.root).as_posix(): file_hash(p)
                    for p in exploration.dir.rglob("*")
                    if p.is_file()
                },
                "node": exploration.id,
            },
        )
        h.run.commit_artifact("exploration", path)
    preparation = preparation_manifest(ScienceStore(h.run), prepared.preparation)
    if h.run.committed("science:intent:initial") is None:
        ScienceStore(h.run).commit("intent",
            {
                "frame": h.run.artifact_ref("frame_reviewed").model_dump(mode="json"),
                "foundation": h.run.artifact_ref("foundation").model_dump(mode="json"),
                "preparation": preparation.model_dump(mode="json"),
                "exploration": h.run.artifact_ref("exploration").model_dump(mode="json"),
            },
            key="initial",
        )
    try:
        candidates = generate_candidates(
            h, reviewed.research, framing, facts, exploration, raw_columns, policy
        )
        while True:
            state = rebuild_state(ScienceStore(h.run))
            if state.dispositions and state.dispositions[-1].ref == state.frontier[-1]:
                terminal = state.dispositions[-1].record
                if (
                    len(terminal.sources) == 1
                    and terminal.sources[0].producer.startswith("science:selection:")
                ):
                    move = selected_move(ScienceStore(h.run), terminal.sources[0])
                    if (
                        (terminal.kind == "stopped" and move.action == "stop")
                        or (terminal.kind == "deferred" and move.action in {"pivot", "reframe", "acquisition"})
                    ) and _current_frontier(h, move.snapshot, state.frontier[:-1]):
                        return build_study(ScienceStore(h.run), terminal.reason)
            completed = {r.record.attempt.record_id for r in state.results}
            pending = next((a for a in state.attempts if a.ref.record_id not in completed), None)
            if pending:
                candidate = next(
                    c.record
                    for c in state.candidates
                    if c.record.id == pending.record.hypothesis_id
                )
                experiment(
                    h,
                    framing,
                    candidate.model_dump(mode="json"),
                    prepared.preparation,
                    reviewed.research.notes.get("experiment", ""),
                    render_fields(reviewed.research, "design"),
                    request=ExperimentRequest(pending.record.test, pending.ref),
                )
                continue
            if not any(c.record.candidates == candidates for c in state.challenges):
                if challenge_candidates(h, candidates) is None:
                    return build_study(ScienceStore(h.run), "Candidate challenge deferred; scientific feedback unavailable")
                continue
            uninterpreted = next(
                (r for r in state.results if not any(i.record.result == r.ref for i in state.interpretations)),
                None,
            )
            if uninterpreted:
                if interpret_result(h, uninterpreted.ref) is None:
                    return build_study(ScienceStore(h.run), "Result interpretation deferred; scientific feedback unavailable")
                continue
            if h.spent_usd >= h.config.budget.max_usd:
                raise BudgetExceeded("discovery resource cap reached")
            if not eligible_candidates(state, h.config.discovery):
                return build_study(
                    ScienceStore(h.run), "Scheduled move or revisit limit reached; no eligible candidate remains"
                )
            selections = [
                ref for name, ref in ScienceStore(h.run).commits() if name.startswith("science:selection:")
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
                        h,
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
                    for name, ref in ScienceStore(h.run).commits()
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
                            h,
                            ArtifactRef.model_validate(
                                json.loads(resolve_artifact(h.run, ref).read_text("utf-8"))["snapshot"]
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
                    snapshot = commit_snapshot(ScienceStore(h.run), state)
                    proposals = propose_moves(h, snapshot)
                if h.spent_usd >= h.config.budget.max_usd:
                    raise BudgetExceeded("resource cap reached before move selection")
                selection = select_move(h, snapshot, proposals)
            move = selected_move(ScienceStore(h.run), selection)
            if move.action == "stop":
                ScienceStore(h.run).commit("disposition",
                    Disposition(
                        kind="stopped", reason=move.stopping_condition, sources=[selection]
                    ),
                    key=move.id,
                )
                return build_study(ScienceStore(h.run), move.stopping_condition)
            if move.action in {"pivot", "reframe", "acquisition"}:
                ScienceStore(h.run).commit("disposition",
                    Disposition(
                        kind="deferred",
                        reason=f"{move.action} is unavailable in this execution policy",
                        sources=[selection],
                        hypothesis_id=move.hypothesis_id,
                    ),
                    key=move.id,
                )
                return build_study(ScienceStore(h.run), f"Selected {move.action} route deferred")
            if h.spent_usd >= h.config.budget.max_usd:
                raise BudgetExceeded("resource cap reached before scheduling selected move")
            parent = next(
                (
                    a.ref
                    for a in reversed(state.attempts)
                    if a.record.hypothesis_id == move.hypothesis_id
                ),
                None,
            )
            make_attempt(h, move, parent)
    except BudgetExceeded as exc:
        return build_study(ScienceStore(h.run), str(exc), "budget_exceeded")
    except EligibilityError as exc:
        ScienceStore(h.run).commit("disposition",
            Disposition(kind="deferred", reason=str(exc), sources=[], resource="cap" in str(exc)),
        )
        return build_study(ScienceStore(h.run), str(exc))
