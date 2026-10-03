"""Sequential experiments for one declared primary estimand."""

import json
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from popper.harness.context.prompts import load_prompt
from popper.harness.context.rendering import RESEARCH_CHARS, part
from popper.harness.session import Harness
from popper.harness.storage.records import ArtifactRef, IntegrityError, resolve_artifact
from popper.scientific.runtime.data.descriptive import describe_input
from popper.scientific.runtime.evidence.outcomes import (
    RecordedStageOutcome,
    assemble_result,
)
from popper.scientific.runtime.evidence.results import validate_results
from popper.scientific.runtime.lifecycle.contracts import (
    Attempt,
    ExperimentSpec,
)
from popper.scientific.runtime.lifecycle.execution import (
    adaptive_goal,
    execution_binding,
    observe_declared_output,
    prepare_execution,
)
from popper.scientific.runtime.lifecycle.requests import ExperimentRequest
from popper.scientific.runtime.lifecycle.transitions import ensure_invalidation
from popper.scientific.runtime.projections.views import node_ref
from popper.scientific.runtime.store import ScienceStore
from popper.strategies.treesearch.engine import (
    AttemptSpec,
    Node,
    StageFailed,
    StageSpec,
    load_nodes,
    run_stage,
)
from popper.strategies.treesearch.judge import JudgeReference


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
    test: ArtifactRef,
    instance_id: str | None = None,
    admission: ArtifactRef | None = None,
) -> Node:
    intended = ExperimentSpec.model_validate_json(resolve_artifact(h.run, test).read_text("utf-8"))
    return run_stage(
        h,
        StageSpec(
            describe_input=describe_input,
            validate_results=validate_results,
            name=name,
            goal=adaptive_goal(intended, name),
            context=(
                f"{part('Framing', json.dumps(framing), RESEARCH_CHARS, untrusted=True, journal=h.journal, tag=f'analyst:{name}')}\n"
                f"{part('Hypothesis', json.dumps(hypothesis), RESEARCH_CHARS, untrusted=True, journal=h.journal, tag=f'analyst:{name}')}\n"
                f"{part('Study design', design or '(none)', RESEARCH_CHARS, untrusted=True, journal=h.journal, tag=f'analyst:{name}')}\n"
                f"{_notes_part(h, f'analyst:{name}', notes)}\n"
                f"{load_prompt('popper.stages.discover', 'analysis_practice.md', timeout=str(h.config.execution.timeout_seconds))}"
            ),
            inputs={"data": h.run.path("data", "processed.parquet")},
            required_outputs=("results.json", "estimand.json"),
            seed_code=seed.code if seed else None,
            seed_node=seed.id if seed else None,
            blind_estimates=True,
            check=partial(observe_declared_output, test=intended, sources=[test]),
            judge_reference=declared_procedure_reference(
                intended,
                pd.read_parquet(h.run.path("data", "processed.parquet")).columns.tolist(),
                purpose=name,
            ),
            instance_id=instance_id,
            binding=execution_binding(ScienceStore(h.run), test, admission),
            artifact_roots={name: h.run.root for name in ("results.json", "analysis.md", "changes.json", "framing.json", "hypotheses.json")},
        ),
    )


def experiment(
    h: Harness,
    framing: dict[str, Any],
    hypothesis: dict[str, Any],
    notes: str = "",
    design: str = "",
    *,
    request: ExperimentRequest,
) -> Path:
    science = ScienceStore(h.run)
    attempt = Attempt.model_validate_json(
        resolve_artifact(h.run, request.attempt).read_text("utf-8")
    )
    ensure_invalidation(science, request.attempt)
    name = f"science:result:{attempt.id}"
    committed = h.run.committed(name)
    if committed:
        return committed
    plan = prepare_execution(science, request.attempt)
    intended = ExperimentSpec.model_validate_json(
        resolve_artifact(h.run, request.test).read_text("utf-8")
    )
    if attempt.test != request.test or attempt.hypothesis_id != intended.hypothesis_id:
        raise IntegrityError("attempt/test ownership mismatch")
    selected: dict[str, Node] = {}
    for role in (r for r in ("baseline", "main") if r in intended.components):
        effective_test = plan.baseline if role == "baseline" else plan.main
        if role in attempt.reuse:
            ref = attempt.reuse[role]
            meta = json.loads(resolve_artifact(h.run, ref).read_text("utf-8"))
            nodes = load_nodes(h, meta["stage_instance"])
            selected[role] = next(n for n in nodes if n.id == meta["id"])
        else:
            assert effective_test is not None, "declared component has no planned test"
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
                    admission=request.admission,
                )
            except StageFailed:
                break
    attempts: list[AttemptSpec] = []
    for ref in plan.variants:
        variant = ExperimentSpec.model_validate(science.read(ref))
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
                execution_binding(science, ref, request.admission),
            )
        )
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
                    blind_estimates=True,
                    seed_node=selected["main"].id,
                    attempts=tuple(attempts[:capacity]),
                    instance_id=attempt.stage_instances["robustness"],
                    artifact_roots={name: h.run.root for name in ("results.json", "analysis.md", "changes.json", "framing.json", "hypotheses.json")},
                ),
            )
        except StageFailed:
            pass
    measured_nodes = list(selected.items())
    measured_nodes.extend(
        ("robustness", n)
        for n in load_nodes(h, attempt.stage_instances["robustness"])
        if n.status == "ok"
    )
    outcomes = [
        RecordedStageOutcome(role, node_ref(science, node.dir / "meta.json"))
        for role, node in measured_nodes
    ]
    result = assemble_result(
        science, plan, outcomes, stage_capacity=h.config.search.steps_for("robustness")
    )
    result = result.model_copy(update={"admission": request.admission})
    ref = science.commit("result", result, key=attempt.id)
    return resolve_artifact(h.run, ref)
