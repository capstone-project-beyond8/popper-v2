import json
from pathlib import Path
from typing import Any

import pytest

from popper.config import load_config
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.session import Harness
from popper.harness.storage.records import ArtifactRef, resolve_artifact
from popper.harness.storage.recovery import read_events
from popper.harness.storage.store import RunStore
from popper.scientific.runtime.lifecycle.contracts import AttemptResult, Candidate, ResearchMove
from popper.scientific.runtime.lifecycle.contracts import ExperimentSpec as ScientificTest
from popper.scientific.runtime.lifecycle.transitions import schedule_attempt
from popper.scientific.runtime.projections.state import commit_snapshot, rebuild_state
from popper.scientific.runtime.store import ScienceStore
from popper.scientific.scientist.feedback import interpret_result
from popper.stages.discover.challenge import challenge_candidates
from tests.unit.test_test_identity import spec_payload

pytestmark = pytest.mark.integration


def candidate_state(tmp_path: Path) -> Harness:
    from popper.harness.storage.recovery import Journal
    from popper.harness.storage.store import file_hash
    from popper.scientific.runtime.projections.views import node_ref, record_exploration

    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    result = h.run.write_json("tree/explore/explore-000/execution/results.json", {"rows": {"value": 3}})
    meta = h.run.write_json("tree/explore/explore-000/meta.json", {"id": "explore-000", "status": "ok", "outputs": {result.relative_to(h.run.root).as_posix(): file_hash(result)}})
    Journal(h.run.path("journal.jsonl")).write("node_commit", stage="explore", node="explore-000", path=meta.relative_to(h.run.root).as_posix(), sha256=file_hash(meta), record_id="node-explore-000")
    ref = record_exploration(ScienceStore(h.run), node_ref(ScienceStore(h.run), meta))
    spec = spec_payload()
    candidates = [Candidate(
        id=f"h{i}", statement=f"Explanation {i}", rationale="Observed association",
        primary_estimand=spec["primary_estimand"], expected_direction="positive",
        refuting_result="An opposing interval", planned_test="Contrast",
        methods=spec["methods"], origins=[ref], exposure=[ref],
    ).model_dump(mode="json") for i in (1, 2)]
    ScienceStore(h.run).commit("candidates", {"candidates": candidates}, key="initial")
    return h


@pytest.mark.parametrize("invalid", ["omitted_candidate", "outside_frontier", "missing_self_citation"])
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
        if submissions == 1 and invalid == "missing_self_citation":
            assessments[0]["sources"] = [h.run.artifact_ref("exploration").model_dump(mode="json")]
        return (ToolCall("challenge", "submit_challenge", {"assessments": assessments}),)

    h.llm = FakeLLM(respond)
    science = ScienceStore(h.run)
    snapshot = commit_snapshot(science, rebuild_state(science))
    result = challenge_candidates(h, science, candidate_ref, snapshot)
    assert result is not None
    committed = json.loads(resolve_artifact(h.run, result).read_text("utf-8"))
    assert {a["hypothesis_id"] for a in committed["assessments"]} == {"h1", "h2"}
    assert all(a["sources"] == [candidate_ref.model_dump(mode="json")] for a in committed["assessments"])
    assert committed["author"] == "judge"
    assert len(rebuild_state(ScienceStore(h.run)).challenges) == 1
    error = next(e for e in read_events(tmp_path) if e["event"] == "tool_call" and e.get("status") == "error")
    expected = {"omitted_candidate": "each candidate", "outside_frontier": "outside the input frontier", "missing_self_citation": "cite the assessed candidate"}
    assert expected[invalid] in error["result"]
    h.llm = FakeLLM(lambda _: pytest.fail("committed challenge must not replay"))
    assert challenge_candidates(h, science, candidate_ref, snapshot) == result


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
    science = ScienceStore(h.run)
    snapshot = commit_snapshot(science, rebuild_state(science))
    with pytest.raises(KeyboardInterrupt):
        challenge_candidates(h, science, h.run.artifact_ref("science:candidates:initial"), snapshot)
    assert challenge_candidates(h, science, h.run.artifact_ref("science:candidates:initial"), snapshot) is None
    state = rebuild_state(ScienceStore(h.run))
    assert not state.challenges and not state.attempts
    assert len(state.dispositions) == 1
    assert state.dispositions[-1].record.kind == "deferred"
    assert state.dispositions[-1].record.sources
    assert len([e for e in read_events(tmp_path) if e["event"] == "llm_call"]) == 2


