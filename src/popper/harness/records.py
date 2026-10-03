"""Immutable, run-confined references backed by exact journal commits."""

import json
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from popper.harness.recovery import read_events
from popper.harness.results import ResultEntry

if TYPE_CHECKING:
    from popper.harness.store import RunStore


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactRef(Record):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    producer: str = Field(min_length=1)
    record_id: str = Field(min_length=1)
    backing: "ArtifactRef | None" = None


class MeasurementRef(Record):
    artifact: ArtifactRef
    result_key: str
    hypothesis_id: str
    test_id: str
    implementation_id: str
    execution_id: str


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


class IntegrityError(ValueError):
    """Reference, access or hash failure; never eligible for model override."""


def resolve_artifact(store: "RunStore", ref: ArtifactRef) -> Path:
    from popper.harness.store import file_hash

    relative = Path(ref.path)
    if relative.is_absolute() or PureWindowsPath(ref.path).drive or ".." in relative.parts:
        raise IntegrityError("unsafe artifact path")
    path = store.path(ref.path).resolve()
    if not path.is_relative_to(store.root) or path.name in {"holdout.sealed", "run.lock"}:
        raise IntegrityError("artifact escaped or is private")
    if not path.is_file() or file_hash(path) != ref.sha256:
        raise IntegrityError("artifact hash mismatch or missing file")
    if ref.backing is not None:
        backing = resolve_artifact(store, ref.backing)
        manifest = json.loads(backing.read_text("utf-8"))
        files = manifest.get("files", manifest.get("outputs", {}))
        if files.get(ref.path) != ref.sha256 or (
            ref.producer != ref.backing.producer or ref.record_id != ref.backing.record_id
        ):
            raise IntegrityError("artifact has no exact committed manifest backing")
    else:
        matches = [
            e
            for index, e in enumerate(read_events(store.root))
            if e["event"] in {"artifact_commit", "node_commit"}
            and e.get("path") == ref.path
            and e.get("sha256") == ref.sha256
            and e.get("record_id", f"historical-{index:06d}") == ref.record_id
            and e.get("producer", e.get("name", "node")) == ref.producer
        ]
        if not matches:
            raise IntegrityError("artifact has no exact committed producer backing")
    return path


def resolve_measurement(store: "RunStore", ref: MeasurementRef) -> ResultEntry:
    path = resolve_artifact(store, ref.artifact)
    backing = ref.artifact.backing
    if backing is None or backing.producer != "node":
        raise IntegrityError("measurement requires an accepted node commit")
    meta = json.loads(resolve_artifact(store, backing).read_text("utf-8"))
    if meta.get("status") != "ok":
        raise IntegrityError("measurement node is not accepted")
    for field in ("hypothesis_id", "test_id", "implementation_id", "execution_id"):
        if meta.get(field) != getattr(ref, field):
            raise IntegrityError(f"measurement {field} mismatch")
    if meta.get("test_ref"):
        test = json.loads(
            resolve_artifact(store, ArtifactRef.model_validate(meta["test_ref"])).read_text("utf-8")
        )
        if test["id"] != ref.test_id or test["hypothesis_id"] != ref.hypothesis_id:
            raise IntegrityError("measurement does not belong to its committed test")
    results = json.loads(path.read_text("utf-8"))
    if ref.result_key not in results:
        raise IntegrityError("missing named measurement key")
    return ResultEntry.model_validate_json(json.dumps(results[ref.result_key]))


def node_measurement(store: "RunStore", meta_path: Path, result_key: str) -> MeasurementRef:
    from popper.harness.store import file_hash

    rel = meta_path.relative_to(store.root).as_posix()
    event = next(
        e
        for e in reversed(read_events(store.root))
        if e["event"] == "node_commit" and e.get("path") == rel
    )
    meta = json.loads(meta_path.read_text("utf-8"))
    backing = ArtifactRef(
        path=rel, sha256=event["sha256"], producer="node", record_id=event["record_id"]
    )
    result = meta_path.parent / "execution" / "results.json"
    ref = MeasurementRef(
        artifact=ArtifactRef(
            path=result.relative_to(store.root).as_posix(),
            sha256=file_hash(result),
            producer="node",
            record_id=backing.record_id,
            backing=backing,
        ),
        result_key=result_key,
        **{
            key: meta[key]
            for key in ("hypothesis_id", "test_id", "implementation_id", "execution_id")
        },
    )
    resolve_measurement(store, ref)
    return ref
