"""Run configuration: packaged defaults, deep-merged with an optional user file."""

import os
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

Role = Literal["theorist", "analyst", "judge", "writer"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Models(_Strict):
    theorist: str
    analyst: str
    judge: str
    writer: str


class Search(_Strict):
    num_drafts: int
    debug_prob: float
    max_debug_depth: int
    steps_per_stage: int
    max_turns: int = Field(ge=1)
    good_score: float = 7
    patience: int = 2


class Execution(_Strict):
    timeout_seconds: int
    max_output_chars: int


class DataConfig(_Strict):
    holdout_fraction: float = Field(default=0.2, ge=0, lt=1)
    split_seed: int = 7
    group_column: str | None = None


class Price(_Strict):
    input: float  # USD per million tokens
    output: float
    cache_write: float = 1.25  # multiples of the input price
    cache_read: float = 0.1


class Budget(_Strict):
    max_usd: float
    prices: dict[str, Price]

    def price(self, model: str) -> Price:
        """The price whose key is a substring of `model`; exactly one must match."""
        keys = [k for k in self.prices if k in model]
        if len(keys) != 1:
            raise ValueError(f"model {model!r} matches price keys {keys}, expected exactly one")
        return self.prices[keys[0]]


class Config(_Strict):
    models: Models
    search: Search
    execution: Execution
    budget: Budget
    data: DataConfig = Field(default_factory=DataConfig)


def _merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        current = out.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            out[key] = _merge(current, value)
        else:
            out[key] = value
    return out


def load_config(path: Path | None = None, env: Mapping[str, str] | None = None) -> Config:
    """Load defaults, overlay `path` if given, and apply `POPPER_MODEL` to every role."""
    env = os.environ if env is None else env
    text = (files("popper.harness") / "default_config.yaml").read_text(encoding="utf-8")
    data: dict[str, Any] = yaml.safe_load(text)
    if path is not None:
        data = _merge(data, yaml.safe_load(path.read_text(encoding="utf-8")) or {})
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
