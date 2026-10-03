"""Shared scientific context rendered through generic journalled fences."""

import json
from functools import partial
from typing import Any, Literal

from popper.harness.context import ARTIFACT_CHARS, RESEARCH_CHARS, part
from popper.harness.recovery import Journal
from popper.science.research import ResearchContext, render_research


def frame_context(
    tag: str,
    journal: Journal,
    research: ResearchContext,
    framing: dict[str, Any],
    foundation: dict[str, Any],
) -> str:
    """The framing plus what the data steward concluded about measuring and trusting it."""
    context_part = partial(part, journal=journal, tag=tag)
    shown = {
        "Concepts": [c.model_dump(mode="json") for c in research.concepts],
        "Operationalization (proposed by the data agent)": foundation["operationalization"],
        "Data concerns": foundation["concerns"],
        "Readiness": foundation["readiness"],
    }
    parts = [
        context_part("Research context", render_research(research), RESEARCH_CHARS, untrusted=True),
        context_part("Framing", json.dumps(framing, indent=2), RESEARCH_CHARS, untrusted=True),
    ]
    parts += [
        context_part(title, json.dumps(value, indent=2), ARTIFACT_CHARS, untrusted=True)
        for title, value in shown.items()
    ]
    return "\n\n".join(parts)


def research_notes(
    journal: Journal, research: ResearchContext, key: Literal["explore", "hypothesis"]
) -> str:
    return part(
        "Researcher notes",
        research.notes.get(key, "(none)"),
        RESEARCH_CHARS,
        untrusted=True,
        journal=journal,
        tag=key,
    )
