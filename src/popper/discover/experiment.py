"""Sequential experiments for one declared primary estimand."""

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from popper.discover.policy import ensure_invalidation
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
from popper.harness.results import ResultEntry
from popper.harness.session import Harness
from popper.science.contracts import (
    AcceptedMeasurement,
    Attempt,
    AttemptResult,
    CheckObservation,
    Diagnosis,
    ExperimentSpec,
    FidelityAssessment,
    MethodSpec,
    classify_change,
)
from popper.science.evidence import node_measurement, resolve_measurement
from popper.science.state import compute_support
from popper.science.store import ScienceStore
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


def check_estimate(
    workdir: Path,
    key: str = "primary_estimate",
    estimand: dict[str, Any] | None = None,
) -> str | None:
    try:
        raw = json.loads((workdir / "results.json").read_text("utf-8"))
        if not isinstance(raw, dict):
            return "results.json must be a JSON object"
        if key not in raw:
            return (
                f"results.json has no {key!r} entry; "
                "write it with value, a 95% ci [low, high] and integer n"
            )
        entry = ResultEntry.model_validate_json(json.dumps(raw[key]))
        if type(entry.value) not in (int, float) or not math.isfinite(float(entry.value)):
            return f"{key} needs a finite numerical estimate"
        if (
            entry.ci is None
            or not all(math.isfinite(v) for v in entry.ci)
            or entry.ci[0] > entry.ci[1]
        ):
            return f"{key} needs an ordered finite interval"
        if entry.n is None or entry.n <= 0:
            return f"{key} needs a positive integer sample size"
        if estimand is not None:
            declared = json.loads((workdir / "estimand.json").read_text("utf-8"))
            if not isinstance(declared, dict):
                return "estimand.json must be a JSON object"
            for name, required in estimand.items():
                if declared.get(name) != required:
                    return f"estimand.json {name!r} must be exactly {required!r}"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return f"invalid {key}: {exc}"
    return None


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
            test=test,
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
        schedule_context(h.config)
    baseline = run_experiment_stage(h, "baseline", framing, hypothesis, None, notes, design)
    main = run_experiment_stage(h, "main", framing, hypothesis, baseline, notes, design)
    plan = plan_robustness(h, hypothesis, main, preparation)
    schedule = load_robustness_plan(plan, h.config)
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


def adaptive_goal(test: ExperimentSpec, role: str) -> str:
    return (
        f"Execute the committed {role} scientific test. "
        "Baseline uses a transparent estimator; all other stages follow the declared procedure. "
        f"Requirements: {test.model_dump_json()}. "
        "Write results.json with declared named measurements, finite value, ordered ci and positive n; "
        "write estimand.json matching the intended estimand. Write coverage.json with actually used "
        "seeds, interval_level and effect_scale; check these against implemented code. "
        "Figures are optional. Negative/null evidence is a valid scientific outcome. "
        "Never alter seeds, sample, inference effort or output scale to obtain significance or save resources."
    )


def check_declared_output(path: Path, test: ExperimentSpec) -> str | None:
    for key in test.outputs:
        if key.endswith(".json"):
            continue
        failure = check_estimate(path, key, test.primary_estimand.model_dump())
        if failure:
            return failure
    try:
        coverage = json.loads((path / "coverage.json").read_text("utf-8"))
        for key in ("seeds",):
            if key in test.requested_coverage and coverage.get(key) != test.requested_coverage[key]:
                return f"coverage {key} does not match committed request"
        if coverage.get("interval_level") != test.inference.get("interval_level"):
            return "interval level does not match committed inference"
        if coverage.get("effect_scale") != test.primary_estimand.unit:
            return "measurement effect scale differs from intended scale"
    except (OSError, ValueError) as exc:
        return f"invalid coverage: {exc}"
    return None


def observe_declared_output(
    path: Path, test: ExperimentSpec, sources: list[ArtifactRef]
) -> dict[str, Any]:
    failure = check_declared_output(path, test)
    return CheckObservation(
        category="measurement",
        requirement="Declared named outputs, estimand, scale and coverage",
        passed=failure is None,
        sources=sources,
        reason=failure
        or "Structural declaration checks passed; algorithm fidelity still requires assessment",
    ).model_dump(mode="json")


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


