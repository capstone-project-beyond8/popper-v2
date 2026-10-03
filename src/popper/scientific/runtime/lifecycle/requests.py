"""Typed scientific capability requests, independent of execution implementations."""

from dataclasses import dataclass
from typing import Literal

from popper.harness.storage.records import ArtifactRef


@dataclass(frozen=True)
class ExperimentRequest:
    test: ArtifactRef
    attempt: ArtifactRef


@dataclass(frozen=True)
class CapabilityRequest:
    kind: Literal["frame", "ground", "explore", "candidates", "challenge", "experiment", "publish", "await_review", "finish"]
    subject: ArtifactRef | None = None
    selection: ArtifactRef | None = None
    guidance: str = ""
    strategy: Literal["adaptive", "historical"] = "adaptive"
    schedule: ArtifactRef | None = None
    implementation_only: bool = False
    snapshot: ArtifactRef | None = None

    def __post_init__(self) -> None:
        if (
            self.kind in {"ground", "explore", "candidates", "challenge", "experiment", "publish", "await_review", "finish"}
            and self.subject is None
        ):
            raise ValueError(f"{self.kind} requires a committed subject")
        if self.guidance and (self.kind != "frame" or self.subject is None):
            raise ValueError("framing guidance requires its foundation subject")
        if self.selection and self.kind != "experiment":
            raise ValueError("selection is only valid for experiment dispatch")
        if self.kind == "challenge" and self.snapshot is None:
            raise ValueError("challenge requires a committed snapshot")
        if self.snapshot is not None and self.kind != "challenge":
            raise ValueError("snapshot is only valid for challenge dispatch")
