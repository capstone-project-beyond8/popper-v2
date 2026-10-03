"""Compute scientific support and assemble committed experiment outcomes."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field

from popper.harness.storage.records import ArtifactRef, Record, reachable_refs, resolve_artifact
from popper.harness.storage.recovery import read_events
from popper.scientific.runtime.evidence.references import node_measurement, resolve_measurement
from popper.scientific.runtime.evidence.results import ResultEntry
from popper.scientific.runtime.lifecycle.contracts import (
    AcceptedMeasurement,
    AttemptResult,
    Standing,
    SupportRule,
)
from popper.scientific.runtime.store import ScienceStore

if TYPE_CHECKING:
    from popper.scientific.runtime.lifecycle.execution import ExecutionPlan


AuditCheck = Literal["references", "coverage", "invalidation", "fidelity"]


class AuditScope(Record):
    version: Literal[1] = 1
    rule_version: Literal[1] = 1
    id: str
    snapshot: ArtifactRef
    sources: list[ArtifactRef]
    checks: list[AuditCheck]


class AuditIssue(Record):
    source: ArtifactRef
    reason: str = Field(min_length=1)


class EvidenceAudit(Record):
    version: Literal[1] = 1
    scope: ArtifactRef
    sources: list[ArtifactRef]
    checks: dict[AuditCheck, bool]
    issues: list[AuditIssue]
    validation_standing: Literal["unavailable"] = "unavailable"


def commit_audit_scope(science: ScienceStore, snapshot: ArtifactRef) -> ArtifactRef:
    from popper.scientific.runtime.projections.state import load_snapshot, validate_sources

    state = load_snapshot(science, snapshot)
    validate_sources(science, state.model_dump(mode="json"))
    reachable_refs(science.run, snapshot)
    content = {
        "version": 1, "rule_version": 1, "snapshot": snapshot.model_dump(mode="json"),
        "sources": [r.model_dump(mode="json") for r in state.frontier],
        "checks": ["references", "coverage", "invalidation", "fidelity"],
    }
    identity = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return science.commit("audit_scope", AuditScope.model_validate({**content, "id": identity}), key=identity)


def compute_support(
    rule: SupportRule | None,
    result: ResultEntry | None,
    *,
    fidelity: str,
    rule_precedes_execution: bool,
) -> Standing:
    if rule is None or result is None or fidelity != "consistent" or result.ci is None:
        return "unavailable"
    lo, hi = result.ci
    if not all(math.isfinite(v) for v in (lo, hi)) or lo > hi:
        return "unavailable"
    if not rule_precedes_execution or rule.kind == "descriptive":
        return "post_hoc"
    if rule.kind == "directional_ci":
        assert rule.null is not None
        if rule.direction == "positive":
            return (
                "supported"
                if lo > rule.null
                else "not_supported"
                if hi < rule.null
                else "inconclusive"
            )
        return (
            "supported" if hi < rule.null else "not_supported" if lo > rule.null else "inconclusive"
        )
    assert rule.lower is not None and rule.upper is not None
    return (
        "supported"
        if rule.lower < lo <= hi < rule.upper
        else "not_supported"
        if hi < rule.lower or lo > rule.upper
        else "inconclusive"
    )


def _sensitivity(science: ScienceStore, measurements: list[AcceptedMeasurement]) -> dict[str, Any]:
    usable = [m for m in measurements if m.fidelity.status == "consistent"]
    main = next((m for m in usable if m.role == "main"), None)
    comparisons = []
    if main:
        primary = resolve_measurement(science.run, main.ref)
        for variant in usable:
            if variant.role != "robustness" or variant.ref.result_key == "placebo_estimate":
                continue
            alternative = resolve_measurement(science.run, variant.ref)
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


@dataclass(frozen=True)
class RecordedStageOutcome:
    role: str
    node: ArtifactRef


def implementation_records(science: ScienceStore, instance: str) -> list[dict[str, Any]]:
    records = []
    for event in read_events(science.run.root):
        if (
            event["event"] == "node_commit"
            and event["stage_instance"] == instance
        ):
            ref = ArtifactRef(
                path=event["path"],
                sha256=event["sha256"],
                producer="node",
                record_id=event["record_id"],
            )
            records.append({**science.read(ref), "ref": ref})
    return records


def assemble_result(
    science: ScienceStore,
    plan: ExecutionPlan,
    outcomes: list[RecordedStageOutcome],
    *,
    stage_capacity: int,
) -> AttemptResult:
    from popper.scientific.runtime.lifecycle.contracts import (
        AcceptedMeasurement,
        Attempt,
        AttemptResult,
        CheckObservation,
        Diagnosis,
        ExperimentSpec,
        FidelityAssessment,
    )

    attempt = Attempt.model_validate(science.read(plan.attempt))
    intended = ExperimentSpec.model_validate(science.read(plan.main))
    stages: dict[str, ArtifactRef] = {}
    diagnoses: list[ArtifactRef] = []
    checks: list[CheckObservation] = []
    variants = plan.variants
    required: tuple[str, ...] = tuple(r for r in ("baseline", "main") if r in intended.components)
    for role in required:
        if role not in {o.role for o in outcomes}:
            diagnoses.append(
                science.commit(
                    "diagnosis",
                    Diagnosis(
                        category="technical",
                        observation_refs=[plan.attempt],
                        author="executor",
                        reason=f"No accepted {role} implementation",
                        affected_refs=[plan.main],
                        affected_roles=[role],
                    ),
                    key=f"{attempt.id}-{role}",
                )
            )
            break
    if len(variants) > stage_capacity and any(o.role == "main" for o in outcomes):
        diagnoses.append(
            science.commit(
                "diagnosis",
                Diagnosis(
                    category="resource",
                    observation_refs=[plan.attempt],
                    author="executor",
                    reason="Declared alternatives exceed the stage execution allowance; excess alternatives remain unavailable",
                    affected_refs=[plan.main],
                    affected_roles=["robustness"],
                ),
                key=f"{attempt.id}-coverage-cap",
            )
        )
    measurements: list[AcceptedMeasurement] = []
    for role, instance in attempt.stage_instances.items():
        for node in implementation_records(science, instance):
            checks.extend(
                CheckObservation.model_validate(o) for o in node.get("check_observations", [])
            )
            if any(
                not o["passed"] and o["category"] == "measurement"
                for o in node.get("check_observations", [])
            ):
                node_ref = node["ref"]
                diagnoses.append(
                    science.commit(
                        "diagnosis",
                        Diagnosis(
                            category="measurement",
                            observation_refs=[node_ref],
                            author="checker",
                            reason=node.get("check_observations", [])[-1]["reason"],
                            affected_refs=[plan.main],
                            affected_roles=[role],
                        ),
                        key=f"check-{node['id']}",
                    )
                )
    for outcome in outcomes:
        role, node = outcome.role, science.read(outcome.node)
        assert node["test_ref"] is not None
        test = ExperimentSpec.model_validate_json(
            resolve_artifact(science.run, ArtifactRef.model_validate(node["test_ref"])).read_text(
                "utf-8"
            )
        )
        ref = outcome.node
        fidelity = FidelityAssessment(
            status=node.get("fidelity", {}).get("status", "unresolved"),
            author="judge",
            reason=node.get("fidelity", {}).get("reason", "No attributed fidelity assessment"),
            requirements=node.get("fidelity", {}).get("requirements", ["Declared procedure"]),
            sources=[ArtifactRef.model_validate(node["test_ref"]), ref],
        )
        if fidelity.status == "defect":
            diagnosis_name = f"science:diagnosis:{node['id']}"
            diagnoses.append(
                science.run.artifact_ref(diagnosis_name)
                if science.run.committed(diagnosis_name)
                else science.commit(
                    "diagnosis",
                    Diagnosis(
                        category="measurement",
                        observation_refs=[plan.attempt, ref],
                        author="judge",
                        reason=fidelity.reason,
                        affected_refs=[plan.main, ArtifactRef.model_validate(node["test_ref"])],
                        affected_roles=[role],
                    ),
                    key=node["id"],
                )
            )
        for key in test.outputs:
            if key.endswith(".json"):
                continue
            measurement = node_measurement(science.run, science.run.path(outcome.node.path), key)
            entry = resolve_measurement(science.run, measurement)
            interval = test.inference.get("interval_level")
            level = float(interval) if isinstance(interval, (int, float)) else None
            events = read_events(science.run.root)
            commit_index = next(
                i
                for i, e in enumerate(events)
                if e["event"] == "artifact_commit"
                and e.get("record_id") == ArtifactRef.model_validate(node["test_ref"]).record_id
            )
            execution_index = next(
                i
                for i, e in enumerate(events)
                if e["event"] == "exec_start" and e.get("execution_id") == node["execution_id"]
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
        stages.setdefault(role if role != "robustness" else node["id"], ref)
    completed = len({m.ref.test_id for m in measurements if m.role == "robustness"})
    coverage = {
        "requested": len(variants),
        "completed": completed,
        "missing": [
            r.path
            for r in variants
            if r.record_id
            not in {
                ArtifactRef.model_validate(science.read(o.node)["test_ref"]).record_id
                for o in outcomes
                if science.read(o.node).get("test_ref")
            }
        ],
        "status": "complete" if completed == len(variants) else "partial",
    }
    result = AttemptResult(
        attempt=plan.attempt,
        hypothesis_id=intended.hypothesis_id,
        test=plan.main,
        measurements=measurements,
        stages=stages,
        variant_tests=variants,
        checks=checks,
        diagnoses=diagnoses,
        coverage=coverage,
        sensitivity={**_sensitivity(science, measurements), "missing": coverage["missing"]},
        status="failed"
        if "main" not in {o.role for o in outcomes}
        else "partial"
        if coverage["status"] == "partial"
        else "complete",
    )
    return result
