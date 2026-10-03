from pathlib import Path

import pytest

from popper.discover.state import commit_snapshot, rebuild_state
from popper.harness.config import load_config
from popper.harness.llm import FakeLLM
from popper.harness.session import Harness
from popper.harness.store import RunStore
from popper.science.contracts import Question
from popper.science.store import ScienceStore


def test_projection_frontier_and_corruption(tmp_path: Path) -> None:
    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    source = h.run.write_json("intent.json", {"objective": "compare"})
    h.run.commit_artifact("science:intent", source)
    ref = h.run.artifact_ref("science:intent")
    question = Question(hypothesis_id="h1", text="Is variance stable?", author="theorist", sources=[ref])
    qref = ScienceStore(h.run).commit("question", question)
    state = rebuild_state(h)
    snap = commit_snapshot(h, state)
    ScienceStore(h.run).commit("proposals", {"snapshot": snap.model_dump(), "moves": []})
    ScienceStore(h.run).commit("selection", {"snapshot": snap.model_dump()})
    h.spent_usd = 1
    refreshed = rebuild_state(h)
    assert refreshed.frontier == state.frontier
    assert refreshed.questions[0].record.resolved is False
    assert refreshed.budget["spent_usd"] == 1
    assert refreshed.model_dump() == rebuild_state(h).model_dump()
    ScienceStore(h.run).commit("question", question.model_copy(update={"text": "What explains the difference?"}))
    assert rebuild_state(h).frontier != state.frontier
    h.run.path(qref.path).write_text("{}")
    with pytest.raises(ValueError, match="hash"):
        rebuild_state(h)
