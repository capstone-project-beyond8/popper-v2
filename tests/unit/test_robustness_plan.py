from copy import deepcopy
from typing import Any

import pytest

from popper.discover.robustness import RobustnessPlan
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
