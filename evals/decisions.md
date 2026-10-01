# Cost and context measurements

All demo measurements use Sonnet 4.6 for Theorist, Steward, Judge and Writer,
Haiku 4.5 for Analyst, a $5 cap and the default three rejected-submit limit.
The control is revision `8669273`; the changed configuration is revision `3ed069d`.
Runs are under `runs/cost-context/`; `popper-metrics <run>` reproduces journal metrics.

| Configuration | Dataset | Run | Status | USD | Cache-read ratio | Avoidable errors |
|---|---|---|---|---:|---:|---:|
| Control | student_performance | 20261001-191824-458c | failed at Understand after Ground | 1.14712005 | 53.15% | 18 |
| Control | student_performance | 20261001-192738-a42b | failed at Understand | 0.23433225 | 46.53% | 8 |
| Control | student_performance_null | 20261001-192959-2b5f | failed at Understand | 0.34311090 | 35.38% | 9 |
| Changed | student_performance | 20261001-193354-0168 | completed with PDF | 2.41032865 | 78.24% | 2 |

The control does not reach publication, so its low spend cannot establish an end-to-end
cost or paper-quality baseline. Rejected frame submissions and unavailable researcher
calls remain live failures at the default limits. A prior collection used an incomplete
Analyst route and is excluded, even though it stopped before any Analyst call.

An isolated three-turn cache probe on Sonnet 4.6 recorded cache-read tokens
`0 → 8085 → 10505` and cache-write tokens `8085 → 2420 → 2420`, at $0.05425275.
This verifies reuse of the growing history on Bedrock, not demo cost or research quality.

| Change | Evidence | Decision |
|---|---|---|
| Rolling conversation cache | Provider probe reuses the preceding conversation prefix; wire regression tests pass | Implemented; end-to-end savings still require completed demos |
| Attempt-specific robustness references | Adversarial reference regression tests preserve blinding and omit unrelated hypothesis methods | Implemented; live placebo and null-quality gates remain open |
| Session/context journal, tool availability, valid-name diagnostics | Focused tests and full parallel suite pass | Implemented; live submit and avoidable-error changes pending |
| Explicit resume cap raise | Existing pipeline survives a budget stop and raise; focused crash-window recovery test passes | Implemented; recorded spend remains continuous |

No default model route, research check, turn limit or submit limit was changed.
No completed paper or quality improvement is claimed by these measurements.

## One completed changed run

The researcher requested stopping after this single changed run; the second positive demo
and the null demo were not started. This collection does not establish the two-run gate
or null quality. The runner was stopped after the completed run released its lock.

- Total cost $2.41032865; Steward $0.77742135 (32.25% of total).
- Ground session costs $0.40288470 and $0.37453665; cache-read ratios 91.7% and 90.1%.
- Run cache-read ratio 78.24%; Steward 91.00%.
- Theorist rejected 2 and 1 submits across two sessions; Steward rejected none.
- Two avoidable tool errors remain; nine scratch-code errors and one other tool error.
- Two context cuts were recorded in the Writer input: framing and analyses.
- Main estimate 3.87619322, interval [3.19846837, 4.55391807], from results.json.
- Two ordinary variants reached ok, three remained buggy; the adversarial attempt reached ok.
- The rendered paper is labeled fragile, has an operationalization table and ten concerns.
- All four planted data issues have counted fixes from results.json. The paper has no
  unresolved number references; the unused fallback definition in the TeX source is not
  a rendered missing number.

Cost, cache, Ground-session spend and adversarial execution gates pass for this one run.
Submit, avoidable-error, no-cut, successful-variant and repeated/null gates remain open.
The observed completion is encouraging but cannot establish a causal cost delta against
controls that failed before publication. Keep model routes and checks unchanged.

The Windows live runner was interrupted once by stdout encoding while printing a progress
arrow. It was resumed from the committed node with cumulative spend; no evidence was
replaced. This intervention is part of the measurement record, not a provider failure.
