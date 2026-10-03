"""Application configuration composed from runtime and scientific settings."""

import os
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator

from popper.harness.config import HarnessConfig
from popper.scientific.runtime.settings import (
    DataConfig,
    Discovery,
    Ground,
    Robustness,
    ScientificOptions,
    Understand,
)


class Config(HarnessConfig):
    data: DataConfig = Field(default_factory=DataConfig)
    robustness: Robustness = Field(default_factory=Robustness)
    understand: Understand = Field(default_factory=Understand)
    ground: Ground = Field(default_factory=Ground)
    discovery: Discovery = Field(default_factory=Discovery)

    @model_validator(mode="after")
    def enough_robustness_steps(self) -> "Config":
        if self.search.steps_for("robustness") < self.robustness.min_variants + 1:
            raise ValueError(
                "robustness budget needs room for ordinary variants and an adversarial check"
            )
        return self


def _merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        current = out.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            out[key] = _merge(current, value)
        else:
            out[key] = value
    return out


def load_config(
    path: Path | None = None, env: Mapping[str, str] | None = None, *, base: Path | None = None
) -> Config:
    """Load defaults, example base, explicit overrides, then the environment model route."""
    env = os.environ if env is None else env
    text = (files("popper") / "default_config.yaml").read_text(encoding="utf-8")
    data: dict[str, Any] = yaml.safe_load(text)
    for overlay in (base, path):
        if overlay is not None:
            data = _merge(data, yaml.safe_load(overlay.read_text(encoding="utf-8")) or {})
    model = env.get("POPPER_MODEL")
    if model:
        data["models"] = dict.fromkeys(data["models"], model)
    cfg = Config.model_validate(data)
    for role, routed in cfg.models.model_dump().items():
        try:
            cfg.budget.price(routed)
        except ValueError as exc:
            raise ValueError(f"route {role}: {exc}") from None
    return cfg


def scientific_options(config: Config) -> ScientificOptions:
    return ScientificOptions(
        data=config.data,
        robustness=config.robustness,
        understand=config.understand,
        ground=config.ground,
        discovery=config.discovery,
    )
