import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from popper.discover.robustness import RobustnessPlan, load_robustness_plan
from popper.harness.config import load_config
from tests.unit.test_hypothesis import ESTIMAND


def schedule() -> dict[str, Any]:
    attempts = []
    for index, dimension in enumerate(
        ["cleaning", "model", "subgroup", "resampling", "adversarial"]
    ):
        adversarial = dimension == "adversarial"
        attempts.append(
            {
                "id": f"choice-{index}",
                "kind": "adversarial" if adversarial else "variant",
                "dimension": dimension,
                "choice": "permutation" if adversarial else f"alternative {index}",
                "estimand": ESTIMAND,
                "result_key": "placebo_estimate" if adversarial else "primary_estimate",
                "seed": 7,
            }
        )
    return {"attempts": attempts, "inapplicable": {}}


def test_schedule_rejects_duplicates_mismatched_units_and_excess_budget() -> None:
    context = {"estimand": ESTIMAND, "steps": 6, "min_variants": 3}
    good = schedule()
    assert len(RobustnessPlan.model_validate(good, context=context).attempts) == 5
    for field, value in [("id", "choice-0"), ("choice", "alternative 0")]:
        bad = deepcopy(good)
        bad["attempts"][1][field] = value
        if field == "choice":
            bad["attempts"][1]["dimension"] = "cleaning"
            bad["inapplicable"]["model"] = "not applicable"
        with pytest.raises(ValueError):
            RobustnessPlan.model_validate(bad, context=context)
    bad = deepcopy(good)
    bad["attempts"][0]["estimand"] = {**ESTIMAND, "unit": "log score"}
    with pytest.raises(ValueError):
        RobustnessPlan.model_validate(bad, context=context)
    with pytest.raises(ValueError):
        RobustnessPlan.model_validate(good, context={**context, "steps": 4})


def test_schedule_requires_minimum_variants_adversary_and_dimension_reasons() -> None:
    context = {"estimand": ESTIMAND, "steps": 6, "min_variants": 3}
    for indexes in ([0, 1, 4], [0, 1, 2, 3], [0, 1, 2, 4]):
        bad = schedule()
        bad["attempts"] = [bad["attempts"][i] for i in indexes]
        with pytest.raises(ValueError):
            RobustnessPlan.model_validate(bad, context=context)
    good = schedule()
    good["attempts"].pop(3)
    good["inapplicable"] = {
        "resampling": "No valid resampling design for these clustered observations"
    }
    assert len(RobustnessPlan.model_validate(good, context=context).attempts) == 4


def test_saved_schedule_uses_configured_budget_and_estimand(tmp_path: Path) -> None:
    cfg = load_config(env={})
    cfg.search.stage_steps["robustness"] = 8
    cfg.robustness.min_variants = 6
    proposal = schedule()
    for i in range(2):
        proposal["attempts"].insert(
            0, {**proposal["attempts"][0], "id": f"extra-{i}", "choice": f"extra model {i}"}
        )
    path = tmp_path / "robustness_plan.json"
    path.write_text(json.dumps({"format_version": 1, "schedule": proposal}))
    assert len(load_robustness_plan(path, cfg, {"primary_estimand": ESTIMAND}).attempts) == 7
    cfg.search.stage_steps["robustness"] = 6
    with pytest.raises(ValueError, match="budget"):
        load_robustness_plan(path, cfg, {"primary_estimand": ESTIMAND})
