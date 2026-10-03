"""Scientific publication transport derived from committed records."""

from typing import Any, Literal

from pydantic import Field

from popper.harness.records import ArtifactRef, Record
from popper.science.evidence import MeasurementRef


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


