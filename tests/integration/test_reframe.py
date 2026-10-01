import json
from pathlib import Path

import pytest

from popper.coordinator.run import RunOutcome, resume, run
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.store import RunStore
from tests.integration.test_run import DATA, EXAMPLE, _config, _respond

pytestmark = pytest.mark.integration

CONCERN = {
    "type": "unmeasured_concept",
    "kind": "frame",
    "description": "No column measures study effort quality.",
    "evidence": ["rows_removed"],
}


def _llm() -> FakeLLM:
    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        if req.tag == "steward":
            mapping = [
                {
                    "concept_id": "study_effort",
                    "columns": ["study_hours_week"],
                    "proxy_strength": "proxy",
                    "rationale": "Hours only.",
                }
            ]
            args = {"code": DATA, "operationalization": mapping, "concerns": [CONCERN]}
            return (ToolCall("ground-1", "submit_ground", args),)
        if req.tag.startswith("analyst:"):
            raise KeyboardInterrupt("reached discovery")
        return _respond(req)

    return FakeLLM(respond)


def _tags(llm: FakeLLM) -> list[str]:
    return [r.tag for r in llm.calls]


def _reframes(root: Path) -> list[dict[str, object]]:
    lines = (root / "journal.jsonl").read_text("utf-8").splitlines()
    return [e for e in map(json.loads, lines) if e["event"] == "reframe"]


def _run(tmp_path: Path, *, auto: bool, max_reframes: int, llm: FakeLLM) -> RunOutcome:
    config = _config()
    config.understand.max_reframes = max_reframes
    return run(
        EXAMPLE / "research.md",
        EXAMPLE / "data.csv",
        config=config,
        auto=auto,
        llm=llm,
        runs_dir=tmp_path,
    )


def test_auto_reframes_once_and_grounds_again_from_raw_rows(tmp_path: Path) -> None:
    llm = _llm()
    with pytest.raises(KeyboardInterrupt):
        _run(tmp_path, auto=True, max_reframes=1, llm=llm)
    root = next(tmp_path.iterdir())
    assert _tags(llm).count("theorist") == 2 and _tags(llm).count("steward") == 2
    revision = next(r for r in llm.calls if "Guidance for this revision" in r.prompt)
    assert "unmeasured_concept: No column measures study effort quality." in revision.prompt
    assert [e["concerns"] for e in _reframes(root)] == [["unmeasured_concept"]]
    assert len(list(root.glob("ground/attempt-*"))) == 2
    assert (root / "data" / "processed.parquet").exists()
    assert (root / "data" / "ida.json").exists()


def test_reframe_stops_for_review_and_resume_grounds_again(tmp_path: Path) -> None:
    first = _llm()
    out = _run(tmp_path, auto=False, max_reframes=1, llm=first)
    assert out.status == "awaiting_review"
    second = _llm()
    out = resume(out.run_dir, llm=second)
    assert out.status == "awaiting_review"
    assert _tags(second) == ["steward", "theorist"]
    root = out.run_dir
    assert len(_reframes(root)) == 1 and len(list(root.glob("ground/attempt-*"))) == 1
    third = _llm()
    with pytest.raises(KeyboardInterrupt):
        resume(root, llm=third)
    assert _tags(third).count("steward") == 1 and "theorist" not in _tags(third)
    assert len(_reframes(root)) == 1 and len(list(root.glob("ground/attempt-*"))) == 2
    assert RunStore(root).committed("frame_reviewed") is not None


def test_no_reframe_when_none_allowed(tmp_path: Path) -> None:
    llm = _llm()
    with pytest.raises(KeyboardInterrupt):
        _run(tmp_path, auto=True, max_reframes=0, llm=llm)
    assert _tags(llm).count("theorist") == 1 and not _reframes(next(tmp_path.iterdir()))
