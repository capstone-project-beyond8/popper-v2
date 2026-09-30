from typing import Any

from popper.communicate.numbers import explain_missing, fill_numbers


def test_fill_known_and_unknown() -> None:
    values = {"experiment.coef": {"value": 0.4213, "ci": [0.3, 0.55]}}
    tex, missing = fill_numbers(r"a \R{experiment.coef} b \R{nope.x}", values)
    assert tex == r"a 0.421 b \textbf{??}"
    assert missing == [r"\R{nope.x}"]


def test_value_interval_and_sample_size_are_separate_macros() -> None:
    values: dict[str, dict[str, Any]] = {
        "experiment.slope": {"value": 0.4213, "ci": [0.3, 0.55], "n": 549},
        "data.rows": {"value": 600},
    }
    tex, missing = fill_numbers(
        r"\R{experiment.slope} (\CI{experiment.slope}, $n = \N{experiment.slope}$)"
        r" \CI{data.rows} \N{data.rows} \CI{data.rows}",
        values,
    )
    assert tex == r"0.421 (0.3--0.55, $n = 549$) \textbf{??} \textbf{??} \textbf{??}"
    assert missing == [r"\CI{data.rows}", r"\N{data.rows}"]


def test_string_values_are_escaped() -> None:
    tex, _ = fill_numbers(r"\R{a.b}", {"a.b": {"value": "50% & up"}})
    assert tex == r"50\% \& up"


def test_dotted_capital_key_is_reported_missing() -> None:
    tex, missing = fill_numbers(r"\R{experiment.R2}", {"experiment.r2": {"value": 1}})
    assert tex == r"\textbf{??}"
    assert missing == [r"\R{experiment.R2}"]


def test_explain_missing_names_the_problem() -> None:
    values: dict[str, dict[str, Any]] = {
        "experiment.slope": {"value": 1.0},
        "experiment.rows": {"value": 3},
    }
    assert explain_missing(r"\N{experiment.slope}", values).endswith("has no n")
    assert explain_missing(r"\CI{experiment.slope}", values).endswith("has no interval")
    assert "did you mean experiment.slope?" in explain_missing(r"\R{explore.slope}", values)