@pytest.mark.parametrize("invalid", ["missing_subject", "stale_frontier"])
def test_challenge_rejects_incompatible_snapshot_before_model(tmp_path: Path, invalid: str) -> None:
    from popper.scientific.runtime.lifecycle.contracts import Disposition

    h = candidate_state(tmp_path)
    science = ScienceStore(h.run)
    subject = h.run.artifact_ref("science:candidates:initial")
    state = rebuild_state(science)
    if invalid == "missing_subject":
        state = state.model_copy(update={"candidates": []})
    snapshot = commit_snapshot(science, state)
    if invalid == "stale_frontier":
        science.commit("disposition", Disposition(kind="deferred", reason="new evidence", sources=[subject]))
    h.llm = FakeLLM(lambda _: pytest.fail("incompatible snapshot must not reach the model"))
    before = science.commits()
    with pytest.raises(ValueError, match="snapshot|frontier"):
        challenge_candidates(h, science, subject, snapshot)
    assert science.commits() == before


@pytest.mark.parametrize("exhausted", [False, True])
def test_interpretation_requires_result_and_preserves_execution_outcome(tmp_path: Path, exhausted: bool) -> None:
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
            "sources": [(candidate_ref if exhausted or submissions == 1 else result_ref).model_dump(mode="json")],
        }),)

    h.llm = FakeLLM(respond)
    interpretation = interpret_result(h, ScienceStore(h.run), result_ref)
    if exhausted:
        assert interpretation is None and submissions == 2
        science = ScienceStore(h.run)
        before = science.commits()
        h.llm = FakeLLM(lambda _: pytest.fail("committed deferral must not replay"))
        assert interpret_result(h, science, result_ref) is None
        assert science.commits() == before
        assert science.read(h.run.artifact_ref(f"science:disposition:interpret_result:{result_ref.record_id}"))["sources"][-1] == result_ref.model_dump(mode="json")
        return
    assert interpretation is not None
    state = rebuild_state(ScienceStore(h.run))
    assert state.results[0].record.status == "failed" and not state.observations
    assert state.interpretations[0].record.result == result_ref
    assert state.questions[0].ref == interpretation
    assert state.questions[0].record.text == "Can a faithful implementation measure the contrast?"
    assert any(e["event"] == "tool_call" and e.get("status") == "error" for e in read_events(tmp_path))
    h.llm = FakeLLM(lambda _: pytest.fail("committed interpretation must not replay"))
    assert interpret_result(h, ScienceStore(h.run), result_ref) == interpretation


