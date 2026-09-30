from popper.communicate.numbers import fill_numbers, format_value


def test_fill_known_and_unknown() -> None:
    values = {"experiment.coef": {"value": 0.4213, "ci": [0.3, 0.55]}}
    tex, missing = fill_numbers(r"a \R{experiment.coef} b \R{nope.x}", values)
    assert tex == r"a 0.421 [0.3, 0.55] b \textbf{??}"
    assert missing == ["nope.x"]


def test_format_int_and_n() -> None:
    assert format_value({"value": 600, "n": 600}) == "600 (n = 600)"


def test_format_escapes_strings() -> None:
    assert format_value({"value": "50% & up"}) == r"50\% \& up"
