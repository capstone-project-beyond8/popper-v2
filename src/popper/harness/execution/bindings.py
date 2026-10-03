"""Opaque execution declarations supplied by an action's owner."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from popper.harness.storage.records import ArtifactRef, IntegrityError, resolve_artifact
from popper.harness.storage.store import RunStore, file_hash

_OWNED = {
    "id",
    "node",
    "stage",
    "parent",
    "kind",
    "debug_depth",
    "dir",
    "code",
    "status",
    "score",
    "goal_met",
    "analysis",
    "results",
    "figures",
    "reason",
    "attempt_id",
    "seed_node",
    "stage_instance",
    "test_ref",
    "implementation_id",
    "execution_id",
    "outputs",
    "fidelity",
    "check_observations",
}


@dataclass(frozen=True)
class ExecutionBinding:
    source: ArtifactRef | None
    expected_inputs: Mapping[str, str]
    metadata: Mapping[str, str]

    def validate(self, store: RunStore, inputs: Mapping[str, Path]) -> None:
        if _OWNED.intersection(self.metadata):
            raise IntegrityError("binding metadata overrides execution-owned identity")
        if self.source:
            resolve_artifact(store, self.source)
        for name, expected in self.expected_inputs.items():
            if name not in inputs or file_hash(inputs[name]) != expected:
                raise IntegrityError("mounted source differs from committed input binding")
