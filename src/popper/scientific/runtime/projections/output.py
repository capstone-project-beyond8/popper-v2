"""Scientific publication transport derived from committed records."""

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from popper.harness.storage.records import ArtifactRef, IntegrityError, Record, resolve_artifact
from popper.harness.storage.recovery import load_state
from popper.harness.storage.store import file_hash
from popper.scientific.runtime.compatibility import decode_policy
from popper.scientific.runtime.evidence.outcomes import EvidenceAudit
from popper.scientific.runtime.evidence.references import MeasurementRef
from popper.scientific.runtime.lifecycle.contracts import MoveSelection, ResearchMove
from popper.scientific.runtime.lifecycle.transitions import selected_move
from popper.scientific.runtime.projections.state import (
    ResearchState,
    rebuild_state,
    validate_sources,
)
from popper.scientific.runtime.store import ScienceStore


class CandidateView(Record):
    id: str
    statement: str
    rationale: str
    source: ArtifactRef
    warnings: list[str]
    selected: bool
    attempted: bool


class MeasurementView(Record):
    ref: MeasurementRef
    role: str
    source: ArtifactRef
    fidelity: str
    fidelity_reason: str
    support: str
    interval_level: float | None
    active: bool


class StudyOutput(Record):
    version: Literal[1] = 1
    adaptive: bool
    frontier: list[ArtifactRef]
    frame: ArtifactRef | None = None
    foundation: ArtifactRef | None = None
    exploration: ArtifactRef | None = None
    preparation: ArtifactRef | None = None
    attempt_history: list[dict[str, Any]] = Field(default_factory=list)
    diagnoses: list[dict[str, Any]] = Field(default_factory=list)
    candidates: list[CandidateView] = Field(default_factory=list)
    attempts: list[ArtifactRef] = Field(default_factory=list)
    usable_measurements: list[MeasurementView] = Field(default_factory=list)
    measurement_history: list[MeasurementView] = Field(default_factory=list)
    coverage: list[dict[str, Any]] = Field(default_factory=list)
    sensitivity: list[dict[str, Any]] = Field(default_factory=list)
    dispositions: list[dict[str, Any]] = Field(default_factory=list)
    questions: list[dict[str, Any]] = Field(default_factory=list)
    challenges: list[dict[str, Any]] = Field(default_factory=list)
    interpretations: list[dict[str, Any]] = Field(default_factory=list)
    stale_interpretations: list[ArtifactRef] = Field(default_factory=list)
    selections: list[ArtifactRef] = Field(default_factory=list)
    syntheses: list[dict[str, Any]] = Field(default_factory=list)
    selection_history: list[dict[str, Any]] = Field(default_factory=list)
    stage_history: list[dict[str, Any]] | None = None
    pending_work: list[dict[str, Any]] | None = None
    sources: list[ArtifactRef] = Field(default_factory=list)
    audits: list[dict[str, Any]] = Field(default_factory=list)
    validation_standing: Literal["unavailable"] = "unavailable"
    stop_reason: str
    operational_status: Literal["completed", "failed", "budget_exceeded"]
    historical_evidence: ArtifactRef | None = None


def upstream(science: ScienceStore, name: str) -> ArtifactRef | None:
    return science.run.artifact_ref(name) if science.run.committed(name) else None


