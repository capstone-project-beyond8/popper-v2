"""A single testable primary claim with code-owned provenance."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class PrimaryEstimand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Text
    exposure: Text
    contrast: Text
    population: Text
    unit: Text


class HypothesisProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: Text
    rationale: Text
    primary_estimand: PrimaryEstimand
    expected_direction: Literal["positive", "negative"]
    refuting_result: Text
    planned_test: Text


class Hypothesis(HypothesisProposal):
    id: Text
    source_nodes: list[Text] = Field(min_length=1)
    supplied_by: Literal["agent"] = "agent"