def _sensitivity(h: Harness, measurements: list[AcceptedMeasurement]) -> dict[str, Any]:
    usable = [m for m in measurements if m.fidelity.status == "consistent"]
    main = next((m for m in usable if m.role == "main"), None)
    comparisons = []
    if main:
        primary = resolve_measurement(h.run, main.ref)
        for variant in usable:
            if variant.role != "robustness" or variant.ref.result_key == "placebo_estimate":
                continue
            alternative = resolve_measurement(h.run, variant.ref)
            assert isinstance(primary.value, (int, float)) and isinstance(
                alternative.value, (int, float)
            )
            comparisons.append(
                {
                    "main": main.ref.model_dump(mode="json"),
                    "variant": variant.ref.model_dump(mode="json"),
                    "same_direction": primary.value * alternative.value > 0,
                    "intervals_overlap": bool(
                        primary.ci
                        and alternative.ci
                        and max(primary.ci[0], alternative.ci[0])
                        <= min(primary.ci[1], alternative.ci[1])
                    ),
                }
            )
    return {"comparisons": comparisons}


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
    ensure_invalidation(h, request.attempt)
    name = f"science:result:{attempt.id}"
    committed = h.run.committed(name)
    if committed:
        return committed
    intended = ExperimentSpec.model_validate_json(
        resolve_artifact(h.run, request.test).read_text("utf-8")
    )
    if attempt.test != request.test or attempt.hypothesis_id != intended.hypothesis_id:
        raise IntegrityError("attempt/test ownership mismatch")
    selected: dict[str, Node] = {}
    stages: dict[str, ArtifactRef] = {}
    diagnoses: list[ArtifactRef] = []
    checks: list[CheckObservation] = []
    variants: list[ArtifactRef] = []
    for role in ("baseline", "main"):
        effective_test = request.test
        if role == "baseline":
            baseline_spec = ExperimentSpec.model_validate(
                {
                    **intended.model_dump(mode="json"),
                    "id": f"{intended.id}-baseline",
                    "parent_test": request.test.model_dump(mode="json"),
                    "support_rule": None,
                    "methods": [
                        {
                            "family": "difference_in_means",
                            "description": "Transparent baseline contrast",
                            "inputs": [
                                intended.primary_estimand.exposure,
                                intended.primary_estimand.outcome,
                            ],
                            "outputs": ["primary_estimate"],
                            "effect_scale": intended.primary_estimand.unit,
                        }
                    ],
                }
            )
            effective_test = ScienceStore(h.run).commit("test", baseline_spec, key=f"{attempt.id}-baseline")
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
                diagnosis = Diagnosis(
                    category="technical",
                    observation_refs=[request.attempt],
                    author="executor",
                    reason=f"No accepted {role} implementation",
                    affected_refs=[request.test],
                    affected_roles=[role],
                )
                diagnoses.append(
                    ScienceStore(h.run).commit("diagnosis", diagnosis, key=f"{attempt.id}-{role}")
                )
                break
        stages[role] = _node_ref(h, selected[role])
    # Each alternative is frozen before its execution and retains the substantive target.
    alternative_payloads = intended.requested_coverage.get("alternatives", [])
    if not isinstance(alternative_payloads, list):
        raise IntegrityError("declared alternatives must be a list")
    attempts: list[AttemptSpec] = []
    for index, payload in enumerate(alternative_payloads):
        if not isinstance(payload, dict):
            raise IntegrityError("variant declaration must be an object")
        variant = ExperimentSpec.model_validate(
            {
                **intended.model_dump(mode="json"),
                **payload,
                "id": f"{intended.id}-v{index:03d}",
                "hypothesis_id": intended.hypothesis_id,
                "parent_test": request.test.model_dump(mode="json"),
            }
        )
        if classify_change(intended, variant) == "pivot":
            raise IntegrityError("robustness cannot change the substantive target")
        ref = ScienceStore(h.run).commit("test", variant, key=f"{attempt.id}-v{index:03d}")
        variants.append(ref)
        key = next(k for k in variant.outputs if not k.endswith(".json"))
        attempts.append(
            AttemptSpec(
                variant.id,
                "adversarial" if key == "placebo_estimate" else "variant",
                adaptive_goal(variant, "robustness"),
                variant.model_dump_json(),
                partial(observe_declared_output, test=variant, sources=[ref]),
                declared_procedure_reference(
                    variant,
                    pd.read_parquet(h.run.path("data", "processed.parquet")).columns.tolist(),
                    purpose="robustness",
                ),
                ref,
            )
        )
    if "main" in selected and attempts:
        capacity = h.config.search.steps_for("robustness")
        if len(attempts) > capacity:
            diagnoses.append(ScienceStore(h.run).commit("diagnosis", Diagnosis(
                    category="resource", observation_refs=[request.attempt], author="executor",
                    reason="Declared alternatives exceed the stage execution allowance; excess alternatives remain unavailable",
                    affected_refs=[request.test], affected_roles=["robustness"],
                ), key=f"{attempt.id}-coverage-cap",
            ))
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
    measurements: list[AcceptedMeasurement] = []
    for role, instance in attempt.stage_instances.items():
        for node in load_nodes(h, instance, include_abandoned=True):
            checks.extend(CheckObservation.model_validate(o) for o in node.check_observations)
            if any(
                not o["passed"] and o["category"] == "measurement" for o in node.check_observations
            ):
                node_ref = _node_ref(h, node)
                diagnoses.append(
                    ScienceStore(h.run).commit("diagnosis",
                        Diagnosis(
                            category="measurement",
                            observation_refs=[node_ref],
                            author="checker",
                            reason=node.check_observations[-1]["reason"],
                            affected_refs=[request.test],
                            affected_roles=[role],
                        ),
                        key=f"check-{node.id}",
                    )
                )
    for role, node in measured_nodes:
        assert node.test_ref is not None
        test = ExperimentSpec.model_validate_json(
            resolve_artifact(h.run, node.test_ref).read_text("utf-8")
        )
        ref = _node_ref(h, node)
        fidelity = FidelityAssessment(
            status=node.fidelity.get("status", "unresolved"),
            author="judge",
            reason=node.fidelity.get("reason", "No attributed fidelity assessment"),
            requirements=node.fidelity.get("requirements", ["Declared procedure"]),
            sources=[node.test_ref, ref],
        )
        if fidelity.status == "defect":
            diagnosis_name = f"science:diagnosis:{node.id}"
            diagnoses.append(
                h.run.artifact_ref(diagnosis_name) if h.run.committed(diagnosis_name) else ScienceStore(h.run).commit("diagnosis",
                    Diagnosis(
                        category="measurement",
                        observation_refs=[request.attempt, ref],
                        author="judge",
                        reason=fidelity.reason,
                        affected_refs=[request.test, node.test_ref],
                        affected_roles=[role],
                    ),
                    key=node.id,
                )
            )
        for key in test.outputs:
            if key.endswith(".json"):
                continue
            measurement = node_measurement(h.run, node.dir / "meta.json", key)
            entry = resolve_measurement(h.run, measurement)
            interval = test.inference.get("interval_level")
            level = float(interval) if isinstance(interval, (int, float)) else None
            events = read_events(h.run.root)
            commit_index = next(
                i
                for i, e in enumerate(events)
                if e["event"] == "artifact_commit" and e.get("record_id") == node.test_ref.record_id
            )
            execution_index = next(
                i
                for i, e in enumerate(events)
                if e["event"] == "exec_start" and e.get("execution_id") == node.execution_id
            )
            precedes = commit_index < execution_index
            rule = test.support_rule
            usable_rule = (
                rule if rule and rule.interval_level == level and rule.result_key == key else None
            )
            support = compute_support(
                usable_rule, entry, fidelity=fidelity.status, rule_precedes_execution=precedes
            )
            measurements.append(
                AcceptedMeasurement(
                    ref=measurement,
                    role=role,
                    interval_level=level,
                    fidelity=fidelity,
                    support=support,
                    rule_precedes_execution=precedes,
                )
            )
        stages.setdefault(role if role != "robustness" else node.id, ref)
    completed = len({m.ref.test_id for m in measurements if m.role == "robustness"})
    coverage = {
        "requested": len(attempts),
        "completed": completed,
        "missing": [
            r.path
            for r in variants
            if r.record_id not in {n.test_ref.record_id for _, n in measured_nodes if n.test_ref}
        ],
        "status": "complete" if completed == len(attempts) else "partial",
    }
    result = AttemptResult(
        attempt=request.attempt,
        hypothesis_id=intended.hypothesis_id,
        test=request.test,
        measurements=measurements,
        stages=stages,
        variant_tests=variants,
        checks=checks,
        diagnoses=diagnoses,
        coverage=coverage,
        sensitivity={**_sensitivity(h, measurements), "missing": coverage["missing"]},
        status="failed"
        if "main" not in selected
        else "partial"
        if coverage["status"] == "partial"
        else "complete",
    )
    ref = ScienceStore(h.run).commit("result", result, key=attempt.id)
    return resolve_artifact(h.run, ref)
