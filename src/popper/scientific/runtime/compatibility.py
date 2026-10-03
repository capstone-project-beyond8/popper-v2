"""Saved-run policy; historical declarations retain their original meaning."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationInfo,
    model_validator,
)

from popper.scientific.runtime.settings import Discovery

HistoricalMethod = Literal[
    "difference_in_means",
    "linear_regression",
    "logistic_regression",
    "log_transform",
    "bootstrap",
    "permutation_test",
    "imputation",
    "robust_standard_errors",
    "cluster_robust_standard_errors",
    "robust_regression",
    "random_forest",
    "nonlinear_smooth",
]


@dataclass(frozen=True)
class StudyPolicy:
    format_version: int
    hypothesis_count: int
    adaptive: bool
    legacy_labels: bool


def decode_policy(metadata: Mapping[str, Any]) -> StudyPolicy:
    version = metadata.get("format_version")
    if version == 4:
        return StudyPolicy(4, 1, False, True)
    if version == 5:
        limits = Discovery.model_validate(metadata.get("config", {}).get("discovery", {}))
        return StudyPolicy(5, limits.hypotheses, True, False)
    raise ValueError(f"unsupported run format: {version!r}")


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
