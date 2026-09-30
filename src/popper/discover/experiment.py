"""Sequential experiments for one declared primary estimand."""

import json
import math
from pathlib import Path
from typing import Any, Literal

from popper.harness.session import Harness
from popper.treesearch.engine import Node, ResultEntry, StageSpec, run_stage


def check_estimate(
    workdir: Path, key: str = "primary_estimate", estimand: dict[str, Any] | None = None,
) -> str | None:
    try:
        raw = json.loads((workdir / "results.json").read_text("utf-8"))
        entry = ResultEntry.model_validate_json(json.dumps(raw[key]))
        if type(entry.value) not in (int, float) or not math.isfinite(float(entry.value)):
            return f"{key} needs a finite numerical estimate"
        if entry.ci is None or not all(math.isfinite(v) for v in entry.ci) or entry.ci[0] > entry.ci[1]:
            return f"{key} needs an ordered finite interval"
        if entry.n is None or entry.n <= 0:
            return f"{key} needs a positive integer sample size"
        if estimand is not None:
            declared = json.loads((workdir / "estimand.json").read_text("utf-8"))
            if declared != estimand:
                return "declared estimand differs from the required contrast, units or population"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return f"invalid {key}: {exc}"
    return None


def run_experiment_stage(
    h: Harness, name: Literal["baseline", "main"], framing: dict[str, Any],
    hypothesis: dict[str, Any], seed: Node | None,
) -> Node:
    estimand = hypothesis["primary_estimand"]
    goal = (
        "Use a simple transparent model or test." if name == "baseline"
        else f"Implement the planned test: {hypothesis['planned_test']}"
    )
    goal += (
        " Re-estimate the declared primary contrast in its original outcome units. "
        "Write primary_estimate in results.json with value, a 95% ci and integer n. "
        "Write exactly the declared primary_estimand object to estimand.json. "
        "Save a result figure in figures/. Secondary estimands need different result keys. "
        "Do not choose preprocessing or a model to obtain a desired sign or significance."
    )
    return run_stage(h, StageSpec(
        name=name, goal=goal,
        context=f"Framing:\n{json.dumps(framing)}\nHypothesis:\n{json.dumps(hypothesis)}",
        inputs={"data": h.run.path("data", "processed.parquet")},
        required_outputs=("results.json", "estimand.json"), min_figures=1,
        seed_code=seed.code if seed else None, seed_node=seed.id if seed else None,
        blind_estimates=True, check=lambda path: check_estimate(path, estimand=estimand),
    ))


def experiment(
    h: Harness, framing: dict[str, Any], hypothesis: dict[str, Any], data_node: Node,
) -> Node:
    baseline = run_experiment_stage(h, "baseline", framing, hypothesis, None)
    return run_experiment_stage(h, "main", framing, hypothesis, baseline)
