"""Exploration and hypothesis phase."""

import json
from typing import Any

from popper.discover.hypothesis import Hypothesis, HypothesisProposal
from popper.harness.context import ARTIFACT_CHARS, part
from popper.harness.prompts import load_prompt
from popper.harness.session import Harness
from popper.treesearch.engine import Node, StageSpec, run_stage

GOAL = (
    "Explore the processed data for the research questions: distributions, relations between "
    "variables and group differences. Flag surprises. Save at least two informative figures, and report the "
    "key observations as numbers in results.json."
)


def explore(h: Harness, framing: dict[str, Any]) -> Node:
    context = json.dumps(framing, indent=2)
    spec = StageSpec(
        name="explore",
        goal=GOAL,
        context=context,
        inputs={"data": h.run.path("data", "processed.parquet")},
        required_outputs=("results.json",),
        min_figures=2,
    )
    return run_stage(h, spec)


def propose_hypothesis(h: Harness, framing: dict[str, Any], best: Node) -> dict[str, Any]:
    context = json.dumps(framing, indent=2)
    hypothesis = h.ask_model(
        "theorist",
        schema=HypothesisProposal,
        tag="hypothesis",
        system="You are a careful research scientist. Reply with JSON only.",
        prompt=load_prompt(
            "popper.discover",
            "hypothesis.md",
            framing=context,
            results=part(
                "Exploration results",
                json.dumps(best.results, indent=2),
                ARTIFACT_CHARS,
                untrusted=True,
            ),
            analysis=part(
                "Analysis of the exploration", best.analysis, ARTIFACT_CHARS, untrusted=True
            ),
            figures="\n".join(f"- {f}" for f in best.figures),
        ),
    )
    result = Hypothesis(
        **hypothesis.model_dump(), id="hypothesis-001", source_nodes=[best.id], supplied_by="agent"
    ).model_dump(mode="json")
    h.run.write_json("hypotheses.json", [result])
    return result
