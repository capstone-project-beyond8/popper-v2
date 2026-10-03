from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from popper.communicate.paper import (
    FigureRef,
    Writeup,
    _best_attempt,
    _problems,
    _unknown_figures,
    _violations,
)
from popper.treesearch.engine import Node

SECTIONS = ("abstract", "introduction", "data", "exploration", "hypothesis", "methods")


def _writeup(results: str, figures: list[FigureRef] | None = None) -> Writeup:
    return Writeup(
        title="t",
        **dict.fromkeys(SECTIONS, "x"),
        results=results,
        robustness="r",
        discussion="l",
        conclusion="c",
        figures=figures or [],
    )


def test_best_attempt_prefers_fewest_problems_then_later_and_rejects_empty_candidates() -> None:
    w = _writeup("x")
    first, second, third = (Path(f"w{i}.json") for i in range(3))
    assert _best_attempt([(2, 0, w, first), (1, 1, w, second), (3, 2, w, third)], [])[3] == second
    assert _best_attempt([(1, 0, w, first), (1, 1, w, second)], [])[3] == second
    with pytest.raises(ValueError, match="forbidden: label"):
        _best_attempt([], ["forbidden: label"])


def test_problems_flag_unknown_numbers_and_unbalanced_math() -> None:
    problems = _problems(_writeup(r"$n = \R{a.b}$, 7$ and \R{a.c} costs \$5"), {"a.b": 1}, [])
    assert r"\R{a.c}: no key a.c" in problems
    assert "results: odd number of $ signs" in problems
    assert _problems(_writeup(r"$n = \R{a.b}$ costs \$5"), {"a.b": 1}, []) == ""


def test_problems_flag_unknown_figures_labels_and_file_primitives() -> None:
    node = cast(Node, SimpleNamespace(id="main-000", stage="main", figures=["fit.png"]))
    good = FigureRef(node_id="main-000", file="fit.png", caption="fit", section="main")
    bad = FigureRef(node_id="main-000", file="gone.png", caption="Stable fit", section="main")
    problems = _problems(_writeup(r"see \input{/etc/passwd}", [good, bad]), {}, [node])
    assert "main-000/gone.png does not exist" in problems
    assert "caption-1: the word 'Stable' is an evidence label inserted by code" in problems
    assert r"results: \input is not allowed" in problems
    assert _unknown_figures(_writeup("x", [good, bad]), [node]) == [bad]


@pytest.mark.parametrize("text", [r"\write18{x}", r"\catcode`\~=0", r"\def\a{b}", r"\label{x}"])
def test_violations_catch_primitives_and_structure(text: str) -> None:
    assert _violations(_writeup(text))
    assert _violations(_writeup(r"\inputs are fine, so is \defined")) == []
