"""Data phase: a tree-search stage that cleans the raw data and records every change."""

import json
import shutil
from typing import Any

from popper.harness.session import Harness
from popper.treesearch.engine import Node, StageSpec, run_stage

GOAL = (
    "Prepare the raw data for analysis. Fix column types, missing values, duplicate rows, "
    "impossible values and inconsistent categories. Derive the variables the research questions "
    "need. Write every change to changes.json as a list of "
    '{"step", "rows_affected", "reason"} objects. Write the cleaned table to processed.parquet. '
    "Report at least rows_before and rows_after in results.json."
)


def prepare(h: Harness, framing: dict[str, Any]) -> Node:
    spec = StageSpec(
        name="data",
        goal=GOAL,
        context=json.dumps(framing, indent=2),
        inputs={"raw": h.run.path("data", "raw.csv")},
        required_outputs=("processed.parquet", "changes.json", "results.json"),
    )
    best = run_stage(h, spec)
    target = h.run.path("data", "processed.parquet")
    if target.exists():
        raise FileExistsError(target)
    shutil.copyfile(best.dir / "processed.parquet", target)
    return best
