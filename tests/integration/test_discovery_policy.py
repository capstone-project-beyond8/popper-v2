import json
from pathlib import Path
from typing import Any

import pytest

from popper.config import load_config
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.session import Harness
from popper.harness.storage.records import resolve_artifact
from popper.harness.storage.store import RunStore
from popper.scientific.runtime.compatibility import decode_policy
from popper.scientific.runtime.lifecycle.contracts import Candidate
from popper.scientific.runtime.lifecycle.requests import CapabilityRequest
from popper.scientific.runtime.lifecycle.transitions import schedule_attempt, selected_move
from popper.scientific.runtime.projections.state import commit_snapshot, rebuild_state
from popper.scientific.runtime.settings import load_options
from popper.scientific.runtime.store import ScienceStore
from popper.scientific.scientist.moves import propose_moves, select_move
from popper.workflow.resources import resource_view
from tests.unit.test_test_identity import spec_payload

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("changed", ["frame_reviewed", "foundation"])
@pytest.mark.parametrize("phase", ["generation", "selection"])
def test_changed_upstream_rejects_discovery_before_model_or_mutation(
    tmp_path: Path, changed: str, phase: str
) -> None:
    from popper.harness.storage.records import IntegrityError
    from popper.scientific.runtime.lifecycle.contracts import MoveSelection, ResearchMove
    from popper.scientific.runtime.lifecycle.requests import CapabilityRequest
    from popper.scientific.scientist.episode import discovery_step
    from popper.workflow.discovery import dispatch_discovery

    h = Harness(load_config(env={}), FakeLLM(lambda _: pytest.fail("stale inputs must not reach model")), RunStore(tmp_path))
    h.run.write_json("run.json", {"format_version": 5, "config": h.config.model_dump(mode="json")})
    _committed_discovery_inputs(h)
    science = ScienceStore(h.run)
    policy = decode_policy(json.loads(h.run.path("run.json").read_text()))
    options = load_options(h.run)
    request = discovery_step(h, science, resource_view(h, options, rebuild_state(science)), policy, options)
    assert request is not None and request.kind == "candidates"
    if phase == "selection":
        payload = spec_payload()
        origin = h.run.artifact_ref("exploration")
        candidate = Candidate(
            id="h1", statement="x predicts y", rationale="observed association",
            primary_estimand=payload["primary_estimand"], methods=payload["methods"],
            expected_direction="positive", refuting_result="negative contrast", planned_test="contrast",
            origins=[origin], exposure=[origin],
        )
        candidates = science.commit("candidates", {"candidates": [candidate.model_dump(mode="json")]}, key="initial")
        snapshot = commit_snapshot(science, rebuild_state(science))
        move = ResearchMove(
            id="stop-1", snapshot=snapshot, action="stop", objective="bounded inquiry",
            trigger_refs=[candidates], cost_usd=0, stopping_condition="stop after assessment",
        )
        proposals = science.commit("proposals", {"snapshot": snapshot.model_dump(mode="json"), "moves": [move.model_dump(mode="json")]}, key=snapshot.record_id)
        science.commit("selection", MoveSelection(
            proposal_id="stop-1", snapshot=snapshot, proposals=proposals, author="scientist", rationale="bounded inquiry",
        ), key=proposals.record_id)
        request = CapabilityRequest("challenge", candidates, snapshot=snapshot)
    frontier = rebuild_state(science).frontier
    previous = h.run.artifact_ref(changed)
    replacement = Path(previous.path).parent / f"changed-{changed}.json"
    h.run.commit_artifact(changed, h.run.write_json(replacement.as_posix(), science.read(previous)))
    assert rebuild_state(science).frontier == frontier
    before = science.commits()
    resources = resource_view(h, options, rebuild_state(science))
    with pytest.raises(IntegrityError, match="intent.*current"):
        discovery_step(h, science, resources, policy, options)
    with pytest.raises(IntegrityError, match="intent.*current"):
        dispatch_discovery(h, request)
    assert science.commits() == before


