"""Research ingest and bounded episode identity."""

import hashlib
import io
import json
import math
import shutil
import stat
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from popper.harness.records import ArtifactRef, resolve_artifact
from popper.harness.store import RunStore, file_hash, seal_bytes, unseal_bytes
from popper.science.compatibility import decode_policy
from popper.science.contracts import Program, Run
from popper.science.descriptive import DescriptiveReport, describe_table, read_table
from popper.science.research import ResearchContext, ResearchError, check_columns, parse_research
from popper.science.settings import DataConfig, ScientificOptions
from popper.science.store import ScienceStore
from popper.science.views import foundation_view


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


def ingest(
    store: RunStore,
    research: Path,
    data: Path,
    *,
    options: ScientificOptions,
    config_payload: dict[str, Any],
    auto: bool,
) -> None:
    split_config = options.data
    frame = pd.read_csv(data, dtype=str, keep_default_na=False)
    mismatches = check_columns(
        parse_research(research.read_text("utf-8")), [str(c) for c in frame.columns]
    )
    if mismatches:
        raise ResearchError("; ".join(mismatches))
    discovery, held = split_rows(frame, split_config)
    store.root.mkdir(parents=True)
    shutil.copyfile(research, store.root / "research.md")
    (store.root / "data").mkdir()
    raw_path = store.path("data", "raw.csv")
    discovery.to_csv(raw_path, index=False, lineterminator="\n")
    plain = held.to_csv(index=False, lineterminator="\n").encode("utf-8")
    sealed_path = store.path("data", "holdout.sealed")
    seal_bytes(sealed_path, plain, key_id=store.root.name)
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
    config_data = dict(config_payload)
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


def read_holdout(store: RunStore) -> pd.DataFrame:
    """Unseal the held-back rows with the run key kept outside the run directory."""
    plain = unseal_bytes(store.path("data", "holdout.sealed"), key_id=store.root.name)
    expected = json.loads(store.path("data", "split.json").read_text("utf-8"))["holdout_hash"]
    if hashlib.sha256(plain).hexdigest() != expected:
        raise ValueError("holdout rows do not match the recorded hash")
    return pd.read_csv(io.BytesIO(plain), dtype=str, keep_default_na=False)


def load_episode(store: RunStore) -> tuple[Program, Run]:
    metadata = json.loads(store.path("run.json").read_text("utf-8"))
    policy = decode_policy(metadata)
    source = store.artifact_ref("inputs")
    manifest = json.loads(resolve_artifact(store, source).read_text("utf-8"))
    intent = ArtifactRef(
        path="research.md",
        sha256=manifest["files"]["research.md"],
        producer=source.producer,
        record_id=source.record_id,
        backing=source,
    )
    resolve_artifact(store, intent)
    program = Program(id=f"program-{store.root.name}", intent=intent)
    return program, Run(
        id=store.root.name,
        program_id=program.id,
        format_version=policy.format_version,
        inputs=source,
        initial_intent=intent,
        auto=bool(metadata.get("auto")),
    )


def prepare_description(science: ScienceStore) -> tuple[ResearchContext, DescriptiveReport]:
    research = parse_research(science.run.path("research.md").read_text("utf-8"))
    report = describe_table(read_table(science.run.path("data", "raw.csv")), research)
    if not science.run.path("data", "ida-raw.json").exists():
        science.run.write_json(
            "data/ida-raw.json", {"results": report.results, "layout": report.layout}
        )
    return research, report


def promote_foundation(science: ScienceStore, source: ArtifactRef | None = None) -> None:
    prepared = foundation_view(science, source)
    for artifact in (
        prepared.preparation / "processed.parquet",
        science.run.path("ground", prepared.facts["attempt"], "ida.json"),
    ):
        science.run.copy_once(artifact, f"data/{artifact.name}").chmod(stat.S_IREAD)
