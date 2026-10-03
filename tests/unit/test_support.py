import pytest

from popper.science.contracts import SupportRule
from popper.science.evidence import compute_support
from popper.science.results import ResultEntry


@pytest.mark.parametrize(("kind", "direction", "ci", "expected"), [
    ("directional_ci", "positive", (1., 2.), "supported"),
    ("directional_ci", "positive", (-2., -1.), "not_supported"),
    ("directional_ci", "positive", (0., 2.), "inconclusive"),
    ("directional_ci", "negative", (-2., -1.), "supported"),
    ("directional_ci", "negative", (-1., 0.), "inconclusive"),
    ("equivalence_ci", None, (-.5, .5), "supported"),
    ("equivalence_ci", None, (1.1, 2.), "not_supported"),
    ("equivalence_ci", None, (-1., .5), "inconclusive"),
])
def test_support_boundary(kind: str, direction: str | None, ci: tuple[float, float], expected: str) -> None:
    rule = SupportRule.model_validate({"kind": kind, "direction": direction, "null": 0, "lower": -1, "upper": 1, "result_key": "estimate", "interval_level": .95})
    result = ResultEntry(value=0., ci=ci)
    assert compute_support(rule, result, fidelity="consistent", rule_precedes_execution=True) == expected
    assert compute_support(rule, result, fidelity="unresolved", rule_precedes_execution=True) == "unavailable"
    assert compute_support(rule, result, fidelity="consistent", rule_precedes_execution=False) == "post_hoc"


def test_invalid_interval_is_unavailable_before_late_rule() -> None:
    rule = SupportRule(kind="directional_ci", result_key="estimate", interval_level=.95, null=0, direction="positive")
    for ci in (None, (2., 1.), (float("nan"), 2.)):
        assert compute_support(rule, ResultEntry(value=1., ci=ci), fidelity="consistent", rule_precedes_execution=False) == "unavailable"
