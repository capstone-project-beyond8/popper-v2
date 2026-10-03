"""Immutable, run-confined references backed by exact journal commits."""

import json
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from popper.harness.recovery import read_events

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




def reachable_refs(store: "RunStore", source: ArtifactRef) -> list[ArtifactRef]:
    found: dict[str, ArtifactRef] = {}

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if {"path", "sha256", "producer", "record_id"} <= value.keys():
                ref = ArtifactRef.model_validate(value)
                if ref.path in found:
                    return
                path = resolve_artifact(store, ref)
                found[ref.path] = ref
                if path.suffix == ".json":
                    visit(json.loads(path.read_text("utf-8")))
            else:
                for item in value.values():
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(source.model_dump(mode="json"))
    return list(found.values())


