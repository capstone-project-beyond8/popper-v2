"""Understand: one Theorist session builds the research frame from the research context."""

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from popper.harness.agent import Tool, agent_loop
from popper.harness.context import ARTIFACT_CHARS, RESEARCH_CHARS, part
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


def check_evidence(evidence: str, body: str, ida: DescriptiveReport) -> bool:
    """Evidence is an exact quote of the research body or an existing descriptive result key."""
    return bool(evidence) and (evidence in body or evidence in ida.results)


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
            raise ValueError(f"{where}: unknown attribute")
        if entry.status == "confirmed":
            raise ValueError(f"{where}: an agent cannot set status confirmed")
        if current.status == "confirmed":
            if entry.value == current.value:
                continue
            raise ValueError(f"{where}: confirmed by the researcher and cannot be changed")
        if where in rejected and rejected[where] == entry.value:
            raise ValueError(f"{where}: this value was rejected by the researcher")
        for quote in entry.evidence:
            if not check_evidence(quote, body, ida):
                raise ValueError(
                    f"{where}: evidence {quote!r} is neither an exact quote of the research "
                    "body nor a descriptive result key"
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
    """The context with the patch applied; ValueError names the first offending entry."""
    columns = {c["name"] for c in ida.layout["columns"]}
    variables = dict(ctx.variables)
    for column, changes in patch.variables.items():
        if column not in columns:
            raise ValueError(f"variables.{column}: column is not in the data")
        variables[column] = _merge(
            variables.get(column, Variable()), f"variables.{column}", changes, body, ida, rejected
        )
    concepts = {c.id: c for c in ctx.concepts}
    for concept in patch.concepts:
        if f"concepts.{concept.id}" in rejected:
            raise ValueError(f"concepts.{concept.id}: this concept was rejected by the researcher")
        concepts[concept.id] = _merge(
            concepts.get(concept.id, Concept(id=concept.id)),
            f"concepts.{concept.id}",
            _set(concept, "name", "definition"),
            body, ida, rejected,
        )  # fmt: skip
    assumptions = {a.id: a for a in ctx.assumptions}
    for assumption in patch.assumptions:
        if f"assumptions.{assumption.id}" in rejected:
            raise ValueError(f"assumptions.{assumption.id}: rejected by the researcher")
        assumptions[assumption.id] = _merge(
            assumptions.get(assumption.id, Assumption(id=assumption.id)),
            f"assumptions.{assumption.id}",
            _set(assumption, "description", "confounder"),
            body, ida, rejected,
        )  # fmt: skip
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
            raise ValueError(f"questions.{q.id}: column {q.outcome_candidate!r} is not in the data")
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
    reader = next(t for t in node_tools(h, {}, attempt) if t.name == "read_artifact")

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

    return [
        reader,
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
    task = load_prompt(
        "popper.understand",
        "theorist.md",
        research=part("Research context", research.body, RESEARCH_CHARS, untrusted=True),
        declared=part("Declared context", declared.strip() or "(none)", RESEARCH_CHARS, untrusted=True),
        description=part("Data description", format_description(ida), ARTIFACT_CHARS, untrusted=True),
        notes=part("Researcher notes", research.notes.get("understand", "(none)"), RESEARCH_CHARS, untrusted=True),
        guidance=part("Guidance for this revision", guidance, RESEARCH_CHARS, untrusted=True)
        if guidance
        else "",
    )  # fmt: skip
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
