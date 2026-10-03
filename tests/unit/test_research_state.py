from pathlib import Path

import pytest
from pydantic import ValidationError

from popper.harness.storage.store import RunStore
from popper.scientific.runtime.lifecycle.contracts import Question
from popper.scientific.runtime.projections.state import (
    commit_snapshot,
    load_snapshot,
    rebuild_state,
)
from popper.scientific.runtime.store import ScienceStore


def test_projection_frontier_and_corruption(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    science = ScienceStore(store)
    source = store.write_json("intent.json", {"objective": "compare"})
    store.commit_artifact("science:intent", source)
    ref = store.artifact_ref("science:intent")
    question = Question(hypothesis_id="h1", text="Is variance stable?", author="theorist", sources=[ref])
    qref = science.commit("question", question)
    state = rebuild_state(science)
    assert "budget" not in state.model_dump()
    snap = commit_snapshot(science, state)
    assert load_snapshot(science, snap) == state
    old = science.commit("snapshot", {**science.read(snap), "version": 3})
    with pytest.raises(ValidationError):
        load_snapshot(science, old)
    science.commit("proposals", {"snapshot": snap.model_dump(), "moves": []})
    science.commit("selection", {"snapshot": snap.model_dump()})
    refreshed = rebuild_state(science)
    assert refreshed.frontier == state.frontier
    assert refreshed.questions[0].record.resolved is False
    assert refreshed.model_dump() == rebuild_state(science).model_dump()
    science.commit("question", question.model_copy(update={"text": "What explains the difference?"}))
    assert rebuild_state(science).frontier != state.frontier
    store.path(qref.path).write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        rebuild_state(science)


def test_pending_decisions_use_newest_unconsumed_current_frontier(tmp_path: Path) -> None:
    from popper.scientific.runtime.lifecycle.contracts import Attempt, MoveSelection
    from popper.scientific.runtime.projections.state import pending_proposal, pending_selection

    science = ScienceStore(RunStore(tmp_path))
    intent = science.commit("intent", {"objective": "compare"})
    old = commit_snapshot(science, rebuild_state(science))
    stale = science.commit("proposals", {"snapshot": old.model_dump(mode="json"), "moves": []}, key="stale")
    science.commit("selection", MoveSelection(proposal_id="stale-move", snapshot=old, proposals=stale, author="scientist", rationale="old frontier"), key="stale")
    science.commit("question", Question(hypothesis_id="h1", text="What distinguishes rivals?", author="theorist", sources=[intent]))
    science.commit("attempt", Attempt(
        id="a1", move=intent, move_id="used", hypothesis_id="h1", test=intent,
        parent=None, diagnosis=None, changed_fields=[], stage_instances={}, move_count=1,
        revisit_count=0, exposure=[],
    ))
    state = rebuild_state(science)
    current = commit_snapshot(science, state)
    assert pending_selection(science, state) is None and pending_proposal(science, state) is None
    first = science.commit("proposals", {"snapshot": current.model_dump(mode="json"), "moves": []}, key="first")
    newest = science.commit("proposals", {"snapshot": current.model_dump(mode="json"), "moves": []}, key="newest")
    assert pending_proposal(science, state) == (newest, current)
    chosen = science.commit("selection", MoveSelection(proposal_id="fresh", snapshot=current, proposals=newest, author="scientist", rationale="current frontier"), key="fresh")
    assert pending_proposal(science, state) == (first, current)
    assert pending_selection(science, state) == chosen
    consumed = science.commit("proposals", {"snapshot": current.model_dump(mode="json"), "moves": []}, key="consumed")
    science.commit("selection", MoveSelection(proposal_id="used", snapshot=current, proposals=consumed, author="scientist", rationale="already attempted"), key="used")
    assert pending_selection(science, state) == chosen
    assert pending_proposal(science, state) == (first, current)


def test_stage_admission_completion_and_deferral(tmp_path: Path) -> None:
    from popper.harness.storage.records import IntegrityError
    from popper.scientific.runtime.lifecycle.contracts import MoveProposal, MoveSelection
    from popper.scientific.runtime.lifecycle.transitions import (
        admit_stage,
        complete_stage,
        defer_stage,
        validate_moves,
    )

    science = ScienceStore(RunStore(tmp_path))
    intent = science.commit("intent", {"objective": "compare"})
    snapshot = commit_snapshot(science, rebuild_state(science))
    moves = validate_moves(science, snapshot, [MoveProposal(
        action="audit", objective="check evidence", trigger_refs=[intent],
        cost_usd=0, stopping_condition="scope checked",
    )])
    proposals = science.commit("proposals", {"snapshot": snapshot.model_dump(mode="json"), "moves": [m.model_dump(mode="json") for m in moves]})
    selection = science.commit("selection", MoveSelection(
        proposal_id=moves[0].id, snapshot=snapshot, proposals=proposals,
        author="scientist", rationale="check gaps before reporting",
    ))
    admission = admit_stage(science, selection)
    assert admit_stage(science, selection) == admission
    pending = rebuild_state(science)
    assert [a.ref for a in pending.pending_admissions] == [admission]
    assert pending.stage_history == []
    output = science.commit("audit", {"sources": [intent.model_dump(mode="json")]})
    terminal = complete_stage(science, admission, "completed", [output], "checked scope")
    assert complete_stage(science, admission, "completed", [output], "checked scope") == terminal
    with pytest.raises(IntegrityError, match="conflicting"):
        complete_stage(science, admission, "failed", [], "different outcome")
    final = rebuild_state(science)
    assert final.pending_admissions == []
    assert final.stage_history[0].record.outputs == [output]
    with pytest.raises(IntegrityError):
        complete_stage(science, admission, "completed", [output.model_copy(update={"sha256": "a" * 64})], "checked scope")
    # A distinct selection can be refused without claiming that its stage ran.
    snapshot = commit_snapshot(science, final)
    selection = science.commit("selection", MoveSelection(
        proposal_id=moves[0].id, snapshot=snapshot, proposals=proposals,
        author="scientist", rationale="resource check",
    ))
    disposition = defer_stage(science, selection, "resource cap reached")
    assert defer_stage(science, selection, "resource cap reached") == disposition
    assert len(rebuild_state(science).stage_admissions) == 1
