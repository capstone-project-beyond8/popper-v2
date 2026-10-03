from pathlib import Path

from popper.harness.execution.interpreter import ExecResult
from popper.scientific.runtime.lifecycle.contracts import ExperimentSpec as ScientificTest
from popper.stages.discover.experiment import declared_procedure_reference
from popper.strategies.treesearch.engine import Node, StageSpec
from popper.strategies.treesearch.judge import judge_input
from tests.unit.test_judge_input import PNG
from tests.unit.test_test_identity import spec_payload


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


