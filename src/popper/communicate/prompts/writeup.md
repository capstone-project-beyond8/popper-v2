Write the sections of a short research report as LaTeX body text (no preamble, no section commands).

## Numbers you may cite
{keys}

Write every number as \R{{key}} using only the keys listed above. Never type a number yourself. Do not state the evidence label; the template adds it.

## Framing
{framing}

## Hypothesis
{hypothesis}

## Analyses
{analyses}

## Figure files available, by stage
{figures}

Reference figures only through the "figures" list, by file name. Never write \includegraphics yourself.

Reply with one JSON object with exactly these keys:
- "title", "abstract", "introduction", "data", "exploration", "hypothesis", "methods", "results", "limitations": LaTeX body text
- "figures": list of {{"file": figure file name, "caption": caption text}}
