from pathlib import Path

import pytest

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
    assert science.read(snap)["version"] == 2
    old = science.commit("snapshot", {**state.model_dump(mode="json"), "version": 1, "budget": {"spent_usd": 100, "max_usd": 1}})
    before = store.path(old.path).read_bytes()
    assert load_snapshot(science, old) == state
    assert store.path(old.path).read_bytes() == before
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