@pytest.mark.parametrize("action", ["audit", "synthesize", "communicate", "stop"])
@pytest.mark.parametrize("exhausted", [False, True])
def test_selected_non_experimental_work_retains_sources_and_questions(tmp_path: Path, action: str, exhausted: bool) -> None:
    from popper.scientific.runtime.lifecycle.contracts import MoveProposal, Question
    from popper.scientific.runtime.projections.output import StudyOutput
    from popper.scientific.runtime.settings import load_options
    from popper.scientific.scientist.episode import request_move
    from popper.scientific.scientist.moves import propose_moves, select_move
    from popper.workflow.resources import resource_view
    from popper.workflow.run import dispatch_selected

    h = candidate_state(tmp_path)
    science = ScienceStore(h.run)
    source = h.run.artifact_ref("science:candidates:initial")
    science.commit("question", Question(hypothesis_id="h1", text="Which rival needs new data?", author="theorist", sources=[source]))
    snapshot = commit_snapshot(science, rebuild_state(science))
    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        if req.tag == "research_moves":
            return (ToolCall("move", "submit_moves", {"moves": [MoveProposal.model_validate({
                "action": action, "objective": "Preserve unresolved rivals", "trigger_refs": [source.model_dump(mode="json")],
                "cost_usd": 0, "stopping_condition": "Useful bounded episode",
            }).model_dump(mode="json")], "omitted": {"h1": "Need additional data", "h2": "Rival retained"}}),)
        if req.tag == "select_move":
            proposals = science.read(h.run.artifact_ref(f"science:proposals:{snapshot.record_id}"))
            return json.dumps({"proposal_id": proposals["moves"][0]["id"], "rationale": "Resolve the recorded question"})
        if req.tag == "synthesize_state":
            return (ToolCall("synthesis", "submit_synthesis", {"summary": "Existing evidence leaves selection unresolved", "rivals": ["Selection"], "limitations": ["Need new data"], "questions": ["Which rival needs new data?"], "sources": [source.model_dump(mode="json")]}),)
        pytest.fail(f"unexpected model call: {req.tag}")
    h.llm = FakeLLM(respond)
    proposals = propose_moves(h, science, snapshot, resource_view(h, load_options(h.run), rebuild_state(science)))
    selection = select_move(h, science, snapshot, proposals)
    request = request_move(science, selection)
    assert request.selection == selection
    if exhausted:
        h.spent_usd = h.config.budget.max_usd
    before_calls = len(h.llm.calls)
    result = dispatch_selected(h, request)
    state = rebuild_state(science)
    assert state.questions[0].record.text == "Which rival needs new data?"
    assert not state.questions[0].record.resolved
    if exhausted and action != "stop":
        assert not state.stage_admissions
        assert state.dispositions[-1].record.sources == [selection]
        assert len(h.llm.calls) == before_calls
        assert dispatch_selected(h, request) == result
        assert len(rebuild_state(science).dispositions) == 1
    elif action == "stop":
        assert result is not None and result.kind == "finish"
        assert not state.stage_admissions and h.run.committed("report") is None
        assert state.dispositions[-1].record.sources == [selection]
    else:
        assert len(state.stage_history) == 1 and not state.pending_admissions
        assert source in state.stage_admissions[0].record.inputs
        assert state.stage_history[0].record.status == "completed"
        if action == "audit":
            audit = science.read(state.stage_history[0].record.outputs[0])
            assert audit["validation_standing"] == "unavailable"
        if action == "synthesize":
            synthesis = science.read(state.stage_history[0].record.outputs[0])
            assert synthesis["sources"] == [source.model_dump(mode="json")]
    if result is not None and result.kind == "finish":
        assert result.subject is not None
        output = StudyOutput.model_validate(science.read(result.subject))
        assert output.validation_standing == "unavailable"


@pytest.mark.parametrize("action", ["audit", "synthesize", "communicate", "evolve", "direct"])
def test_saved_policy_corrects_unavailable_actions(tmp_path: Path, action: str) -> None:
    from popper.scientific.runtime.settings import load_options
    from popper.scientific.scientist.moves import propose_moves
    from popper.workflow.resources import resource_view

    h = candidate_state(tmp_path)
    h.run.write_json("run.json", {"format_version": 5, "config": h.config.model_dump(mode="json")})
    science = ScienceStore(h.run)
    source = h.run.artifact_ref("science:candidates:initial")
    snapshot = commit_snapshot(science, rebuild_state(science))
    submissions = 0

    def respond(_: LLMRequest) -> tuple[ToolCall, ...]:
        nonlocal submissions
        submissions += 1
        return (ToolCall("move", "submit_moves", {"moves": [{
            "action": action if submissions == 1 else "stop", "objective": "Retain the rival",
            "trigger_refs": [source.model_dump(mode="json")], "cost_usd": 0,
            "stopping_condition": "No justified empirical work",
        }], "omitted": {"h1": "Need data", "h2": "Need data"}}),)

    h.llm = FakeLLM(respond)
    resources = resource_view(h, load_options(h.run), rebuild_state(science))
    proposals = propose_moves(h, science, snapshot, resources)
    assert [move["action"] for move in science.read(proposals)["moves"]] == ["stop"]
    assert submissions == 2
    assert propose_moves(h, science, snapshot, resources) == proposals
    assert submissions == 2 and not rebuild_state(science).stage_admissions


