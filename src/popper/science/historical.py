"""Recorded analytic specifications and stability computed from executed results."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from popper.harness.config import Search
from popper.harness.records import ArtifactRef, resolve_artifact
from popper.science.compatibility import HistoricalMethod, Text
from popper.science.results import ResultEntry
from popper.science.settings import Robustness
from popper.science.store import ScienceStore
from popper.science.views import node_results

Dimension = Literal["cleaning", "model", "subgroup", "resampling", "adversarial"]


class Specification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Text
    kind: Literal["variant", "adversarial"]
    dimension: Dimension
    choice: Text
    methods: list[HistoricalMethod] = Field(default_factory=list)
    population: Text | None = None
    result_key: Literal["primary_estimate", "placebo_estimate"]
    seed: int = Field(default=7, ge=0)

    @model_validator(mode="after")
    def consistent_kind(self) -> Self:
        adversarial = self.kind == "adversarial"
        if adversarial != (self.dimension == "adversarial"):
            raise ValueError("adversarial kind and dimension must agree")
        if self.result_key != ("placebo_estimate" if adversarial else "primary_estimate"):
            raise ValueError("result key does not match specification kind")
        if adversarial and self.choice != "permutation":
            raise ValueError("adversarial choice must be permutation")
        if (self.dimension == "subgroup") != (self.population is not None):
            raise ValueError("only subgroup variants set, and must set, a restricted population")
        return self

    def estimand(self, primary: Mapping[str, Any]) -> dict[str, Any]:
        return {**primary, **({"population": self.population} if self.population else {})}


class RobustnessPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempts: list[Specification]
    inapplicable: dict[Literal["cleaning", "model", "subgroup", "resampling"], Text] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def valid_schedule(self, info: ValidationInfo) -> Self:
        context = info.context or {}
        ordinary = [a for a in self.attempts if a.kind == "variant"]
        if len(ordinary) < context.get("min_variants", 3) or not any(
            a.kind == "adversarial" for a in self.attempts
        ):
            raise ValueError(
                "schedule requires ordinary variants and at least one adversarial check"
            )
        if len(self.attempts) > context.get("steps", 6):
            raise ValueError("schedule exceeds stage step budget")
        if len({a.id for a in self.attempts}) != len(self.attempts):
            raise ValueError("specification IDs must be unique")
        if len({(a.dimension, a.choice.casefold()) for a in self.attempts}) != len(self.attempts):
            raise ValueError("specification choices must be distinct")
        dimensions = {a.dimension for a in ordinary}
        for dimension in ("cleaning", "model", "subgroup", "resampling"):
            if dimension not in dimensions and dimension not in self.inapplicable:
                raise ValueError(f"missing {dimension} variation needs an applicability reason")
            if dimension in dimensions and dimension in self.inapplicable:
                raise ValueError(f"{dimension} cannot be both varied and inapplicable")
        return self


def schedule_context(
    search: Search, policy: Robustness, *, reserve_repair: bool = True
) -> dict[str, Any]:
    steps = search.steps_for("robustness") - int(reserve_repair)
    if reserve_repair and steps < policy.min_variants + 1:
        raise ValueError("robustness budget needs room for variants, an adversary and a repair")
    return {
        "steps": steps,
        "min_variants": policy.min_variants,
    }


def load_robustness_plan(path: Path, search: Search, policy: Robustness) -> RobustnessPlan:
    record = json.loads(path.read_text("utf-8"))
    if record.get("format_version") != 2:
        raise ValueError("unsupported robustness schedule version")
    return RobustnessPlan.model_validate(
        record["schedule"], context=schedule_context(search, policy, reserve_repair=False)
    )


def supports(main: ResultEntry, variant: ResultEntry | None) -> bool:
    if (
        variant is None
        or variant.ci is None
        or not isinstance(main.value, (float, int))
        or not isinstance(variant.value, (float, int))
    ):
        return False
    lo, hi = variant.ci
    return main.value * variant.value > 0 and (lo > 0 or hi < 0)


def compute_stability(
    main: ResultEntry,
    variants: Sequence[ResultEntry | None],
    adversarial: Sequence[ResultEntry | None],
    *,
    share: float = 0.8,
    min_variants: int = 3,
) -> tuple[Literal["stable", "fragile"], list[str]]:
    reasons: list[str] = []
    if sum(v is not None for v in variants) < min_variants:
        reasons.append("Too few successfully executed ordinary specifications.")
    if not variants or sum(supports(main, v) for v in variants) / len(variants) < share:
        reasons.append(
            "Insufficient variants retain the main sign with an interval excluding zero."
        )
    if not adversarial or any(
        a is None or a.ci is None or not (a.ci[0] <= 0 <= a.ci[1]) for a in adversarial
    ):
        reasons.append("An adversarial check failed or has no successful executed result.")
    return ("fragile" if reasons else "stable"), reasons


def collect_historical_evidence(
    science: ScienceStore,
    hypothesis: dict[str, Any],
    selected: Mapping[str, ArtifactRef],
    plan: ArtifactRef,
    representatives: Mapping[str, ArtifactRef | None],
    nodes: list[ArtifactRef],
    search: Search,
    policy: Robustness,
) -> Path:
    store = science.run
    plan_path = resolve_artifact(store, plan)
    schedule = load_robustness_plan(plan_path, search, policy)
    main = ResultEntry.model_validate(node_results(science, selected["main"])["primary_estimate"])
    variants: list[ResultEntry | None] = []
    adversarial: list[ResultEntry | None] = []
    outcomes = []
    for attempt in schedule.attempts:
        representative = representatives.get(attempt.id)
        entry = (
            ResultEntry.model_validate(node_results(science, representative)[attempt.result_key])
            if representative
            else None
        )
        (adversarial if attempt.kind == "adversarial" else variants).append(entry)
        outcomes.append(
            {
                "id": attempt.id,
                "node": science.read(representative)["id"] if representative else None,
            }
        )
    label, reasons = compute_stability(
        main,
        variants,
        adversarial,
        share=policy.stability_share,
        min_variants=policy.min_variants,
    )
    supporting = sum(supports(main, variant) for variant in variants)
    destination = store.new_attempt("discover/evidence").relative_to(store.root).as_posix()
    summary = store.write_json(
        f"{destination}/results.json",
        {
            "variant_count": {"value": len(variants)},
            "supporting_count": {"value": supporting},
            "supporting_share": {"value": supporting / len(variants) if variants else 0},
            "adversarial_count": {"value": len(adversarial)},
        },
    )
    hypothesis_path = store.committed("hypothesis")
    if hypothesis_path is None:
        raise ValueError("selected hypothesis has not been committed")
    path = store.write_json(
        f"{destination}/evidence.json",
        {
            "format_version": 1,
            "hypothesis": hypothesis_path.relative_to(store.root).as_posix(),
            "hypothesis_id": hypothesis["id"],
            "selected": {stage: science.read(ref)["id"] for stage, ref in selected.items()},
            "plan": plan.path,
            "summary": summary.relative_to(store.root).as_posix(),
            "standing": "exploratory",
            "stability": label,
            "reasons": reasons,
            "specifications": outcomes,
            "nodes": [
                {
                    "id": metadata["id"],
                    "stage": metadata["stage"],
                    "kind": metadata["kind"],
                    "attempt_id": metadata["attempt_id"],
                    "status": metadata["status"],
                    "results": f"{folder}/execution/results.json"
                    if metadata["status"] == "ok"
                    else None,
                    "code": f"{folder}/execution/code.py"
                    if store.path(folder, "execution", "code.py").exists()
                    else None,
                    "analysis": f"{folder}/analysis.md"
                    if store.path(folder, "analysis.md").exists()
                    else None,
                    "figures": [
                        f"{folder}/execution/figures/{figure}" for figure in metadata["figures"]
                    ],
                }
                for ref in nodes
                for metadata in [science.read(ref)]
                for folder in [Path(ref.path).parent.as_posix()]
            ],
        },
    )
    store.commit_artifact("evidence", path)
    return path
