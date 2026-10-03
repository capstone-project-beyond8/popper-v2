import json
from dataclasses import replace
from pathlib import Path

import pytest

from popper.discover.experiment import declared_procedure_reference, method_reference
from popper.harness.interpreter import ExecResult
from popper.science.contracts import ExperimentSpec as ScientificTest
from popper.treesearch.engine import Node, StageSpec
from popper.treesearch.judge import judge_input
from tests.unit.test_hypothesis import ESTIMAND, PROPOSAL
from tests.unit.test_judge_input import PNG
from tests.unit.test_test_identity import spec_payload


def test_validated_method_roles_and_requirements_reach_blinded_judge(tmp_path: Path) -> None:
    hypothesis = {
        **PROPOSAL,
        "planned_test": "linear regression bootstrap SECRET_EFFECT -0.731",
        "methods": ["linear_regression", "bootstrap"],
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
    assert "linear regression" in prompt and "bootstrap" in prompt
    assert "<outcome_column>" in prompt and "<exposure_column>" in prompt
    assert "original outcome units" in prompt and "declared difference" in prompt
    assert "SECRET_EFFECT" not in prompt and "0.731" not in prompt and "-'<withheld>'" not in prompt
    adversarial = method_reference(
        hypothesis,
        ["hours", "score"],
        purpose="adversarial",
        choice="permutation SECRET_EFFECT",
        methods=["permutation_test"],
    )
    other, _ = judge_input(
        replace(spec, judge_reference=adversarial), node, ExecResult(0, False, "", "", 0.1)
    )
    assert "permutation test" in other and prompt != other and "SECRET_EFFECT" not in other
    assert "expected_direction" not in json.dumps(reference.requirements)


def test_method_reference_rejects_unknown_column_roles() -> None:
    with pytest.raises(ValueError, match="column"):
        method_reference(PROPOSAL, ["hours"], purpose="main")


def test_effective_procedure_reaches_blinded_judge(tmp_path: Path) -> None:
    payload = spec_payload()
    payload.update(selection={"slice": "x > 30", "assumptions": ["same target"]}, inference={"bootstrap": 100, "interval_level": .95}, adjustment=["age"])
    payload["methods"][0].update(algorithm="trim 20% then compare means", parameters={"trim": .2})
    reference = declared_procedure_reference(ScientificTest.model_validate(payload), ["x", "y"], purpose="main")
    node = Node("main-000", "main", None, "draft", 0, tmp_path, "estimate=-0.731", "ok", 7, True, "", {}, [], "")
    (tmp_path / "judge_figures").mkdir()
    (tmp_path / "judge_figures/samples.png").write_bytes(PNG)
    stage = StageSpec("main", "positive predicted effect", "rationale", {}, (), blind_estimates=True, judge_reference=reference)
    prompt, _ = judge_input(stage, node, ExecResult(0, False, "", "", .1))
    for requirement in ("trim 20%", '"trim": 0.2', "x > 30", '"bootstrap": 100', "age"):
        assert requirement in prompt
    assert "positive predicted" not in prompt and "0.731" not in prompt


def test_open_method_requirements_reach_reference() -> None:
    method = {"family": "custom", "description": "trimmed mean", "algorithm": "trim then compare", "inputs": ["hours", "score"], "outputs": ["primary_estimate"], "effect_scale": "points", "assumptions": ["exchangeability"], "diagnostics": ["check trimming"], "parameters": {}}
    reference = method_reference({**PROPOSAL, "methods": [method]}, ["hours", "score"], purpose="main")
    text = " ".join(reference.requirements)
    assert "trim then compare" in text and "check trimming" in text
    assert "expected_direction" not in text and str(PROPOSAL["rationale"]) not in text


def test_transform_reference_distinguishes_exposure_from_outcome() -> None:
    def text(hypothesis_methods: list[str], purpose: str, methods: list[str]) -> str:
        reference = method_reference(
            {**PROPOSAL, "methods": hypothesis_methods},
            ["hours", "score"],
            purpose=purpose,
            methods=methods,
        )
        return " ".join(reference.requirements)

    assert "If the outcome is transformed" not in text(["bootstrap"], "main", [])
    main = text(["log_transform"], "main", [])
    alternative = text(["bootstrap"], "model", ["log_transform"])
    for transformed in (main, alternative):
        assert "If the outcome is transformed" in transformed
        assert "Transforming only the exposure" in transformed
        assert "does not require back-transforming the outcome" in transformed
    assert "If the outcome is transformed" not in text(["log_transform"], "baseline", [])
    adversary = text(
        ["bootstrap", "log_transform"], "adversarial", ["permutation_test", "linear_regression"]
    )
    assert "If the outcome is transformed" not in adversary
    assert "bootstrap" not in adversary and "log transform" not in adversary
    assert "linear regression" in adversary


def test_method_reference_lists_only_declared_methods() -> None:
    hypothesis = {
        **PROPOSAL,
        "planned_test": "compare log-odds with robust standard errors",
        "methods": ["logistic_regression"],
    }
    reference = method_reference(
        hypothesis, ["hours", "score"], purpose="main", choice="log-odds robust", methods=[]
    )
    text = " ".join(reference.requirements)
    assert "logistic regression" in text
    assert "log transform" not in text and "robust" not in text
    assert "Recorded alternative" not in text
    assert "declared difference" in text
