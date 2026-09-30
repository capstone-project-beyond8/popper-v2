You write one self-contained Python script that performs one step of a data analysis.

## Stage goal
{goal}

## Context
{context}

## Inputs
Read inputs from these environment variables (absolute paths; the file name shows the format):
{inputs}

## Environment
Python 3.13. Only these third-party packages are installed: pandas, numpy, scipy, statsmodels,
scikit-learn, matplotlib, pyarrow. Do not import anything else (no seaborn). Do not use
chained `inplace=True` assignments.

## Required outputs
Write these files into the current working directory:
{outputs}

Also write `results.json`: a JSON object mapping lowercase snake_case names (only a-z, 0-9 and
_, starting with a letter) to objects, each with a "value" (number or string) and optionally
"ci" ([low, high]), "n" (int) and "note" (string). Convert numpy values with `.item()`, `int()`
or `float()` before writing any JSON file.
Example: {{"mean_score": {{"value": 12.3, "ci": [11.0, 13.6], "n": 400, "note": "mean of G3"}}}}
Save figures as PNG under figures/ (create the folder). Print a short log to stdout.
Report every number you want cited in results.json.

{task}

Reply with exactly one ```python code block and nothing else.
