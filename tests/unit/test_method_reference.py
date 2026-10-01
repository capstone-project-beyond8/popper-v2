import json
from dataclasses import replace
from pathlib import Path

import pytest

from popper.discover.experiment import method_reference
from popper.harness.interpreter import ExecResult
from popper.treesearch.engine import Node, StageSpec
from popper.treesearch.judge import judge_input
from tests.unit.test_hypothesis import ESTIMAND, PROPOSAL
from tests.unit.test_judge_input import PNG


def test_validated_method_roles_and_requirements_reach_blinded_judge(tmp_path: Path) -> None:
    hypothesis = {
        **PROPOSAL,
        "planned_test": "linear regression bootstrap SECRET_EFFECT -0.731",
        "primary_estimand": {**ESTIMAND, "unit": "SECRET_EFFECT"},
    }
    reference = method_reference(hypothesis, ["hours", "score"], purpose="main")
    source = 'y=df["score"]; x=df["hours"]; primary_estimate=-0.731'
    node = Node(
        "main-000",
        "main",
        None,
        "draft",
        0,
        tmp_path,
        source,
        "ok",
        7,
        True,
        "",
        {"primary_estimate": {"value": -0.731, "ci": [-1.0, -0.5], "n": 20}},
        [],
        "",
    )
    (tmp_path / "judge_figures").mkdir()
    (tmp_path / "judge_figures" / "samples.png").write_bytes(PNG)
    spec = StageSpec(
        "main",
        "SECRET_EFFECT",
        "SECRET_EFFECT",
        {},
        ("results.json",),
        blind_estimates=True,
        judge_reference=reference,
    )
    prompt, _ = judge_input(spec, node, ExecResult(0, False, "-0.731", "SECRET_EFFECT", 0.1))
    assert "regression" in prompt and "bootstrap" in prompt
    assert "<outcome_column>" in prompt and "<exposure_column>" in prompt
    assert "original outcome units" in prompt and "declared difference" in prompt
    assert "SECRET_EFFECT" not in prompt and "0.731" not in prompt and "-'<withheld>'" not in prompt
    adversarial = method_reference(
        hypothesis, ["hours", "score"], purpose="adversarial", choice="permutation SECRET_EFFECT"
    )
    other, _ = judge_input(
        replace(spec, judge_reference=adversarial), node, ExecResult(0, False, "", "", 0.1)
    )
    assert "permutation" in other and prompt != other and "SECRET_EFFECT" not in other
    assert "expected_direction" not in json.dumps(reference.requirements)


def test_method_reference_rejects_unknown_column_roles() -> None:
    with pytest.raises(ValueError, match="column"):
        method_reference(PROPOSAL, ["hours"], purpose="main")
