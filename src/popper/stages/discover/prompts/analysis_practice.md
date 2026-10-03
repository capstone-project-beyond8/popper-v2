## Implementation checks

Implement the supplied goal and declared procedure; these checks do not authorize changing
the scientific target, support rule, data selection, inference or requested coverage. If a
required method is infeasible or defective, report the limitation/failure instead of silently
substituting a cheaper method or retrying for a favorable result. Apply the method-specific
checks below only when that method is part of the delegated task.

Each execution has a {timeout}-second limit. Keep resampling and fitting feasible within it;
do not nest thousands of bootstrap draws with repeated imputer/model fits without a feasible
cost estimate. Test the submitted script with run_python, including its final result-writing
path. Fail clearly if no fits succeed; never silently discard every error or pool an empty list.

Keep boolean predicates parenthesized. Combine masks from the same aligned dataframe;
after deduplication/resetting an index, do not mix masks from the original rows. Count sentinel
strings before converting them to numeric missing values. Report row exclusions separately
from cell replacements, including reasons and counts, so sample sizes remain traceable.

For statsmodels robust-covariance results, params and bse may be arrays. Find coefficient
indices using model.exog_names; do not index an array by a column name. Clustered inference
must account for the number of independent clusters; do not replace cluster inference degrees
of freedom with the number of rows when manually pooling intervals. A warning is not a fix.

If using multiple imputation, generate stochastic draws that propagate missing-data
uncertainty. IterativeImputer requires sample_posterior=True for this use; changing only its
seed with deterministic defaults does not give distinct imputations. Check between-imputation
variation before claiming pooled multiple-imputation uncertainty. Single imputation and
complete-case analyses must be named honestly.

If implementing a censored likelihood, initialize a coefficient for every design column,
including the intercept, and assert matching shapes. Sum per-observation density terms: for
a scalar sigma, the uncensored Gaussian log-density includes -n_uncensored * log(sigma).
Use stable log-tail probabilities for censored observations. Check optimizer convergence and
fit validity before pooling; do not treat a returned parameter vector as proof of convergence.
