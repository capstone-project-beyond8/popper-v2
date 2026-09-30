"""Exploration and hypothesis phase."""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from popper.harness.context import ARTIFACT_CHARS, part
from popper.harness.prompts import load_prompt
from popper.harness.session import Harness
from popper.treesearch.engine import Node, StageSpec, run_stage

GOAL = (
    "Explore the processed data for the research questions: distributions, relations between "
    "variables and group differences. Flag surprises. Save at least two informative figures, and report the "
    "key observations as numbers in results.json."
)


class Hypothesis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    rationale: str
    variables: list[str]
    planned_experiments: list[str]


def explore(h: Harness, framing: dict[str, Any]) -> tuple[Node, dict[str, Any]]:
    context = json.dumps(framing, indent=2)
    spec = StageSpec(
        name="explore",
        goal=GOAL,
        context=context,
        inputs={"data": h.run.path("data", "processed.parquet")},
        required_outputs=("results.json",),
        min_figures=2,
    )
    best = run_stage(h, spec)
    hypothesis = h.ask_model(
        "theorist",
        schema=Hypothesis,
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
    result = {**hypothesis.model_dump(), "source_node": best.id, "supplied_by": "agent"}
    h.run.write_json("hypotheses.json", [result])
    return best, result
