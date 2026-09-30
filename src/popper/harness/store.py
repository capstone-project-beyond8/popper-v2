"""Write-once run directory."""

import hashlib
import json
import math
import secrets
import shutil
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from popper.harness.config import Config, DataConfig, load_config
from popper.harness.recovery import Journal, read_events


def split_rows(data: pd.DataFrame, config: DataConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    if config.holdout_fraction == 0:
        return data.copy(), data.iloc[:0].copy()
    rng = np.random.default_rng(config.split_seed)
    if config.group_column is not None:
        column = config.group_column
        if column not in data:
            raise ValueError(f"group column {column!r} does not exist")
        if data[column].isna().any():
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


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RunStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def create(
        cls, runs_dir: Path, brief: Path, data: Path, *, data_config: DataConfig | None = None,
        config: Config | None = None,
    ) -> "RunStore":
        snapshot = config or load_config(env={})
        split_config = data_config or snapshot.data
        discovery, held = split_rows(pd.read_csv(data), split_config)
        run_id = f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        store = cls(runs_dir / run_id)
        store.root.mkdir(parents=True)
        shutil.copyfile(brief, store.root / "brief.md")
        (store.root / "data").mkdir()
        for name, rows in (("raw.csv", discovery), ("holdout.csv", held)):
            path = store.path("data", name)
            rows.to_csv(path, index=False)
            path.chmod(stat.S_IREAD)
        store.write_json("data/split.json", {
            **split_config.model_dump(), "discovery_rows": len(discovery), "holdout_rows": len(held),
            "verification_eligible": not held.empty,
            "discovery_hash": file_hash(store.path("data", "raw.csv")),
            "holdout_hash": file_hash(store.path("data", "holdout.csv")),
        })
        config_data = snapshot.model_dump(mode="json")
        config_data["data"] = split_config.model_dump()
        store.write_json("run.json", {
            "format_version": 2, "status": "running", "config": config_data,
            "inputs": {"brief": str(brief.resolve()), "data": str(data.resolve())},
            "source_hash": file_hash(data), "brief_hash": file_hash(brief),
        })
        return store

    def path(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def write_text(self, rel: str, text: str) -> Path:
        target = self.path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as f:
            f.write(text)
        return target

    def write_json(self, rel: str, obj: object) -> Path:
        return self.write_text(rel, json.dumps(obj, indent=2, default=str))

    def checkpoint(self, state: Mapping[str, Any]) -> Path:
        files = list(self.path("state").glob("*.json"))
        sequence = max((int(p.stem) for p in files), default=-1) + 1
        commits = [e for e in read_events(self.root) if e["event"] == "state_commit"]
        rel = f"state/{sequence:06d}.json"
        path = self.write_json(rel, {
            **state, "previous": commits[-1]["path"] if commits else None,
        })
        Journal(self.path("journal.jsonl")).write("state_commit", path=rel)
        return path
