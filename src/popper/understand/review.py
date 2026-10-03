"""Researcher review of the research frame: signals per item, applied by code."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from popper.harness.session import Harness
from popper.harness.store import RunStore
from popper.harness.validation import format_errors
from popper.science.descriptive import DescriptiveReport
from popper.science.research import Entry, ResearchContext, Variable, check_columns
from popper.understand.frame import (
    Direction,
    Frame,
    Framing,
    Question,
    framing_warnings,
    save_frame,
    understand,
)

_CONCEPT_ATTRS = ("name", "definition")
_ASSUMPTION_ATTRS = ("description", "confounder")


class Signal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    signal: Literal["approve", "edit", "reject", "unknown"]
    value: Any = None
    note: str = ""

    @model_validator(mode="after")
    def _edit_has_value(self) -> "Signal":
        if self.signal == "edit" and self.value is None:
            raise ValueError("an edit signal needs a value")
        return self


class Review(BaseModel):
    model_config = ConfigDict(extra="ignore")

    frame: str = ""
    items: dict[str, Signal]
    note: str = ""


@dataclass(frozen=True)
class ReviewOutcome:
    research: ResearchContext
    framing: Framing
    rejected: dict[str, object]
    needs_revision: bool
    review: Review

    def guidance(self) -> str:
        """The signals and notes a revision session needs, with the framing as it now stands."""
        lines = ["The researcher reviewed the frame."]
        if self.review.note:
            lines.append(f"Researcher note: {self.review.note}")
        for key, sig in self.review.items.items():
            if sig.signal != "approve" or sig.note:
                value = "" if sig.value is None else f" value={json.dumps(sig.value)}"
                note = f" note={sig.note!r}" if sig.note else ""
                lines.append(f"- {key}: {sig.signal}{value}{note}")
        lines.append(f"Current framing:\n{json.dumps(self.framing.model_dump(), indent=2)}")
        return "\n".join(lines)


def _status(entries: Sequence[Entry[Any]]) -> str:
    statuses = {e.status for e in entries}
    return next((s for s in ("unknown", "proposed") if s in statuses), "confirmed")


def _grouped(model: BaseModel, attrs: Sequence[str]) -> dict[str, Any]:
    entries = [getattr(model, a) for a in attrs]
    return {
        "value": {a: e.value for a, e in zip(attrs, entries, strict=True)},
        "status": _status(entries),
        "evidence": [q for e in entries for q in e.evidence],
    }


def _items(frame: Frame) -> dict[str, dict[str, Any]]:
    """Every reviewable item, keyed by a stable id."""
    items: dict[str, dict[str, Any]] = {}
    for column, variable in frame.research.variables.items():
        for attr in Variable.model_fields:
            entry = getattr(variable, attr)
            if entry.status != "confirmed":
                items[f"variables.{column}.{attr}"] = entry.model_dump()
    for assumption in frame.research.assumptions:
        grouped = _grouped(assumption, _ASSUMPTION_ATTRS)
        if grouped["status"] != "confirmed":
            items[f"assumptions.{assumption.id}"] = grouped
    for concept in frame.research.concepts:
        items[f"concepts.{concept.id}"] = _grouped(concept, _CONCEPT_ATTRS)
    for q in frame.framing.questions:
        items[f"questions.{q.id}"] = {"value": q.model_dump(), "status": "proposed", "evidence": []}
    for d in frame.framing.directions:
        items[f"directions.{d.id}"] = {
            "value": d.model_dump(),
            "status": "proposed",
            "evidence": [],
        }
    return items


def write_review(frame: Frame, run: RunStore) -> Path:
    """Write `review.yaml` into the frame's attempt folder; an existing file is kept."""
    path = run.path("understand", frame.attempt, "review.yaml")
    if path.exists():
        return path
    items = {key: {**item, "signal": "approve", "note": ""} for key, item in _items(frame).items()}
    text = yaml.safe_dump(
        {"frame": frame.attempt, "note": "", "warnings": frame.warnings, "items": items},
        sort_keys=False,
        allow_unicode=True,
    )
    return run.write_text(path.relative_to(run.root).as_posix(), text)


def approve_all(frame: Frame) -> Review:
    return Review(frame=frame.attempt, items={key: Signal(signal="approve") for key in _items(frame)})


def load_review(path: Path) -> Review:
    try:
        return Review.model_validate(yaml.safe_load(path.read_text("utf-8")))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path}: not valid YAML: {exc}") from exc
    except ValidationError as exc:
        raise ValueError(f"{path}: invalid review: {format_errors(exc)}") from exc


