"""Exploration and hypothesis phase."""

import json
from collections.abc import Mapping, Sequence
from functools import partial
from typing import Any, Literal

import pandas as pd
from pydantic import Field, ValidationInfo, model_validator

from popper.harness.context import ARTIFACT_CHARS, RESEARCH_CHARS, part
from popper.harness.prompts import load_prompt
from popper.harness.records import ArtifactRef, Record
from popper.harness.research import ResearchContext, render_research
from popper.harness.session import Harness
from popper.science.compatibility import StudyPolicy
from popper.science.contracts import Candidate, CandidateProposal
from popper.science.hypothesis import Hypothesis, HypothesisProposal
from popper.science.store import ScienceStore
from popper.science.warnings import hypothesis_warnings
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
        name="explore",
        goal=GOAL,
        context=context,
        inputs={"data": h.run.path("data", "processed.parquet")},
        required_outputs=("results.json",),
        min_figures=2,
    )
    return run_stage(h, spec)


def propose_hypothesis(
    h: Harness,
    research: ResearchContext,
    framing: dict[str, Any],
    foundation: dict[str, Any],
    best: Node,
    raw_columns: list[str],
) -> dict[str, Any]:
    committed = h.run.committed("hypothesis")
    if committed:
        result: dict[str, Any] = json.loads(committed.read_text("utf-8"))[0]
        return result
    processed = pd.read_parquet(h.run.path("data", "processed.parquet"))
    context_part = partial(part, journal=h.journal, tag="hypothesis")
    hypothesis = h.ask_model(
        "theorist",
        schema=HypothesisProposal,
        tag="hypothesis",
        system="You are a careful research scientist.",
        prompt=load_prompt(
            "popper.discover",
            "hypothesis.md",
            framing=_frame_context(h, "hypothesis", research, framing, foundation),
            notes=_notes(h, research, "hypothesis"),
            results=context_part(
                "Exploration results",
                json.dumps(best.results, indent=2),
                ARTIFACT_CHARS,
                untrusted=True,
            ),
            analysis=context_part(
                "Analysis of the exploration", best.analysis, ARTIFACT_CHARS, untrusted=True
            ),
            figures="\n".join(f"- {f}" for f in best.figures),
        ),
        validation_context={"columns": processed.columns.tolist()},
    )
    result = Hypothesis(
        **hypothesis.model_dump(), id="hypothesis-001", source_nodes=[best.id], supplied_by="agent"
    ).model_dump(mode="json")
    attempt = h.run.new_attempt("hypotheses").relative_to(h.run.root).as_posix()
    warnings = hypothesis_warnings(
        result, research, foundation["operationalization"], processed, raw_columns
    )
    h.run.write_json(f"{attempt}/warnings.json", warnings)
    path = h.run.write_json(f"{attempt}/hypotheses.json", [result])
    h.run.commit_artifact("hypothesis", path)
    return result


class CandidateSetProposal(Record):
    candidates: list[CandidateProposal] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def configured_count(self, info: ValidationInfo) -> "CandidateSetProposal":
        if len(self.candidates) != (info.context or {}).get("count", 3):
            raise ValueError("candidate set must contain exactly the configured count")
        return self


def generate_candidates(
    h: Harness, research: ResearchContext, framing: Mapping[str, Any],
    foundation: Mapping[str, Any], best: Node, raw_columns: Sequence[str],
    policy: StudyPolicy,
) -> ArtifactRef:
    if not policy.adaptive:
        propose_hypothesis(h, research, dict(framing), dict(foundation), best, list(raw_columns))
        return h.run.artifact_ref("hypothesis")
    if h.run.committed("science:candidates:initial"):
        return h.run.artifact_ref("science:candidates:initial")
    processed = pd.read_parquet(h.run.path("data", "processed.parquet"))
    origins = [h.run.artifact_ref("frame_reviewed"), h.run.artifact_ref("exploration")]
    exposure = [h.run.artifact_ref("inputs")]
    proposal = h.ask_model(
        "theorist", schema=CandidateSetProposal, tag="candidates",
        system="You are a careful research scientist.",
        prompt=(
            f"Generate exactly {policy.hypothesis_count} distinct sourced, testable hypotheses. "
            "Retain plausible competing explanations and refuting outcomes. Return candidates only; "
            "code assigns IDs and sources. Each methods item is an open MethodSpec with family, "
            "description, algorithm for custom methods, inputs, outputs, effect_scale, assumptions, "
            "diagnostics and parameters. No family-name allowlist.\n"
            + _frame_context(h, "candidates", research, dict(framing), dict(foundation))
            + f"\nExploration: {json.dumps(best.results)}\n{best.analysis}\n"
            + _notes(h, research, "hypothesis")
        ), validation_context={"columns": processed.columns.tolist(), "count": policy.hypothesis_count},
    )
    candidates = []
    for index, item in enumerate(proposal.candidates):
        warnings = hypothesis_warnings(item.model_dump(mode="json"), research, foundation["operationalization"], processed, list(raw_columns))
        candidates.append(Candidate(
            **item.model_dump(), id=f"hypothesis-{index+1:03d}",
            origins=origins, exposure=exposure, warnings=warnings,
        ).model_dump(mode="json"))
    return ScienceStore(h.run).commit("candidates", {"version": 1, "candidates": candidates}, key="initial")
