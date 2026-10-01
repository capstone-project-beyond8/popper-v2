Write the sections of a short research report as LaTeX body text (no preamble, no section commands).

## Numbers you may cite
{keys}

Cite quantitative values only as \R{{key}}, copying a key exactly. `.ci` is the reported interval;
`.n` is sample size. Put units outside macros. Never invent numbers, labels or figure paths.
Do not write the words stable, fragile or confirmed; code inserts the evidence label and places the figures.
Interpret direction relative to the selected hypothesis, including equally legitimate negative results.

{framing}

{research}

## Hypothesis
{hypothesis}

{analyses}

{notes}

Code adds the operationalization table and a Limitations list; do not repeat them.

## Figure files available, by node identity
{figures}

Choose existing figures through the figures list only. Do not write includegraphics or label commands.
Code reserves one slot for its specification curve and places at most three other figures.
Captions also use \R{{key}}. Discuss adaptive exploration, reserved ingest rows (not evidence of verification), restricted
subgroup populations and failed attempts. Do not claim independent verification.

Reply with one JSON object with exactly these keys:
- "title", "abstract", "introduction", "data", "exploration", "hypothesis", "methods", "results", "robustness", "discussion", "conclusion": LaTeX body text
- "figures": list of {{"node_id": node identity, "file": existing file name, "caption": text, "section": "data_methods"|"exploratory"|"main"|"robustness"}}
