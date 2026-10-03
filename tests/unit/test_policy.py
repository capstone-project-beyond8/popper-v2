import random
from pathlib import Path
from typing import Literal

from popper.harness.config import Search
from popper.strategies.treesearch.engine import Node, choose_action, select_best


class _Rng(random.Random):
    def __init__(self, value: float) -> None:
        super().__init__(0)
        self._value = value

    def random(self) -> float:
        return self._value


def _node(
    id: str, status: Literal["ok", "buggy"] = "ok", score: float | None = None, depth: int = 0
) -> Node:
    return Node(
        id=id,
        stage="s",
        parent=None,
        kind="draft",
        debug_depth=depth,
        dir=Path(id),
        code="",
        status=status,
        score=score,
        goal_met=False,
        analysis="",
        results={},
        figures=[],
        reason="",
    )


def _search(num_drafts: int = 3) -> Search:
    return Search(
        num_drafts=num_drafts, debug_prob=0.5, max_debug_depth=2, steps_per_stage=10, max_turns=12
    )


def test_drafts_first() -> None:
    assert choose_action([_node("a", "buggy")], _search(), random.Random(0), 10) == ("draft", None)


def test_debugs_buggy_leaf_when_no_ok_node() -> None:
    nodes = [_node(c, "buggy") for c in "abc"]
    kind, target = choose_action(nodes, _search(), random.Random(0), 10)
    assert kind == "debug" and target in nodes


def test_skips_leaf_at_max_debug_depth() -> None:
    nodes = [_node("a", "buggy", depth=2)]
    assert choose_action(nodes, _search(num_drafts=1), random.Random(0), 10) == ("draft", None)


def test_improves_best_when_rng_says_so() -> None:
    nodes = [_node("a", score=4), _node("b", score=7), _node("c", "buggy")]
    kind, target = choose_action(nodes, _search(num_drafts=1), _Rng(0.9), 10)
    assert kind == "improve" and target is nodes[1]


def test_short_stage_keeps_a_step_for_debugging() -> None:
    nodes = [_node("a", "buggy"), _node("b", "buggy")]
    kind, target = choose_action(nodes, _search(num_drafts=3), random.Random(0), 3)
    assert kind == "debug" and target in nodes


def test_single_step_stage_still_drafts() -> None:
    assert choose_action([], _search(num_drafts=3), random.Random(0), 1) == ("draft", None)


def test_select_best_ignores_buggy_and_breaks_ties_by_order() -> None:
    nodes = [_node("x", "buggy", score=9), _node("a", score=6), _node("b", score=6)]
    assert select_best(nodes) is nodes[1]
