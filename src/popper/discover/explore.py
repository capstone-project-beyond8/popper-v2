"""Execute exploratory analysis within the reviewed scientific frame."""

from typing import Any

from popper.harness.session import Harness
from popper.science.context import frame_context, research_notes
from popper.science.descriptive import describe_input
from popper.science.research import ResearchContext
from popper.science.results import validate_results
from popper.treesearch.engine import Node, StageSpec, run_stage

GOAL = (
    "Explore the processed data for the research questions: distributions, relations between "
    "variables and group differences. Flag surprises. Save at least two informative figures, and report the "
    "key observations as numbers in results.json."
)


def explore(
    h: Harness, research: ResearchContext, framing: dict[str, Any], foundation: dict[str, Any]
) -> Node:
    context = f"{frame_context('analyst:explore', h.journal, research, framing, foundation)}\n\n{research_notes(h.journal, research, 'explore')}"
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
