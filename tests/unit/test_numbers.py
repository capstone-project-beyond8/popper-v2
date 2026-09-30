from types import SimpleNamespace
from typing import Any, cast

from popper.communicate.numbers import collect_values, explain_missing, fill_numbers
from popper.treesearch.engine import Node


def test_fill_known_and_unknown() -> None:
    values = {"experiment.coef": 0.4213}
    tex, missing = fill_numbers(r"a \R{experiment.coef} b \R{nope.x}", values)
    assert tex == r"a 0.421 b \textbf{??}"
    assert missing == [r"\R{nope.x}"]


def test_interval_and_sample_size_are_their_own_keys() -> None:
    node = SimpleNamespace(
        stage="experiment",
        results={"slope": {"value": 0.4213, "ci": [0.3, 0.55], "n": 549}, "rows": {"value": 600}},
    )
    values = collect_values([cast(Node, node)])
    tex, missing = fill_numbers(
        r"\R{experiment.slope} (\R{experiment.slope.ci}, $n = \R{experiment.slope.n}$)"
        r" \R{experiment.rows.n}",
        values,
    )
    assert tex == r"0.421 (0.3--0.55, $n = 549$) \textbf{??}"
    assert missing == [r"\R{experiment.rows.n}"]


def test_string_values_are_escaped() -> None:
    tex, _ = fill_numbers(r"\R{a.b}", {"a.b": "50% & up"})
    assert tex == r"50\% \& up"


def test_dotted_capital_key_is_reported_missing() -> None:
    tex, missing = fill_numbers(r"\R{experiment.R2}", {"experiment.r2": 1})
    assert tex == r"\textbf{??}"
    assert missing == [r"\R{experiment.R2}"]


def test_explain_missing_suggests_the_closest_key() -> None:
    values: dict[str, Any] = {"experiment.slope": 1.0, "experiment.rows": 3}
    assert "did you mean experiment.slope?" in explain_missing(r"\R{explore.slope}", values)
