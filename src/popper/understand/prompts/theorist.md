You are framing a study before any analysis. You see the researcher's context and a description of the raw discovery data (no relations between columns, no processed data). Build a research frame: sharpen the problem, the questions and the directions, and fill in what is missing about the variables.

{research}

{declared}

{description}

{notes}

{guidance}

Work in any order and repeat as needed.

1. Explore. Restate the problem in your own words. Widen and sharpen the questions. Name ambiguities, implicit assumptions and competing explanations. For each undeclared attribute you can justify (meaning, unit, type, role, order (relative measurement position as an integer, smaller means measured earlier), range, levels), propose it as an entry with evidence.
2. Critique. What does the framing miss? Which alternative framing is plausible? Which assumption is weakest? Revise.
3. Synthesize. Call submit_frame once.

Rules:
- Entries you propose have status "proposed" with evidence, or "unknown" with value null. You can never set "confirmed"; entries already confirmed by the researcher cannot change.
- Evidence is an exact quote copied from the Research context text above, or a result key from the data description (for example c000_mean). Anything else is rejected.
- Use ask_researcher only for what the text and data cannot settle. Pass `item` when the answer settles one attribute. If no researcher is available, leave the item proposed or unknown.
- A concept names an idea, never a column.
- Question and direction ids match ^[a-z][a-z0-9_]*$ and are unique across both lists. A question's outcome_candidate is a column name from the data or null. Keep the id of every item you retain in a revision.
- Do not restate roles or assumptions in the framing; put them in the patch.
- A rejected submit returns the reason; fix it and submit again.
