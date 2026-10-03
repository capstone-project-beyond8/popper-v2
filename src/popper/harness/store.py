"""Write-once run directory."""

import hashlib
import io
import json
import math
import os
import secrets
import shutil
import stat
import zlib
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from popper.harness.config import Config, DataConfig, load_config
from popper.harness.records import ArtifactRef
from popper.harness.recovery import Journal, read_events
from popper.harness.research import ResearchError, check_columns, parse_research


def split_rows(data: pd.DataFrame, config: DataConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    if config.holdout_fraction == 0:
        return data.copy(), data.iloc[:0].copy()
    rng = np.random.default_rng(config.split_seed)
    if config.group_column is not None:
        column = config.group_column
        if column not in data:
            raise ValueError(f"group column {column!r} does not exist")
        if (data[column].isna() | (data[column].astype(str).str.strip() == "")).any():
            raise ValueError("group IDs cannot be missing")
        groups = data[column].drop_duplicates().to_numpy()
        selected = rng.permutation(groups)[: math.ceil(len(groups) * config.holdout_fraction)]
        mask = data[column].isin(selected).to_numpy()
    else:
        selected = rng.permutation(len(data))[: math.ceil(len(data) * config.holdout_fraction)]
        mask = np.zeros(len(data), dtype=bool)
        mask[selected] = True
    discovery, held = data.iloc[~mask].copy(), data.iloc[mask].copy()
    if discovery.empty or held.empty:
        raise ValueError("holdout split must leave nonempty discovery and holdout partitions")
    return discovery, held


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

    @classmethod
    def create(
        cls,
        runs_dir: Path,
        research: Path,
        data: Path,
        *,
        config: Config | None = None,
        auto: bool = False,
    ) -> "RunStore":
        snapshot = config or load_config(env={})
        split_config = snapshot.data
        frame = pd.read_csv(data, dtype=str, keep_default_na=False)
        mismatches = check_columns(
            parse_research(research.read_text("utf-8")), [str(c) for c in frame.columns]
        )
        if mismatches:
            raise ResearchError("; ".join(mismatches))
        discovery, held = split_rows(frame, split_config)
        run_id = f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        store = cls(runs_dir / run_id)
        store.root.mkdir(parents=True)
        shutil.copyfile(research, store.root / "research.md")
        (store.root / "data").mkdir()
        raw_path = store.path("data", "raw.csv")
        discovery.to_csv(raw_path, index=False, lineterminator="\n")
        plain = held.to_csv(index=False, lineterminator="\n").encode("utf-8")
        key = secrets.token_bytes(32)
        key_file = key_path(run_id)
        key_file.parent.mkdir(parents=True, exist_ok=True)
        with key_file.open("xb") as f:
            f.write(key)
        key_file.chmod(stat.S_IREAD | stat.S_IWRITE)
        sealed_path = store.path("data", "holdout.sealed")
        sealed_path.write_bytes(_xor_stream(zlib.compress(plain), key))
        for path in (raw_path, sealed_path):
            path.chmod(stat.S_IREAD)
        store.write_json(
            "data/split.json",
            {
                **split_config.model_dump(),
                "discovery_rows": len(discovery),
                "holdout_rows": len(held),
                "verification_eligible": not held.empty,
                "discovery_hash": file_hash(store.path("data", "raw.csv")),
                "holdout_hash": hashlib.sha256(plain).hexdigest(),
            },
        )
        config_data = snapshot.model_dump(mode="json")
        config_data["data"] = split_config.model_dump()
        store.write_json(
            "run.json",
            {
                "format_version": 5,
                "status": "running",
                "auto": auto,
                "config": config_data,
                "inputs": {"research": str(research.resolve()), "data": str(data.resolve())},
                "source_hash": file_hash(data),
                "research_hash": file_hash(research),
            },
        )
        manifest = store.write_json(
            "inputs/manifest.json",
            {
                "files": {
                    rel: file_hash(store.path(rel))
                    for rel in ("research.md", "data/raw.csv", "data/split.json")
                },
            },
        )
        store.commit_artifact("inputs", manifest)
        return store

    def read_holdout(self) -> pd.DataFrame:
        """Unseal the held-back rows with the run key kept outside the run directory."""
        key_file = key_path(self.root.name)
        if not key_file.is_file():
            raise FileNotFoundError(f"holdout key not found at {key_file}")
        sealed = self.path("data", "holdout.sealed").read_bytes()
        plain = zlib.decompress(_xor_stream(sealed, key_file.read_bytes()))
        expected = json.loads(self.path("data", "split.json").read_text("utf-8"))["holdout_hash"]
        if hashlib.sha256(plain).hexdigest() != expected:
            raise ValueError("holdout rows do not match the recorded hash")
        return pd.read_csv(io.BytesIO(plain), dtype=str, keep_default_na=False)

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