def _apply_entries[M: BaseModel](model: M, key: str, attrs: Sequence[str], sig: Signal) -> M:
    """The model after one signal; whole-item rejection is handled by the caller."""
    edits = sig.value if sig.signal == "edit" else {}
    if not isinstance(edits, dict) or not set(edits) <= set(attrs):
        raise ValueError(f"{key}: value must be a mapping of {', '.join(attrs)}")
    merged = model.model_dump()
    for attr in attrs:
        entry: Entry[Any] = getattr(model, attr)
        if sig.signal == "approve" and entry.value is not None:
            merged[attr] = {**entry.model_dump(), "status": "confirmed"}
        elif sig.signal == "edit" and attr in edits:
            merged[attr] = {"value": edits[attr], "status": "confirmed"}
        elif sig.signal in ("unknown", "reject"):
            merged[attr] = {}
    try:
        return type(model).model_validate(merged)
    except ValidationError as exc:
        raise ValueError(f"{key}: invalid value: {exc.errors()[0]['msg']}") from exc


def _grouped_value(model: BaseModel, attrs: Sequence[str]) -> dict[str, Any]:
    return {a: getattr(model, a).value for a in attrs}


def apply_review(frame: Frame, review: Review, columns: Sequence[str]) -> ReviewOutcome:
    """The frame after the signals; ValueError names the first problem."""
    if review.frame != frame.attempt:
        raise ValueError(
            f"the review is for frame {review.frame or '(none)'}, "
            f"but the pending frame is {frame.attempt}"
        )
    expected = set(_items(frame))
    missing, unknown = expected - set(review.items), set(review.items) - expected
    if missing or unknown:
        raise ValueError(
            "review items do not match the written review: "
            + "; ".join(
                part
                for part in (
                    f"missing {', '.join(sorted(missing))}" if missing else "",
                    f"unknown {', '.join(sorted(unknown))}" if unknown else "",
                )
                if part
            )
        )
    rejected: dict[str, object] = {}
    ctx, framing = frame.research, frame.framing
    variables = dict(ctx.variables)
    concepts = {c.id: c for c in ctx.concepts}
    assumptions = {a.id: a for a in ctx.assumptions}
    questions = {q.id: q for q in framing.questions}
    directions = {d.id: d for d in framing.directions}
    for key, sig in review.items.items():
        kind, _, rest = key.partition(".")
        if kind == "variables":
            column, _, attr = rest.rpartition(".")
            old = getattr(variables[column], attr)
            if sig.signal == "reject" and old.value is not None:
                rejected[key] = old.value
            sig_value = {attr: sig.value} if sig.signal == "edit" else None
            variables[column] = _apply_entries(
                variables[column], key, [attr], Signal(signal=sig.signal, value=sig_value)
            )
        elif kind in ("concepts", "assumptions"):
            group: dict[str, Any] = concepts if kind == "concepts" else assumptions
            attrs = _CONCEPT_ATTRS if kind == "concepts" else _ASSUMPTION_ATTRS
            if sig.signal == "reject":
                rejected[key] = _grouped_value(group[rest], attrs)
                del group[rest]
            else:
                group[rest] = _apply_entries(group[rest], key, attrs, sig)
        else:
            model = Question if kind == "questions" else Direction
            items: dict[str, Any] = questions if kind == "questions" else directions
            if sig.signal == "reject":
                rejected[key] = items[rest].model_dump()
            if sig.signal in ("reject", "unknown"):
                del items[rest]
            elif sig.signal == "edit":
                if not isinstance(sig.value, dict):
                    raise ValueError(f"{key}: value must be a mapping")
                try:
                    items[rest] = model.model_validate({**sig.value, "id": rest})
                except ValidationError as exc:
                    raise ValueError(f"{key}: invalid value: {exc.errors()[0]['msg']}") from exc
    context = ctx.model_copy(
        update={
            "variables": variables,
            "concepts": list(concepts.values()),
            "assumptions": list(assumptions.values()),
        }
    )
    revised = framing.model_copy(
        update={"questions": list(questions.values()), "directions": list(directions.values())}
    )
    problems = check_columns(context, columns) + [
        f"questions.{q.id}: column {q.outcome_candidate!r} is not in the data"
        for q in revised.questions
        if q.outcome_candidate is not None and q.outcome_candidate not in columns
    ]
    if problems:
        raise ValueError("; ".join(problems))
    needs_revision = bool(review.note) or any(
        s.signal in ("edit", "reject") or s.note for s in review.items.values()
    )
    return ReviewOutcome(context, revised, rejected, needs_revision, review)


def commit_review(h: Harness, outcome: ReviewOutcome, ida: DescriptiveReport) -> Frame:
    """The reviewed frame: one revision session when the signals call for it, else as is."""
    review = outcome.review.model_dump(mode="json")
    if outcome.needs_revision:
        return understand(
            h,
            outcome.research,
            ida,
            guidance=outcome.guidance(),
            rejected=outcome.rejected,
            review=review,
        )
    return save_frame(
        h.run,
        h.run.new_attempt("understand"),
        outcome.research,
        outcome.framing,
        framing_warnings(outcome.research, outcome.framing),
        [],
        review,
    )
