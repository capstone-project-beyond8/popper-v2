import json
from pathlib import Path
from typing import Any

import pytest

from popper.config import load_config
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.session import Harness
from popper.harness.storage.records import resolve_artifact
from popper.harness.storage.store import RunStore
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
    from popper.scientific.scientist.episode import discovery_step
    from popper.workflow.discovery import dispatch_discovery

    h = Harness(load_config(env={}), FakeLLM(lambda _: pytest.fail("stale inputs must not reach model")), RunStore(tmp_path))
    h.run.write_json("run.json", {"format_version": 7, "config": h.config.model_dump(mode="json")})
    _committed_discovery_inputs(h)
    science = ScienceStore(h.run)
    options = load_options(h.run)
    request = discovery_step(h, science, resource_view(h, options, rebuild_state(science)))
    assert request.kind == "candidates"
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
    with pytest.raises(IntegrityError, match="intent.*current"):
        dispatch_discovery(h, request)
    assert science.commits() == before


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


def _candidate_set(h: Harness, reply: dict[str, Any], capacity: int = 3) -> Any:
    from popper.scientific.scientist.episode import discovery_step
    from popper.stages.discover.candidates import generate_candidates

    saved = h.config.model_dump(mode="json")
    saved["discovery"] = {"hypotheses": capacity}
    h.run.write_json("run.json", {"format_version": 7, "config": saved})
    _committed_discovery_inputs(h)
    science = ScienceStore(h.run)
    options = load_options(h.run)
    request = discovery_step(h, science, resource_view(h, options, rebuild_state(science)))
    assert request.kind == "candidates" and request.subject is not None
    h.llm = FakeLLM(lambda _: json.dumps(reply))
    return science, generate_candidates(h, science, request.subject)


def _reply(count: int, **extra: str) -> dict[str, Any]:
    payload = spec_payload()
    return {"candidates": [{
        "statement": f"Explanation {i}", "rationale": "sourced question",
        "primary_estimand": payload["primary_estimand"], "expected_direction": "positive",
        "refuting_result": "negative", "planned_test": "contrast", "methods": payload["methods"],
    } for i in range(count)], **extra}


def test_fewer_candidates_are_allowed_with_a_reason(tmp_path: Path) -> None:
    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    science, ref = _candidate_set(h, _reply(1, omission="Only one explanation is distinguishable"))
    record = science.read(ref)
    assert len(record["candidates"]) == 1
    assert record["omission"] == "Only one explanation is distinguishable"


@pytest.mark.parametrize("reply", [
    _reply(1),
    _reply(1, omission="  "),
    _reply(4, omission="Too many"),
])
def test_candidate_count_rules_refuse_unjustified_sets(tmp_path: Path, reply: dict[str, Any]) -> None:
    from pydantic import ValidationError

    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    with pytest.raises(ValidationError):
        _candidate_set(h, reply)
    assert h.run.committed("science:candidates:initial") is None


@pytest.mark.parametrize("capacity", [1, 5])
def test_configured_capacity_bounds_the_candidate_set(tmp_path: Path, capacity: int) -> None:
    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    science, ref = _candidate_set(h, _reply(capacity), capacity)
    record = science.read(ref)
    assert len(record["candidates"]) == capacity and "omission" not in record
