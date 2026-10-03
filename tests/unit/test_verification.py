from pathlib import Path

import pytest

from popper.harness.storage.records import ArtifactRef, IntegrityError
from popper.harness.storage.recovery import Journal
from popper.harness.storage.store import RunStore, file_hash
from popper.scientific.runtime.evidence.references import node_measurement
from popper.scientific.runtime.lifecycle.contracts import (
    AcceptedMeasurement,
    AttemptResult,
    Diagnosis,
    FidelityAssessment,
    Invalidation,
)
from popper.scientific.runtime.projections.output import StudyOutput, build_study
from popper.scientific.runtime.projections.state import commit_snapshot, rebuild_state
from popper.scientific.runtime.store import ScienceStore


def evidence_state(tmp_path: Path, *, fidelity: str = "consistent") -> tuple[ScienceStore, ArtifactRef]:
    science = ScienceStore(RunStore(tmp_path))
    test = science.commit("test", {"id": "t1", "hypothesis_id": "h1"})
    attempt = science.commit("source", {"test": test.model_dump(mode="json")})
    result = science.run.write_json("tree/main/node/execution/results.json", {"estimate": {"value": 2.0, "ci": [1, 3]}})
    meta = science.run.write_json("tree/main/node/meta.json", {
        "status": "ok", "hypothesis_id": "h1", "test_id": "t1", "test_ref": test.model_dump(mode="json"),
        "implementation_id": "i1", "execution_id": "exec-1",
        "outputs": {result.relative_to(tmp_path).as_posix(): file_hash(result)},
    })
    Journal(tmp_path / "journal.jsonl").write("node_commit", node="node", path=meta.relative_to(tmp_path).as_posix(), sha256=file_hash(meta), record_id="node-1")
    measurement = node_measurement(science.run, meta, "estimate")
    science.commit("result", AttemptResult(
        attempt=attempt, hypothesis_id="h1", test=test, stages={},
        measurements=[AcceptedMeasurement(
            ref=measurement, role="main", interval_level=0.95, support="supported",
            fidelity=FidelityAssessment.model_validate({"status": fidelity, "author": "judge", "reason": "Recorded procedure", "requirements": ["Declared contrast"], "sources": [test.model_dump(mode="json")]}),
            rule_precedes_execution=True,
        )],
        coverage={"missing": ["rival_estimate"], "status": "partial"}, sensitivity={}, status="partial",
    ))
    return science, commit_snapshot(science, rebuild_state(science))


def test_audit_preserves_limited_evidence(tmp_path: Path) -> None:
    from popper.stages.verify.audit import audit_evidence

    science, snapshot = evidence_state(tmp_path)
    ref = audit_evidence(science, snapshot)
    audit = science.read(ref)
    assert audit["validation_standing"] == "unavailable"
    assert any("rival_estimate" in issue["reason"] for issue in audit["issues"])
    assert all(issue["source"] for issue in audit["issues"])
    state = rebuild_state(science)
    assert len(state.observations) == 1 and state.observations[0].record.support == "supported"
    output = StudyOutput.model_validate_json(build_study(science, "Evidence is limited").read_bytes())
    assert output.audits[0]["ref"] == ref.model_dump(mode="json")
    assert output.validation_standing == "unavailable"


@pytest.mark.parametrize("condition", ["invalidated", "unresolved", "tampered", "empty"])
def test_audit_reports_evidence_standing(tmp_path: Path, condition: str) -> None:
    from popper.stages.verify.audit import audit_evidence

    science, snapshot = evidence_state(tmp_path, fidelity="unresolved" if condition == "unresolved" else "consistent")
    if condition == "empty":
        science = ScienceStore(RunStore(tmp_path / "empty"))
        snapshot = commit_snapshot(science, rebuild_state(science))
    elif condition == "invalidated":
        state = rebuild_state(science)
        diagnosis = science.commit("diagnosis", Diagnosis(category="measurement", observation_refs=[state.results[0].ref], author="judge", reason="Wrong population"))
        science.commit("invalidation", Invalidation(measurements=[state.history[0].record.ref], diagnosis=diagnosis))
        snapshot = commit_snapshot(science, rebuild_state(science))
    elif condition == "tampered":
        science.run.path("tree/main/node/execution/results.json").write_text("{}")
        with pytest.raises(IntegrityError):
            audit_evidence(science, snapshot)
        return
    audit = science.read(audit_evidence(science, snapshot))
    assert audit["validation_standing"] == "unavailable"
    assert audit["issues"]
    assert rebuild_state(science).observations == []
    assert any(condition in issue["reason"].lower() or condition == "empty" and "measurement" in issue["reason"].lower() for issue in audit["issues"])


def test_audit_scope_resume_and_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from popper.scientific.runtime.evidence.outcomes import AuditScope, commit_audit_scope
    from popper.stages.verify.audit import audit_evidence

    science, snapshot = evidence_state(tmp_path)
    original = RunStore.commit_artifact
    def commit(store: RunStore, name: str, path: Path) -> None:
        original(store, name, path)
        if name.startswith("science:audit_scope:"):
            raise KeyboardInterrupt()
    monkeypatch.setattr(RunStore, "commit_artifact", commit)
    with pytest.raises(KeyboardInterrupt):
        audit_evidence(science, snapshot)
    monkeypatch.setattr(RunStore, "commit_artifact", original)
    final = audit_evidence(science, snapshot)
    assert audit_evidence(science, snapshot) == final
    scopes = [(name, ref) for name, ref in science.commits() if name.startswith("science:audit_scope:")]
    assert len(scopes) == 1
    assert len([name for name, _ in science.commits() if name.startswith("science:audit:")]) == 1
    scope = AuditScope.model_validate(science.read(scopes[0][1]))
    changed_snapshot = commit_snapshot(science, rebuild_state(science))
    for changed in (scope.model_copy(update={"snapshot": changed_snapshot}), scope.model_copy(update={"checks": ["references"]})):
        with pytest.raises(IntegrityError):
            science.commit("audit_scope", changed, key=scope.id)
    assert commit_audit_scope(science, changed_snapshot) != scopes[0][1]
    science.run.path("tree/main/node/execution/results.json").write_text("{}")
    with pytest.raises(IntegrityError):
        audit_evidence(science, snapshot)
