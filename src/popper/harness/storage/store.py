"""Write-once run directory."""

import hashlib
import json
import os
import secrets
import stat
import zlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from popper.harness.storage.records import ArtifactRef
from popper.harness.storage.recovery import Journal, read_events


def next_sequence(folder: Path, prefix: str = "", suffix: str = "") -> int:
    """One past the highest number in names `<prefix><digits><suffix>` under folder; 0 if none."""
    numbers = (
        p.name.removeprefix(prefix).removesuffix(suffix) for p in folder.glob(f"{prefix}*{suffix}")
    )
    return max((int(n) for n in numbers if n.isdigit()), default=-1) + 1


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key_path(run_id: str) -> Path:
    base = os.environ.get("POPPER_KEY_DIR")
    return (Path(base) if base else Path.home() / ".popper" / "keys") / f"{run_id}.key"


def _xor_stream(data: bytes, key: bytes) -> bytes:
    stream = hashlib.shake_256(key + b"popper-holdout").digest(len(data))
    return bytes(a ^ b for a, b in zip(data, stream, strict=True))


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    @contextmanager
    def lock(self) -> Iterator[None]:
        path = self.path("run.lock")
        try:
            with path.open("x", encoding="utf-8") as f:
                f.write(str(os.getpid()))
        except FileExistsError:
            pid = path.read_text("utf-8").strip()
            raise RuntimeError(
                f"run is in use by process {pid}; delete {path} if no process is running"
            ) from None
        try:
            yield
        finally:
            path.unlink(missing_ok=True)

    def write_text(self, rel: str, text: str) -> Path:
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as f:
            f.write(text)
        return target

    def write_json(self, rel: str, obj: object) -> Path:
        return self.write_text(rel, json.dumps(obj, indent=2, default=str))

    def checkpoint(self, state: Mapping[str, Any]) -> Path:
        sequence = next_sequence(self.path("state"), suffix=".json")
        commits = [e for e in read_events(self.root) if e["event"] == "state_commit"]
        rel = f"state/{sequence:06d}.json"
        path = self.write_json(
            rel,
            {
                **state,
                "previous": commits[-1]["path"] if commits else None,
            },
        )
        Journal(self.path("journal.jsonl")).write("state_commit", path=rel)
        return path

    def new_attempt(self, folder: str) -> Path:
        base = self.path(folder)
        sequence = next_sequence(base, prefix="attempt-")
        target = base / f"attempt-{sequence:06d}"
        target.mkdir(parents=True)
        return target

    def commit_artifact(self, name: str, path: Path) -> None:
        rel = path.resolve().relative_to(self.root).as_posix()
        Journal(self.path("journal.jsonl")).write(
            "artifact_commit",
            name=name,
            path=rel,
            sha256=file_hash(path),
            producer=name,
            record_id=f"artifact-{len(read_events(self.root)):06d}",
        )

    def artifact_ref(self, name: str) -> ArtifactRef:
        match = next(
            (
                (i, e)
                for i, e in reversed(list(enumerate(read_events(self.root))))
                if e["event"] == "artifact_commit" and e.get("name") == name
            ),
            None,
        )
        if match is None:
            raise ValueError(f"no reference-backed commit for {name!r}")
        index, event = match
        return ArtifactRef(
            path=event["path"],
            sha256=event["sha256"],
            producer=event.get("producer", name),
            record_id=event.get("record_id", f"historical-{index:06d}"),
        )

    def committed(self, name: str) -> Path | None:
        events = [
            e
            for e in read_events(self.root)
            if e["event"] == "artifact_commit" and e.get("name") == name
        ]
        if not events:
            return None
        event = events[-1]
        path = self.path(str(event["path"])).resolve()
        if not path.is_relative_to(self.root) or file_hash(path) != event["sha256"]:
            raise ValueError(f"committed {name} artifact was changed or escaped the run directory")
        return path

    def copy_once(self, source: Path, rel: str) -> Path:
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if file_hash(source) != file_hash(target):
                raise ValueError(f"existing export differs from its source: {rel}")
            return target
        # A hard link publishes a complete file atomically without overwriting an existing target.
        os.link(source, target)
        return target


def seal_bytes(path: Path, payload: bytes, *, key_id: str) -> None:
    key = secrets.token_bytes(32)
    key_file = key_path(key_id)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    with key_file.open("xb") as stream:
        stream.write(key)
    key_file.chmod(stat.S_IREAD | stat.S_IWRITE)
    path.write_bytes(_xor_stream(zlib.compress(payload), key))


def unseal_bytes(path: Path, *, key_id: str) -> bytes:
    key_file = key_path(key_id)
    if not key_file.is_file():
        raise FileNotFoundError(f"holdout key not found at {key_file}")
    return zlib.decompress(_xor_stream(path.read_bytes(), key_file.read_bytes()))
