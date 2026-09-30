You review the outcome of one analysis script against the stage goal.

## Stage goal
{goal}

## Code
```python
{code}
```

## Output (tail)
{stdout}

## results.json
{results}

## Independent summary of the outputs (computed by the harness, not the script)
{summary}

Decide whether the values are sensible and the script did what the goal asks. Mark it buggy for
nonsensical values or a wrong approach, even if it ran. Score 1-10 against the goal, and say
whether the goal is fully met. Trust the independent summary over the script's own claims: mark
the node buggy when it shows impossible values or unhandled missing values that the goal requires
fixing.

Reply with JSON only:
{{"is_buggy": false, "analysis": "short reading of the outputs", "score": 7, "goal_met": false}}
