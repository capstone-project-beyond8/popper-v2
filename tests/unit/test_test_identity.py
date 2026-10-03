from typing import Any

import pytest
from pydantic import ValidationError

from popper.discover.contracts import MethodSpec, SupportRule, classify_change
from popper.discover.contracts import TestSpec as ScientificTest


def spec_payload() -> dict[str, Any]:
    return {
        "id": "t1", "hypothesis_id": "h1",
        "primary_estimand": {"outcome": "y", "exposure": "x", "contrast": "one unit", "comparison": "difference", "population": "adults", "unit": "points"},
        "selection": {"slice": "all", "assumptions": []},
        "preparation": {"path": "prep.json", "sha256": "a"*64, "producer": "prep", "record_id": "r1"},
        "methods": [{"family": "custom", "description": "trimmed means", "algorithm": "trim 10% then compare means", "inputs": ["x", "y"], "outputs": ["primary_estimate"], "effect_scale": "points", "assumptions": [], "diagnostics": [], "parameters": {"trim": .1}}],
        "inference": {"bootstrap": 1000, "interval_level": .95}, "adjustment": [],
        "requested_coverage": {"seeds": [7], "alternatives": []},
        "outputs": ["primary_estimate", "estimand.json"], "sources": [],
    }


def test_open_methods_and_custom_algorithm() -> None:
    spec = ScientificTest.model_validate(spec_payload())
    assert spec.methods[0].family == "custom"
    payload = spec.methods[0].model_dump()
    payload["family"] = "quantile_regression"
    payload["algorithm"] = None
    assert MethodSpec.model_validate(payload).family == "quantile_regression"
    changes_list: tuple[dict[str, Any], ...] = ({"family": "custom", "algorithm": None}, {"inputs": []}, {"outputs": []})
    for changes in changes_list:
        with pytest.raises(ValidationError):
            MethodSpec.model_validate({**payload, **changes})


@pytest.mark.parametrize(("change", "expected"), [
    ({"id": "child"}, "same_test"),
    ({"inference": {"bootstrap": 100, "interval_level": .95}}, "refine"),
    ({"selection": {"slice": "age > 30", "assumptions": ["same target"]}}, "refine"),
    ({"primary_estimand": {**spec_payload()["primary_estimand"], "population": "children"}}, "pivot"),
])
def test_semantic_changes(change: dict[str, Any], expected: str) -> None:
    before = ScientificTest.model_validate(spec_payload())
    after = ScientificTest.model_validate({**spec_payload(), **change})
    assert classify_change(before, after) == expected


def test_support_rule_bounds_and_interval() -> None:
    for change in ({"lower": 2, "upper": 1}, {"lower": float("nan"), "upper": 2}, {"interval_level": 1}):
        with pytest.raises(ValidationError):
            SupportRule.model_validate({"kind": "equivalence_ci", "result_key": "primary_estimate", "interval_level": .95, "lower": -1, "upper": 1, **change})
