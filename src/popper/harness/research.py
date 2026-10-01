"""Research context: the researcher's typed input, `research.md` (Markdown body, optional YAML front matter)."""

import math
from collections.abc import Sequence
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

Status = Literal["confirmed", "proposed", "unknown"]
VariableType = Literal[
    "continuous", "binary", "categorical", "ordinal", "count", "id", "time", "text"
]
Role = Literal[
    "outcome",
    "exposure",
    "covariate",
    "id",
    "cluster",
    "time",
    "post_outcome",
    "protected",
    "ignore",
    "unknown",
]
NoteKey = Literal["understand", "ground", "explore", "hypothesis", "experiment", "writing"]


class ResearchError(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Entry[T](_Strict):
    """A value with provenance. A bare researcher value is `confirmed`; a bare null is `unknown`."""

    value: T | None = None
    status: Status = "unknown"
    evidence: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _shorthand(cls, raw: Any) -> Any:
        if isinstance(raw, dict):
            return raw
        if raw is None:
            return {}
        return {"value": raw, "status": "confirmed"}

    @model_validator(mode="after")
    def _provenance(self) -> "Entry[T]":
        if (self.status == "unknown") != (self.value is None):
            raise ValueError("an entry is unknown exactly when its value is null")
        if self.status == "proposed" and not self.evidence:
            raise ValueError("a proposed entry needs evidence")
        return self


class Variable(_Strict):
    meaning: Entry[str] = Field(default_factory=Entry[str])
    unit: Entry[str] = Field(default_factory=Entry[str])
    type: Entry[VariableType] = Field(default_factory=Entry[VariableType])
    role: Entry[Role] = Field(default_factory=Entry[Role])
    range: Entry[list[float]] = Field(default_factory=Entry[list[float]])
    levels: Entry[list[str]] = Field(default_factory=Entry[list[str]])
    order: Entry[int] = Field(default_factory=Entry[int])

    @field_validator("range")
    @classmethod
    def _range(cls, entry: Entry[list[float]]) -> Entry[list[float]]:
        if entry.value is not None:
            if len(entry.value) != 2 or not all(math.isfinite(x) for x in entry.value):
                raise ValueError("range must be two finite numbers [lower, upper]")
            if entry.value[0] > entry.value[1]:
                raise ValueError("range lower bound exceeds upper bound")
        return entry

    @field_validator("levels")
    @classmethod
    def _levels(cls, entry: Entry[list[str]]) -> Entry[list[str]]:
        if entry.value is not None and (
            not entry.value or len(set(entry.value)) != len(entry.value)
        ):
            raise ValueError("levels must be nonempty and distinct")
        return entry


class Design(_Strict):
    observation_unit: Entry[str] = Field(default_factory=Entry[str])
    kind: Entry[Literal["observational", "experimental"]] = Field(
        default_factory=Entry[Literal["observational", "experimental"]]
    )
    sampling: Entry[str] = Field(default_factory=Entry[str])
    collection_period: Entry[str] = Field(default_factory=Entry[str])
    cluster_column: Entry[str] = Field(default_factory=Entry[str])
    id_column: Entry[str] = Field(default_factory=Entry[str])
    time_column: Entry[str] = Field(default_factory=Entry[str])


class Assumption(_Strict):
    id: str
    description: Entry[str] = Field(default_factory=Entry[str])
    confounder: Entry[bool] = Field(default_factory=Entry[bool])


class Constraints(_Strict):
    excluded: Entry[list[str]] = Field(default_factory=Entry[list[str]])
    protected: Entry[list[str]] = Field(default_factory=Entry[list[str]])


class Concept(_Strict):
    id: str
    name: Entry[str] = Field(default_factory=Entry[str])
    definition: Entry[str] = Field(default_factory=Entry[str])


class ResearchContext(_Strict):
    body: str
    domain: Entry[str] = Field(default_factory=Entry[str])
    objectives: Entry[list[str]] = Field(default_factory=Entry[list[str]])
    variables: dict[str, Variable] = {}
    design: Design = Field(default_factory=Design)
    assumptions: list[Assumption] = []
    constraints: Constraints = Field(default_factory=Constraints)
    concepts: list[Concept] = []
    notes: dict[NoteKey, str] = {}


_FENCE = "---"


def _split(text: str) -> tuple[Any, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip() != _FENCE:
        return {}, text
    for i, line in enumerate(lines[1:], start=1):
        if line.rstrip() == _FENCE:
            try:
                front = yaml.safe_load("".join(lines[1:i]))
            except yaml.YAMLError as exc:
                raise ResearchError(f"front matter is not valid YAML: {exc}") from exc
            return {} if front is None else front, "".join(lines[i + 1 :])
    raise ResearchError("front matter is not closed by a --- line")


def parse_research(text: str) -> ResearchContext:
    front, body = _split(text)
    if not isinstance(front, dict) or "body" in front:
        raise ResearchError("front matter must be a mapping of the documented keys")
    if not body.strip():
        raise ResearchError("research body is empty")
    try:
        return ResearchContext.model_validate({**front, "body": body})
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise ResearchError(f"invalid research context: {problems}") from exc


def render_research(ctx: ResearchContext) -> str:
    front = ctx.model_dump(mode="json", exclude={"body"}, exclude_defaults=True)
    if not front:
        return ctx.body
    return f"{_FENCE}\n{yaml.safe_dump(front, sort_keys=False, allow_unicode=True)}{_FENCE}\n{ctx.body}"


def check_columns(ctx: ResearchContext, columns: Sequence[str]) -> list[str]:
    """Every named column that is not in the dataset header (exact match)."""
    known = set(columns)
    named = {f"variables.{name}": name for name in ctx.variables}
    for field in ("cluster_column", "id_column", "time_column"):
        value = getattr(ctx.design, field).value
        if value is not None:
            named[f"design.{field}"] = value
    for field in ("excluded", "protected"):
        for name in getattr(ctx.constraints, field).value or []:
            named[f"constraints.{field}.{name}"] = name
    return [
        f"{where}: column {name!r} is not in the data"
        for where, name in named.items()
        if name not in known
    ]
