import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from popper.config import load_config
from popper.scientific.runtime.evidence.historical import (
    RobustnessPlan,
    load_robustness_plan,
    schedule_context,
)
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
                "result_key": "placebo_estimate" if adversarial else "primary_estimate",
                "seed": 7,
            }
        )
        if dimension == "subgroup":
            attempts[-1]["population"] = "students with high attendance"
    return {"attempts": attempts, "inapplicable": {}}


def test_schedule_rejects_duplicates_and_excess_budget() -> None:
    context = {"steps": 6, "min_variants": 3}
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
    with pytest.raises(ValueError):
        RobustnessPlan.model_validate(good, context={**context, "steps": 4})


def test_population_belongs_to_subgroup_variants_only() -> None:
    context = {"steps": 6, "min_variants": 3}
    missing = schedule()
    del missing["attempts"][2]["population"]
    extra = schedule()
    extra["attempts"][1]["population"] = "students with high attendance"
    for bad in (missing, extra):
        with pytest.raises(ValueError, match="population"):
            RobustnessPlan.model_validate(bad, context=context)


def test_specification_estimand_replaces_only_population() -> None:
    attempts = RobustnessPlan.model_validate(schedule(), context={}).attempts
    assert attempts[0].estimand(ESTIMAND) == ESTIMAND
    assert attempts[2].estimand(ESTIMAND) == {
        **ESTIMAND,
        "population": "students with high attendance",
    }


def test_schedule_requires_minimum_variants_adversary_and_dimension_reasons() -> None:
    context = {"steps": 6, "min_variants": 3}
    for indexes, reasons, message in (
        (
            [0, 1, 4],
            {"subgroup": "No valid subgroup", "resampling": "No valid resampling design"},
            "requires ordinary variants",
        ),
        ([0, 1, 2, 3], {}, "at least one adversarial check"),
        ([0, 1, 2, 4], {}, "missing resampling"),
    ):
        bad = schedule()
        bad["attempts"] = [bad["attempts"][i] for i in indexes]
        bad["inapplicable"] = reasons
        with pytest.raises(ValueError, match=message):
            RobustnessPlan.model_validate(bad, context=context)
    good = schedule()
    good["attempts"].pop(3)
    good["inapplicable"] = {
        "resampling": "No valid resampling design for these clustered observations"
    }
    assert len(RobustnessPlan.model_validate(good, context=context).attempts) == 4


def test_saved_schedule_uses_configured_budget(tmp_path: Path) -> None:
    cfg = load_config(env={})
    cfg.search.stage_steps["robustness"] = 8
    cfg.robustness.min_variants = 6
    proposal = schedule()
    for i in range(2):
        proposal["attempts"].insert(
            0, {**proposal["attempts"][0], "id": f"extra-{i}", "choice": f"extra model {i}"}
        )
    path = tmp_path / "robustness_plan.json"
    path.write_text(json.dumps({"format_version": 2, "schedule": proposal}))
    assert len(load_robustness_plan(path, cfg.search, cfg.robustness).attempts) == 7
    cfg.search.stage_steps["robustness"] = 6
    with pytest.raises(ValueError, match="budget"):
        load_robustness_plan(path, cfg.search, cfg.robustness)


def test_new_schedule_reserves_repair_without_invalidating_saved_schedule(tmp_path: Path) -> None:
    cfg = load_config(env={})
    full = schedule()
    full["attempts"].insert(
        0, {**full["attempts"][1], "id": "second-model", "choice": "different estimator"}
    )
    path = tmp_path / "robustness_plan.json"
    path.write_text(json.dumps({"format_version": 2, "schedule": full}))
    assert len(load_robustness_plan(path, cfg.search, cfg.robustness).attempts) == 6
    assert len(RobustnessPlan.model_validate(schedule(), context=schedule_context(cfg.search, cfg.robustness)).attempts) == 5
    with pytest.raises(ValueError, match="budget"):
        RobustnessPlan.model_validate(full, context=schedule_context(cfg.search, cfg.robustness))


def test_new_schedule_rejects_budget_without_room_for_repair(tmp_path: Path) -> None:
    cfg = load_config(env={})
    cfg.search.stage_steps["robustness"] = cfg.robustness.min_variants + 1
    recorded = schedule()
    recorded["attempts"].pop(3)
    recorded["inapplicable"]["resampling"] = "No valid resampling design"
    path = tmp_path / "robustness_plan.json"
    path.write_text(json.dumps({"format_version": 2, "schedule": recorded}))
    assert len(load_robustness_plan(path, cfg.search, cfg.robustness).attempts) == 4
    with pytest.raises(ValueError, match="repair"):
        schedule_context(cfg.search, cfg.robustness)