def episode_summary(science: ScienceStore, state: ResearchState | None = None) -> dict[str, Any]:
    """Read committed decisions and work without inventing historical stage records."""
    state = state if state is not None else rebuild_state(science)
    metadata = science.run.path("run.json")
    policy = decode_policy(json.loads(metadata.read_text("utf-8"))) if metadata.exists() else None
    stage_aware = policy is not None and policy.stage_aware
    idea_evolution = policy is not None and policy.idea_evolution
    decisions = []
    sources = list(state.frontier)
    audits = []
    for name, ref in science.commits():
        if name.startswith("science:selection:"):
            selection = MoveSelection.model_validate(science.read(ref))
            proposals = science.read(selection.proposals)
            validate_sources(science, proposals)
            moves = [ResearchMove.model_validate(move) for move in proposals["moves"]]
            selected = next(move for move in moves if move.id == selection.proposal_id)
            decisions.append({"ref": ref.model_dump(mode="json"),
                **selection.model_dump(mode="json"), "selected": selected.model_dump(mode="json"),
                "displaced": [move.model_dump(mode="json") for move in moves if move.id != selected.id]})
            sources.extend([ref, selection.snapshot, selection.proposals, *selected.trigger_refs])
        elif name.startswith("science:audit:"):
            audits.append({"ref": ref.model_dump(mode="json"),
                "record": EvidenceAudit.model_validate(science.read(ref)).model_dump(mode="json")})
    admissions = {item.ref: item for item in state.stage_admissions}
    for item in state.stage_admissions:
        sources.extend([item.ref, item.record.move, item.record.snapshot, *item.record.inputs])
    if idea_evolution:
        for revision in state.ideas:
            sources.extend([revision.ref, *revision.record.parents, *([revision.record.candidate] if revision.record.candidate else [])])
        sources.extend(item.ref for item in state.idea_challenges)
        sources.extend(item.ref for item in state.directions)
    checkpoint = load_state(science.run)
    stop_reason = None
    if study_ref := upstream(science, "study"):
        study = StudyOutput.model_validate(science.read(study_ref))
        if (study.frontier == state.frontier
            and checkpoint.get("status") == study.operational_status):
            stop_reason = study.stop_reason
    return {
        "stage_history": [{**item.model_dump(mode="json"),
            "work": admissions[item.record.admission].model_dump(mode="json")}
            for item in state.stage_history] if stage_aware else None,
        "pending_work": [item.model_dump(mode="json") for item in state.pending_admissions] if stage_aware else None,
        "ideas": [item.model_dump(mode="json") for item in state.ideas] if idea_evolution else None,
        "idea_challenges": [item.model_dump(mode="json") for item in state.idea_challenges] if idea_evolution else None,
        "directions": [item.model_dump(mode="json") for item in state.directions] if idea_evolution else None,
        "decisions": decisions,
        "sources": [ref.model_dump(mode="json") for ref in dict.fromkeys(sources)],
        "stop_reason": stop_reason,
        "operational_status": checkpoint.get("status", "unknown"),
        "questions": [item.model_dump(mode="json") for item in state.questions],
        "syntheses": [item.model_dump(mode="json") for item in state.syntheses],
        "audits": audits,
        "validation_standing": "unavailable",
    }


