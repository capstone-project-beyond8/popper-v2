"""Scientific candidate generation."""

import json
from dataclasses import dataclass
from functools import partial
from typing import Any

import pandas as pd
from pydantic import Field, ValidationInfo, model_validator

from popper.harness.context.prompts import load_prompt
from popper.harness.context.rendering import ARTIFACT_CHARS, part
from popper.harness.session import Harness
from popper.harness.storage.records import ArtifactRef, Record
from popper.scientific.runtime.context import frame_context, research_notes
from popper.scientific.runtime.data.descriptive import read_table
from popper.scientific.runtime.data.research import ResearchContext
from popper.scientific.runtime.lifecycle.contracts import Candidate, CandidateProposal
from popper.scientific.runtime.projections.views import (
    ExplorationView,
    exploration_view,
    foundation_view,
    reviewed_frame,
    validate_intent_inputs,
)
from popper.scientific.runtime.settings import load_options
from popper.scientific.runtime.store import ScienceStore
from popper.scientific.runtime.warnings import hypothesis_warnings


@dataclass(frozen=True)
class CandidateContext:
    research: ResearchContext
    framing: dict[str, Any]
    foundation: dict[str, Any]
    exploration: ExplorationView
    raw_columns: list[str]


class CandidateSetProposal(Record):
    candidates: list[CandidateProposal] = Field(min_length=1)
    omission: str | None = None

    @model_validator(mode="after")
    def configured_count(self, info: ValidationInfo) -> "CandidateSetProposal":
        context = info.context or {}
        count = context.get("count", 3)
        if len(self.candidates) > count:
            raise ValueError("candidate set exceeds the configured count")
        if len(self.candidates) < count and not (self.omission and self.omission.strip()):
            raise ValueError("fewer candidates than the configured count need a non-empty omission reason")
        return self


def intent_context(
    h: Harness, science: ScienceStore, source: ArtifactRef
) -> tuple[CandidateContext, dict[str, ArtifactRef]]:
    """Validated upstream inputs of a committed intent and the exact records it names."""
    validate_intent_inputs(science, source)
    intent = science.read(source)
    refs = {name: ArtifactRef.model_validate(intent[name]) for name in (
        "frame", "foundation", "preparation", "exploration"
    )}
    reviewed, prepared = reviewed_frame(science, refs["frame"]), foundation_view(science, refs["foundation"])
    context = CandidateContext(
        reviewed.research, reviewed.framing, prepared.facts,
        exploration_view(science, refs["exploration"]), list(read_table(h.run.path("data/raw.csv")).columns),
    )
    return context, refs


def processed_table(h: Harness, science: ScienceStore, preparation: ArtifactRef) -> pd.DataFrame:
    return pd.read_parquet(h.run.path(science.read(preparation)["mounts"]["data"]["path"]))


def candidate_warnings(item: CandidateProposal, context: CandidateContext, processed: pd.DataFrame) -> list[str]:
    return hypothesis_warnings(
        item.model_dump(mode="json"), context.research, context.foundation["operationalization"],
        processed, context.raw_columns,
    )


def generate_candidates(
    h: Harness, science: ScienceStore, source: ArtifactRef, *, admission: ArtifactRef | None = None
) -> ArtifactRef:
    count = load_options(h.run).discovery.hypotheses
    context, refs = intent_context(h, science, source)
    research, framing, foundation, best = context.research, context.framing, context.foundation, context.exploration
    if h.run.committed("science:candidates:initial"):
        return h.run.artifact_ref("science:candidates:initial")
    processed = processed_table(h, science, refs["preparation"])
    origins = [refs["frame"], refs["exploration"]]
    exposure = [h.run.artifact_ref("inputs")]
    context_part = partial(part, journal=h.journal, tag="candidates")
    proposal = h.ask_model(
        "theorist",
        schema=CandidateSetProposal,
        tag="candidates",
        system="You are a careful research scientist.",
        prompt=load_prompt(
            "popper.stages.discover", "candidates.md",
            count=str(count),
            framing=frame_context("candidates", h.journal, research, dict(framing), dict(foundation)),
            notes=research_notes(h.journal, research, "hypothesis"),
            results=context_part("Exploration results", json.dumps(best.results), ARTIFACT_CHARS, untrusted=True),
            analysis=context_part("Exploration assessment", best.analysis, ARTIFACT_CHARS, untrusted=True),
        ),
        validation_context={
            "columns": processed.columns.tolist(),
            "count": count,
        },
    )
    candidates = []
    for index, item in enumerate(proposal.candidates):
        warnings = candidate_warnings(item, context, processed)
        candidates.append(
            Candidate(
                **item.model_dump(),
                id=f"hypothesis-{index + 1:03d}",
                origins=origins,
                exposure=exposure,
                warnings=warnings,
            ).model_dump(mode="json")
        )
    omission = {"omission": proposal.omission} if len(candidates) < count else {}
    return science.commit("candidates", {"version": 1, "candidates": candidates, **omission, **({"admission": admission.model_dump(mode="json")} if admission else {})}, key="initial")
