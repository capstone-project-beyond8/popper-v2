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

Reply with one JSON object with exactly these keys:
- "node_buggy": true or false
- "goal_met": true or false
- "node_score": a number from 1 to 10
- "analysis": a short reading of the outputs
