"""Sequential experiments for one declared primary estimand."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from popper.discover.robustness import (
    Specification,
    collect_evidence,
    load_robustness_plan,
    plan_robustness,
    schedule_context,
)
from popper.harness.context import RESEARCH_CHARS, part
from popper.harness.prompts import load_prompt
from popper.harness.records import ArtifactRef, IntegrityError, resolve_artifact
from popper.harness.recovery import read_events
from popper.harness.session import Harness
from popper.science.contracts import (
    Attempt,
    ExperimentSpec,
    MethodSpec,
)
from popper.science.descriptive import describe_input
from popper.science.evidence import (
    RecordedStageOutcome,
    assemble_result,
)
from popper.science.execution import (
    adaptive_goal,
    check_estimate,
    execution_binding,
    observe_declared_output,
    prepare_execution,
)
from popper.science.results import validate_results
from popper.science.settings import load_options
from popper.science.store import ScienceStore
from popper.science.transitions import ensure_invalidation
from popper.treesearch.engine import (
    AttemptSpec,
    Node,
    StageFailed,
    StageSpec,
    load_nodes,
    run_stage,
)
from popper.treesearch.judge import JudgeReference

_TRANSFORM_NOTE = (
    "If the model uses a transformed outcome, back-transform predictions and get the interval "
    "of the original-scale contrast by bootstrap; do not hand-derive delta-method derivatives."
)


def _names(methods: Sequence[Any]) -> str:
    return ", ".join((m if isinstance(m, str) else m["family"]).replace("_", " ") for m in methods)


def method_reference(
    hypothesis: Mapping[str, Any],
    columns: Sequence[str],
    *,
    purpose: str,
    choice: str = "",
    methods: Sequence[Any] = (),
) -> JudgeReference:
    """Only checked column roles and closed method vocabulary can cross the blinding boundary."""
    primary = hypothesis["primary_estimand"]
    outcome, exposure = primary["outcome"], primary["exposure"]
    if outcome not in columns or exposure not in columns:
        raise ValueError("primary outcome and exposure must identify processed data columns")
    if purpose not in {
        "baseline",
        "main",
        "cleaning",
        "model",
        "subgroup",
        "resampling",
        "adversarial",
    }:
        raise ValueError("unknown experiment purpose")
    requirements = [
        f"Stage/specification: {purpose}.",
        f"Compute the declared {primary['comparison']} using the designated exposure and outcome in original outcome units.",
        "Use the declared restricted subgroup population."
        if purpose == "subgroup"
        else "Use the primary declared population.",
    ]
    if purpose == "baseline":
        requirements.append("Use a simple transparent baseline and report an uncertainty interval.")
    elif purpose == "main":
        requirements.append(f"Main planned method operations: {_names(hypothesis['methods'])}.")
    if methods:
        requirements.append(f"Recorded alternative operations: {_names(methods)}.")
    declared_methods = hypothesis["methods"] if purpose == "main" else methods
    for declaration in declared_methods:
        if isinstance(declaration, dict):
            method = MethodSpec.model_validate(declaration)
            requirements.extend(
                [
                    f"Declared algorithm: {method.algorithm or method.description}.",
                    f"Method assumptions: {json.dumps(method.assumptions)}.",
                    f"Method diagnostics: {json.dumps(method.diagnostics)}.",
                    f"Declared inputs/outputs: {json.dumps(method.inputs)} / {json.dumps(method.outputs)}.",
                    "Custom output blinding retains structural diagnostics only; full numerical fidelity may remain unresolved.",
                ]
            )
    if "imputation" in declared_methods:
        requirements.append(
            "Multiple imputation must propagate missingness uncertainty using stochastic draws; "
            "repeating deterministic imputations is not multiple imputation. Check within- and "
            "between-imputation variance before accepting a pooled interval."
        )
    if "cluster_robust_standard_errors" in declared_methods:
        requirements.append(
            "Clustered intervals must respect the number of independent clusters, including "
            "cluster-based inference degrees of freedom when pooling manually."
        )
    requirements.append(
        "For a custom likelihood, check design/parameter dimensions, per-observation density "
        "normalization and optimizer convergence before accepting a fit."
    )
    if "log_transform" in declared_methods:
        requirements.append(
            "If the outcome is transformed, the contrast and its interval must be on the original outcome "
            "scale, with the interval from bootstrap or from transformed prediction endpoints, "
            "not a hand-derived delta method. Transforming only the exposure does not require "
            "back-transforming the outcome; compute predictions at the declared exposure endpoints."
        )
    if purpose == "adversarial":
        requirements.append(
            "Permute the exposure once; refit the same estimator and contrast, reporting a placebo interval."
        )
    identity = hashlib.sha256(
        json.dumps(
            {
                "primary": primary,
                "test": hypothesis["planned_test"],
                "purpose": purpose,
                "choice": choice,
                "methods": [hypothesis["methods"], list(methods)],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    requirements.append(f"Opaque method/specification identity: {identity}.")
    return JudgeReference({outcome: "outcome", exposure: "exposure"}, tuple(requirements))


def declared_procedure_reference(
    test: ExperimentSpec, columns: Sequence[str], *, purpose: str
) -> JudgeReference:
    """Carry the effective operational declaration across the estimate blinding boundary."""
    primary = test.primary_estimand
    if primary.outcome not in columns or primary.exposure not in columns:
        raise ValueError("primary outcome and exposure must identify processed data columns")
    requirements = [
        f"Stage/specification: {purpose}.",
        f"Declared estimand: {primary.model_dump_json()}.",
        f"Selection and assumptions: {json.dumps(test.selection)}.",
        f"Inference: {json.dumps(test.inference)}.",
        f"Adjustments: {json.dumps(test.adjustment)}.",
        f"Requested coverage: {json.dumps({k: v for k, v in test.requested_coverage.items() if k != 'alternatives'})}.",
        f"Required outputs: {json.dumps(test.outputs)}.",
    ]
    for method in test.methods:
        declaration = method.model_dump(mode="json", exclude={"implementation_ref"})
        requirements.append(f"Declared method: {json.dumps(declaration)}.")
    requirements.append(
        "Assess operational fidelity from code and structural diagnostics; signed estimates "
        "and support predictions are withheld. Unverified requirements remain unresolved."
    )
    return JudgeReference(
        {primary.outcome: "outcome", primary.exposure: "exposure"}, tuple(requirements)
    )


def _notes_part(h: Harness, tag: str, notes: str) -> str:
    return part(
        "Researcher notes",
        notes or "(none)",
        RESEARCH_CHARS,
        untrusted=True,
        journal=h.journal,
        tag=tag,
    )


def run_experiment_stage(
    h: Harness,
    name: Literal["baseline", "main"],
    framing: dict[str, Any],
    hypothesis: dict[str, Any],
    seed: Node | None,
    notes: str = "",
    design: str = "",
    *,
    instance_id: str | None = None,
    test: ArtifactRef | None = None,
) -> Node:
    estimand = hypothesis["primary_estimand"]
    goal = (
        "Use a simple transparent model or test."
        if name == "baseline"
        else f"Implement the planned test: {hypothesis['planned_test']}"
    )
    goal += (
        " Re-estimate the declared primary contrast in its original outcome units. "
        "Write primary_estimate in results.json with value, a 95% ci and integer n. "
        f"Write exactly this JSON object to estimand.json: {json.dumps(estimand)}. "
        "Save a result figure in figures/. Secondary estimands need different result keys. "
        "Do not choose preprocessing or a model to obtain a desired sign or significance. "
        f"{_TRANSFORM_NOTE}"
    )
    intended = (
        ExperimentSpec.model_validate_json(resolve_artifact(h.run, test).read_text("utf-8"))
        if test
        else None
    )
    if intended:
        goal = adaptive_goal(intended, name)
    return run_stage(
        h,
        StageSpec(
            describe_input=describe_input,
            validate_results=validate_results,
            name=name,
            goal=goal,
            context=(
                f"{part('Framing', json.dumps(framing), RESEARCH_CHARS, untrusted=True, journal=h.journal, tag=f'analyst:{name}')}\n"
                f"Hypothesis:\n{json.dumps(hypothesis)}\n"
                f"{part('Study design', design or '(none)', RESEARCH_CHARS, untrusted=True, journal=h.journal, tag=f'analyst:{name}')}\n"
                f"{_notes_part(h, f'analyst:{name}', notes)}\n"
                f"{load_prompt('popper.discover', 'analysis_practice.md', timeout=str(h.config.execution.timeout_seconds))}"
            ),
            inputs={"data": h.run.path("data", "processed.parquet")},
            required_outputs=("results.json", "estimand.json"),
            min_figures=0 if intended else 1,
            seed_code=seed.code if seed else None,
            seed_node=seed.id if seed else None,
            blind_estimates=True,
            check=partial(observe_declared_output, test=intended, sources=[test])
            if intended and test
            else (lambda path: check_estimate(path, estimand=estimand)),
            judge_reference=declared_procedure_reference(
                intended,
                pd.read_parquet(h.run.path("data", "processed.parquet")).columns.tolist(),
                purpose=name,
            ) if intended else method_reference(
                hypothesis,
                pd.read_parquet(h.run.path("data", "processed.parquet")).columns.tolist(),
                purpose=name,
            ),
            instance_id=instance_id,
            binding=execution_binding(ScienceStore(h.run), test) if test else None,
        ),
    )


def experiment(
    h: Harness,
    framing: dict[str, Any],
    hypothesis: dict[str, Any],
    preparation: Path,
    notes: str = "",
    design: str = "",
    *,
    request: "ExperimentRequest | None" = None,
) -> Path:
    if request:
        return _scoped_experiment(h, framing, hypothesis, preparation, notes, design, request)
    committed = h.run.committed("evidence")
    if committed:
        return committed
    if h.run.committed("robustness_plan") is None:
        schedule_context(h.config.search, load_options(h.run).robustness)
    baseline = run_experiment_stage(h, "baseline", framing, hypothesis, None, notes, design)
    main = run_experiment_stage(h, "main", framing, hypothesis, baseline, notes, design)
    plan = plan_robustness(h, hypothesis, main, preparation)
    schedule = load_robustness_plan(plan, h.config.search, load_options(h.run).robustness)
    columns = pd.read_parquet(h.run.path("data", "processed.parquet")).columns.tolist()
    attempts = tuple(
        _attempt(
            item,
            item.estimand(hypothesis["primary_estimand"]),
            method_reference(
                hypothesis,
                columns,
                purpose=item.dimension,
                choice=item.choice,
                methods=item.methods,
            ),
        )
        for item in schedule.attempts
    )
    selected = {"baseline": baseline, "main": main}
    try:
        selected["robustness"] = run_stage(
            h,
            StageSpec(
            describe_input=describe_input,
            validate_results=validate_results,
                name="robustness",
                goal="Test the main contrast under recorded alternative analyses.",
                context=(
                    f"Hypothesis:\n{json.dumps(hypothesis)}\n{_notes_part(h, 'analyst:robustness', notes)}\n"
                    f"{load_prompt('popper.discover', 'analysis_practice.md', timeout=str(h.config.execution.timeout_seconds))}"
                ),
                inputs={
                    "data": h.run.path("data", "processed.parquet"),
                    "raw": h.run.path("data", "raw.csv"),
                    "prepare": preparation / "code.py",
                    "changes": preparation / "changes.json",
                },
                required_outputs=("results.json", "estimand.json"),
                seed_code=main.code,
                seed_node=main.id,
                blind_estimates=True,
                attempts=attempts,
            ),
        )
    except StageFailed:
        # Failed robustness attempts remain evidence of fragility, not a missing main result.
        pass
    return collect_evidence(h, hypothesis, selected, plan)


def _attempt(
    item: Specification, estimand: dict[str, Any], reference: JudgeReference
) -> AttemptSpec:
    goal = (
        f"Implement only this recorded {item.dimension} alternative: {item.choice}. "
        "Adapt the seeded main script; keep the declared exposure, outcome, contrast and units. "
        "For cleaning alternatives, rerun recorded preparation on the raw discovery input with "
        "the declared change; the preparation script and change log are mounted as prepare and changes. "
        f"Write {item.result_key} in results.json with value, 95% ci and positive integer n. "
        f"Write exactly this JSON object to estimand.json: {json.dumps(estimand)}. "
        f"Do not write a pass/fail flag or a stability label. {_TRANSFORM_NOTE}"
    )
    if item.kind == "adversarial":
        goal += (
            f" Permute the exposure once with numpy.random.default_rng({item.seed}).permutation, "
            "then refit the SAME estimator and primary contrast. Report the placebo interval, "
            "not a permutation p-value. Do not retry seeds to obtain a desired outcome."
        )

    def check(path: Path) -> str | None:
        return check_estimate(path, item.result_key, estimand)

    return AttemptSpec(
        item.id, item.kind, goal, json.dumps(item.model_dump(mode="json")), check, reference
    )


@dataclass(frozen=True)
class ExperimentRequest:
    test: ArtifactRef
    attempt: ArtifactRef


def _node_ref(h: Harness, node: Node) -> ArtifactRef:
    path = (node.dir / "meta.json").relative_to(h.run.root).as_posix()
    event = next(
        e
        for e in reversed(read_events(h.run.root))
        if e["event"] == "node_commit" and e.get("path") == path
    )
    return ArtifactRef(
        path=path, sha256=event["sha256"], producer="node", record_id=event["record_id"]
    )


def _scoped_experiment(
    h: Harness,
    framing: dict[str, Any],
    hypothesis: dict[str, Any],
    preparation: Path,
    notes: str,
    design: str,
    request: ExperimentRequest,
) -> Path:
    attempt = Attempt.model_validate_json(
        resolve_artifact(h.run, request.attempt).read_text("utf-8")
    )
    ensure_invalidation(ScienceStore(h.run), request.attempt)
    name = f"science:result:{attempt.id}"
    committed = h.run.committed(name)
    if committed:
        return committed
    plan = prepare_execution(ScienceStore(h.run), request.attempt)
    intended = ExperimentSpec.model_validate_json(
        resolve_artifact(h.run, request.test).read_text("utf-8")
    )
    if attempt.test != request.test or attempt.hypothesis_id != intended.hypothesis_id:
        raise IntegrityError("attempt/test ownership mismatch")
    selected: dict[str, Node] = {}
    stages: dict[str, ArtifactRef] = {}
    variants: list[ArtifactRef] = []
    for role in ("baseline", "main"):
        effective_test = plan.baseline if role == "baseline" else plan.main
        if role in attempt.reuse:
            ref = attempt.reuse[role]
            meta = json.loads(resolve_artifact(h.run, ref).read_text("utf-8"))
            nodes = load_nodes(h, meta["stage_instance"])
            selected[role] = next(n for n in nodes if n.id == meta["id"])
        else:
            try:
                selected[role] = run_experiment_stage(
                    h,
                    role,
                    framing,
                    hypothesis,
                    selected.get("baseline"),
                    notes,
                    design,
                    instance_id=attempt.stage_instances[role],
                    test=effective_test,
                )
            except StageFailed:
                break
        stages[role] = _node_ref(h, selected[role])
    variants = plan.variants
    attempts: list[AttemptSpec] = []
    for ref in variants:
        variant = ExperimentSpec.model_validate(ScienceStore(h.run).read(ref))
        key = next(k for k in variant.outputs if not k.endswith(".json"))
        attempts.append(AttemptSpec(variant.id, "adversarial" if key == "placebo_estimate" else "variant",
            adaptive_goal(variant, "robustness"), variant.model_dump_json(),
            partial(observe_declared_output, test=variant, sources=[ref]),
            declared_procedure_reference(variant, pd.read_parquet(h.run.path("data", "processed.parquet")).columns.tolist(), purpose="robustness"),
            execution_binding(ScienceStore(h.run), ref)))
    if "main" in selected and attempts:
        capacity = h.config.search.steps_for("robustness")
        try:
            run_stage(
                h,
                StageSpec(
                    "robustness",
                    "Execute predeclared sensitivity tests.",
                    "",
                    {"data": h.run.path("data", "processed.parquet")},
                    ("results.json", "estimand.json", "coverage.json"),
                    seed_code=selected["main"].code,
                    describe_input=describe_input,
            validate_results=validate_results,
                    min_figures=0,
                    blind_estimates=True,
                    seed_node=selected["main"].id,
                    attempts=tuple(attempts[:capacity]),
                    instance_id=attempt.stage_instances["robustness"],
                ),
            )
        except StageFailed:
            pass
    measured_nodes = [(role, node) for role, node in selected.items()]
    measured_nodes.extend(
        ("robustness", n)
        for n in load_nodes(h, attempt.stage_instances["robustness"])
        if n.status == "ok"
    )
    science = ScienceStore(h.run)
    outcomes = [RecordedStageOutcome(role, _node_ref(h, node)) for role, node in measured_nodes]
    result = assemble_result(science, plan, outcomes, stage_capacity=h.config.search.steps_for("robustness"))
    ref = science.commit("result", result, key=attempt.id)
    return resolve_artifact(h.run, ref)
