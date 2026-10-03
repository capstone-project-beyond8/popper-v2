"""Generic model, execution, search and resource configuration."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Role = Literal["theorist", "analyst", "steward", "judge", "writer"]
ImplementationPolicy = Literal["tree", "linear"]
_NonnegativeFinite = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Models(_Strict):
    theorist: str
    analyst: str
    steward: str
    judge: str
    writer: str

    @model_validator(mode="before")
    @classmethod
    def steward_follows_analyst(cls, data: Any) -> Any:
        if isinstance(data, dict) and "steward" not in data and "analyst" in data:
            return {**data, "steward": data["analyst"]}
        return data


class Search(_Strict):
    num_drafts: int
    debug_prob: float
    max_debug_depth: int
    steps_per_stage: int
    max_turns: int = Field(ge=1)
    good_score: float = 7
    patience: int = 2
    implementation_policy: ImplementationPolicy = "tree"
    stage_steps: dict[
        Literal["data", "explore", "baseline", "main", "robustness"], Annotated[int, Field(ge=1)]
    ] = Field(default_factory=dict)

    def steps_for(self, stage: str) -> int:
        return next(
            (steps for name, steps in self.stage_steps.items() if name == stage),
            self.steps_per_stage,
        )


class Execution(_Strict):
    timeout_seconds: int
    max_output_chars: int


class Price(_Strict):
    input: _NonnegativeFinite  # USD per million tokens
    output: _NonnegativeFinite
    cache_write: _NonnegativeFinite = 1.25  # multiples of the input price
    cache_read: _NonnegativeFinite = 0.1


class Budget(_Strict):
    max_usd: _NonnegativeFinite
    prices: dict[str, Price]

    def price(self, model: str) -> Price:
        """The price whose key is a substring of `model`; exactly one must match."""
        keys = [k for k in self.prices if k in model]
        if len(keys) != 1:
            raise ValueError(f"model {model!r} matches price keys {keys}, expected exactly one")
        return self.prices[keys[0]]


class HarnessConfig(_Strict):
    models: Models
    search: Search
    execution: Execution
    budget: Budget
