"""A single testable primary claim with code-owned provenance."""

from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    model_validator,
)

from popper.science.compatibility import HistoricalMethod

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Comparison = Literal["difference", "ratio"]
MAX_LISTED_COLUMNS = 50


class PrimaryEstimand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Text
    exposure: Text
    contrast: Text
    comparison: Comparison
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
    methods: list[HistoricalMethod] = Field(min_length=1)
    assumptions: list[Text] = Field(default_factory=list)

    @model_validator(mode="after")
    def checked_roles(self, info: ValidationInfo) -> Self:
        outcome, exposure = self.primary_estimand.outcome, self.primary_estimand.exposure
        if outcome == exposure:
            raise ValueError("primary outcome and exposure must be different columns")
        columns = (info.context or {}).get("columns")
        if columns is not None:
            missing = [name for name in (outcome, exposure) if name not in columns]
            if missing:
                listed = ", ".join(columns[:MAX_LISTED_COLUMNS])
                more = ", ..." if len(columns) > MAX_LISTED_COLUMNS else ""
                raise ValueError(
                    f"primary outcome and exposure must be processed data columns; "
                    f"{missing} not found. Available columns: {listed}{more}"
                )
        return self


class Hypothesis(HypothesisProposal):
    id: Text
    source_nodes: list[Text] = Field(min_length=1)
    supplied_by: Literal["agent"] = "agent"
