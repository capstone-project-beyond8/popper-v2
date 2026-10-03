"""Current operational resource admission, independent of saved scientific snapshots."""

from popper.harness.session import BudgetExceeded, Harness
from popper.science.contracts import ResearchMove, RunResources
from popper.science.settings import Discovery, ScientificOptions
from popper.science.state import ResearchState
from popper.science.transitions import EligibilityError


def eligible_candidates(state: ResearchState, limits: Discovery) -> list[str]:
    if state.counters.get("moves", 0) >= limits.max_moves:
        return []
    return [
        c.record.id
        for c in state.candidates
        if state.counters.get(c.record.id, 0) <= limits.max_revisits
    ]


def resource_view(h: Harness, options: ScientificOptions, state: ResearchState) -> RunResources:
    return RunResources(
        spent_usd=h.spent_usd,
        max_usd=h.config.budget.max_usd,
        max_moves=options.discovery.max_moves,
        max_revisits=options.discovery.max_revisits,
        max_reframes=options.understand.max_reframes,
        available_routes=frozenset(
            {"test", "refine", "technical_repair", "measurement_repair", "stop"}
        ),
        eligible_hypotheses=frozenset(eligible_candidates(state, options.discovery)),
    )


def admit_move(resources: RunResources, state: ResearchState, move: ResearchMove) -> None:
    if resources.spent_usd >= resources.max_usd:
        raise BudgetExceeded("discovery resource cap reached")
    if move.action == "stop":
        return
    if move.action not in resources.available_routes:
        raise EligibilityError(f"{move.action} route is deferred")
    if state.counters.get("moves", 0) >= resources.max_moves:
        raise EligibilityError("scheduled move cap reached")
    if state.counters.get(move.hypothesis_id or "", 0) > resources.max_revisits:
        raise EligibilityError("hypothesis revisit cap reached")
