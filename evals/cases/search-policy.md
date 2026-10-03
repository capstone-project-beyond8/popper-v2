# Implementation search policy comparison

Offline protocol; it runs no code. It compares the `tree` and `linear` values of `search.implementation_policy` on the same work.

## Setup

- Use the identical authored cases from the portfolio in [README.md](README.md), the identical ExperimentSpec for each case, and identical attempt and money caps (`search` step limits and `budget.max_usd`) for both policies.
- Change only `search.implementation_policy`. The `stage_start` journal event records the policy and seed for each stage; check it before comparing.
- Run each case under each policy from a fresh run directory.

## Record per case and policy

- Completion: whether the stage produced an accepted execution, and how many attempts it used.
- Fidelity: the attributed fidelity status of the accepted implementation and any recorded defects.
- Coverage: requested, completed and missing declared components and variants.
- Selection transparency: whether each node's reason shows why it was drafted, debugged or improved.
- Actual cost: recorded spend from `popper-metrics`, reported separately from the scientific trace.

## Rules

- Keep every failure and abandoned run in the denominator.
- Do not combine the measures into one score.
- Make no provider-backed trial without a declared budget and stopping condition.
- `tree` stays the default until recorded evidence supports a change.
