"""Recorded analytic specifications and stability computed from executed results."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from popper.discover.hypothesis import PrimaryEstimand, Text
from popper.harness.session import Harness
from popper.treesearch.engine import Node, ResultEntry, load_nodes, select_best

Dimension = Literal["cleaning", "model", "subgroup", "resampling", "adversarial"]


class Specification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Text
    kind: Literal["variant", "adversarial"]
    dimension: Dimension
    choice: Text
    estimand: PrimaryEstimand
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
        return self


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
        primary = context.get("estimand")
        if primary:
            for attempt in self.attempts:
                actual = attempt.estimand.model_dump()
                keys = ("outcome", "exposure", "contrast", "unit")
                if any(actual[key] != primary[key] for key in keys):
                    raise ValueError("all specifications must preserve contrast and units")
                if (
                    attempt.dimension != "subgroup"
                    and actual["population"] != primary["population"]
                ):
                    raise ValueError("only subgroup variants may restrict the population")
        return self


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


def plan_robustness(h: Harness, hypothesis: dict[str, Any], main: Node, data_node: Node) -> Path:
    committed = h.run.committed("robustness_plan")
    if committed:
        return committed
    primary = hypothesis["primary_estimand"]
    steps = h.config.search.steps_for("robustness")
    proposal = h.ask_model(
        "theorist",
        schema=RobustnessPlan,
        tag="robustness_plan",
        system="You are a careful research scientist. Reply with JSON only.",
        prompt=(
            f"Plan a bounded multiverse for this hypothesis:\n{json.dumps(hypothesis)}\n"
            f"Recorded data changes:\n{(data_node.execution_dir / 'changes.json').read_text('utf-8')}\n"
            f"Use at most {steps} attempts, at least {h.config.robustness.min_variants} ordinary variants "
            "and one adversarial permutation of the exposure. Prefer four ordinary variants plus one "
            "adversarial attempt, leaving repair budget. Cover cleaning, model, subgroup and resampling, "
            "or record an inapplicable reason. Preserve outcome/exposure/contrast/units; only subgroup "
            "may restrict population. Do not select choices to obtain significance. "
            "Return {attempts: [{id, kind: variant|adversarial, dimension: cleaning|model|subgroup|resampling|adversarial, "
            "choice, estimand: {outcome, exposure, contrast, population, unit}, "
            "result_key: primary_estimate|placebo_estimate, seed: 7}], inapplicable: {dimension: reason}}. "
            "Adversarial choice must be exactly permutation. Do not include estimates or a label."
        ),
        validation_context={
            "estimand": primary,
            "steps": steps,
            "min_variants": h.config.robustness.min_variants,
        },
    )
    destination = h.run.new_attempt("discover/robustness").relative_to(h.run.root).as_posix()
    path = h.run.write_json(
        f"{destination}/robustness_plan.json",
        {
            "format_version": 1,
            "main_node": main.id,
            "schedule": proposal.model_dump(mode="json"),
        },
    )
    h.run.commit_artifact("robustness_plan", path)
    return path


def collect_evidence(
    h: Harness,
    hypothesis: dict[str, Any],
    selected: Mapping[str, Node],
    plan: Path,
) -> Path:
    schedule = RobustnessPlan.model_validate(json.loads(plan.read_text("utf-8"))["schedule"])
    nodes = [
        node
        for stage in ("baseline", "main", "robustness")
        for node in load_nodes(h, stage, include_abandoned=True)
    ]
    main = ResultEntry.model_validate_json(json.dumps(selected["main"].results["primary_estimate"]))
    variants: list[ResultEntry | None] = []
    adversarial: list[ResultEntry | None] = []
    outcomes = []
    for attempt in schedule.attempts:
        representative = select_best([n for n in nodes if n.attempt_id == attempt.id])
        entry = (
            ResultEntry.model_validate_json(json.dumps(representative.results[attempt.result_key]))
            if representative
            else None
        )
        (adversarial if attempt.kind == "adversarial" else variants).append(entry)
        outcomes.append({"id": attempt.id, "node": representative.id if representative else None})
    label, reasons = compute_stability(
        main,
        variants,
        adversarial,
        share=h.config.robustness.stability_share,
        min_variants=h.config.robustness.min_variants,
    )
    supporting = sum(supports(main, variant) for variant in variants)
    destination = h.run.new_attempt("discover/evidence").relative_to(h.run.root).as_posix()
    summary = h.run.write_json(
        f"{destination}/results.json",
        {
            "variant_count": {"value": len(variants)},
            "supporting_count": {"value": supporting},
            "supporting_share": {"value": supporting / len(variants) if variants else 0},
            "adversarial_count": {"value": len(adversarial)},
        },
    )
    hypothesis_path = h.run.committed("hypothesis")
    if hypothesis_path is None:
        raise ValueError("selected hypothesis has not been committed")
    path = h.run.write_json(
        f"{destination}/evidence.json",
        {
            "format_version": 1,
            "hypothesis": hypothesis_path.relative_to(h.run.root).as_posix(),
            "hypothesis_id": hypothesis["id"],
            "selected": {stage: node.id for stage, node in selected.items()},
            "plan": plan.relative_to(h.run.root).as_posix(),
            "summary": summary.relative_to(h.run.root).as_posix(),
            "standing": "exploratory",
            "stability": label,
            "reasons": reasons,
            "specifications": outcomes,
            "nodes": [
                {
                    "id": n.id,
                    "stage": n.stage,
                    "kind": n.kind,
                    "attempt_id": n.attempt_id,
                    "status": n.status,
                    "results": (n.execution_dir / "results.json").relative_to(h.run.root).as_posix()
                    if n.status == "ok"
                    else None,
                    "code": (n.execution_dir / "code.py").relative_to(h.run.root).as_posix()
                    if n.code
                    else None,
                    "analysis": (n.dir / "analysis.md").relative_to(h.run.root).as_posix()
                    if (n.dir / "analysis.md").exists()
                    else None,
                    "figures": [
                        (n.execution_dir / "figures" / f).relative_to(h.run.root).as_posix()
                        for f in n.figures
                    ],
                }
                for n in nodes
            ],
        },
    )
    h.run.commit_artifact("evidence", path)
    return path