@pytest.mark.parametrize("interrupted", [False, True])
@pytest.mark.parametrize("action", ["synthesize", "direct"])
def test_synthesis_exhaustion_terminalizes_sourced_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: bool, action: str,
) -> None:
    deferral, tool = {"synthesize": ("synthesize_state", "submit_synthesis"), "direct": ("update_direction", "submit_direction")}[action]
    from popper.scientific.runtime.lifecycle.contracts import Question
    from popper.scientific.runtime.settings import load_options
    from popper.scientific.scientist.episode import request_move
    from popper.scientific.scientist.moves import propose_moves, select_move
    from popper.workflow.resources import resource_view
    from popper.workflow.run import dispatch_selected

    h = candidate_state(tmp_path)
    h.run.write_json("run.json", {"format_version": 6 if action == "synthesize" else 7, "config": h.config.model_dump(mode="json")})
    science = ScienceStore(h.run)
    source = h.run.artifact_ref("science:candidates:initial")
    science.commit("question", Question(text="Can the rival be distinguished?", author="theorist", sources=[source]))
    snapshot = commit_snapshot(science, rebuild_state(science))

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        if req.tag == "research_moves":
            return (ToolCall("move", "submit_moves", {"moves": [{"action": action,
                "objective": "Retain the rival", "trigger_refs": [source.model_dump(mode="json")],
                "cost_usd": 0, "stopping_condition": "Evidence incomplete"}],
                "omitted": {"h1": "Need data", "h2": "Need data"}}),)
        if req.tag == "select_move":
            proposed = science.read(h.run.artifact_ref(f"science:proposals:{snapshot.record_id}"))
            return json.dumps({"proposal_id": proposed["moves"][0]["id"], "rationale": "Retain the rival"})
        return (ToolCall("bad", tool, {}),)

    h.llm = FakeLLM(respond)
    proposals = propose_moves(h, science, snapshot, resource_view(h, load_options(h.run), rebuild_state(science)))
    request = request_move(science, select_move(h, science, snapshot, proposals))
    if interrupted:
        original_commit = RunStore.commit_artifact
        def interrupt(store: RunStore, name: str, path: Path) -> None:
            original_commit(store, name, path)
            if name.startswith(f"science:disposition:{deferral}:"):
                raise KeyboardInterrupt()
        monkeypatch.setattr(RunStore, "commit_artifact", interrupt)
        with pytest.raises(KeyboardInterrupt):
            dispatch_selected(h, request)
        monkeypatch.setattr(RunStore, "commit_artifact", original_commit)
    outcome = dispatch_selected(h, request)
    assert outcome is not None and outcome.kind == "finish"
    state = rebuild_state(science)
    assert not state.pending_admissions and len(state.stage_history) == 1
    assert state.stage_history[0].record.status == "deferred"
    assert state.stage_history[0].record.outputs == []
    assert state.dispositions[-1].record.sources == [snapshot]
    assert state.questions[0].record.text == "Can the rival be distinguished?"
    assert not state.questions[0].record.resolved and not state.syntheses
    before_calls = len(h.llm.calls)
    assert dispatch_selected(h, request) == outcome
    assert len(h.llm.calls) == before_calls and len(rebuild_state(science).stage_history) == 1


def _idea_world(tmp_path: Path, version: int = 7, **discovery: int) -> tuple[Harness, ScienceStore, ArtifactRef]:
    h = candidate_state(tmp_path)
    config = h.config.model_dump(mode="json")
    config["discovery"].update(discovery)
    h.run.write_json("run.json", {"format_version": version, "config": config})
    return h, ScienceStore(h.run), h.run.artifact_ref("science:candidates:initial")


def _select_move(
    h: Harness, science: ScienceStore, source: ArtifactRef, action: str, *, directed: bool = True,
) -> tuple[ArtifactRef, ArtifactRef]:
    """Script the PI to propose and select one non-empirical move; returns (snapshot, selection)."""
    from popper.scientific.runtime.settings import load_options
    from popper.scientific.scientist.moves import propose_moves, select_move
    from popper.workflow.resources import resource_view

    state = rebuild_state(science)
    snapshot = commit_snapshot(science, state)
    move: dict[str, Any] = {
        "action": action, "objective": "Keep the inquiry coherent", "trigger_refs": [source.model_dump(mode="json")],
        "cost_usd": 0, "stopping_condition": "Bounded episode",
    }
    if directed and state.directions:
        move |= {"direction": state.directions[-1].ref.model_dump(mode="json"), "contribution": "Advances the stated question"}

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        if req.tag == "research_moves":
            return (ToolCall("move", "submit_moves", {"moves": [move], "omitted": {"h1": "Held", "h2": "Held"}}),)
        if req.tag == "select_move":
            proposed = science.read(h.run.artifact_ref(f"science:proposals:{snapshot.record_id}"))
            return json.dumps({"proposal_id": proposed["moves"][0]["id"], "rationale": "Most informative"})
        if req.tag == "update_direction":
            return (ToolCall("direction", "submit_direction", {
                "central_question": "Which explanation accounts for the association?",
                "explanations": ["Selection", "Confounding"], "uncertainties": ["Missing measurements"],
                "evidence_sequence": ["Contrast the exposure groups"], "sources": [source.model_dump(mode="json")],
            }),)
        pytest.fail(f"unexpected model call: {req.tag}")

    h.llm = FakeLLM(respond)
    proposals = propose_moves(h, science, snapshot, resource_view(h, load_options(h.run), rebuild_state(science)))
    return snapshot, select_move(h, science, snapshot, proposals)


