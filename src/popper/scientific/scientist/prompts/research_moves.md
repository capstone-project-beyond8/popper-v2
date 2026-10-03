Propose at most one executable move per eligible candidate plus an optional stop.
Current operational resources (not persisted scientific state): {resources}
Snapshot reference: {snapshot}
Sourced state: {state}
Read omitted cited contents with read_artifact; only reachable committed records are available.
Copy complete ArtifactRef objects for trigger_refs, test, preparation, exposure and diagnosis;
IDs or file paths alone are not references. Retrieve omitted candidate, test, result or diagnosis
contents before relying on them. Every eligible candidate needs a move or an omitted reason.
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
requested_coverage.alternatives is a list of operational procedure patch objects, such as
{{"inference": {{"interval_level": 0.95, "bootstrap": 1000}}}}, or [] for no variants.
Describe competing scientific explanations in discriminating_outcomes, not in alternatives.
Test positive, negative and null possibilities. Choose informative work, never retry for significance.
Use sourced candidate challenge and current result interpretations to explain what remains unresolved and why a next move distinguishes surviving rivals. Interpretation is attributed reasoning, not empirical support. Stale interpretations and invalidated history cannot supply current support; retained questions need their source limitations.
Repair needs a sourced technical/measurement defect; altered seeds/effort/slice is refinement.
Actions available for execution are test, technical_repair, measurement_repair and refine.
A repair reuses the exact existing test reference and cites an existing diagnosis of the
matching defect category; do not create a new test_proposal or change the intended procedure.
Refinement creates an operationally changed test_proposal with the candidate's exact primary
estimand, cites the result/question/diagnosis motivating it and lists changed_fields. A first
test can use test_proposal. Do not use both test and test_proposal to describe competing procedures.
Stop may omit test and hypothesis and outcomes; cite intent and terminal condition.
Pivot/reframe/acquisition are retained deferred routes. No analysis execution tools are available here.
They are recommendations, not completed work or a way to bypass the fixed target identity.
Current resources constrain feasibility, not scientific truth. A stop with unresolved questions
is legitimate when informative eligible work is unavailable. No Verify, literature retrieval,
new-data procurement or cross-run continuation tool is available in this session.
