"""Ideation and framing: restate the problem, then reflect once and improve."""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from popper.harness.context import ARTIFACT_CHARS, RESEARCH_CHARS, part
from popper.harness.prompts import load_prompt
from popper.harness.session import Harness

_SYSTEM = "You are a careful research scientist."


class Framing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    problem: str
    questions: list[str]
    key_variables: list[str]
    directions: list[str]
    data_concerns: list[str]


def frame(h: Harness, research: str, description: str) -> dict[str, Any]:
    committed = h.run.committed("framing")
    if committed:
        result: dict[str, Any] = json.loads(committed.read_text("utf-8"))
        return result
    attempt = h.run.new_attempt("understand").relative_to(h.run.root).as_posix()
    draft = h.ask_model(
        "theorist",
        schema=Framing,
        tag="framing",
        system=_SYSTEM,
        prompt=load_prompt(
            "popper.understand",
            "framing.md",
            research=part("Research context", research, RESEARCH_CHARS, untrusted=True),
            profile=part("Data description", description, ARTIFACT_CHARS, untrusted=True),
        ),
    )
    final = h.ask_model(
        "theorist",
        schema=Framing,
        tag="framing:reflect",
        system=_SYSTEM,
        prompt=load_prompt(
            "popper.understand",
            "reflect.md",
            framing=json.dumps(draft.model_dump(), indent=2),
        ),
    )
    framing = {**final.model_dump(), "supplied_by": "agent"}
    path = h.run.write_json(f"{attempt}/framing.json", framing)
    h.run.commit_artifact("framing", path)
    return framing
