"""Computed, never blocking warnings about the hypothesis against the reviewed frame."""

import re
from typing import Any

import pandas as pd

from popper.harness.research import ResearchContext

MIN_CLUSTERS = 30
_UNUSABLE_ROLES = {"id", "cluster", "post_outcome", "protected", "ignore"}
_CORE = ("meaning", "unit", "type", "role")
_OTHER = ("range", "levels", "order")


def _position(order: list[str] | None) -> float | None:
    """The measurement position when a variable's order is a single number."""
    try:
        return float(order[0]) if order and len(order) == 1 else None
    except ValueError:
        return None


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
            variable.role.value in _UNUSABLE_ROLES or variable.type.value == "id"
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
        later, earlier = _position(exposure.order.value), _position(outcome.order.value)
        if later is not None and earlier is not None and later > earlier:
            warnings.append("The exposure is measured after the outcome.")
    text = " ".join(str(v) for v in hypothesis.values() if not isinstance(v, (dict, list)))
    for assumption in research.assumptions:
        status = assumption.description.status
        if status != "confirmed" and re.search(rf"\b{re.escape(assumption.id)}\b", text):
            warnings.append(
                f"The hypothesis relies on assumption {assumption.id}, which is {status}."
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
