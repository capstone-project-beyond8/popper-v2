# Scientific case reviews

Read a run with `uv run popper-metrics runs/<run_id>`. Keep the scientific trace beside recorded cost; the stage count and operational status alone do not show useful progress.

For each case, record:

1. What was believed, including unresolved rival explanations and assumptions.
2. What appeared in accepted named results, with exact artifact identities and missing coverage.
3. What changed in understanding, and what remains unresolved.
4. Why the selected move or stop followed from those sources; inspect displaced moves and rationale.
5. Whether the outcome is an execution failure, evidence limitation or justified scientific decision.

Retain failed and abandoned runs in the comparison denominator. Declare equal monetary and execution budgets for baseline and new strategy, and report recorded cost and useful progress separately. Do not combine them into a universal score.

Local checks use committed fixtures, FakeLLM and the real interpreter. They establish record integrity and recovery, not provider performance or scientific validity. Provider-backed comparisons require a separate budget and stopping condition before execution. Validation standing is currently `unavailable` throughout.

Start with [the unresolved-rival case](unresolved-rival.md).
