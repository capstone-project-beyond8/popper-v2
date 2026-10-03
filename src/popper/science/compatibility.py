"""Saved-run policy; historical declarations retain their original meaning."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from popper.science.settings import Discovery

HistoricalMethod = Literal[
    "difference_in_means", "linear_regression", "logistic_regression", "log_transform",
    "bootstrap", "permutation_test", "imputation", "robust_standard_errors",
    "cluster_robust_standard_errors", "robust_regression", "random_forest", "nonlinear_smooth",
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
