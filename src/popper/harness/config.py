"""Run configuration: packaged defaults, deep-merged with an optional user file."""

import os
from collections.abc import Mapping
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

Role = Literal["ideation", "code", "feedback", "vision", "writeup"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Models(_Strict):
    ideation: str
    code: str
    feedback: str
    vision: str
    writeup: str


class Search(_Strict):
    num_drafts: int
    debug_prob: float
    max_debug_depth: int
    steps_per_stage: int


class Execution(_Strict):
    timeout_seconds: int
    max_output_chars: int


class Budget(_Strict):
    max_usd: float
    usd_per_mtok_input: float
    usd_per_mtok_output: float


class Config(_Strict):
    models: Models
    search: Search
    execution: Execution
    budget: Budget


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
    return Config.model_validate(data)
