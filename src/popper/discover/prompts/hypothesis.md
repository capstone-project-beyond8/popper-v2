An exploratory analysis of the data has finished. Turn what it found into one testable hypothesis.

## Framing
{framing}

{results}

{analysis}

## Figures produced
{figures}

Weigh all observations: group differences (for example a category whose mean differs clearly),
non-linear shapes (diminishing returns, an optimum) and interactions. Pick the hypothesis best
supported by the exploration results. The planned experiments should test the functional form
(for example log or quadratic terms) and the relevant group effects.

Choose one exposure/outcome contrast and state its population and outcome units. Pick a
contrast comparable across linear, nonlinear and adjusted specifications (for example a
predicted score difference between two stated study-hour values). Interactions and moderators
are secondary, never a second primary estimand. A null result is valid.

Reply with JSON only, exactly these keys:
- statement: testable claim
- rationale: which exploration observations motivated it
- primary_estimand: {{"outcome": "column", "exposure": "column", "contrast": "precise comparison", "population": "eligible population", "unit": "outcome unit"}}
- expected_direction: positive or negative
- refuting_result: the executed result that would refute this claim
- planned_test: model/test, covariates, contrast calculation and interval method

Do not supply IDs, source nodes, attribution or a confidence/stability label.
