"""Scientific publication transport derived from committed records."""

from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from popper.harness.records import ArtifactRef, Record, resolve_artifact
from popper.harness.store import file_hash
from popper.science.contracts import MoveSelection
from popper.science.evidence import MeasurementRef
from popper.science.state import rebuild_state
from popper.science.store import ScienceStore
from popper.science.transitions import selected_move


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
    selection_history: list[dict[str, Any]] = Field(default_factory=list)
    stop_reason: str
    operational_status: Literal["completed", "failed", "budget_exceeded"]
    historical_evidence: ArtifactRef | None = None




def upstream(science: ScienceStore, name: str) -> ArtifactRef | None:
    return science.run.artifact_ref(name) if science.run.committed(name) else None


def build_study(
    science: ScienceStore,
    reason: str,
    status: Literal["completed", "failed", "budget_exceeded"] = "completed",
    *,
    adaptive: bool = True,
    evidence: ArtifactRef | None = None,
) -> Path:
    state = rebuild_state(science)
    selections = [
        ref for name, ref in science.commits() if name.startswith("science:selection:")
    ]
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
        selection_history=[
            {
                "ref": ref.model_dump(mode="json"),
                **MoveSelection.model_validate_json(
                    resolve_artifact(science.run, ref).read_text("utf-8")
                ).model_dump(mode="json"),
            }
            for ref in selections
        ],
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
    ref = science.commit("study", study)
    # Public transport name is a pointer to the exact same immutable record.
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
                    "path": (preparation / "processed.parquet").relative_to(science.run.root).as_posix(),
                    "sha256": file_hash(preparation / "processed.parquet"),
                }
            },
            "foundation": science.run.artifact_ref("foundation").model_dump(mode="json"),
        },
    )
    science.run.commit_artifact("preparation", path)
    return science.run.artifact_ref("preparation")


