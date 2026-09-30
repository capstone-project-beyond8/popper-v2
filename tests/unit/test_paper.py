from popper.communicate.paper import Writeup, _problems

SECTIONS = ("abstract", "introduction", "data", "exploration", "hypothesis", "methods")


def _writeup(results: str) -> Writeup:
    return Writeup(
        title="t",
        **dict.fromkeys(SECTIONS, "x"),
        results=results,
        limitations="l",
        figures=[],
    )


def test_problems_flag_unknown_numbers_and_unbalanced_math() -> None:
    problems = _problems(_writeup(r"$n = \R{a.b}$, 7$ and \R{a.c} costs \$5"), {"a.b": 1})
    assert r"\R{a.c}: no key a.c" in problems
    assert "results: odd number of $ signs" in problems
    assert _problems(_writeup(r"$n = \R{a.b}$ costs \$5"), {"a.b": 1}) == ""
