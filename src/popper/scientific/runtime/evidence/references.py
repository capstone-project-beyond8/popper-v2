"""Exact scientific measurement identities and committed resolution."""

import json
from pathlib import Path

from popper.harness.storage.records import ArtifactRef, IntegrityError, Record, resolve_artifact
from popper.harness.storage.recovery import read_events
from popper.harness.storage.store import RunStore
from popper.scientific.runtime.evidence.results import ResultEntry


class MeasurementRef(Record):
    artifact: ArtifactRef
    result_key: str
    hypothesis_id: str
    test_id: str
    implementation_id: str
    execution_id: str


def resolve_measurement(store: RunStore, ref: MeasurementRef) -> ResultEntry:
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


def node_measurement(store: RunStore, meta_path: Path, result_key: str) -> MeasurementRef:
    from popper.harness.storage.store import file_hash

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
