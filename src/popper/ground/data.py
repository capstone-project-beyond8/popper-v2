"""Data phase: a tree-search stage that cleans the raw data and records every change."""

import json
import stat
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from popper.harness.session import Harness
from popper.treesearch.engine import Node, StageSpec, run_stage

GOAL = (
    "Prepare the raw data for analysis. Fix column types, missing values, duplicate rows, "
    "impossible values and inconsistent categories. Derive the variables the research questions "
    "need. Write every change to changes.json as a list of "
    '{"step", "rows_affected", "reason"} objects. rows_affected is a named result key, NOT a '
    "literal count: write its nonnegative integer value in results.json, then cite that key "
    "(e.g. rows_removed) in changes.json. Write the cleaned table to processed.parquet. "
    "Afterwards no impossible values may remain (e.g. rates outside [0, 1], negative hours or "
    "counts, values outside a variable's physical range), and missing values in variables the "
    "questions need are either handled or explicitly justified in changes.json. "
    "Report rows_before and rows_after in results.json."
)


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step: str
    rows_affected: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    reason: str


def _check_changes(workdir: Path) -> str | None:
    try:
        changes = TypeAdapter(list[Change]).validate_json((workdir / "changes.json").read_bytes())
        results = json.loads((workdir / "results.json").read_text("utf-8"))
        for change in changes:
            if change.rows_affected not in results:
                return (
                    f"rows_affected {change.rows_affected!r} has no entry in results.json; "
                    "report that count there under the same key"
                )
            value = results[change.rows_affected]["value"]
            if type(value) is not int or value < 0:
                return f"{change.rows_affected} must be a nonnegative integer count in results.json"
    except (OSError, ValidationError, ValueError, KeyError, TypeError) as exc:
        return f"invalid changes.json: {exc}"
    return None


def _check_data(workdir: Path) -> str | None:
    reported = json.loads((workdir / "results.json").read_text(encoding="utf-8"))
    if not {"rows_before", "rows_after"} <= reported.keys():
        return "results.json must report rows_before and rows_after"
    value = reported["rows_after"]["value"]
    n = len(pd.read_parquet(workdir / "processed.parquet"))
    if value != n:
        return f"rows_after {value} does not match processed.parquet ({n} rows)"
    return _check_changes(workdir)


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
        check=_check_data,
        describe=_summarise,
    )
    best = run_stage(h, spec)
    target = h.run.copy_once(best.execution_dir / "processed.parquet", "data/processed.parquet")
    target.chmod(stat.S_IREAD)
    return best