def test_historical_candidate_dispatch_preserves_reentry(tmp_path: Path) -> None:
    from popper.harness.storage.store import file_hash
    from popper.scientific.scientist.episode import discovery_step
    from popper.workflow.discovery import dispatch_discovery

    payload = spec_payload()
    hypothesis = {
        "statement": "x predicts y", "rationale": "association", "primary_estimand": payload["primary_estimand"],
        "expected_direction": "positive", "refuting_result": "negative contrast", "planned_test": "linear regression",
        "methods": ["linear_regression"],
    }
    fake = FakeLLM(lambda _: json.dumps(hypothesis))
    h = Harness(load_config(env={}), fake, RunStore(tmp_path))
    h.run.write_json("run.json", {"format_version": 4, "config": h.config.model_dump(mode="json")})
    _committed_discovery_inputs(h)
    science = ScienceStore(h.run)
    policy = decode_policy(json.loads(h.run.path("run.json").read_text()))
    options = load_options(h.run)

    def step() -> CapabilityRequest | None:
        return discovery_step(h, science, resource_view(h, options, rebuild_state(science)), policy, options)

    request = step()
    assert request is not None and request.kind == "candidates" and request.strategy == "historical"
    assert request.subject == h.run.artifact_ref("exploration")
    assert dispatch_discovery(h, request) is None
    request = step()
    assert request is not None and request.kind == "experiment" and request.implementation_only
    assert request.subject == h.run.artifact_ref("hypothesis") and request.strategy == "historical"
    assert step() == request
    main = h.run.write_json("tree/main/accepted/meta.json", {"id": "accepted"})
    h.journal.write("node_commit", path=main.relative_to(tmp_path).as_posix(), sha256=file_hash(main), record_id="historical-main", stage_instance="main", node="accepted")
    h.journal.write("stage_end", stage_instance="main", best="accepted")
    h.run.commit_artifact("robustness_plan", h.run.write_json("schedule.json", {"format_version": 2, "main_node": "accepted", "schedule": {}}))
    request = step()
    assert request is not None and not request.implementation_only
    assert request.schedule == h.run.artifact_ref("robustness_plan") and request.strategy == "historical"
    assert [r.tag for r in fake.calls] == ["hypothesis"]
    assert not any(name.startswith(("science:intent", "science:candidates", "science:challenge")) for name, _ in science.commits())



def _committed_discovery_inputs(h: Harness) -> None:
    import pandas as pd

    from popper.harness.storage.store import file_hash
    from popper.scientific.runtime.data.research import parse_research
    from popper.scientific.runtime.projections.output import preparation_manifest
    from popper.scientific.runtime.projections.views import node_ref, record_exploration
    from popper.stages.understand.frame import Framing, save_frame
    from tests.integration.test_run import EXAMPLE, FRAMING

    h.run.write_text("data/raw.csv", "x,y\n1,2\n2,3\n")
    h.run.commit_artifact("inputs", h.run.write_json("inputs.json", {}))
    research = parse_research((EXAMPLE / "research.md").read_text("utf-8"))
    save_frame(h.run, h.run.path("reviewed"), research, Framing.model_validate(FRAMING), [], [], review={})
    h.run.path("preparation").mkdir()
    pd.DataFrame({"x": [1, 2], "y": [2, 3]}).to_parquet(h.run.path("preparation/processed.parquet"))
    h.run.path("data/processed.parquet").write_bytes(h.run.path("preparation/processed.parquet").read_bytes())
    h.run.commit_artifact("prep", h.run.write_json("preparation/changes.json", []))
    for name, value in (("operationalization", []), ("concerns", []), ("readiness", {})):
        h.run.write_json(f"{name}.json", value)
    h.run.commit_artifact("foundation", h.run.write_json("accepted-foundation.json", {"preparation": "preparation"}))
    science = ScienceStore(h.run)
    preparation_manifest(science, h.run.path("preparation"))
    result = h.run.write_json("tree/explore/accepted/execution/results.json", {"association": {"value": 0.4}})
    meta = h.run.write_json("tree/explore/accepted/meta.json", {
        "id": "accepted", "status": "ok", "analysis": "An association with plausible rivals", "figures": [],
        "outputs": {result.relative_to(h.run.root).as_posix(): file_hash(result)},
    })
    h.journal.write("node_commit", path=meta.relative_to(h.run.root).as_posix(), sha256=file_hash(meta), record_id="explore-accepted", node="accepted", stage_instance="explore")
    record_exploration(science, node_ref(science, meta))

