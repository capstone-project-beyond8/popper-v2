import json
from pathlib import Path

import pytest

from popper.discover.experiment import check_estimate
from popper.discover.hypothesis import HypothesisProposal
from popper.harness.config import Search, load_config

ESTIMAND = {"outcome": "score", "exposure": "hours", "contrast": "one additional hour",
            "population": "students", "unit": "score points"}
PROPOSAL = {"statement": "More hours increase score", "rationale": "observed relation",
            "primary_estimand": ESTIMAND, "expected_direction": "positive",
            "refuting_result": "negative contrast", "planned_test": "linear regression with bootstrap CI"}


@pytest.mark.parametrize("field", ["statement", "refuting_result", "planned_test"])
def test_empty_hypothesis_field_is_rejected(field: str) -> None:
    with pytest.raises(ValueError):
        HypothesisProposal.model_validate({**PROPOSAL, field: " "})


def test_hypothesis_has_one_primary_and_code_owned_attribution() -> None:
    for change in ({"primary_estimand": [ESTIMAND, ESTIMAND]}, {"expected_direction": "unknown"},
                   {"supplied_by": "researcher"}):
        with pytest.raises(ValueError):
            HypothesisProposal.model_validate({**PROPOSAL, **change})


@pytest.mark.parametrize("entry", [
    {"value": float("nan"), "ci": [0, 1], "n": 10},
    {"value": 1, "ci": [2, 0], "n": 10},
    {"value": 1, "ci": [0, float("inf")], "n": 10},
    {"value": 1, "n": 10},
    {"value": 1, "ci": [0, 2], "n": 0},
    {"value": 1, "ci": [0, 2], "n": 1.5},
], ids=["nan", "reversed", "infinite", "no-interval", "zero-n", "fractional-n"])
def test_invalid_primary_estimate_fails_code_check(tmp_path: Path, entry: dict[str, object]) -> None:
    (tmp_path / "results.json").write_text(json.dumps({"primary_estimate": entry}))
    assert check_estimate(tmp_path) is not None


def test_stage_budget_validation_and_fallback() -> None:
    cfg = load_config(env={})
    assert cfg.search.stage_steps["baseline"] < cfg.search.stage_steps["main"]
    for value in ({"unknown": 2}, {"main": 0}):
        with pytest.raises(ValueError):
            Search.model_validate({**cfg.search.model_dump(), "stage_steps": value})
