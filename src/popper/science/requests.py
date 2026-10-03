"""Typed scientific capability requests, independent of execution implementations."""

from dataclasses import dataclass
from typing import Literal

from popper.harness.records import ArtifactRef


@dataclass(frozen=True)
class ExperimentRequest:
    test: ArtifactRef
    attempt: ArtifactRef


@dataclass(frozen=True)
class CapabilityRequest:
    kind: Literal["frame", "ground", "explore", "experiment", "publish", "await_review", "finish"]
    subject: ArtifactRef | None = None
    selection: ArtifactRef | None = None
    guidance: str = ""
    strategy: Literal["adaptive", "historical"] = "adaptive"
    schedule: ArtifactRef | None = None
    implementation_only: bool = False

    def __post_init__(self) -> None:
        if (
            self.kind in {"ground", "explore", "experiment", "publish", "await_review", "finish"}
            and self.subject is None
        ):
            raise ValueError(f"{self.kind} requires a committed subject")
        if self.guidance and (self.kind != "frame" or self.subject is None):
            raise ValueError("framing guidance requires its foundation subject")
        if self.selection and self.kind != "experiment":
            raise ValueError("selection is only valid for experiment dispatch")