@pytest.mark.parametrize("corrected", [False, True])
def test_sourced_tool_proposals_and_idempotent_schedule(tmp_path: Path, corrected: bool) -> None:
    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    source = h.run.write_json("explore.json", {"question": "What explains variance?"})
    h.run.commit_artifact("exploration", source)
    ref = h.run.artifact_ref("exploration")
    payload = spec_payload()
    candidate = Candidate(
        id="hypothesis-001",
        statement="x predicts y",
        rationale="exploration",
        primary_estimand=payload["primary_estimand"],
        expected_direction="positive",
        refuting_result="negative interval",
        planned_test="trimmed contrast",
        methods=payload["methods"],
        origins=[ref],
        exposure=[ref],
    )
    candidates = [candidate]
    if corrected:
        candidates.append(candidate.model_copy(update={"id": "hypothesis-002"}))
    ScienceStore(h.run).commit(
        "candidates", {"candidates": [c.model_dump(mode="json") for c in candidates]}
    )
    snapshot = commit_snapshot(ScienceStore(h.run), rebuild_state(ScienceStore(h.run)))
    prep = h.run.write_json("prep.json", {})
    h.run.commit_artifact("prep", prep)
    preparation_manifest = h.run.write_json("prep-manifest.json", {})
    h.run.commit_artifact("preparation", preparation_manifest)
    payload["preparation"] = h.run.artifact_ref("preparation").model_dump(mode="json")
    proposal = {k: v for k, v in payload.items() if k not in {"id", "hypothesis_id"}}

    submissions = 0

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        nonlocal submissions
        if req.tag == "research_moves":
            if len(req.messages) == 1:
                return (ToolCall("read", "read_artifact", {"path": ref.path}),)
            submissions += 1
            declared = {
                **proposal,
                "inference": {
                    "bootstrap": 100 if submissions > 1 else 1000,
                    "interval_level": 0.95,
                },
            }
            return (
                ToolCall(
                    "submit",
                    "submit_moves",
                    {
                        "moves": [
                            {
                                "action": "test",
                                "objective": "resolve exploration question",
                                "hypothesis_id": candidate.id,
                                "trigger_refs": [ref.model_dump(mode="json")],
                                "test_proposal": declared,
                                "discriminating_outcomes": ["positive", "negative"],
                                "cost_usd": 0.1,
                                "stopping_condition": "one accepted analysis",
                            }
                        ],
                        "omitted": {"hypothesis-002": "reserve alternative"}
                        if submissions > 1
                        else {},
                    },
                ),
            )
        data = json.loads(
            resolve_artifact(
                h.run, h.run.artifact_ref(f"science:proposals:{snapshot.record_id}")
            ).read_text()
        )
        return json.dumps(
            {"proposal_id": data["moves"][0]["id"], "rationale": "resolve sourced uncertainty"}
        )

    h.llm = FakeLLM(respond)
    proposals = propose_moves(
        h,
        ScienceStore(h.run),
        snapshot,
        resource_view(h, load_options(h.run), rebuild_state(ScienceStore(h.run))),
    )
    selection = select_move(h, ScienceStore(h.run), snapshot, proposals)
    move = selected_move(ScienceStore(h.run), selection)
    first = schedule_attempt(ScienceStore(h.run), move, None)
    assert schedule_attempt(ScienceStore(h.run), move, None) == first
    assert rebuild_state(ScienceStore(h.run)).counters == {"moves": 1, "hypothesis-001": 1}
    assert move.test is not None
    assert resolve_artifact(h.run, move.test).is_file()
    executable = json.loads(resolve_artifact(h.run, move.test).read_text())
    assert executable["inference"]["bootstrap"] == (100 if corrected else 1000)
    assert len(json.loads(resolve_artifact(h.run, proposals).read_text())["moves"]) == 1


