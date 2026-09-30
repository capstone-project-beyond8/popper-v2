"""Data phase: a tree-search stage that cleans the raw data and records every change."""

import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from popper.harness.session import Harness
from popper.treesearch.engine import Node, StageSpec, run_stage

GOAL = (
    "Prepare the raw data for analysis. Fix column types, missing values, duplicate rows, "
    "impossible values and inconsistent categories. Derive the variables the research questions "
    "need. Write every change to changes.json as a list of "
    '{"step", "rows_affected", "reason"} objects. Write the cleaned table to processed.parquet. '
    "Afterwards no impossible values may remain (e.g. rates outside [0, 1], negative hours or "
    "counts, values outside a variable's physical range), and missing values in variables the "
    "questions need are either handled or explicitly justified in changes.json. "
    "Report at least rows_before and rows_after in results.json."
)


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: str
    rows_affected: int | str
    reason: str


def _check_changes(workdir: Path) -> str | None:
    try:
        TypeAdapter(list[Change]).validate_json((workdir / "changes.json").read_bytes())
    except (OSError, ValidationError) as exc:
        return f"invalid changes.json: {exc}"
    return None


def _summarise(workdir: Path) -> str:
    df = pd.read_parquet(workdir / "processed.parquet")
    lines = [f"shape: {df.shape[0]} rows x {df.shape[1]} columns"]
    for col in df.columns:
        s = df[col]
        head = f"{col}: dtype={s.dtype}, n_missing={int(s.isna().sum())}"
        if pd.api.types.is_bool_dtype(s) or not pd.api.types.is_numeric_dtype(s):
            top = ", ".join(f"{v!r} ({c})" for v, c in s.value_counts().head(8).items())
            lines.append(f"{head}, n_unique={s.nunique()}, top: {top}")
        else:
            lines.append(f"{head}, min={s.min():.3g}, max={s.max():.3g}, mean={s.mean():.3g}")
    return "\n".join(lines)


def prepare(h: Harness, framing: dict[str, Any]) -> Node:
    spec = StageSpec(
        name="data",
        goal=GOAL,
        context=json.dumps(framing, indent=2),
        inputs={"raw": h.run.path("data", "raw.csv")},
        required_outputs=("processed.parquet", "changes.json", "results.json"),
        check=_check_changes,
        describe=_summarise,
    )
    best = run_stage(h, spec)
    target = h.run.path("data", "processed.parquet")
    if target.exists():
        raise FileExistsError(target)
    shutil.copyfile(best.dir / "processed.parquet", target)
    return best
