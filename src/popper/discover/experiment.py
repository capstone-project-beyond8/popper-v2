"""Sequential experiments for one declared primary estimand."""

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from popper.discover.robustness import (
    Specification,
    collect_evidence,
    load_robustness_plan,
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
from popper.treesearch.judge import JudgeReference

_METHOD_TERMS = (
    (r"\b(regress\w*|ols)\b", "regression"),
    (r"\b(linear|ols)\b", "linear model"),
    (r"\b(logistic|logit|binomial)\b", "logistic model"),
    (r"\blog(?:1p)?\b", "log transform"),
    (r"\b(bootstrap|bootstrapping)\b", "bootstrap"),
    (r"\b(permutation|permute)\b", "permutation"),
    (r"\b(median|mean)[ -]imput\w*|\bimputation\b", "imputation"),
    (r"\b(robust|huber)\b", "robust estimator"),
    (r"\brandom forest\b", "random forest"),
    (r"\b(gam|spline\w*)\b", "nonlinear smooth model"),
    (r"\b(cluster\w*)\b", "cluster-aware uncertainty"),
)


def method_reference(
    hypothesis: Mapping[str, Any], columns: Sequence[str], *, purpose: str, choice: str = ""
) -> JudgeReference:
    """Only checked column roles and closed method vocabulary can cross the blinding boundary."""
    primary = hypothesis["primary_estimand"]
    outcome, exposure = primary["outcome"], primary["exposure"]
    if outcome not in columns or exposure not in columns:
        raise ValueError("primary outcome and exposure must identify processed data columns")
    if purpose not in {
        "baseline",
        "main",
        "cleaning",
        "model",
        "subgroup",
        "resampling",
        "adversarial",
    }:
        raise ValueError("unknown experiment purpose")
    contrast = primary["contrast"].casefold()
    comparison = (
        "ratio"
        if re.search(r"\bratio\b", contrast)
        else "difference"
        if re.search(r"\b(difference|additional|to|minus)\b", contrast)
        else "contrast"
    )
    requirements = [
        f"Stage/specification: {purpose}.",
        f"Compute the declared {comparison} using the designated exposure and outcome in original outcome units.",
        "Use the declared restricted subgroup population."
        if purpose == "subgroup"
        else "Use the primary declared population.",
    ]
    if purpose == "baseline":
        requirements.append("Use a simple transparent baseline and report an uncertainty interval.")
    else:
        text = hypothesis["planned_test"].casefold()
        operations = [label for pattern, label in _METHOD_TERMS if re.search(pattern, text)]
        requirements.append(
            "Main planned method operations: "
            + ", ".join(operations or ["no recognized method terms"])
            + "."
        )
    alternatives = [
        label for pattern, label in _METHOD_TERMS if re.search(pattern, choice.casefold())
    ]
    if alternatives:
        requirements.append("Recorded alternative operations: " + ", ".join(alternatives) + ".")
    if purpose == "adversarial":
        requirements.append(
            "Permute the exposure once; refit the same estimator and contrast, reporting a placebo interval."
        )
    identity = hashlib.sha256(
        json.dumps(
            {
                "primary": primary,
                "test": hypothesis["planned_test"],
                "purpose": purpose,
                "choice": choice,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    requirements.append(f"Opaque method/specification identity: {identity}.")
    return JudgeReference({outcome: "outcome", exposure: "exposure"}, tuple(requirements))


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
            judge_reference=method_reference(
                hypothesis,
                pd.read_parquet(h.run.path("data", "processed.parquet")).columns.tolist(),
                purpose=name,
            ),
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
    schedule = load_robustness_plan(plan, h.config, hypothesis)
    columns = pd.read_parquet(h.run.path("data", "processed.parquet")).columns.tolist()
    attempts = tuple(
        _attempt(
            item, method_reference(hypothesis, columns, purpose=item.dimension, choice=item.choice)
        )
        for item in schedule.attempts
    )
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


def _attempt(item: Specification, reference: JudgeReference) -> AttemptSpec:
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

    return AttemptSpec(
        item.id, item.kind, goal, json.dumps(item.model_dump(mode="json")), check, reference
    )
