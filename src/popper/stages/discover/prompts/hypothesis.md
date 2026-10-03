An exploratory analysis of discovery data has finished. Turn its recorded observations into
one testable conjecture within the reviewed frame, for the single-hypothesis reporting path.

{framing}

{notes}

{results}

{analysis}

## Figures produced
{figures}

Weigh relevant observations, data concerns and uncertainty. Choose a scientifically useful
hypothesis with refuting outcomes, rather than optimizing effect size, significance or a
preferred direction. Exploration motivates it; it does not independently validate it.
Plan experiments that could distinguish it from plausible alternatives.

Choose one exposure/outcome contrast and state its population and outcome units. Pick a
contrast comparable across linear, nonlinear and adjusted specifications (for example a
predicted score difference between two stated study-hour values). Interactions and moderators
are secondary, never a second primary estimand. expected_direction states the conjecture's
positive or negative prediction; null, opposite-direction and inconclusive results remain valid.

State the eligible population, missingness policy and covariate encoding explicitly in the
planned test. Distinguish complete-case, single-imputation and multiple-imputation analyses;
retaining rows is not by itself stronger evidence. Keep methods feasible within script execution
limits, and specify which variable any transformation targets.

Reply with JSON only, exactly these keys:
- statement: testable claim
- rationale: which exploration observations motivated it
- primary_estimand: {{"outcome": "column", "exposure": "column, different from outcome", "contrast": "precise comparison", "comparison": "difference or ratio", "population": "eligible population", "unit": "outcome unit"}}
- expected_direction: positive or negative
- refuting_result: the executed result that would refute this claim
- planned_test: model/test, covariates, contrast calculation and interval method
- methods: list of the operations the planned test uses, chosen only from the allowed values in the schema

- assumptions: ids of the research-context assumptions this hypothesis relies on (empty list if none)

Do not supply IDs, source nodes, attribution or a confidence/stability label.
Use only the supplied records. No tools, literature retrieval or additional execution are
available in this call. Model recall is not verified prior work; do not invent citations.
