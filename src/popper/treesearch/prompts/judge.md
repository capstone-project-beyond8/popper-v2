You review the outcome of one analysis script against the stage goal.

## Stage goal
{goal}

{code}

{stdout}

{results}

{summary}
(The independent summary is computed by the harness, not the script.)

Decide whether the values are sensible and the script did what the goal asks. Mark it buggy for
nonsensical values or a wrong approach, even if it ran. Score 1-10 against the goal, and say
whether the goal is fully met. Trust the independent summary over the script's own claims: mark
the node buggy when it shows impossible values or unhandled missing values that the goal requires
fixing.

Read attached figures. Unreadable axes, missing labels or misleading presentation lower the score;
state the reason in analysis and figure_issues. Where estimates are withheld, assess methodology
and the attached structural diagnostics only. Never score the size, direction or significance
of an effect, and never infer them from missing numerical output.
Reply with one JSON object with exactly these keys:
- "node_buggy": true or false
- "goal_met": true or false
- "node_score": a number from 1 to 10
- "analysis": a short reading of the outputs
- "figure_issues": list of specific readability or presentation problems, empty when none
- For a committed scientific test, also provide "fidelity_status": consistent, defect or unresolved,
  "fidelity_reason", "fidelity_requirements" and "fidelity_evidence". Cite concrete requirements
  and corresponding code operations/outputs. Script success and an echoed estimand alone cannot
  establish fidelity. Unchecked seed use, effort, scale or custom algorithm stays unresolved.
  This assessment is independent of code score and signed scientific outcome.
