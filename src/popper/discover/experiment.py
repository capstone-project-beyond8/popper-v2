"""Experiment phase: a tree-search stage that tests one hypothesis."""

import json
from typing import Any

from popper.harness.session import Harness
from popper.treesearch.engine import Node, StageSpec, run_stage

GOAL = (
    "Test the hypothesis on the processed data with a transparent analysis. Report every key "
    "estimate in results.json with its 95% interval as ci, and the sample size as n. Save "
    "figures that show the result."
)


def experiment(
    h: Harness, framing: dict[str, Any], hypothesis: dict[str, Any], seed_code: str | None
) -> Node:
    context = f"Framing:\n{json.dumps(framing, indent=2)}\n\nHypothesis:\n{json.dumps(hypothesis, indent=2)}"
    spec = StageSpec(
        name="experiment",
        goal=GOAL,
        context=context,
        inputs={"data": h.run.path("data", "processed.parquet")},
        required_outputs=("results.json",),
        seed_code=seed_code,
        min_figures=1,
    )
    return run_stage(h, spec)
