from pathlib import Path

import pytest

from popper.harness.store import RunStore
from popper.science.contracts import Question
from popper.science.state import commit_snapshot, load_snapshot, rebuild_state
from popper.science.store import ScienceStore


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
