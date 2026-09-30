An exploratory analysis of the data has finished. Turn what it found into one testable hypothesis.

## Framing
{framing}

## Exploration results
{results}

## Analysis of the exploration
{analysis}

## Figures produced
{figures}

Weigh all observations: group differences (for example a category whose mean differs clearly),
non-linear shapes (diminishing returns, an optimum) and interactions. Pick the hypothesis best
supported by the exploration results. The planned experiments should test the functional form
(for example log or quadratic terms) and the relevant group effects.

Reply with one JSON object with exactly these keys:
- "statement": the hypothesis, testable with the data
- "rationale": which observations support it
- "variables": list of columns involved
- "planned_experiments": list of analyses that would test it
