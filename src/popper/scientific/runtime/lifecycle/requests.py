"""Typed scientific capability requests, independent of execution implementations."""

from dataclasses import dataclass
from typing import Literal

from popper.harness.storage.records import ArtifactRef


@dataclass(frozen=True)
class ExperimentRequest:
    test: ArtifactRef
    attempt: ArtifactRef
    admission: ArtifactRef | None = None


@dataclass(frozen=True)
class CapabilityRequest:
    kind: Literal["frame", "ground", "explore", "candidates", "challenge", "experiment", "publish", "audit", "synthesize", "evolve", "direct", "await_review", "finish"]
    subject: ArtifactRef | None = None
    selection: ArtifactRef | None = None
    guidance: str = ""
    snapshot: ArtifactRef | None = None
    admission: ArtifactRef | None = None
    outcome: Literal["completed", "failed", "budget_exceeded"] | None = None

    def __post_init__(self) -> None:
        if (
            self.kind in {"ground", "explore", "candidates", "challenge", "experiment", "publish", "audit", "synthesize", "evolve", "direct", "await_review", "finish"}
            and self.subject is None
        ):
            raise ValueError(f"{self.kind} requires a committed subject")
        if self.guidance and (self.kind != "frame" or self.subject is None):
            raise ValueError("framing guidance requires its foundation subject")
        if self.kind == "challenge" and self.snapshot is None:
            raise ValueError("challenge requires a committed snapshot")
        if self.snapshot is not None and self.kind not in {"challenge", "audit", "synthesize", "evolve", "direct"} and self.selection is None and self.admission is None:
            raise ValueError("snapshot requires a selected stage dispatch")
        if self.snapshot is not None and self.kind not in {"challenge", "audit", "synthesize", "evolve", "direct", "publish", "experiment", "frame", "ground", "explore", "candidates", "finish"}:
            raise ValueError("snapshot is not valid for this dispatch")
