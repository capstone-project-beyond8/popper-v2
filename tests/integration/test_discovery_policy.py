import json
from pathlib import Path
from typing import Any

import pytest

from popper.config import load_config
from popper.discover.policy import propose_moves, select_move
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.records import resolve_artifact
from popper.harness.session import Harness
from popper.harness.store import RunStore
from popper.science.contracts import Candidate
from popper.science.state import commit_snapshot, rebuild_state
from popper.science.store import ScienceStore
from popper.science.transitions import schedule_attempt, selected_move
from tests.unit.test_test_identity import spec_payload

pytestmark = pytest.mark.integration


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
    ScienceStore(h.run).commit("candidates", {"candidates": [c.model_dump(mode="json") for c in candidates]})
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
            declared = {**proposal, "inference": {"bootstrap": 100 if submissions > 1 else 1000, "interval_level": .95}}
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
                        "omitted": {"hypothesis-002": "reserve alternative"} if submissions > 1 else {},
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
    proposals = propose_moves(h, snapshot)
    selection = select_move(h, snapshot, proposals)
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
    ["science:challenge:", "science:selection:", "science:attempt:", "node_commit", "science:result:", "science:interpretation:", "science:disposition:", "deferred_disposition", "science:study"],
)
def test_scheduler_resumes_committed_boundary_without_duplicate_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    import pandas as pd

    from popper.coordinator.discovery import advance_discovery
    from popper.ground.steward import Foundation
    from popper.harness.recovery import Journal, read_events
    from popper.science.contracts import AttemptResult
    from popper.science.research import parse_research
    from popper.understand.frame import Frame, Framing
    from tests.integration.test_run import EXAMPLE, FRAMING, _respond

    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    h.run.write_json("run.json", {"format_version": 5, "config": h.config.model_dump(mode="json")})
    h.run.write_text("data/raw.csv", "x,y\n1,2\n2,3\n")
    h.run.path("preparation").mkdir()
    pd.DataFrame({"x": [1, 2], "y": [2, 3]}).to_parquet(h.run.path("preparation/processed.parquet"))
    h.run.path("data/processed.parquet").write_bytes(
        h.run.path("preparation/processed.parquet").read_bytes()
    )
    prep = h.run.write_json("preparation/changes.json", [])
    h.run.commit_artifact("prep", prep)
    for name in ("frame_reviewed", "foundation", "exploration", "inputs"):
        h.run.commit_artifact(name, h.run.write_json(f"{name}.json", {}))
    payload = spec_payload()
    preparation_source = h.run.write_json("prep-manifest.json", {})
    h.run.commit_artifact("preparation", preparation_source)
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
    ScienceStore(h.run).commit("candidates",
        {"candidates": [c.model_dump(mode="json") for c in candidates]},
        key="initial",
    )
    frame = Frame(
        parse_research((EXAMPLE / "research.md").read_text("utf-8")),
        Framing.model_validate(FRAMING),
    )
    foundation = Foundation(prep.parent, [], [], {}, "attempt-000")
    monkeypatch.setattr("popper.coordinator.discovery.load_frame", lambda _: frame)
    monkeypatch.setattr("popper.coordinator.discovery.load_foundation", lambda _: foundation)

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        state = rebuild_state(ScienceStore(h.run))
        if req.tag in {"candidate_challenge", "interpret_result"}:
            return _respond(req)
        if req.tag == "research_moves":
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
            proposal_path = h.run.committed(f"science:proposals:{h.run.artifact_ref('science:snapshot').record_id}")
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
        commit_boundary = "science:disposition:" if boundary == "deferred_disposition" else boundary
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
    # Already committed exploration is consumed, so only its opaque node identity is needed.
    from types import SimpleNamespace
    from typing import cast

    from popper.treesearch.engine import Node

    exploration = cast(Node, SimpleNamespace(id="explore-000"))
    with pytest.raises(KeyboardInterrupt):
        advance_discovery(
            h,
            frame=h.run.path("frame_reviewed.json"),
            foundation=h.run.path("foundation.json"),
            exploration=exploration,
        )
    output = advance_discovery(
        h,
        frame=h.run.path("frame_reviewed.json"),
        foundation=h.run.path("foundation.json"),
        exploration=exploration,
    )
    assert output.is_file()
    state = rebuild_state(ScienceStore(h.run))
    assert len(state.attempts) == 1 and len(state.results) == 1
    assert state.counters["moves"] == 1 and len(state.observations) == 2
    assert len(state.challenges) == 1 and len(state.interpretations) == 1
    events = read_events(h.run.root)
    assert (
        len([e for e in events if e["event"] == "exec_start" and e["purpose"] == "submitted"]) == 2
    )
    assert (
        len(
            [
                e
                for e in events
                if e["event"] == "artifact_commit"
                and str(e.get("name", "")).startswith("science:selection:")
            ]
        )
        == 2
    )
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
            advance_discovery(
                h,
                frame=h.run.path("frame_reviewed.json"),
                foundation=h.run.path("foundation.json"),
                exploration=exploration,
            )
