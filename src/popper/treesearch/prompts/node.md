You write one self-contained Python script that performs one step of a data analysis.

## Stage goal
{goal}

## Context
{context}

## Inputs
Read inputs from these environment variables (absolute paths):
{inputs}

## Required outputs
Write these files into the current working directory:
{outputs}

Also write `results.json`: a JSON object mapping snake_case names to objects, each with a
"value" (number or string) and optionally "ci" ([low, high]), "n" (int) and "note" (string).
Example: {{"mean_score": {{"value": 12.3, "ci": [11.0, 13.6], "n": 400, "note": "mean of G3"}}}}
Save figures as PNG under figures/ (create the folder). Print a short log to stdout.
Report every number you want cited in results.json.

{task}

Reply with exactly one ```python code block and nothing else.
