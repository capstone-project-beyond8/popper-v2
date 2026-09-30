"""Journal, budget and the single entry point for model calls."""

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from popper.harness.config import Config, Role
from popper.harness.llm import LLM, LLMRequest
from popper.harness.store import RunStore

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")
_FENCE = re.compile(r"```json\s*(.*?)```", re.DOTALL)


class BudgetExceeded(Exception):
    pass


class Journal:
    def __init__(self, path: Path) -> None:
        self._path = path

    def write(self, event: str, **fields: object) -> None:
        entry = {"ts": datetime.now(UTC).isoformat(), "event": event, **fields}
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")


def _parse_json(text: str) -> dict[str, Any]:
    fenced = _FENCE.search(text)
    if fenced:
        raw = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("no JSON object found in reply")
        raw = text[start : end + 1]
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("reply JSON is not an object")
    return obj


@dataclass
class Harness:
    config: Config
    llm: LLM
    run: RunStore
    journal: Journal = field(init=False)
    spent_usd: float = 0.0

    def __post_init__(self) -> None:
        self.journal = Journal(self.run.path("journal.jsonl"))

    def ask(
        self,
        role: Role,
        *,
        tag: str,
        system: str,
        prompt: str,
        images: Sequence[Path] = (),
        max_tokens: int = 8000,
    ) -> str:
        budget = self.config.budget
        if self.spent_usd >= budget.max_usd:
            raise BudgetExceeded(f"spent ${self.spent_usd:.4f} of ${budget.max_usd:.2f}")
        model: str = getattr(self.config.models, role)
        req = LLMRequest(model, tag, system, prompt, tuple(images))
        try:
            done = self.llm.complete(req, max_tokens)
        except Exception as exc:
            self.journal.write("llm_error", tag=tag, role=role, model=model, error=repr(exc)[:500])
            raise
        usd = (
            done.input_tokens * budget.usd_per_mtok_input
            + done.output_tokens * budget.usd_per_mtok_output
        ) / 1e6
        self.spent_usd += usd
        self.journal.write(
            "llm_call",
            tag=tag,
            role=role,
            model=model,
            input_tokens=done.input_tokens,
            output_tokens=done.output_tokens,
            usd=usd,
            stop_reason=done.stop_reason,
        )
        if done.stop_reason == "max_tokens":
            raise ValueError("reply truncated at max_tokens")
        return done.text

    def _ask_parsed(
        self, role: Role, tag: str, system: str, prompt: str, parse: Callable[[str], R]
    ) -> R:
        try:
            return parse(self.ask(role, tag=tag, system=system, prompt=prompt))
        except ValueError as err:  # JSON, schema and truncation errors all derive from ValueError
            retry = (
                f"{prompt}\n\nYour previous reply was not valid JSON for this task ({err}). "
                "Reply with JSON only."
            )
            return parse(self.ask(role, tag=tag, system=system, prompt=retry))

    def ask_json(self, role: Role, *, tag: str, system: str, prompt: str) -> dict[str, Any]:
        return self._ask_parsed(role, tag, system, prompt, _parse_json)

    def ask_model(self, role: Role, *, schema: type[T], tag: str, system: str, prompt: str) -> T:
        return self._ask_parsed(
            role, tag, system, prompt, lambda text: schema.model_validate(_parse_json(text))
        )
