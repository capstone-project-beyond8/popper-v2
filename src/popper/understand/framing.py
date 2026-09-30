"""Ideation and framing: restate the problem, then reflect once and improve."""

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from popper.harness.prompts import load_prompt
from popper.harness.session import Harness

_SYSTEM = "You are a careful research scientist. Reply with JSON only."


class Framing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    problem: str
    questions: list[str]
    key_variables: list[str]
    directions: list[str]
    data_concerns: list[str]


def frame(h: Harness, brief: str, profile: dict[str, Any]) -> dict[str, Any]:
    h.run.write_json("understand/profile.json", profile)
    draft = h.ask_model(
        "ideation",
        schema=Framing,
        tag="framing",
        system=_SYSTEM,
        prompt=load_prompt(
            "popper.understand",
            "framing.md",
            brief=brief,
            profile=json.dumps(profile, indent=2),
        ),
    )
    final = h.ask_model(
        "ideation",
        schema=Framing,
        tag="framing:reflect",
        system=_SYSTEM,
        prompt=load_prompt(
            "popper.understand",
            "reflect.md",
            framing=json.dumps(draft.model_dump(), indent=2),
        ),
    )
    framing = final.model_dump()
    h.run.write_json("understand/framing.json", framing)
    return framing
