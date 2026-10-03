"""Current operational resource admission, independent of saved scientific snapshots."""

import json

from popper.harness.session import BudgetExceeded, Harness
from popper.scientific.runtime.compatibility import decode_policy
from popper.scientific.runtime.lifecycle.contracts import ResearchMove, RunResources
from popper.scientific.runtime.lifecycle.transitions import EligibilityError
from popper.scientific.runtime.projections.state import ResearchState
from popper.scientific.runtime.settings import Discovery, ScientificOptions


def eligible_candidates(state: ResearchState, limits: Discovery) -> list[str]:
    return [
        c.record.id
        for c in state.candidates
        if _candidate_limit_reason(state, c.record.id, limits.max_moves, limits.max_revisits) is None
    ]


def _candidate_limit_reason(state: ResearchState, hypothesis_id: str, max_moves: int, max_revisits: int) -> str | None:
    if state.counters.get("moves", 0) >= max_moves:
        return "scheduled move cap reached"
    if state.counters.get(hypothesis_id, 0) > max_revisits:
        return "hypothesis revisit cap reached"
    return None


def resource_view(h: Harness, options: ScientificOptions, state: ResearchState) -> RunResources:
    stage_aware = not h.run.path("run.json").exists() or decode_policy(json.loads(h.run.path("run.json").read_text("utf-8"))).stage_aware
    return RunResources(
        spent_usd=h.spent_usd,
        max_usd=h.config.budget.max_usd,
        max_moves=options.discovery.max_moves,
        max_revisits=options.discovery.max_revisits,
        max_reframes=options.understand.max_reframes,
        available_routes=frozenset(
            {"test", "refine", "technical_repair", "measurement_repair", "stop"}
            | ({"audit", "synthesize", "communicate"} if stage_aware else set())
        ),
        eligible_hypotheses=frozenset(eligible_candidates(state, options.discovery)),
    )


def admit_move(resources: RunResources, state: ResearchState, move: ResearchMove) -> None:
    if resources.spent_usd >= resources.max_usd:
        raise BudgetExceeded("discovery resource cap reached")
    if move.action == "stop":
        return
    if move.action in {"frame", "ground", "explore", "candidates", "challenge"}:
        return
    if move.action not in resources.available_routes:
        raise EligibilityError(f"{move.action} route is deferred")
    if move.action in {"audit", "synthesize", "communicate", "frame", "ground", "explore", "candidates", "challenge"}:
        return
    reason = _candidate_limit_reason(state, move.hypothesis_id or "", resources.max_moves, resources.max_revisits)
    if reason is not None:
        raise EligibilityError(reason)