@pytest.mark.slow
@pytest.mark.parametrize(
    "boundary",
    [
        "science:candidates:",
        "challenge_snapshot",
        "challenge_deferral",
        "science:challenge:",
        "science:selection:",
        "science:attempt:",
        "node_commit",
        "science:result:",
        "science:interpretation:",
        "science:disposition:",
        "deferred_disposition",
        "science:study",
        "science:proposals:",
        "correction_disposition",
        "admission_refusal",
        "request_subject",
        "decision_refusal",
    ],
)
def test_scheduler_resumes_committed_boundary_without_duplicate_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    from popper.scientific.scientist.episode import discovery_step
    from popper.workflow.discovery import dispatch_discovery

    def advance_discovery() -> Path:
        science = ScienceStore(h.run)
        while True:
            options = load_options(h.run)
            policy = decode_policy(json.loads(h.run.path("run.json").read_text("utf-8")))
            request = discovery_step(
                h, science, resource_view(h, options, rebuild_state(science)), policy, options
            )
            if request is None:
                continue
            if request.kind == "publish":
                assert request.subject is not None
                return resolve_artifact(h.run, request.subject)
            if boundary == "request_subject" and request.selection:
                from dataclasses import replace

                from popper.harness.storage.records import IntegrityError

                assert request.subject is not None
                invalid = request.subject.model_copy(update={"path": "uncommitted.json"})
                before = len(rebuild_state(science).attempts)
                with pytest.raises(IntegrityError):
                    dispatch_discovery(h, replace(request, subject=invalid))
                assert len(rebuild_state(science).attempts) == before
            feedback = dispatch_discovery(h, request)
            if feedback:
                assert feedback.subject is not None
                return resolve_artifact(h.run, feedback.subject)

    from popper.harness.storage.recovery import Journal, read_events
    from popper.scientific.runtime.lifecycle.contracts import AttemptResult
    from tests.integration.test_run import _respond

    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    if boundary in {"admission_refusal", "decision_refusal"}:
        h.config.budget.max_usd = 100
    saved_config = h.config.model_dump(mode="json")
    if boundary == "admission_refusal":
        saved_config["discovery"]["max_revisits"] = 0
    h.run.write_json("run.json", {"format_version": 5, "config": saved_config})
    _committed_discovery_inputs(h)
    payload = spec_payload()
    payload["preparation"] = h.run.artifact_ref("preparation").model_dump(mode="json")
    origin = h.run.artifact_ref("exploration")
    candidates = [
        Candidate(
            id=f"hypothesis-{i:03d}",
            statement="x predicts y",
            rationale="sourced question",
            primary_estimand=payload["primary_estimand"],
            expected_direction="positive",
            refuting_result="negative",
            planned_test="contrast",
            methods=payload["methods"],
            origins=[origin],
            exposure=[origin],
        )
        for i in (1, 2, 3)
    ]
    if boundary != "science:candidates:":
        ScienceStore(h.run).commit(
            "candidates", {"candidates": [c.model_dump(mode="json") for c in candidates]}, key="initial",
        )

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        state = rebuild_state(ScienceStore(h.run))
        if req.tag == "candidates":
            return json.dumps({"candidates": [
                {k: v for k, v in c.model_dump(mode="json").items()
                 if k not in {"id", "origins", "exposure", "warnings"}}
                for c in candidates
            ]})
        if req.tag == "candidate_challenge" and boundary == "challenge_deferral":
            return (ToolCall("bad", "submit_challenge", {"assessments": []}),)
        if req.tag in {"candidate_challenge", "interpret_result"}:
            return _respond(req)
        if req.tag == "research_moves":
            if boundary == "correction_disposition":
                return (ToolCall("invalid", "submit_moves", {"moves": [{"action": "test"}]}),)
            move: dict[str, Any]
            if state.results:
                move = {
                    "action": "pivot" if boundary == "deferred_disposition" else "stop",
                    "objective": "stop after informative observation",
                    "trigger_refs": [state.results[-1].ref.model_dump(mode="json")],
                    "cost_usd": 0,
                    "stopping_condition": "question answered for this test",
                }
            else:
                move = {
                    "action": "test",
                    "objective": "compare",
                    "hypothesis_id": "hypothesis-001",
                    "trigger_refs": [origin.model_dump(mode="json")],
                    "cost_usd": 0,
                    "stopping_condition": "one test",
                    "discriminating_outcomes": ["positive", "negative"],
                    "test_proposal": {
                        k: v for k, v in payload.items() if k not in {"id", "hypothesis_id"}
                    },
                }
            if state.results and boundary == "admission_refusal":
                move = {
                    "action": "test",
                    "objective": "revisit",
                    "hypothesis_id": "hypothesis-001",
                    "test": state.attempts[-1].record.test.model_dump(mode="json"),
                    "trigger_refs": [state.results[-1].ref.model_dump(mode="json")],
                    "cost_usd": 0,
                    "stopping_condition": "another observation",
                    "discriminating_outcomes": ["positive", "negative"],
                }
            return (
                ToolCall(
                    "submit",
                    "submit_moves",
                    {
                        "moves": [move],
                        "omitted": {
                            "hypothesis-002": "reserve alternative",
                            "hypothesis-003": "reserve alternative",
                            **({"hypothesis-001": "answered"} if state.results else {}),
                        },
                    },
                ),
            )
        if req.tag == "select_move":
            if boundary == "decision_refusal" and state.results:
                return json.dumps({"proposal_id": "unknown", "rationale": "unavailable"})
            proposal_path = h.run.committed(
                f"science:proposals:{h.run.artifact_ref('science:snapshot').record_id}"
            )
            assert proposal_path is not None
            proposals = json.loads(proposal_path.read_text())
            return json.dumps(
                {"proposal_id": proposals["moves"][0]["id"], "rationale": "sourced information"}
            )
        if req.tag.startswith("judge:"):
            return json.dumps(
                {
                    "node_buggy": False,
                    "goal_met": True,
                    "node_score": 7,
                    "analysis": "valid",
                    "fidelity_status": "consistent",
                    "fidelity_reason": "requirements match code",
                    "fidelity_requirements": ["contrast"],
                    "fidelity_evidence": ["code and output"],
                }
            )
        return (
            ToolCall(
                "submit",
                "submit",
                {
                    "code": "import json\njson.dump({'primary_estimate':{'value':1.,'ci':[.5,1.5],'n':2}},open('results.json','w'))\n"
                    + f"json.dump({payload['primary_estimand']!r},open('estimand.json','w'))\n"
                    + "json.dump({'seeds':[7],'interval_level':.95,'effect_scale':'points'},open('coverage.json','w'))"
                },
            ),
        )

    h.llm = FakeLLM(respond)
    interrupted = False
    original_commit = RunStore.commit_artifact
    original_write = Journal.write

    def commit(store: RunStore, name: str, path: Path) -> None:
        nonlocal interrupted
        original_commit(store, name, path)
        commit_boundary = (
            "science:disposition:"
            if boundary
            in {
                "deferred_disposition",
                "correction_disposition",
                "admission_refusal",
                "decision_refusal",
            }
            else boundary
        )
        if boundary == "challenge_snapshot":
            commit_boundary = "science:snapshot"
        if boundary == "challenge_deferral":
            commit_boundary = "science:disposition:candidate_challenge:"
        if boundary == "request_subject":
            commit_boundary = "science:selection:"
        if boundary == "decision_refusal":
            commit_boundary = "science:disposition"
        if name.startswith(commit_boundary) and not interrupted:
            interrupted = True
            raise KeyboardInterrupt()

    def write(journal: Journal, event: str, **fields: object) -> None:
        nonlocal interrupted
        original_write(journal, event, **fields)
        if boundary == event and not interrupted:
            interrupted = True
            raise KeyboardInterrupt()

    monkeypatch.setattr(RunStore, "commit_artifact", commit)
    monkeypatch.setattr(Journal, "write", write)
    with pytest.raises(KeyboardInterrupt):
        advance_discovery()
    selections_before_resume = len([r for r in h.llm.calls if r.tag == "select_move"])
    snapshots_before = sum(name == "science:snapshot" for name, _ in ScienceStore(h.run).commits())
    output = advance_discovery()
    assert output.is_file()
    assert sum(name == "science:candidates:initial" for name, _ in ScienceStore(h.run).commits()) == 1
    assert sum(r.tag == "candidates" for r in h.llm.calls) == (1 if boundary == "science:candidates:" else 0)
    if boundary == "challenge_deferral":
        assert sum(name == "science:snapshot" for name, _ in ScienceStore(h.run).commits()) == snapshots_before
        assert sum(r.tag == "candidate_challenge" for r in h.llm.calls) == 2
        assert not rebuild_state(ScienceStore(h.run)).attempts
        return
    assert sum(r.tag == "candidate_challenge" for r in h.llm.calls) == 1
    if boundary == "decision_refusal":
        assert len([r for r in h.llm.calls if r.tag == "select_move"]) == selections_before_resume
    if boundary == "correction_disposition":
        assert len([r for r in h.llm.calls if r.tag == "research_moves"]) == 2
        assert not rebuild_state(ScienceStore(h.run)).attempts
        assert not any(r.tag == "select_move" for r in h.llm.calls)
        return
    state = rebuild_state(ScienceStore(h.run))
    assert len(state.attempts) == 1 and len(state.results) == 1
    assert state.counters["moves"] == 1 and len(state.observations) == 2
    assert len(state.challenges) == 1 and len(state.interpretations) == 1
    assert state.challenges[0].record.author == "judge"
    assert state.challenges[0].record.candidates == h.run.artifact_ref("science:candidates:initial")
    assert state.interpretations[0].record.author == "theorist"
    events = read_events(h.run.root)
    assert (
        len([e for e in events if e["event"] == "exec_start" and e["purpose"] == "submitted"]) == 2
    )
    assert len(
        [
            e
            for e in events
            if e["event"] == "artifact_commit"
            and str(e.get("name", "")).startswith("science:selection:")
        ]
    ) == (1 if boundary == "decision_refusal" else 2)
    assert (
        AttemptResult.model_validate_json(
            resolve_artifact(h.run, state.results[0].ref).read_text()
        ).status
        == "complete"
    )
    if boundary == "science:study":
        output.chmod(0o666)
        output.write_text(output.read_text("utf-8") + " ", encoding="utf-8")
        with pytest.raises(ValueError, match="committed science:study artifact was changed"):
            advance_discovery()
