Propose at most one executable move per eligible candidate plus an optional stop.
Current operational resources (not persisted scientific state): {resources}
Snapshot reference: {snapshot}
Sourced state: {state}
Read omitted cited contents with read_artifact; only reachable committed records are available.
Use submit_moves with moves and an omitted mapping of candidate IDs to attributed reasons.
Each move needs objective, trigger_refs, action, hypothesis_id, test or test_proposal,
discriminating_outcomes, cost_usd, execution_effort, assumptions, exposure, stopping_condition.
Tests declare open MethodSpecs, selection, preparation source, inference including interval_level,
requested_coverage including seeds and explicit alternatives, outputs including estimand.json
and primary_estimate, and optional prospective support_rule. Code assigns IDs.
Copy the candidate's complete primary_estimand object exactly into test_proposal. Preserve every
string, including population and contrast; do not shorten, reword or summarize them. Scientific
target identity uses exact field equality. A changed target belongs to a deferred pivot.
support_rule.result_key must exactly match one measurement key in test_proposal.outputs, such
as primary_estimate. outputs declares estimand.json plus results.json measurement keys, not only
artifact filenames. Align the declared outputs and support rule before submitting.
Test positive, negative and null possibilities. Choose informative work, never retry for significance.
Use sourced candidate challenge and current result interpretations to explain what remains unresolved and why a next move distinguishes surviving rivals. Interpretation is attributed reasoning, not empirical support. Stale interpretations and invalidated history cannot supply current support; retained questions need their source limitations.
Repair needs a sourced technical/measurement defect; altered seeds/effort/slice is refinement.
Stop may omit test and hypothesis and outcomes; cite intent and terminal condition.
Pivot/reframe/acquisition are retained deferred routes. No analysis execution tools are available here.