def build_study(
    science: ScienceStore,
    reason: str,
    status: Literal["completed", "failed", "budget_exceeded"] = "completed",
    *,
    adaptive: bool = True,
    evidence: ArtifactRef | None = None,
    key: str | None = None,
) -> Path:
    state = rebuild_state(science)
    summary = episode_summary(science, state)
    selections = [ref for name, ref in science.commits() if name.startswith("science:selection:")]
    attempted_ids = {a.record.hypothesis_id for a in state.attempts}
    selected_ids = {selected_move(science, ref).hypothesis_id for ref in selections}
    history = [
        MeasurementView(
            ref=m.record.ref,
            role=m.record.role,
            source=m.ref,
            fidelity=m.record.fidelity.status,
            fidelity_reason=m.record.fidelity.reason,
            support=m.record.support,
            interval_level=m.record.interval_level,
            active=m in state.observations,
        )
        for m in state.history
    ]
    study = StudyOutput(
        adaptive=adaptive,
        frontier=state.frontier,
        syntheses=summary["syntheses"],
        audits=summary["audits"],
        stage_history=summary["stage_history"],
        pending_work=summary["pending_work"],
        sources=summary["sources"],
        frame=upstream(science, "frame_reviewed"),
        foundation=upstream(science, "foundation"),
        exploration=upstream(science, "exploration"),
        preparation=upstream(science, "preparation"),
        attempt_history=[
            {
                "ref": a.ref.model_dump(mode="json"),
                "id": a.record.id,
                "hypothesis_id": a.record.hypothesis_id,
                "status": next(
                    (r.record.status for r in state.results if r.record.attempt == a.ref),
                    "incomplete",
                ),
            }
            for a in state.attempts
        ],
        diagnoses=[d.model_dump(mode="json") for d in state.diagnoses],
        candidates=[
            CandidateView(
                id=c.record.id,
                statement=c.record.statement,
                rationale=c.record.rationale,
                source=c.ref,
                warnings=c.record.warnings,
                selected=c.record.id in selected_ids,
                attempted=c.record.id in attempted_ids,
            )
            for c in state.candidates
        ],
        attempts=[a.ref for a in state.attempts],
        selections=selections,
        selection_history=summary["decisions"],
        usable_measurements=[m for m in history if m.active],
        measurement_history=history,
        coverage=[r.record.coverage for r in state.results],
        sensitivity=[r.record.sensitivity for r in state.results],
        dispositions=[d.model_dump(mode="json") for d in state.dispositions],
        questions=[q.model_dump(mode="json") for q in state.questions],
        challenges=[c.model_dump(mode="json") for c in state.challenges],
        interpretations=[i.model_dump(mode="json") for i in state.interpretations],
        stale_interpretations=state.stale_interpretations,
        stop_reason=reason,
        operational_status=status,
        historical_evidence=evidence,
    )
    ref = science.commit("study", study, key=key)
    # Public transport name is a pointer to the exact same immutable record.
    if science.run.committed("study") != resolve_artifact(science.run, ref):
        science.run.commit_artifact("study", resolve_artifact(science.run, ref))
    return resolve_artifact(science.run, ref)


def preparation_manifest(science: ScienceStore, preparation: Path) -> ArtifactRef:
    if science.run.committed("preparation"):
        return science.run.artifact_ref("preparation")
    files = {
        p.relative_to(science.run.root).as_posix(): file_hash(p)
        for p in preparation.rglob("*")
        if p.is_file()
    }
    path = science.run.write_json(
        "inputs/preparation.json",
        {
            "files": files,
            "mounts": {
                "data": {
                    "path": (preparation / "processed.parquet")
                    .relative_to(science.run.root)
                    .as_posix(),
                    "sha256": file_hash(preparation / "processed.parquet"),
                }
            },
            "foundation": science.run.artifact_ref("foundation").model_dump(mode="json"),
        },
    )
    science.run.commit_artifact("preparation", path)
    return science.run.artifact_ref("preparation")


def partial_study(
    science: ScienceStore, reason: str, status: Literal["failed", "budget_exceeded"]
) -> Path | None:
    metadata = json.loads(science.run.path("run.json").read_text("utf-8"))
    if not decode_policy(metadata).adaptive:
        return None
    return build_study(science, reason, status)


def publication_inputs(science: ScienceStore, source: ArtifactRef, kind: str) -> list[ArtifactRef]:
    manifest = science.read(source)
    files = manifest.get("files", {})
    if kind == "explore":
        roots = [
            Path(path).parent / "execution"
            for path in files
            if Path(path).name == "meta.json" and Path(path).parent.name == manifest["node"]
        ]
    elif kind == "data":
        mount = manifest.get("mounts", {}).get("data")
        roots = (
            [Path(mount["path"]).parent]
            if mount
            else [Path(path).parent for path in files if Path(path).name == "processed.parquet"]
        )
    else:
        raise ValueError("unknown publication input kind")
    if len(roots) != 1:
        raise IntegrityError("publication requires one accepted upstream execution")
    names = ("results.json", "changes.json") if kind == "data" else ("results.json",)
    return [
        ArtifactRef(
            path=path,
            sha256=files[path],
            producer=source.producer,
            record_id=source.record_id,
            backing=source,
        )
        for name in names
        for path in [(roots[0] / name).as_posix()]
        if path in files
    ]
