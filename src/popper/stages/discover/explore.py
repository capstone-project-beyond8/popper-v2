"""Execute exploratory analysis within the reviewed scientific frame."""

from typing import Any

from popper.harness.session import Harness
from popper.scientific.runtime.context import frame_context, research_notes
from popper.scientific.runtime.data.descriptive import describe_input
from popper.scientific.runtime.data.research import ResearchContext
from popper.scientific.runtime.evidence.results import validate_results
from popper.strategies.treesearch.engine import Node, StageSpec, run_stage

GOAL = (
    "Explore the processed data for the research questions: distributions, relations between "
    "variables and group differences. Flag surprises. Save at least two informative figures, and report the "
    "key observations as numbers in results.json. These are exploratory observations, not "
    "independent confirmation. Respect the reviewed frame, preparation concerns and authorized "
    "discovery inputs. Distinguish plausible alternatives and uncertainty without optimizing "
    "a favorable sign or significance; do not silently change the prepared data."
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
        artifact_roots={name: h.run.root for name in ("results.json", "analysis.md", "changes.json", "framing.json", "hypotheses.json")},
    )
    return run_stage(h, spec)
