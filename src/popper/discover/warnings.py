"""Computed, never blocking warnings about the hypothesis against the reviewed frame."""

from typing import Any

import pandas as pd

from popper.harness.research import UNUSABLE_ROLES, ResearchContext

MIN_CLUSTERS = 30
_CORE = ("meaning", "unit", "type", "role")
_OTHER = ("range", "levels", "order")


def hypothesis_warnings(
    hypothesis: dict[str, Any],
    research: ResearchContext,
    operationalization: list[dict[str, Any]],
    processed: pd.DataFrame,
) -> list[str]:
    estimand = hypothesis["primary_estimand"]
    named = {"outcome": estimand["outcome"], "exposure": estimand["exposure"]}
    warnings: list[str] = []
    excluded = research.constraints.excluded.value or []
    protected = research.constraints.protected.value or []
    for label, column in named.items():
        variable = research.variables.get(column)
        if variable is not None and (
            variable.role.value in UNUSABLE_ROLES or variable.type.value == "id"
        ):
            kind = variable.type.value if variable.type.value == "id" else variable.role.value
            warnings.append(f"The {label} {column} is declared as {kind}, not a measured variable.")
        if column in excluded:
            warnings.append(f"The {label} {column} is an excluded column.")
        if column in protected:
            warnings.append(f"The {label} {column} is a protected column.")
        if variable is not None:
            for attr in (*_CORE, *_OTHER):
                entry = getattr(variable, attr)
                if entry.status == "proposed" or (entry.status == "unknown" and attr in _CORE):
                    warnings.append(f"The {attr} of {column} is {entry.status}, not confirmed.")
        strengths = {o["proxy_strength"] for o in operationalization if column in o["columns"]}
        if strengths and strengths <= {"weak", "none"}:
            warnings.append(
                f"The {label} {column} is measured only by weak or absent proxies "
                f"({', '.join(sorted(strengths))})."
            )
    outcome = research.variables.get(named["outcome"])
    exposure = research.variables.get(named["exposure"])
    if outcome is not None and exposure is not None:
        if (
            exposure.order.value is not None
            and outcome.order.value is not None
            and exposure.order.value > outcome.order.value
        ):
            warnings.append("The exposure is measured after the outcome.")
    known = {a.id: a for a in research.assumptions}
    for assumption_id in hypothesis.get("assumptions", []):
        assumption = known.get(assumption_id)
        if assumption is None:
            warnings.append(
                f"The hypothesis relies on assumption {assumption_id}, which is not declared."
            )
            continue
        for attr in ("description", "confounder"):
            status = getattr(assumption, attr).status
            # confounder is optional: only a proposed value is relied on
            if status == "proposed" or (attr == "description" and status == "unknown"):
                warnings.append(
                    f"The hypothesis relies on assumption {assumption_id}, "
                    f"whose {attr} is {status}, not confirmed."
                )
    cluster = research.design.cluster_column.value
    if cluster is not None and cluster in processed.columns:
        count = int(processed[cluster].nunique())
        if count < MIN_CLUSTERS:
            warnings.append(
                f"Only {count} clusters in {cluster} (fewer than {MIN_CLUSTERS}); "
                "cluster-robust inference is limited."
            )
    return warnings
