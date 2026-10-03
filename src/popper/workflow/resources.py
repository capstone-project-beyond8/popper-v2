"""Current operational resource admission, independent of saved scientific snapshots."""

from popper.harness.session import BudgetExceeded, Harness
from popper.scientific.runtime.lifecycle.contracts import (
    NON_EMPIRICAL_ACTIONS,
    PREREQUISITE_ACTIONS,
    ResearchMove,
    RunResources,
)
from popper.scientific.runtime.lifecycle.transitions import EligibilityError
from popper.scientific.runtime.projections.state import ResearchState
from popper.scientific.runtime.settings import Discovery, ScientificOptions
from popper.scientific.runtime.store import ScienceStore


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
    science = ScienceStore(h.run)
    return RunResources(
        spent_usd=h.spent_usd,
        max_usd=h.config.budget.max_usd,
        max_moves=options.discovery.max_moves,
        max_revisits=options.discovery.max_revisits,
        max_reframes=options.understand.max_reframes,
        available_routes=frozenset(
            {
                "test", "refine", "technical_repair", "measurement_repair", "stop",
                "audit", "synthesize", "communicate", "evolve", "direct",
            }
        ),
        eligible_hypotheses=frozenset(eligible_candidates(state, options.discovery)),
        idea_rounds=sum(science.read(a.record.move)["action"] == "evolve" for a in state.stage_admissions),
        max_idea_rounds=options.discovery.max_idea_rounds,
    )


def admit_move(resources: RunResources, state: ResearchState, move: ResearchMove) -> None:
    if resources.spent_usd >= resources.max_usd:
        raise BudgetExceeded("discovery resource cap reached")
    if move.action == "stop":
        return
    if move.action in PREREQUISITE_ACTIONS:
        return
    if move.action not in resources.available_routes:
        raise EligibilityError(f"{move.action} route is deferred")
    if move.action == "evolve" and resources.idea_rounds >= resources.max_idea_rounds:
        raise EligibilityError("idea round cap reached")
    if move.action in NON_EMPIRICAL_ACTIONS:
        return
    reason = _candidate_limit_reason(state, move.hypothesis_id or "", resources.max_moves, resources.max_revisits)
    if reason is not None:
        raise EligibilityError(reason)
