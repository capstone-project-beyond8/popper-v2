"""Scientific record persistence on the generic write-once store."""

import json
from typing import Any

from popper.harness.records import ArtifactRef, IntegrityError, Record, resolve_artifact
from popper.harness.recovery import read_events
from popper.harness.store import RunStore


class ScienceStore:
    def __init__(self, store: RunStore) -> None:
        self.run = store

    def read(self, ref: ArtifactRef) -> dict[str, Any]:
        payload = json.loads(resolve_artifact(self.run, ref).read_text("utf-8"))
        if not isinstance(payload, dict):
            raise IntegrityError("scientific record must be an object")
        return payload

    def commits(self) -> list[tuple[str, ArtifactRef]]:
        return [(str(e["name"]), ArtifactRef(path=e["path"], sha256=e["sha256"], producer=e.get("producer", e["name"]), record_id=e["record_id"])) for e in read_events(self.run.root) if e["event"] == "artifact_commit" and "record_id" in e]

    def commit(
        self, kind: str, record: Record | dict[str, Any], *, key: str | None = None
    ) -> ArtifactRef:
        name = f"science:{kind}" + (f":{key}" if key else "")
        data = record.model_dump(mode="json") if isinstance(record, Record) else record
        if key and self.run.committed(name):
            ref = self.run.artifact_ref(name)
            if json.loads(resolve_artifact(self.run, ref).read_text("utf-8")) != data:
                raise IntegrityError(f"conflicting scientific record for {name}")
            return ref
        folder = self.run.new_attempt(f"discover/{kind}")
        rel = folder.relative_to(self.run.root).as_posix()
        path = self.run.write_json(f"{rel}/{kind}.json", data)
        self.run.commit_artifact(name, path)
        return self.run.artifact_ref(name)
