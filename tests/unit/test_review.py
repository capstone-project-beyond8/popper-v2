from pathlib import Path
from typing import Any

import pytest
import yaml

from popper.harness.research import parse_research
from popper.harness.store import RunStore
from popper.understand.frame import Frame, Framing
from popper.understand.review import (
    Review,
    Signal,
    apply_review,
    approve_all,
    load_review,
    write_review,
)

COLUMNS = ["score", "hours", "school"]
CTX = parse_research(
    """---
variables:
  score:
    role: outcome
    unit: {value: points, status: proposed, evidence: [marks]}
concepts:
  - id: effort
    name: {value: Effort, status: proposed, evidence: [marks]}
---
marks
"""
)


def _question(qid: str, column: str = "score") -> dict[str, Any]:
    return {"id": qid, "text": qid, "objective": "o", "outcome_candidate": column}


def _frame(*questions: str) -> Frame:
    framing = Framing.model_validate(
        {
            "title": "t",
            "problem": "p",
            "questions": [_question(q) for q in questions],
            "scope": {"inside": [], "outside": []},
            "unknowns": [],
            "directions": [{"id": "d1", "text": "x", "origin": "o", "competing_explanations": []}],
        }
    )
    return Frame(CTX, framing, [], "attempt-000000")


def _review(frame: Frame, **signals: Signal) -> Review:
    base = approve_all(frame)
    return Review(items={**base.items, **{k.replace("__", "."): v for k, v in signals.items()}})


def test_signal_effects() -> None:
    frame = _frame("q1", "q2")
    unit, name = "variables.score.unit", "concepts.effort"
    review = _review(
        frame,
        **{
            "variables__score__unit": Signal(signal="reject"),
            "concepts__effort": Signal(signal="edit", value={"name": "Study effort"}),
            "questions__q1": Signal(signal="edit", value={**_question("zzz"), "text": "new"}),
            "questions__q2": Signal(signal="reject"),
        },
    )
    out = apply_review(frame, review, COLUMNS)
    assert out.research.variables["score"].unit.status == "unknown"
    assert out.rejected[unit] == "points" and out.rejected["questions.q2"] == _question("q2")
    assert out.research.concepts[0].name.status == "confirmed"
    assert out.research.concepts[0].name.value == "Study effort"
    assert [(q.id, q.text) for q in out.framing.questions] == [("q1", "new")]
    assert (
        out.needs_revision and name in out.guidance() and "questions.q2: reject" in out.guidance()
    )
    bare = apply_review(frame, approve_all(frame), COLUMNS)
    assert bare.research.variables["score"].unit.status == "confirmed"
    assert bare.research.variables["score"].meaning.status == "unknown"  # nothing to confirm
    assert not bare.needs_revision and not bare.rejected
    assert apply_review(
        frame, _review(frame).model_copy(update={"note": "more"}), COLUMNS
    ).needs_revision


def test_rejected_concept_leaves_the_frame() -> None:
    frame = _frame("q1")
    review = _review(frame, concepts__effort=Signal(signal="reject"))
    out = apply_review(frame, review, COLUMNS)
    assert out.research.concepts == [] and "concepts.effort" in out.rejected


def test_signal_addresses_question_by_id_after_reorder() -> None:
    review = _review(_frame("a", "b"), questions__b=Signal(signal="reject"))
    out = apply_review(_frame("b", "a"), review, COLUMNS)
    assert [q.id for q in out.framing.questions] == ["a"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("missing", "missing"),
        ("unknown", "unknown"),
        ("badcolumn", "not in the data"),
    ],
)
def test_invalid_review(change: str, message: str) -> None:
    frame = _frame("q1")
    review = approve_all(frame)
    if change == "missing":
        del review.items["questions.q1"]
    elif change == "unknown":
        review.items["questions.nope"] = Signal(signal="approve")
    else:
        review.items["questions.q1"] = Signal(signal="edit", value=_question("q1", column="ghost"))
    with pytest.raises(ValueError, match=message):
        apply_review(frame, review, COLUMNS)


def test_edit_needs_value_and_valid_type(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="needs a value"):
        Signal(signal="edit")
    frame = _frame("q1")
    review = _review(frame, variables__score__unit=Signal(signal="edit", value=["not", "text"]))
    with pytest.raises(ValueError, match="variables.score.unit"):
        apply_review(frame, review, COLUMNS)
    path = tmp_path / "r.yaml"
    path.write_text("items: {a: {signal: maybe}}", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid review"):
        load_review(path)


def test_written_review_round_trips(tmp_path: Path) -> None:
    example = Path(__file__).resolve().parents[2] / "examples" / "student_performance"
    run = RunStore.create(tmp_path, example / "research.md", example / "data.csv")
    frame = _frame("q1")
    (run.path("understand") / frame.attempt).mkdir(parents=True)
    path = write_review(frame, run)
    written = yaml.safe_load(path.read_text("utf-8"))
    assert written["items"]["questions.q1"]["signal"] == "approve"
    assert written["items"]["variables.score.unit"]["status"] == "proposed"
    assert set(load_review(path).items) == set(approve_all(frame).items)
