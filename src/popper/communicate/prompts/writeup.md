Write the sections of a short research report as LaTeX body text (no preamble, no section commands).

## Numbers you may cite
{keys}

Cite numbers only through macros with the keys listed above: \R{{key}} for the value, \CI{{key}} for its 95\% interval, \N{{key}} for the sample size, e.g. slope \R{{experiment.slope}} (95\% CI \CI{{experiment.slope}}, $n = \N{{experiment.slope}}$). Use \CI or \N only where the key lists an interval or n. Never type a number yourself. Put units and percent signs outside the macro (write \%). Do not state the evidence label; the template adds it.

{framing}

## Hypothesis
{hypothesis}

{analyses}

## Figure files available, by stage
{figures}

Reference figures only through the "figures" list, by stage and file name. Never write \includegraphics yourself.

Reply with one JSON object with exactly these keys:
- "title", "abstract", "introduction", "data", "exploration", "hypothesis", "methods", "results", "limitations": LaTeX body text
- "figures": list of {{"stage": "explore" or "experiment", "file": figure file name in that stage, "caption": caption text}}
