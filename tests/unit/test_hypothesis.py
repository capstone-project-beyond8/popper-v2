import json
from pathlib import Path
from typing import Literal

import pytest

from popper.config import load_config
from popper.harness.config import Search
from popper.scientific.runtime.lifecycle.execution import check_estimate

ESTIMAND = {
    "outcome": "score",
    "exposure": "hours",
    "contrast": "one additional hour",
    "comparison": "difference",
    "population": "students",
    "unit": "score points",
}
PROPOSAL = {
    "statement": "More hours increase score",
    "rationale": "observed relation",
    "primary_estimand": ESTIMAND,
    "expected_direction": "positive",
    "refuting_result": "negative contrast",
    "planned_test": "linear regression with bootstrap CI",
    "methods": ["linear_regression", "bootstrap"],
}


@pytest.mark.parametrize(
    "entry",
    [
        {"value": float("nan"), "ci": [0, 1], "n": 10},
        {"value": 1, "ci": [2, 0], "n": 10},
        {"value": 1, "ci": [0, float("inf")], "n": 10},
        {"value": 1, "n": 10},
        {"value": 1, "ci": [0, 2], "n": 0},
        {"value": 1, "ci": [0, 2], "n": 1.5},
    ],
    ids=["nan", "reversed", "infinite", "no-interval", "zero-n", "fractional-n"],
)
def test_invalid_primary_estimate_fails_code_check(
    tmp_path: Path, entry: dict[str, object]
) -> None:
    (tmp_path / "results.json").write_text(json.dumps({"primary_estimate": entry}))
    assert check_estimate(tmp_path) is not None


def test_missing_or_malformed_results_name_the_problem(tmp_path: Path) -> None:
    (tmp_path / "results.json").write_text("{}")
    assert "has no 'primary_estimate' entry" in str(check_estimate(tmp_path))
    (tmp_path / "results.json").write_text("[]")
    assert "JSON object" in str(check_estimate(tmp_path))


def test_declared_estimand_checks_required_keys_and_allows_extras(tmp_path: Path) -> None:
    entry = {"value": 1, "ci": [0, 2], "n": 10}
    (tmp_path / "results.json").write_text(json.dumps({"primary_estimate": entry}))
    (tmp_path / "estimand.json").write_text(json.dumps({**ESTIMAND, "method": "ols"}))
    assert check_estimate(tmp_path, estimand=ESTIMAND) is None
    (tmp_path / "estimand.json").write_text(json.dumps({**ESTIMAND, "unit": "log score"}))
    assert "'unit'" in str(check_estimate(tmp_path, estimand=ESTIMAND))
    (tmp_path / "estimand.json").write_text("[]")
    assert check_estimate(tmp_path, estimand=ESTIMAND) is not None


def test_stage_budget_validation_and_fallback() -> None:
    cfg = load_config(env={})
    assert cfg.search.stage_steps["baseline"] < cfg.search.stage_steps["main"]
    for value in ({"unknown": 2}, {"main": 0}):
        with pytest.raises(ValueError):
            Search.model_validate({**cfg.search.model_dump(), "stage_steps": value})


def test_discovery_request_subject_and_snapshot_invariants() -> None:
    from popper.harness.storage.records import ArtifactRef
    from popper.scientific.runtime.lifecycle.requests import CapabilityRequest

    ref = ArtifactRef(path="subject.json", sha256="a" * 64, producer="science:candidates", record_id="r1")
    assert CapabilityRequest("candidates", ref).subject == ref
    assert CapabilityRequest("challenge", ref, snapshot=ref).snapshot == ref
    for kind in ("candidates", "challenge"):
        with pytest.raises(ValueError, match="subject"):
            CapabilityRequest(kind)
    with pytest.raises(ValueError, match="snapshot"):
        CapabilityRequest("challenge", ref)
    kinds: tuple[Literal["candidates", "experiment", "publish", "frame"], ...] = ("candidates", "experiment", "publish", "frame")
    for kind in kinds:
        with pytest.raises(ValueError, match="snapshot"):
            CapabilityRequest(kind, ref, snapshot=ref)
