import json
from pathlib import Path

import pytest

from popper.harness.records import (
    ArtifactRef,
    MeasurementRef,
    resolve_artifact,
    resolve_measurement,
)
from popper.harness.recovery import Journal
from popper.harness.store import RunStore, file_hash


def test_exact_commit_history_and_uncommitted_rejection(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    old = store.write_json("first.json", {"value": 1})
    store.commit_artifact("sample", old)
    ref = store.artifact_ref("sample")
    store.commit_artifact("sample", store.write_json("second.json", {"value": 2}))
    assert resolve_artifact(store, ref) == old
    scratch = store.write_text("scratch/results.json", "{}")
    forged = ref.model_copy(update={"path": "scratch/results.json", "sha256": file_hash(scratch)})
    with pytest.raises(ValueError, match="committed"):
        resolve_artifact(store, forged)
    old.write_text("changed")
    with pytest.raises(ValueError, match="hash"):
        resolve_artifact(store, ref)


@pytest.mark.parametrize("path", ["../out.json", "C:/out.json", "/out.json", "data/holdout.sealed"])
def test_reference_rejects_unsafe_paths(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError):
        resolve_artifact(RunStore(tmp_path), ArtifactRef(path=path, sha256="a"*64, producer="input", record_id="r1"))


def test_symlink_reference_cannot_escape_committed_root(tmp_path: Path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    link = root / "linked.json"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("operating system denies symlink creation")
    with pytest.raises(ValueError, match="escaped"):
        resolve_artifact(RunStore(root), ArtifactRef(path="linked.json", sha256=file_hash(outside), producer="source", record_id="r1"))


def test_measurement_requires_exact_accepted_node(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    result = store.write_json("tree/scoped/node/execution/results.json", {"estimate": {"value": 2.0, "ci": [1, 3]}})
    meta = store.write_json("tree/scoped/node/meta.json", {
        "status": "ok", "hypothesis_id": "h1", "test_id": "t1",
        "implementation_id": "i1", "execution_id": "exec-1",
        "outputs": {result.relative_to(tmp_path).as_posix(): file_hash(result)},
    })
    Journal(tmp_path / "journal.jsonl").write("node_commit", node="node", path=meta.relative_to(tmp_path).as_posix(), sha256=file_hash(meta), record_id="node-1")
    backing = ArtifactRef(path=meta.relative_to(tmp_path).as_posix(), sha256=file_hash(meta), producer="node", record_id="node-1")
    ref = MeasurementRef(artifact=ArtifactRef(path=result.relative_to(tmp_path).as_posix(), sha256=file_hash(result), producer="node", record_id="node-1", backing=backing), result_key="estimate", hypothesis_id="h1", test_id="t1", implementation_id="i1", execution_id="exec-1")
    assert resolve_measurement(store, ref).value == 2.0
    for updates in ({"test_id": "foreign"}, {"result_key": "absent"}, {"execution_id": "scratch"}):
        with pytest.raises(ValueError):
            resolve_measurement(store, ref.model_copy(update=updates))
    metadata = json.loads(meta.read_text())
    metadata["status"] = "buggy"
    meta.write_text(json.dumps(metadata))
    with pytest.raises(ValueError):
        resolve_measurement(store, ref)


def test_independently_encoded_historical_artifact_reference(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    source = store.write_json("old.json", {"statement": "historical"})
    store.write_text("journal.jsonl", json.dumps({"event": "artifact_commit", "name": "hypothesis", "path": "old.json", "sha256": file_hash(source)}) + "\n")
    before = source.read_bytes()
    assert resolve_artifact(store, store.artifact_ref("hypothesis")) == source
    assert source.read_bytes() == before
