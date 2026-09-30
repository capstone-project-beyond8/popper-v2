"""Sequential experiments for one declared primary estimand."""

import json
import math
from pathlib import Path
from typing import Any, Literal

from popper.discover.robustness import (
    RobustnessPlan,
    Specification,
    collect_evidence,
    plan_robustness,
)
from popper.harness.session import Harness
from popper.treesearch.engine import (
    AttemptSpec,
    Node,
    ResultEntry,
    StageFailed,
    StageSpec,
    run_stage,
)


def check_estimate(
    workdir: Path,
    key: str = "primary_estimate",
    estimand: dict[str, Any] | None = None,
) -> str | None:
    try:
        raw = json.loads((workdir / "results.json").read_text("utf-8"))
        entry = ResultEntry.model_validate_json(json.dumps(raw[key]))
        if type(entry.value) not in (int, float) or not math.isfinite(float(entry.value)):
            return f"{key} needs a finite numerical estimate"
        if (
            entry.ci is None
            or not all(math.isfinite(v) for v in entry.ci)
            or entry.ci[0] > entry.ci[1]
        ):
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
    h: Harness,
    name: Literal["baseline", "main"],
    framing: dict[str, Any],
    hypothesis: dict[str, Any],
    seed: Node | None,
) -> Node:
    estimand = hypothesis["primary_estimand"]
    goal = (
        "Use a simple transparent model or test."
        if name == "baseline"
        else f"Implement the planned test: {hypothesis['planned_test']}"
    )
    goal += (
        " Re-estimate the declared primary contrast in its original outcome units. "
        "Write primary_estimate in results.json with value, a 95% ci and integer n. "
        "Write exactly the declared primary_estimand object to estimand.json. "
        "Save a result figure in figures/. Secondary estimands need different result keys. "
        "Do not choose preprocessing or a model to obtain a desired sign or significance."
    )
    return run_stage(
        h,
        StageSpec(
            name=name,
            goal=goal,
            context=f"Framing:\n{json.dumps(framing)}\nHypothesis:\n{json.dumps(hypothesis)}",
            inputs={"data": h.run.path("data", "processed.parquet")},
            required_outputs=("results.json", "estimand.json"),
            min_figures=1,
            seed_code=seed.code if seed else None,
            seed_node=seed.id if seed else None,
            blind_estimates=True,
            check=lambda path: check_estimate(path, estimand=estimand),
        ),
    )


def experiment(
    h: Harness,
    framing: dict[str, Any],
    hypothesis: dict[str, Any],
    data_node: Node,
) -> Path:
    committed = h.run.committed("evidence")
    if committed:
        return committed
    baseline = run_experiment_stage(h, "baseline", framing, hypothesis, None)
    main = run_experiment_stage(h, "main", framing, hypothesis, baseline)
    plan = plan_robustness(h, hypothesis, main, data_node)
    schedule = RobustnessPlan.model_validate(json.loads(plan.read_text("utf-8"))["schedule"])
    attempts = tuple(_attempt(item) for item in schedule.attempts)
    selected = {"baseline": baseline, "main": main}
    try:
        selected["robustness"] = run_stage(
            h,
            StageSpec(
                name="robustness",
                goal="Test the main contrast under recorded alternative analyses.",
                context=f"Hypothesis:\n{json.dumps(hypothesis)}",
                inputs={
                    "data": h.run.path("data", "processed.parquet"),
                    "raw": h.run.path("data", "raw.csv"),
                    "prepare": data_node.execution_dir / "code.py",
                    "changes": data_node.execution_dir / "changes.json",
                },
                required_outputs=("results.json", "estimand.json", "specification.json"),
                seed_code=main.code,
                seed_node=main.id,
                blind_estimates=True,
                attempts=attempts,
            ),
        )
    except StageFailed:
        # Failed robustness attempts remain evidence of fragility, not a missing main result.
        pass
    return collect_evidence(h, hypothesis, selected, plan)


def _attempt(item: Specification) -> AttemptSpec:
    goal = (
        f"Implement only this recorded {item.dimension} alternative: {item.choice}. "
        "Adapt the seeded main script; keep the declared exposure, outcome, contrast and units. "
        "For cleaning alternatives, rerun recorded preparation on the raw discovery input with "
        "the declared change; the preparation script and change log are mounted as prepare and changes. "
        f"Write {item.result_key} in results.json with value, 95% ci and positive integer n. "
        "Write the declared estimand to estimand.json and this specification exactly to specification.json. "
        "Do not write a pass/fail flag or a stability label."
    )
    if item.kind == "adversarial":
        goal += (
            f" Permute the exposure once with numpy.random.default_rng({item.seed}).permutation, "
            "then refit the SAME estimator and primary contrast. Report the placebo interval, "
            "not a permutation p-value. Do not retry seeds to obtain a desired outcome."
        )

    def check(path: Path) -> str | None:
        failure = check_estimate(path, item.result_key, item.estimand.model_dump())
        if failure:
            return failure
        try:
            saved = Specification.model_validate_json((path / "specification.json").read_bytes())
            if saved != item:
                return "executed specification metadata differs from the recorded choice"
        except (OSError, ValueError) as exc:
            return f"invalid specification metadata: {exc}"
        return None

    return AttemptSpec(item.id, item.kind, goal, json.dumps(item.model_dump(mode="json")), check)
