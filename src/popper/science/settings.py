"""Declared scientific episode policies."""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from popper.harness.store import RunStore


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataConfig(_Strict):
    holdout_fraction: float = Field(default=0.2, ge=0, lt=1)
    split_seed: int = 7
    group_column: str | None = None


class Robustness(_Strict):
    stability_share: float = Field(default=0.8, gt=0, le=1)
    min_variants: int = Field(default=3, ge=3)


class Understand(_Strict):
    max_turns: int = Field(default=30, ge=1)
    max_submits: int = Field(default=3, ge=1)
    max_questions: int = Field(default=5, ge=1)
    max_reframes: int = Field(default=1, ge=0)


class Ground(_Strict):
    max_turns: int = Field(default=40, ge=1)
    max_submits: int = Field(default=3, ge=1)


class Discovery(_Strict):
    hypotheses: Literal[2, 3] = 3
    max_moves: int = Field(default=4, ge=1)
    max_revisits: int = Field(default=1, ge=0)


class ScientificOptions(_Strict):
    data: DataConfig = Field(default_factory=DataConfig)
    robustness: Robustness = Field(default_factory=Robustness)
    understand: Understand = Field(default_factory=Understand)
    ground: Ground = Field(default_factory=Ground)
    discovery: Discovery = Field(default_factory=Discovery)


def load_options(store: RunStore) -> ScientificOptions:
    if not store.path("run.json").is_file():
        return ScientificOptions()
    payload = json.loads(store.path("run.json").read_text("utf-8"))["config"]
    return ScientificOptions.model_validate(
        {k: v for k, v in payload.items() if k in ScientificOptions.model_fields}
    )
