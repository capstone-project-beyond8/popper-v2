"""Deterministic audit of committed evidence within an immutable scope."""

from popper.harness.storage.records import ArtifactRef, IntegrityError
from popper.scientific.runtime.evidence.outcomes import (
    AuditIssue,
    AuditScope,
    EvidenceAudit,
    commit_audit_scope,
)
from popper.scientific.runtime.evidence.references import resolve_measurement
from popper.scientific.runtime.projections.state import load_snapshot, validate_sources
from popper.scientific.runtime.store import ScienceStore


def audit_evidence(science: ScienceStore, snapshot: ArtifactRef) -> ArtifactRef:
    scope_ref = commit_audit_scope(science, snapshot)
    scope = AuditScope.model_validate(science.read(scope_ref))
    state = load_snapshot(science, scope.snapshot)
    for measurement in state.history:
        resolve_measurement(science.run, measurement.record.ref)
    name = f"science:audit:{scope.id}"
    if science.run.committed(name):
        ref = science.run.artifact_ref(name)
        existing = EvidenceAudit.model_validate(science.read(ref))
        validate_sources(science, existing.model_dump(mode="json"))
        return ref
    issues: list[AuditIssue] = []
    checks = dict.fromkeys(scope.checks, True)
    if not state.history:
        issues.append(AuditIssue(source=snapshot, reason="No accepted measurement; diagnostic evidence only"))
        checks["coverage"] = False
    for result in state.results:
        missing_outputs = result.record.coverage.get("missing", [])
        if not isinstance(missing_outputs, list):
            raise IntegrityError("coverage missing outputs must be a list")
        for missing in missing_outputs:
            issues.append(AuditIssue(source=result.ref, reason=f"Missing requested measurement or execution: {missing}"))
            checks["coverage"] = False
        for check in result.record.checks:
            if not check.passed:
                issues.append(AuditIssue(source=result.ref, reason=f"Unsatisfied {check.category} check: {check.reason}"))
                checks["coverage"] = False
    active = {m.record.ref.model_dump_json() for m in state.observations}
    for measurement in state.history:
        if measurement.record.fidelity.status != "consistent":
            checks["fidelity"] = False
            issues.append(AuditIssue(source=measurement.ref, reason=f"{measurement.record.fidelity.status} fidelity: {measurement.record.fidelity.reason}"))
        elif measurement.record.ref.model_dump_json() not in active:
            checks["invalidation"] = False
            issues.append(AuditIssue(source=measurement.ref, reason="Invalidated measurement is excluded from current support"))
    return science.commit("audit", EvidenceAudit(
        scope=scope_ref, sources=scope.sources, checks=checks, issues=issues,
    ), key=scope.id)
