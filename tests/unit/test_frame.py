from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

from popper.harness.config import load_config
from popper.harness.descriptive import DescriptiveReport, describe_table
from popper.harness.llm import FakeLLM, ToolCall
from popper.harness.research import ResearchContext, parse_research
from popper.harness.session import Harness
from popper.harness.store import RunStore
from popper.treesearch.engine import StageFailed
from popper.understand.frame import (
    FramePatch,
    Framing,
    apply_patch,
    check_evidence,
    framing_warnings,
    understand,
)

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "student_performance"
BODY = "Study time may drive exam scores."
TEXT = f"""---
variables:
  exam_score: {{role: outcome}}
  school: {{role: cluster, type: categorical}}
concepts:
  - id: effort
    name: Effort
constraints:
  excluded: [gender]
---
{BODY}
"""
CTX = parse_research(TEXT)
IDA = describe_table(
    pd.DataFrame({"exam_score": ["1", "2"], "school": ["a", "b"], "study_hours_week": ["3", "4"]})
)


def _proposed(value: object, *evidence: str) -> dict[str, Any]:
    return {"value": value, "status": "proposed", "evidence": list(evidence)}


def _framing(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "title": "t",
        "problem": "p",
        "questions": [
            {"id": "q1", "text": "x", "objective": "o", "outcome_candidate": "exam_score"}
        ],
        "scope": {"inside": ["a"], "outside": ["b"]},
        "unknowns": [],
        "directions": [
            {"id": "d1", "text": "Fit a trend", "origin": "o", "competing_explanations": []}
        ],
    }
    return {**base, **changes}


def test_check_evidence() -> None:
    assert check_evidence("Study time may drive", BODY, IDA)
    assert check_evidence("c000_mean", BODY, IDA)
    assert not check_evidence("study time", BODY, IDA)
    assert not check_evidence("Study time", BODY, IDA)
    assert check_evidence("time may drive", BODY, IDA)
    assert not check_evidence("c999_mean", BODY, IDA)
    assert not check_evidence("", BODY, IDA)


def test_apply_patch_valid() -> None:
    patch = FramePatch.model_validate(
        {
            "variables": {"study_hours_week": {"unit": _proposed("hours", "c002_mean")}},
            "concepts": [{"id": "effort", "definition": _proposed("time spent", "Study time may drive")}],
        }
    )
    out = apply_patch(CTX, patch, BODY, IDA)
    assert out.variables["study_hours_week"].unit.status == "proposed"
    assert out.concepts[0].definition.value == "time spent"
    assert out.concepts[0].name.value == "Effort"


def test_evidence_quoting_a_result_key_with_its_value_cites_the_key() -> None:
    patch = FramePatch.model_validate(
        {"variables": {"study_hours_week": {"unit": _proposed("hours", "c002_mean = 3.5")}}}
    )
    out = apply_patch(CTX, patch, BODY, IDA)
    assert out.variables["study_hours_week"].unit.evidence == ["c002_mean"]


def test_column_key_cites_the_column_and_every_error_is_reported() -> None:
    patch = FramePatch.model_validate(
        {"variables": {"study_hours_week": {"unit": _proposed("hours", "c002 'study_hours_week'")}}}
    )
    assert apply_patch(CTX, patch, BODY, IDA).variables["study_hours_week"].unit.evidence == [
        "c002"
    ]
    bad = FramePatch.model_validate(
        {"variables": {"school": {"colour": _proposed("x", "c000_mean")}, "nope": {}}}
    )
    with pytest.raises(ValueError, match=r"(?s)colour.*allowed: meaning.*variables\.nope"):
        apply_patch(CTX, bad, BODY, IDA)


def _var(column: str, **attrs: Any) -> dict[str, Any]:
    return {"variables": {column: attrs}}


@pytest.mark.parametrize(
    ("patch", "rejected", "needle"),
    [
        (_var("exam_score", role=_proposed("covariate", "c000_mean")), {}, "confirmed"),
        (_var("school", unit={"value": "x", "status": "confirmed"}), {}, "confirmed"),
        (_var("nope", unit=_proposed("x", "c000_mean")), {}, "variables.nope"),
        (_var("school", unit=_proposed("x", "invented quote")), {}, "evidence"),
        (
            _var("school", unit=_proposed("x", "c000_mean")),
            {"variables.school.unit": "x"},
            "rejected",
        ),
        (
            {"concepts": [{"id": "gone", "name": _proposed("n", "c000_mean")}]},
            {"concepts.gone": 0},
            "concepts.gone",
        ),
        (_var("school", colour=_proposed("x", "c000_mean")), {}, "colour"),
    ],
)
def test_apply_patch_rejects(
    patch: dict[str, Any], rejected: dict[str, object], needle: str
) -> None:
    with pytest.raises(ValueError, match=needle):
        apply_patch(CTX, FramePatch.model_validate(patch), BODY, IDA, rejected)


