import json
from pathlib import Path
from typing import Any

import pytest
from evals.run_metrics import main, summarize

from popper.harness.storage.recovery import Journal
from popper.harness.storage.store import RunStore
from popper.scientific.runtime.lifecycle.contracts import MoveProposal, MoveSelection
from popper.scientific.runtime.lifecycle.transitions import (
    admit_stage,
    complete_stage,
    validate_moves,
)
from popper.scientific.runtime.projections.output import build_study
from popper.scientific.runtime.projections.state import commit_snapshot, rebuild_state
from popper.scientific.runtime.store import ScienceStore
from popper.stages.verify.audit import audit_evidence


def test_metrics_keep_sessions_costs_and_failures_separate() -> None:
    events: list[dict[str, Any]] = [
        {"event": "phase", "name": "ground"},
        {
            "event": "llm_call",
            "role": "theorist",
            "tag": "ground",
            "session": "a",
            "input_tokens": 10,
            "cache_read_tokens": 80,
            "cache_write_tokens": 10,
            "output_tokens": 5,
            "usd": 0.2,
        },
        {
            "event": "tool_call",
            "tag": "ground",
            "session": "a",
            "tool": "submit_ground",
            "status": "error",
            "result": "invalid evidence",
        },
        {
            "event": "tool_call",
            "tag": "ground",
            "session": "a",
            "tool": "read_artifact",
            "status": "error",
            "result": "error: artifact does not exist",
        },
        {
            "event": "tool_call",
            "tag": "ground",
            "session": "a",
            "tool": "run_python",
            "status": "error",
            "result": "exit code 1",
        },
        {
            "event": "tool_call",
            "tag": "ground",
            "session": "a",
            "tool": "ask_researcher",
            "status": "success",
            "result": "No researcher is available",
        },
        {
            "event": "tool_call",
            "tag": "ground",
            "session": "a",
            "tool": "submit_ground",
            "status": "success",
        },
        {
            "event": "llm_call",
            "role": "theorist",
            "tag": "ground",
            "session": "b",
            "input_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 0,
            "usd": 0.1,
        },
        {"event": "context_cut", "tag": "ground", "title": "data", "length": 20, "limit": 10},
        {"event": "phase", "name": "communicate"},
        {"event": "llm_call", "role": "writer", "tag": "writeup", "usd": 0.1},
        {"event": "state_commit", "path": "state/000001.json"},
        {
            "event": "tool_call", "tag": "ground", "session": "a", "tool": "submit_ground",
            "terminal": True, "status": "skipped", "result": "submission already accepted",
        },
        {
            "event": "tool_call", "tag": "ground", "session": "b", "tool": "finish",
            "terminal": True, "status": "skipped", "result": "reply truncated",
        },
        {
            "event": "tool_call", "tag": "ground", "session": "b", "tool": "ask_researcher",
            "status": "skipped", "result": "No researcher is available",
        },
    ]
    report = summarize(events)
    assert report["total"]["usd"] == 0.4
    assert report["total"]["cache_read_ratio"] == 0.8
    assert report["roles"]["theorist"]["calls"] == 2
    assert report["tags"]["ground"]["input_tokens"] == 10
    assert report["sessions"]["a"]["rejected_submits"] == 1
    assert report["sessions"]["a"]["accepted_submits"] == 1
    assert report["sessions"]["b"]["cache_read_ratio"] == 0
    assert report["sessions"]["b"]["accepted_submits"] == 0
    assert report["tool_errors"] == {"avoidable": 2, "code": 1, "other": 0}
    assert report["sessions"]["a"]["role"] == "theorist"
    assert report["sessions"]["a"]["tag"] == "ground"
    assert len(report["context_cuts"]) == 1
    assert report["phases"]["ground"]["usd"] == 0.3
    assert report["phases"]["communicate"]["cumulative_usd"] == 0.4


@pytest.mark.parametrize(("version", "finished"), [(4, True), (5, True), (6, False), (6, True)])
def test_metrics_deliver_committed_science_without_mutation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], version: int, finished: bool,
) -> None:
    store = RunStore(tmp_path)
    store.write_json("run.json", {"format_version": version, "config": {}})
    science = ScienceStore(store)
    source = science.commit("intent", {"research": "Association does not resolve the rival"}, key="initial")
    Journal(store.path("journal.jsonl")).write("llm_call", tag="scientist", usd=0.25)
    if version == 6:
        snapshot = commit_snapshot(science, rebuild_state(science))
        moves = validate_moves(science, snapshot, [
            MoveProposal(action=action, objective="Check the evidence gap", trigger_refs=[source],
                cost_usd=0, stopping_condition="Rival remains unresolved")
            for action in ("audit", "synthesize")
        ])
        proposals = science.commit("proposals", {"snapshot": snapshot.model_dump(mode="json"),
            "moves": [move.model_dump(mode="json") for move in moves]}, key=snapshot.record_id)
        selection = science.commit("selection", MoveSelection(proposal_id=moves[0].id,
            snapshot=snapshot, proposals=proposals, author="scientist",
            rationale="Check the missing evidence before further interpretation"), key=proposals.record_id)
        admission = admit_stage(science, selection)
        if finished:
            audit = audit_evidence(science, snapshot)
            complete_stage(science, admission, "completed", [audit], "Evidence gap recorded")
            build_study(science, "Rival remains unresolved", key="finish:case")
    else:
        # A saved report alone is not an admission or a scientific decision.
        report = store.write_json("report/report.json", {"tex": "report/paper.tex"})
        store.commit_artifact("report", report)
    if finished:
        store.checkpoint({"status": "completed", "message": ""})
    original = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    assert main([str(tmp_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    trace = report["scientific"]
    assert report["total"]["usd"] == 0.25
    assert source.model_dump(mode="json") in trace["sources"]
    assert trace["validation_standing"] == "unavailable"
    if version == 6:
        decision = trace["decisions"][0]
        assert decision["selected"]["action"] == "audit"
        assert decision["selected"]["trigger_refs"] == [source.model_dump(mode="json")]
        assert decision["displaced"][0]["action"] == "synthesize"
        assert decision["rationale"] == "Check the missing evidence before further interpretation"
        if finished:
            assert trace["pending_work"] == []
            assert trace["stage_history"][0]["work"]["record"]["stage"] == "verify"
            assert trace["stage_history"][0]["record"]["status"] == "completed"
            assert trace["stop_reason"] == "Rival remains unresolved"
        else:
            assert trace["stage_history"] == []
            assert trace["pending_work"][0]["ref"] == admission.model_dump(mode="json")
            assert trace["operational_status"] == "running"
            assert trace["stop_reason"] is None
    else:
        assert trace["stage_history"] is None and trace["pending_work"] is None
        assert trace["decisions"] == [] and trace["stop_reason"] is None
    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == original
