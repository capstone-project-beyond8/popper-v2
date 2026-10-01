"""Limitations the paper states, computed from the foundation and the hypothesis warnings."""

from typing import Any

PREPARATION_ACCESS = (
    "Data preparation was carried out by an AI agent with access to the raw discovery rows, "
    "including the outcome."
)


def _readiness(readiness: dict[str, Any]) -> list[str]:
    items = []
    for name, fact in readiness.get("columns", {}).items():
        label = f"The {fact['role']} {name}"
        if not fact["present"]:
            items.append(f"{label} is missing from the prepared data.")
            continue
        if fact.get("constant"):
            items.append(f"{label} is constant in the prepared data.")
        for key, text in (
            ("missing_share", "is missing in"),
            ("floor_share", "is at its lower bound in"),
            ("ceiling_share", "is at its upper bound in"),
        ):
            if fact.get(key, 0) > 0:
                items.append(f"{label} {text} {fact[key]:.1%} of the prepared rows.")
    return items


def limitations(foundation: dict[str, Any], warnings: list[str]) -> list[str]:
    """Hypothesis warnings, unresolved frame concerns, data concerns, readiness, the fixed note."""
    kinds = {"frame": "Unresolved frame concern", "data": "Data concern"}
    concerns = [
        f"{kinds[c['kind']]} ({c['type']}): {c['description']}" for c in foundation["concerns"]
    ]
    return [*warnings, *concerns, *_readiness(foundation["readiness"]), PREPARATION_ACCESS]