def test_direct_move_commits_sourced_direction_and_supersedes(tmp_path: Path) -> None:
    from popper.scientific.runtime.projections.output import episode_summary
    from popper.scientific.scientist.episode import request_move
    from popper.workflow.run import dispatch_selected

    h, science, source = _idea_world(tmp_path)
    for _ in range(2):
        _, selection = _select_move(h, science, source, "direct")
        assert dispatch_selected(h, request_move(science, selection)) is None
        state = rebuild_state(science)
        work = state.stage_history[-1].record
        assert work.status == "completed" and work.outputs == [state.directions[-1].ref]
    first, second = rebuild_state(science).directions
    assert source in first.record.sources and first.record.supersedes is None
    assert second.record.supersedes == first.ref
    summary = episode_summary(science)
    assert [d["ref"] for d in summary["directions"]] == [first.ref.model_dump(mode="json"), second.ref.model_dump(mode="json")]


def test_moves_must_carry_the_latest_direction_once_one_exists(tmp_path: Path) -> None:
    from popper.scientific.runtime.settings import load_options
    from popper.scientific.scientist.episode import request_move
    from popper.scientific.scientist.moves import propose_moves
    from popper.workflow.resources import resource_view
    from popper.workflow.run import dispatch_selected

    h, science, source = _idea_world(tmp_path)
    _, selection = _select_move(h, science, source, "direct")
    dispatch_selected(h, request_move(science, selection))
    latest = rebuild_state(science).directions[-1].ref
    snapshot = commit_snapshot(science, rebuild_state(science))
    submissions = 0

    def respond(_: LLMRequest) -> tuple[ToolCall, ...]:
        nonlocal submissions
        submissions += 1
        move: dict[str, Any] = {
            "action": "synthesize", "objective": "Retain the rival", "trigger_refs": [source.model_dump(mode="json")],
            "cost_usd": 0, "stopping_condition": "Bounded episode",
        }
        if submissions == 2:
            move |= {"direction": latest.model_dump(mode="json"), "contribution": "Keeps the rivals visible"}
        return (ToolCall("move", "submit_moves", {"moves": [move], "omitted": {"h1": "Held", "h2": "Held"}}),)

    h.llm = FakeLLM(respond)
    resources = resource_view(h, load_options(h.run), rebuild_state(science))
    moves = science.read(propose_moves(h, science, snapshot, resources))["moves"]
    assert submissions == 2 and [m["direction"] for m in moves] == [latest.model_dump(mode="json")]


def test_evolve_beyond_idea_round_cap_is_deferred_at_admission(tmp_path: Path) -> None:
    from popper.scientific.runtime.settings import load_options
    from popper.scientific.scientist.episode import request_move
    from popper.workflow.resources import resource_view
    from popper.workflow.run import dispatch_selected

    h, science, source = _idea_world(tmp_path, max_idea_rounds=1)
    _, selection = _select_move(h, science, source, "evolve")
    assert dispatch_selected(h, request_move(science, selection)) is not None
    state = rebuild_state(science)
    assert state.stage_history[0].record.status == "deferred"
    assert state.stage_history[0].record.reason == "idea evolution is unavailable"
    resources = resource_view(h, load_options(h.run), state)
    assert (resources.idea_rounds, resources.max_idea_rounds) == (1, 1)

    _, second = _select_move(h, science, source, "evolve")
    before, spent = rebuild_state(science), h.spent_usd
    assert dispatch_selected(h, request_move(science, second)) is not None
    after = rebuild_state(science)
    assert len(after.stage_admissions) == 1 and len(after.stage_history) == 1
    assert after.dispositions[-1].record.sources == [second]
    assert after.dispositions[-1].record.reason == "idea round cap reached"
    assert after.counters == before.counters and h.spent_usd == spent


@pytest.mark.parametrize("version", [5, 6])
def test_idea_routes_are_unavailable_before_idea_evolution(tmp_path: Path, version: int) -> None:
    from popper.scientific.runtime.settings import load_options
    from popper.workflow.resources import resource_view

    h, science, _ = _idea_world(tmp_path, version)
    resources = resource_view(h, load_options(h.run), rebuild_state(science))
    assert not {"evolve", "direct"} & resources.available_routes and not resources.idea_evolution