def test_framing_ids() -> None:
    Framing.model_validate(_framing())
    clash = _framing(
        directions=[{"id": "q1", "text": "t", "origin": "o", "competing_explanations": []}]
    )
    malformed = _framing(questions=[{**_framing()["questions"][0], "id": "Q-1"}])
    for bad in (clash, malformed):
        with pytest.raises(ValidationError):
            Framing.model_validate(bad)


def test_framing_warnings() -> None:
    assert framing_warnings(CTX, Framing.model_validate(_framing())) == []
    patch = FramePatch.model_validate(
        _var("study_hours_week", role=_proposed("post_outcome", "c002_mean"))
    )
    ctx = apply_patch(CTX, patch, BODY, IDA)
    questions = [
        {"id": "q1", "text": "x", "objective": "o", "outcome_candidate": "study_hours_week"},
        {"id": "q2", "text": "x", "objective": "o", "outcome_candidate": "gender"},
    ]
    first = {"id": "d1", "text": "Fit a  Trend", "origin": "o", "competing_explanations": []}
    second = {**first, "id": "d2", "text": "fit a trend"}
    framing = Framing.model_validate(_framing(questions=questions, directions=[first, second]))
    warnings = framing_warnings(ctx, framing)
    assert len(warnings) == 3
    assert "post_outcome" in warnings[0]
    assert "excluded" in warnings[1]
    assert "duplicates" in warnings[2]


def _harness(tmp_path: Path, llm: FakeLLM, researcher: Any = None) -> Harness:
    run = RunStore.create(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv")
    return Harness(load_config(env={}), llm, run, researcher=researcher)


def _context() -> tuple[ResearchContext, DescriptiveReport]:
    ctx = parse_research((EXAMPLE / "research.md").read_text("utf-8"))
    frame = pd.read_csv(EXAMPLE / "data.csv", dtype=str, keep_default_na=False)
    return ctx, describe_table(frame, ctx)


def _scripted(replies: Iterator[tuple[ToolCall, ...]]) -> FakeLLM:
    return FakeLLM(lambda req: next(replies))


def _submit(call_id: str, quote: str) -> tuple[ToolCall, ...]:
    patch = _var("sleep_hours", unit=_proposed("hours", quote))
    return (ToolCall(call_id, "submit_frame", {"patch": patch, "framing": _framing()}),)


def test_session_retries_fabricated_evidence(tmp_path: Path) -> None:
    ctx, ida = _context()
    replies = iter([_submit("a", "not in the text"), _submit("b", "c005_mean")])
    fake = FakeLLM(lambda req: next(replies))
    h = _harness(tmp_path, fake)
    frame = understand(h, ctx, ida)
    result = fake.calls[1].messages[-1].tool_results[0]
    assert result.status == "error" and "evidence" in result.text
    assert frame.research.variables["sleep_hours"].unit.value == "hours"
    assert h.run.committed("frame") is not None


def test_session_fails_after_rejected_submits(tmp_path: Path) -> None:
    ctx, ida = _context()
    fake = FakeLLM(lambda req: _submit("a", "not in the text"))
    with pytest.raises(StageFailed):
        understand(_harness(tmp_path, fake), ctx, ida)


def test_ask_researcher(tmp_path: Path) -> None:
    ctx, ida = _context()
    args = {"question": "Unit?", "proposed_answer": "hours", "item": "variables.sleep_hours.unit"}
    ask = (ToolCall("q", "ask_researcher", args),)
    for name, researcher, text, status, value in (
        ("none", None, "No researcher is available", "proposed", "hours"),
        ("some", lambda q, p: "hrs", "hrs", "confirmed", "hrs"),
    ):
        replies = iter([ask, _submit("s", "c005_mean")])
        fake = _scripted(replies)
        frame = understand(_harness(tmp_path / name, fake, researcher), ctx, ida)
        assert text in fake.calls[1].messages[-1].tool_results[0].text
        unit = frame.research.variables["sleep_hours"].unit
        assert (unit.status, unit.value) == (status, value)


def test_answers_create_variables_and_unapplied_ones_warn(tmp_path: Path) -> None:
    ctx, ida = _context()
    answers = {
        "variables.gender.meaning": "pupil gender",
        "variables.ghost.unit": "x",
        "concepts.effort.name": "x",
        "": "x",
        "variables.sleep_hours.range": "[5",
    }
    asks = tuple(
        ToolCall(
            f"q{i}", "ask_researcher", {"question": f"Q{i}", "proposed_answer": "p", "item": k}
        )
        for i, k in enumerate(answers)
    )
    replies = iter([asks, _submit("s", "c005_mean")])
    h = _harness(tmp_path, _scripted(replies), lambda q, p: answers[list(answers)[int(q[1:])]])
    h.config.understand.max_questions = 9
    frame = understand(h, ctx, ida)
    meaning = frame.research.variables["gender"].meaning
    assert (meaning.status, meaning.value) == ("confirmed", "pupil gender")
    assert len(frame.warnings) == 4
    assert all("was not applied" in w for w in frame.warnings)
