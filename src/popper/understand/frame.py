"""Understand: one Theorist session builds the research frame from the research context."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from popper.harness.agent import Tool, agent_loop
from popper.harness.context import ARTIFACT_CHARS, RESEARCH_CHARS, fence, part, valid_names
from popper.harness.descriptive import DescriptiveReport, format_description
from popper.harness.prompts import load_prompt
from popper.harness.research import (
    UNUSABLE_ROLES,
    Assumption,
    Concept,
    Entry,
    ResearchContext,
    Variable,
    format_errors,
    render_research,
)
from popper.harness.session import Harness
from popper.harness.store import RunStore
from popper.treesearch.engine import StageFailed
from popper.treesearch.tools import node_tools

_ID = re.compile(r"^[a-z][a-z0-9_]*$")
_YAML_ATTRIBUTES = {"range", "levels", "order"}
_NO_RESEARCHER = "No researcher is available; leave the item proposed or unknown."


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Question(_Model):
    id: str
    text: str
    objective: str
    outcome_candidate: str | None = None


class Scope(_Model):
    inside: list[str]
    outside: list[str]


class Direction(_Model):
    id: str
    text: str
    origin: str
    competing_explanations: list[str]


class Framing(_Model):
    title: str
    problem: str
    questions: list[Question]
    scope: Scope
    unknowns: list[str]
    directions: list[Direction]

    @model_validator(mode="after")
    def _ids(self) -> "Framing":
        ids = [*(q.id for q in self.questions), *(d.id for d in self.directions)]
        bad = [i for i in ids if not _ID.match(i)]
        if bad:
            raise ValueError(f"ids must match {_ID.pattern}: {', '.join(bad)}")
        if len(set(ids)) != len(ids):
            raise ValueError("question and direction ids must be unique")
        return self


class FramePatch(_Model):
    variables: dict[str, dict[str, Entry[Any]]] = {}
    concepts: list[Concept] = []
    assumptions: list[Assumption] = []


@dataclass
class Frame:
    research: ResearchContext
    framing: Framing
    warnings: list[str] = field(default_factory=list)
    attempt: str = ""


_MIN_QUOTE_WORDS = 3


def check_evidence(evidence: str, body: str, ida: DescriptiveReport) -> bool:
    """Evidence is an exact quote of at least three words of the body, a descriptive result key
    or a column key of the description."""
    return (
        (len(evidence.split()) >= _MIN_QUOTE_WORDS and evidence in body)
        or evidence in ida.results
        or evidence in {c["key"] for c in ida.layout["columns"]}
    )


def _cited(evidence: str, ida: DescriptiveReport) -> str:
    """A key quoted with its value or description line, as in c000_mean=12.5, cites the key alone."""
    key = evidence.split("=", 1)[0].split(maxsplit=1)[0] if evidence.strip() else evidence
    return key if check_evidence(key, "", ida) else evidence


def _merge[M: BaseModel](
    model: M, label: str, changes: Mapping[str, Entry[Any]], body: str, ida: DescriptiveReport,
    rejected: Mapping[str, object],
) -> M:  # fmt: skip
    """The model with each changed entry replaced; confirmed entries never change."""
    merged = model.model_dump()
    for attr, entry in changes.items():
        where = f"{label}.{attr}"
        current = getattr(model, attr, None)
        if not isinstance(current, Entry):
            allowed = ", ".join(a for a, v in type(model).model_fields.items() if a != "id")
            raise ValueError(f"{where}: unknown attribute; allowed: {allowed}")
        if entry.status == "confirmed":
            raise ValueError(
                f"{where}: an agent cannot set status confirmed (a bare value means confirmed); "
                'send {"value": ..., "status": "proposed", "evidence": [...]} instead'
            )
        if current.status == "confirmed":
            if entry.value == current.value:
                continue
            raise ValueError(f"{where}: confirmed by the researcher and cannot be changed")
        if where in rejected and rejected[where] == entry.value:
            raise ValueError(f"{where}: this value was rejected by the researcher")
        entry = entry.model_copy(update={"evidence": [_cited(q, ida) for q in entry.evidence]})
        for quote in entry.evidence:
            if not check_evidence(quote, body, ida):
                raise ValueError(
                    f"{where}: evidence {quote!r} is neither an exact quote of the research "
                    "body (at least three words), descriptive result key or column key; "
                    + valid_names(ida.results, "Data description")
                    + "; "
                    + valid_names(
                        (c["key"] for c in ida.layout["columns"]), "Data description columns"
                    )
                )
        merged[attr] = entry.model_dump()
    try:
        return type(model).model_validate(merged)
    except ValidationError as exc:
        raise ValueError(f"{label}: {format_errors(exc)}") from exc


def _set(model: BaseModel, *attrs: str) -> dict[str, Entry[Any]]:
    """The entries the agent actually supplied."""
    return {a: getattr(model, a) for a in attrs if a in model.model_fields_set}


def apply_patch(
    ctx: ResearchContext,
    patch: FramePatch,
    body: str,
    ida: DescriptiveReport,
    rejected: Mapping[str, object] = {},
) -> ResearchContext:
    """The context with the patch applied; ValueError names every offending entry, one per line."""
    columns = {c["name"] for c in ida.layout["columns"]}
    errors: list[str] = []

    def merge[M: BaseModel](
        model: M, label: str, changes: Mapping[str, Entry[Any]], refused: str | None = None
    ) -> M:
        try:
            if refused is not None:
                raise ValueError(f"{label}: {refused}")
            return _merge(model, label, changes, body, ida, rejected)
        except ValueError as exc:
            errors.append(str(exc))
            return model

    variables = dict(ctx.variables)
    for column, changes in patch.variables.items():
        variables[column] = merge(
            variables.get(column, Variable()),
            f"variables.{column}",
            changes,
            None
            if column in columns
            else "column is not in the data; " + valid_names(columns, "Data description columns"),
        )
    concepts = {c.id: c for c in ctx.concepts}
    for concept in patch.concepts:
        concepts[concept.id] = merge(
            concepts.get(concept.id, Concept(id=concept.id)),
            f"concepts.{concept.id}",
            _set(concept, "name", "definition"),
            "this concept was rejected by the researcher"
            if f"concepts.{concept.id}" in rejected
            else None,
        )
    assumptions = {a.id: a for a in ctx.assumptions}
    for assumption in patch.assumptions:
        assumptions[assumption.id] = merge(
            assumptions.get(assumption.id, Assumption(id=assumption.id)),
            f"assumptions.{assumption.id}",
            _set(assumption, "description", "confounder"),
            "rejected by the researcher" if f"assumptions.{assumption.id}" in rejected else None,
        )
    if errors:
        raise ValueError("\n".join(errors))
    return ctx.model_copy(
        update={
            "variables": variables,
            "concepts": list(concepts.values()),
            "assumptions": list(assumptions.values()),
        }
    )


def _check_framing(framing: Framing, columns: set[str], rejected: Mapping[str, object]) -> None:
    for q in framing.questions:
        if f"questions.{q.id}" in rejected:
            raise ValueError(f"questions.{q.id}: this question was rejected by the researcher")
        if q.outcome_candidate is not None and q.outcome_candidate not in columns:
            raise ValueError(
                f"questions.{q.id}: column {q.outcome_candidate!r} is not in the data; "
                + valid_names(columns, "Data description columns")
            )
    for d in framing.directions:
        if f"directions.{d.id}" in rejected:
            raise ValueError(f"directions.{d.id}: this direction was rejected by the researcher")


def framing_warnings(ctx: ResearchContext, framing: Framing) -> list[str]:
    """Computed facts about the framing; shown in review and the paper, never blocking."""
    out: list[str] = []
    excluded = ctx.constraints.excluded.value or []
    for q in framing.questions:
        column = q.outcome_candidate
        if column is None:
            continue
        variable = ctx.variables.get(column)
        role = variable.role.value if variable else None
        if role in UNUSABLE_ROLES:
            out.append(f"question {q.id}: outcome candidate {column!r} has role {role}")
        if column in excluded:
            out.append(f"question {q.id}: outcome candidate {column!r} is an excluded column")
    seen: dict[str, str] = {}
    for d in framing.directions:
        key = " ".join(d.text.casefold().split())
        if key in seen:
            out.append(f"directions {seen[key]} and {d.id} are duplicates")
        seen.setdefault(key, d.id)
    return out


def _schema(**props: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
        "required": [k for k in props if k != "item"],
    }


def _answered(
    ctx: ResearchContext, asked: list[dict[str, Any]], columns: set[str]
) -> tuple[ResearchContext, list[str]]:
    """Apply researcher answers to attributes as confirmed entries; report each one not applied."""
    variables = dict(ctx.variables)
    problems: list[str] = []
    for q in asked:
        answer, item = q["answer"], str(q.get("item") or "")
        if answer is None or not answer.strip():
            continue
        why = f"researcher answer to {q['question']!r} was not applied: "
        parts = item.split(".")
        if len(parts) != 3 or parts[0] != "variables":
            problems.append(f"{why}item {item!r} is not variables.<column>.<attribute>")
            continue
        _, column, attr = parts
        if column not in columns:
            problems.append(f"{why}column {column!r} is not in the data")
            continue
        variable = variables.get(column, Variable())
        current = getattr(variable, attr, None)
        if not isinstance(current, Entry):
            problems.append(f"{why}unknown attribute {attr!r}")
            continue
        if current.status == "confirmed":
            problems.append(f"{why}{item} is already confirmed")
            continue
        try:
            value = yaml.safe_load(answer) if attr in _YAML_ATTRIBUTES else answer
            merged = variable.model_dump()
            merged[attr] = {"value": value, "status": "confirmed"}
            variables[column] = Variable.model_validate(merged)
        except (ValidationError, yaml.YAMLError):
            problems.append(f"{why}{answer!r} is not a valid value for {item}")
    return ctx.model_copy(update={"variables": variables}), problems


def _tools(
    h: Harness,
    attempt: Path,
    research: ResearchContext,
    ida: DescriptiveReport,
    rejected: Mapping[str, object],
    asked: list[dict[str, Any]],
    result: dict[str, Any],
) -> list[Tool]:
    columns = {c["name"] for c in ida.layout["columns"]}
    readers = [t for t in node_tools(h, {}, attempt) if t.name == "read_artifact"]

    def ask_researcher(args: dict[str, Any]) -> str:
        if h.researcher is None:
            return _NO_RESEARCHER
        if len(asked) >= h.config.understand.max_questions:
            raise ValueError("question limit reached; leave the item proposed or unknown")
        question, proposed = str(args["question"]), str(args["proposed_answer"])
        answer = h.researcher(question, proposed)
        asked.append(
            {
                "question": question,
                "proposed_answer": proposed,
                "item": args.get("item"),
                "answer": answer,
            }
        )
        return "The researcher does not know." if answer is None else f"Researcher: {answer}"

    def submit_frame(args: dict[str, Any]) -> str:
        try:
            patch = FramePatch.model_validate(args.get("patch") or {})
            framing = Framing.model_validate(args.get("framing"))
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        _check_framing(framing, columns, rejected)
        result["research"] = apply_patch(research, patch, research.body, ida, rejected)
        result["framing"] = framing
        return "Frame accepted."

    tools = [
        *readers,
        Tool(
            "ask_researcher",
            "Ask the researcher one question about the study. They can accept your proposed "
            "answer, give their own, or say they do not know. Their answer becomes confirmed "
            "for the item named in `item`.",
            _schema(
                question="The question.",
                proposed_answer="Your best proposed answer.",
                item="Optional attribute the answer settles, as variables.<column>.<attribute>.",
            ),
            ask_researcher,
        ),
        Tool(
            "submit_frame",
            "Submit the frame: `patch` (new or changed proposed or unknown research-context "
            "entries) and `framing`. Call it once, last. A rejected submit returns the reason.",
            {
                "type": "object",
                "properties": {
                    "patch": {
                        "type": "object",
                        "description": "{variables: {column: {attribute: {value, status, "
                        "evidence}}}, concepts: [{id, name, definition}], assumptions: "
                        "[{id, description, confounder}]}. Entries are {value, status: "
                        "proposed|unknown, evidence: [exact quotes of the body or result keys]}.",
                    },
                    "framing": {
                        "type": "object",
                        "description": "{title, problem, questions: [{id, text, objective, "
                        "outcome_candidate}], scope: {inside, outside}, unknowns, directions: "
                        "[{id, text, origin, competing_explanations}]}",
                    },
                },
                "required": ["framing"],
            },
            submit_frame,
            terminal=True,
        ),
    ]
    return [t for t in tools if t.name != "ask_researcher" or h.researcher is not None]


def load_frame(path: Path) -> Frame:
    """The frame stored beside a committed `framing.json`."""
    folder = path.parent
    return Frame(
        ResearchContext.model_validate_json((folder / "research.json").read_text("utf-8")),
        Framing.model_validate_json(path.read_text("utf-8")),
        json.loads((folder / "warnings.json").read_text("utf-8")),
        folder.name,
    )


def save_frame(
    run: RunStore,
    attempt: Path,
    context: ResearchContext,
    framing: Framing,
    warnings: list[str],
    asked: list[dict[str, Any]],
    review: Mapping[str, object] | None = None,
) -> Frame:
    """Write a frame into its attempt folder and commit it; a review makes it the reviewed frame."""
    rel = attempt.relative_to(run.root).as_posix()
    run.write_json(f"{rel}/research.json", context.model_dump(mode="json"))
    run.write_text(f"{rel}/research.md", render_research(context))
    run.write_json(f"{rel}/questions.json", asked)
    run.write_json(f"{rel}/warnings.json", warnings)
    if review is not None:
        run.write_json(
            f"{rel}/provenance.json",
            {"supplied_by": "researcher", "researcher_steered": True, "review": review},
        )
    path = run.write_json(f"{rel}/framing.json", framing.model_dump())
    run.commit_artifact("frame" if review is None else "frame_reviewed", path)
    return Frame(context, framing, warnings, attempt.name)


def understand(
    h: Harness,
    research: ResearchContext,
    ida: DescriptiveReport,
    *,
    guidance: str = "",
    rejected: Mapping[str, object] = {},
    review: Mapping[str, object] | None = None,
) -> Frame:
    run: RunStore = h.run
    attempt = run.new_attempt("understand")
    declared = render_research(research.model_copy(update={"body": ""}))
    context_part = partial(part, journal=h.journal, tag="theorist")
    task = load_prompt(
        "popper.understand",
        "theorist.md",
        research=context_part("Research context", research.body, RESEARCH_CHARS, untrusted=True),
        declared=context_part("Declared context", declared.strip() or "(none)", RESEARCH_CHARS, untrusted=True),
        description=context_part("Data description", format_description(ida), ARTIFACT_CHARS, untrusted=True),
        notes=context_part("Researcher notes", research.notes.get("understand", "(none)"), RESEARCH_CHARS, untrusted=True),
        guidance=context_part("Guidance for this revision", guidance, RESEARCH_CHARS, untrusted=True)
        if guidance
        else "",
    )  # fmt: skip
    task += "\nValid columns and evidence keys:\n" + fence(
        json.dumps(
            {
                "columns": [{"name": c["name"], "key": c["key"]} for c in ida.layout["columns"]],
                "result_keys": list(ida.results),
            }
        )
    )
    asked: list[dict[str, Any]] = []
    result: dict[str, Any] = {}
    config = h.config.understand
    submitted = agent_loop(
        h,
        "theorist",
        tag="theorist",
        system="You are a careful research theorist who frames studies before any analysis.",
        task=task,
        tools=_tools(h, attempt, research, ida, rejected, asked, result),
        max_turns=config.max_turns,
        max_submits=config.max_submits,
    )
    if submitted is None:
        raise StageFailed("understand")
    context, problems = _answered(
        result["research"], asked, {c["name"] for c in ida.layout["columns"]}
    )
    framing: Framing = result["framing"]
    warnings = [*framing_warnings(context, framing), *problems]
    return save_frame(run, attempt, context, framing, warnings, asked, review)
