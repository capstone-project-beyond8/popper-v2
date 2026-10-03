import json
from pathlib import Path

import pytest

from popper.config import load_config
from popper.discover.feedback import challenge_candidates, interpret_result
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.records import resolve_artifact
from popper.harness.recovery import read_events
from popper.harness.session import Harness
from popper.harness.store import RunStore
from popper.science.contracts import AttemptResult, Candidate, ResearchMove
from popper.science.contracts import ExperimentSpec as ScientificTest
from popper.science.state import commit_snapshot, rebuild_state
from popper.science.store import ScienceStore
from popper.science.transitions import schedule_attempt
from tests.unit.test_test_identity import spec_payload

pytestmark = pytest.mark.integration


def candidate_state(tmp_path: Path) -> Harness:
    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    source = h.run.write_json("exploration.json", {"question": "What explains the association?"})
    h.run.commit_artifact("exploration", source)
    ref = h.run.artifact_ref("exploration")
    spec = spec_payload()
    candidates = [Candidate(
        id=f"h{i}", statement=f"Explanation {i}", rationale="Observed association",
        primary_estimand=spec["primary_estimand"], expected_direction="positive",
        refuting_result="An opposing interval", planned_test="Contrast",
        methods=spec["methods"], origins=[ref], exposure=[ref],
    ).model_dump(mode="json") for i in (1, 2)]
    ScienceStore(h.run).commit("candidates", {"candidates": candidates}, key="initial")
    return h


@pytest.mark.parametrize("invalid", ["omitted_candidate", "outside_frontier"])
def test_challenge_corrects_coverage_and_source_before_commit(tmp_path: Path, invalid: str) -> None:
    h = candidate_state(tmp_path)
    candidate_ref = h.run.artifact_ref("science:candidates:initial")
    h.run.commit_artifact("unrelated", h.run.write_json("unrelated.json", {}))
    unrelated = h.run.artifact_ref("unrelated")
    submissions = 0

    def respond(req: LLMRequest) -> tuple[ToolCall, ...]:
        nonlocal submissions
        assert req.tag == "candidate_challenge" and len(req.messages) == (1 if submissions == 0 else 3)
        submissions += 1
        assessments = [{
            "hypothesis_id": f"h{i}", "assessment": "Association cannot identify the mechanism.",
            "concerns": ["Unmeasured prior attainment"], "rivals": ["Selection"],
            "discriminating_checks": ["Measure prior attainment before the outcome"],
            "sources": [candidate_ref.model_dump(mode="json")] + ([unrelated.model_dump(mode="json")] if submissions == 1 and invalid == "outside_frontier" else []),
        } for i in (1, 2)]
        if submissions == 1 and invalid == "omitted_candidate":
            assessments.pop()
        return (ToolCall("challenge", "submit_challenge", {"assessments": assessments}),)

    h.llm = FakeLLM(respond)
    result = challenge_candidates(h, candidate_ref)
    assert result is not None
    committed = json.loads(resolve_artifact(h.run, result).read_text("utf-8"))
    assert {a["hypothesis_id"] for a in committed["assessments"]} == {"h1", "h2"}
    assert all(a["sources"] == [candidate_ref.model_dump(mode="json")] for a in committed["assessments"])
    assert committed["author"] == "judge"
    assert len(rebuild_state(ScienceStore(h.run)).challenges) == 1
    error = next(e for e in read_events(tmp_path) if e["event"] == "tool_call" and e.get("status") == "error")
    assert ("each candidate" if invalid == "omitted_candidate" else "outside the input frontier") in error["result"]
    h.llm = FakeLLM(lambda _: pytest.fail("committed challenge must not replay"))
    assert challenge_candidates(h, candidate_ref) == result


def test_feedback_correction_exhaustion_is_a_sourced_deferral(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    h = candidate_state(tmp_path)
    h.llm = FakeLLM(lambda _: (ToolCall("bad", "submit_challenge", {"assessments": []}),))
    original_commit = RunStore.commit_artifact
    interrupted = False

    def commit(store: RunStore, name: str, path: Path) -> None:
        nonlocal interrupted
        original_commit(store, name, path)
        if name.startswith("science:disposition") and not interrupted:
            interrupted = True
            raise KeyboardInterrupt()

    monkeypatch.setattr(RunStore, "commit_artifact", commit)
    with pytest.raises(KeyboardInterrupt):
        challenge_candidates(h, h.run.artifact_ref("science:candidates:initial"))
    assert challenge_candidates(h, h.run.artifact_ref("science:candidates:initial")) is None
    state = rebuild_state(ScienceStore(h.run))
    assert not state.challenges and not state.attempts
    assert len(state.dispositions) == 1
    assert state.dispositions[-1].record.kind == "deferred"
    assert state.dispositions[-1].record.sources
    assert len([e for e in read_events(tmp_path) if e["event"] == "llm_call"]) == 2


def test_interpretation_requires_result_and_preserves_execution_outcome(tmp_path: Path) -> None:
    h = candidate_state(tmp_path)
    candidate_ref = h.run.artifact_ref("science:candidates:initial")
    spec = spec_payload()
    spec.update({"hypothesis_id": "h1", "preparation": candidate_ref.model_dump(mode="json")})
    test_ref = ScienceStore(h.run).commit("test", ScientificTest.model_validate(spec), key="t1")
    attempt_ref = schedule_attempt(ScienceStore(h.run), ResearchMove(
        id="m1", snapshot=commit_snapshot(ScienceStore(h.run), rebuild_state(ScienceStore(h.run))), action="test", objective="Test explanation",
        trigger_refs=[candidate_ref], hypothesis_id="h1", test=test_ref,
        discriminating_outcomes=["Positive", "Negative", "Inconclusive"], cost_usd=0, stopping_condition="One test",
    ), None)
    result_ref = ScienceStore(h.run).commit("result", AttemptResult(
        attempt=attempt_ref, hypothesis_id="h1", test=test_ref,
        measurements=[], stages={}, coverage={"status": "partial"}, sensitivity={}, status="failed",
    ), key="attempt-000")
    submissions = 0

    def respond(req: LLMRequest) -> tuple[ToolCall, ...]:
        nonlocal submissions
        submissions += 1
        return (ToolCall("interpret", "submit_interpretation", {
            "summary": "Execution failed; there is no usable observation for this test.",
            "rivals": ["Selection"], "limitations": ["No accepted main measurement"],
            "questions": ["Can a faithful implementation measure the contrast?"],
            "sources": [(candidate_ref if submissions == 1 else result_ref).model_dump(mode="json")],
        }),)

    h.llm = FakeLLM(respond)
    interpretation = interpret_result(h, result_ref)
    assert interpretation is not None
    state = rebuild_state(ScienceStore(h.run))
    assert state.results[0].record.status == "failed" and not state.observations
    assert state.interpretations[0].record.result == result_ref
    assert state.questions[0].ref == interpretation
    assert state.questions[0].record.text == "Can a faithful implementation measure the contrast?"
    assert any(e["event"] == "tool_call" and e.get("status") == "error" for e in read_events(tmp_path))
    h.llm = FakeLLM(lambda _: pytest.fail("committed interpretation must not replay"))
    assert interpret_result(h, result_ref) == interpretation
