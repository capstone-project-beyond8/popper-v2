"""Exploration and hypothesis phase."""

import json
from functools import partial
from typing import Any, Literal

from popper.harness.context import ARTIFACT_CHARS, RESEARCH_CHARS, part
from popper.harness.session import Harness
from popper.science.descriptive import describe_input
from popper.science.research import ResearchContext, render_research
from popper.science.results import validate_results
from popper.treesearch.engine import Node, StageSpec, run_stage

GOAL = (
    "Explore the processed data for the research questions: distributions, relations between "
    "variables and group differences. Flag surprises. Save at least two informative figures, and report the "
    "key observations as numbers in results.json."
)


def _frame_context(
    h: Harness,
    tag: str,
    research: ResearchContext,
    framing: dict[str, Any],
    foundation: dict[str, Any],
) -> str:
    """The framing plus what the data steward concluded about measuring and trusting it."""
    context_part = partial(part, journal=h.journal, tag=tag)
    shown = {
        "Concepts": [c.model_dump(mode="json") for c in research.concepts],
        "Operationalization (proposed by the data agent)": foundation["operationalization"],
        "Data concerns": foundation["concerns"],
        "Readiness": foundation["readiness"],
    }
    parts = [
        context_part("Research context", render_research(research), RESEARCH_CHARS, untrusted=True),
        context_part("Framing", json.dumps(framing, indent=2), RESEARCH_CHARS, untrusted=True),
    ]
    parts += [
        context_part(title, json.dumps(value, indent=2), ARTIFACT_CHARS, untrusted=True)
        for title, value in shown.items()
    ]
    return "\n\n".join(parts)


def _notes(h: Harness, research: ResearchContext, key: Literal["explore", "hypothesis"]) -> str:
    return part(
        "Researcher notes",
        research.notes.get(key, "(none)"),
        RESEARCH_CHARS,
        untrusted=True,
        journal=h.journal,
        tag=key,
    )


def explore(
    h: Harness, research: ResearchContext, framing: dict[str, Any], foundation: dict[str, Any]
) -> Node:
    context = f"{_frame_context(h, 'analyst:explore', research, framing, foundation)}\n\n{_notes(h, research, 'explore')}"
    spec = StageSpec(
        describe_input=describe_input,
        validate_results=validate_results,
        name="explore",
        goal=GOAL,
        context=context,
        inputs={"data": h.run.path("data", "processed.parquet")},
        required_outputs=("results.json",),
        min_figures=2,
    )
    return run_stage(h, spec)
