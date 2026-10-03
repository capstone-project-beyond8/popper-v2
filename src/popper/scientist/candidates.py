"""Scientific candidate and historical hypothesis generation."""

import json
from dataclasses import dataclass
from functools import partial
from typing import Any

import pandas as pd
from pydantic import Field, ValidationInfo, model_validator

from popper.harness.context import ARTIFACT_CHARS, part
from popper.harness.prompts import load_prompt
from popper.harness.records import ArtifactRef, Record
from popper.harness.session import Harness
from popper.science.compatibility import Hypothesis, HypothesisProposal, StudyPolicy
from popper.science.context import frame_context, research_notes
from popper.science.contracts import Candidate, CandidateProposal
from popper.science.research import ResearchContext
from popper.science.store import ScienceStore
from popper.science.views import ExplorationView
from popper.science.warnings import hypothesis_warnings


@dataclass(frozen=True)
class CandidateContext:
    research: ResearchContext
    framing: dict[str, Any]
    foundation: dict[str, Any]
    exploration: ExplorationView
    raw_columns: list[str]


def propose_hypothesis(
    h: Harness, science: ScienceStore, context: CandidateContext
) -> dict[str, Any]:
    research, framing, foundation = context.research, context.framing, context.foundation
    best, raw_columns = context.exploration, context.raw_columns
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
            "popper.scientist",
            "hypothesis.md",
            framing=frame_context("hypothesis", h.journal, research, framing, foundation),
            notes=research_notes(h.journal, research, "hypothesis"),
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
    h: Harness, science: ScienceStore, context: CandidateContext, policy: StudyPolicy
) -> ArtifactRef:
    research, framing, foundation = context.research, context.framing, context.foundation
    best, raw_columns = context.exploration, context.raw_columns
    if h.run.committed("science:candidates:initial"):
        return h.run.artifact_ref("science:candidates:initial")
    processed = pd.read_parquet(h.run.path("data", "processed.parquet"))
    origins = [h.run.artifact_ref("frame_reviewed"), h.run.artifact_ref("exploration")]
    exposure = [h.run.artifact_ref("inputs")]
    proposal = h.ask_model(
        "theorist",
        schema=CandidateSetProposal,
        tag="candidates",
        system="You are a careful research scientist.",
        prompt=(
            f"Generate exactly {policy.hypothesis_count} distinct sourced, testable hypotheses. "
            "Retain plausible competing explanations and refuting outcomes. Return candidates only; "
            "code assigns IDs and sources. Each methods item is an open MethodSpec with family, "
            "description, algorithm for custom methods, inputs, outputs, effect_scale, assumptions, "
            "diagnostics and parameters. No family-name allowlist.\n"
            + frame_context("candidates", h.journal, research, dict(framing), dict(foundation))
            + f"\nExploration: {json.dumps(best.results)}\n{best.analysis}\n"
            + research_notes(h.journal, research, "hypothesis")
        ),
        validation_context={
            "columns": processed.columns.tolist(),
            "count": policy.hypothesis_count,
        },
    )
    candidates = []
    for index, item in enumerate(proposal.candidates):
        warnings = hypothesis_warnings(
            item.model_dump(mode="json"),
            research,
            foundation["operationalization"],
            processed,
            list(raw_columns),
        )
        candidates.append(
            Candidate(
                **item.model_dump(),
                id=f"hypothesis-{index + 1:03d}",
                origins=origins,
                exposure=exposure,
                warnings=warnings,
            ).model_dump(mode="json")
        )
    return science.commit("candidates", {"version": 1, "candidates": candidates}, key="initial")
