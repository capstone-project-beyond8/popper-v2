import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from popper.coordinator.run import RunOutcome, resume, run
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.recovery import load_state
from popper.harness.store import RunStore
from tests.integration.test_run import EXAMPLE, FRAMING, _config, _respond

pytestmark = pytest.mark.integration

REVISED = {
    **FRAMING,
    "questions": [{**FRAMING["questions"][0], "id": "hours_vs_marks"}],  # type: ignore[index]
}


def _llm(revision: bool = False) -> FakeLLM:
    """Replies like a normal run but stops at the first data-stage call."""

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        if req.tag == "analyst:data":
            raise KeyboardInterrupt("reached the data stage")
        if revision and req.tag == "theorist" and "Guidance for this revision" in req.prompt:
            return (ToolCall("frame-2", "submit_frame", {"framing": REVISED}),)
        return _respond(req)

    return FakeLLM(respond)


def _start(tmp_path: Path, *, auto: bool = False) -> tuple[RunOutcome | None, Path, FakeLLM]:
    llm = _llm()
    outcome = None
    try:
        outcome = run(
            EXAMPLE / "research.md",
            EXAMPLE / "data.csv",
            config=_config(),
            auto=auto,
            llm=llm,
            runs_dir=tmp_path,
        )
    except KeyboardInterrupt:
        pass
    return outcome, next(p for p in tmp_path.iterdir() if p.is_dir()), llm


def _reach_data_stage(root: Path, llm: FakeLLM, review: Path | None = None) -> None:
    with pytest.raises(KeyboardInterrupt):
        resume(root, llm=llm, review=review)


def _tags(llm: FakeLLM) -> list[str]:
    return [r.tag for r in llm.calls]


def _write_signals(root: Path, edit: dict[str, Any]) -> Path:
    path = next(root.glob("understand/*/review.yaml"))
    review = yaml.safe_load(path.read_text("utf-8"))
    for key, change in edit.items():
        review["items"][key].update(change)
    target = root / "my-review.yaml"
    target.write_text(yaml.safe_dump(review), encoding="utf-8")
    return target


def _provenance(root: Path) -> dict[str, Any]:
    framing = RunStore(root).committed("frame_reviewed")
    assert framing is not None
    path = framing.parent / "provenance.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else {}


def test_run_stops_for_review_before_the_data_stage(tmp_path: Path) -> None:
    outcome, root, llm = _start(tmp_path)
    assert outcome is not None and outcome.status == "awaiting_review"
    assert outcome.review == next(root.glob("understand/*/review.yaml"))
    assert _tags(llm) == ["theorist"]
    assert load_state(RunStore(root))["status"] == "awaiting_review"
    assert RunStore(root).committed("frame_reviewed") is None


def test_bare_resume_confirms_proposals_without_a_theorist_call(tmp_path: Path) -> None:
    _, root, _ = _start(tmp_path)
    llm = _llm()
    _reach_data_stage(root, llm)
    assert "theorist" not in _tags(llm)
    assert _provenance(root)["researcher_steered"] is True
    assert len(list(root.glob("understand/attempt-*"))) == 2


def test_reject_triggers_one_revision_session(tmp_path: Path) -> None:
    _, root, _ = _start(tmp_path)
    review = _write_signals(root, {"questions.hours_score": {"signal": "reject"}})
    llm = _llm(revision=True)
    _reach_data_stage(root, llm, review)
    assert _tags(llm).count("theorist") == 1
    assert "questions.hours_score: reject" in llm.calls[0].prompt
    reviewed = RunStore(root).committed("frame_reviewed")
    assert reviewed is not None
    assert [q["id"] for q in json.loads(reviewed.read_text("utf-8"))["questions"]] == [
        "hours_vs_marks"
    ]
    assert _provenance(root)["supplied_by"] == "researcher"


def test_auto_commits_the_frame_unchanged_without_stopping(tmp_path: Path) -> None:
    outcome, root, llm = _start(tmp_path, auto=True)
    assert outcome is None and _tags(llm)[-1] == "analyst:data"  # ran past the frame
    store = RunStore(root)
    assert store.committed("frame_reviewed") == store.committed("frame")
    assert _provenance(root) == {}


def test_invalid_review_keeps_awaiting_review_and_calls_no_model(tmp_path: Path) -> None:
    _, root, _ = _start(tmp_path)
    bad = root / "bad.yaml"
    bad.write_text("items: {questions.ghost: {signal: approve}}", encoding="utf-8")
    llm = FakeLLM(lambda req: pytest.fail("no model call expected"))
    with pytest.raises(ValueError, match="review"):
        resume(root, llm=llm, review=bad)
    assert load_state(RunStore(root))["status"] == "awaiting_review"
    assert RunStore(root).committed("frame_reviewed") is None


def test_crash_after_review_commit_repeats_neither_review_nor_model_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, root, _ = _start(tmp_path)
    review = _write_signals(root, {"questions.hours_score": {"signal": "reject"}})

    def crash(self: RunStore, state: Any) -> Path:
        raise KeyboardInterrupt("crashed before the checkpoint")

    with monkeypatch.context() as patched:
        patched.setattr(RunStore, "checkpoint", crash)
        with pytest.raises(KeyboardInterrupt):
            resume(root, llm=_llm(revision=True), review=review)
    assert load_state(RunStore(root))["status"] == "awaiting_review"
    reviewed = RunStore(root).committed("frame_reviewed")
    assert reviewed is not None
    llm = _llm()
    _reach_data_stage(root, llm)
    assert _tags(llm) == ["analyst:data"]  # the review and the revision are not repeated
    assert RunStore(root).committed("frame_reviewed") == reviewed
    assert len(list(root.glob("understand/attempt-*"))) == 2


def test_review_on_a_completed_run_fails_clearly(tmp_path: Path) -> None:
    _, root, _ = _start(tmp_path)
    RunStore(root).checkpoint({"status": "completed", "message": "", "missing": []})
    with pytest.raises(ValueError, match="not awaiting review"):
        resume(root, llm=FakeLLM(lambda req: pytest.fail("no model call")), review=root / "x.yaml")
