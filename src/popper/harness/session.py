"""Journal, budget and the single entry point for model calls."""

import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel

from popper.harness.config import Config, Role
from popper.harness.context import UNTRUSTED_NOTE
from popper.harness.interpreter import ExecResult, run_script
from popper.harness.llm import (
    LLM,
    Completion,
    LLMRequest,
    Message,
    ToolSpec,
    TransientLLMError,
)
from popper.harness.recovery import Journal
from popper.harness.store import RunStore

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")
_MAX_ATTEMPTS = 5
_BACKOFF_SECONDS = 2.0
_FENCE = re.compile(r"```json\s*(.*?)```", re.DOTALL)


class BudgetExceeded(Exception):
    pass


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
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    progress: Callable[[str], None] = field(default=lambda _line: None, repr=False)

    def __post_init__(self) -> None:
        self.journal = Journal(self.run.path("journal.jsonl"))

    def execute(
        self, code: str, workdir: Path, *, inputs: Mapping[str, Path], node: str,
        purpose: Literal["scratch", "submitted", "plot"],
    ) -> ExecResult:
        fields = {"node": node, "purpose": purpose, "path": str(workdir.resolve())}
        self.journal.write("exec_start", **fields)
        try:
            result = run_script(
                code, workdir, timeout=self.config.execution.timeout_seconds, inputs=inputs,
                max_output_chars=self.config.execution.max_output_chars,
            )
        except Exception as exc:
            self.journal.write("exec", **fields, error=str(exc), exit_code=None, timed_out=False)
            raise
        self.journal.write(
            "exec", **fields, exit_code=result.exit_code,
            timed_out=result.timed_out, seconds=result.seconds,
        )
        return result

    def converse(
        self,
        role: Role,
        *,
        tag: str,
        system: str,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec] = (),
        max_tokens: int = 8000,
    ) -> Completion:
        budget = self.config.budget
        if self.spent_usd >= budget.max_usd:
            raise BudgetExceeded(f"spent ${self.spent_usd:.4f} of ${budget.max_usd:.2f}")
        model: str = getattr(self.config.models, role)
        req = LLMRequest(model, tag, f"{system}\n\n{UNTRUSTED_NOTE}", tuple(messages), tuple(tools))
        attempt = 1
        while True:
            try:
                done = self.llm.complete(req, max_tokens)
                break
            except Exception as exc:
                if isinstance(exc, TransientLLMError) and attempt < _MAX_ATTEMPTS:
                    delay = _BACKOFF_SECONDS * 2 ** (attempt - 1)
                    self.journal.write(
                        "llm_retry", tag=tag, attempt=attempt, delay=delay, error=repr(exc)[:500]
                    )
                    self.sleep(delay)
                    attempt += 1
                    continue
                self.journal.write(
                    "llm_error",
                    tag=tag,
                    role=role,
                    model=model,
                    error=repr(exc)[:500],
                    attempts=attempt,
                )
                raise
        price = budget.price(model)
        usd = (
            done.input_tokens * price.input
            + done.cache_write_tokens * price.input * price.cache_write
            + done.cache_read_tokens * price.input * price.cache_read
            + done.output_tokens * price.output
        ) / 1e6
        self.spent_usd += usd
        self.journal.write(
            "llm_call",
            tag=tag,
            role=role,
            model=model,
            input_tokens=done.input_tokens,
            output_tokens=done.output_tokens,
            cache_read_tokens=done.cache_read_tokens,
            cache_write_tokens=done.cache_write_tokens,
            usd=usd,
            stop_reason=done.stop_reason,
            tools=[c.name for c in done.tool_calls],
        )
        return done

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
        done = self.converse(
            role,
            tag=tag,
            system=system,
            messages=(Message("user", prompt, images=tuple(images)),),
            max_tokens=max_tokens,
        )
        if done.stop_reason == "max_tokens":
            raise ValueError("reply truncated at max_tokens")
        return done.text

    def _ask_parsed(
        self, role: Role, tag: str, system: str, prompt: str, parse: Callable[[str], R],
        images: Sequence[Path] = (),
    ) -> R:
        try:
            return parse(self.ask(role, tag=tag, system=system, prompt=prompt, images=images))
        except ValueError as err:  # JSON, schema and truncation errors all derive from ValueError
            retry = (
                f"{prompt}\n\nYour previous reply was not valid JSON for this task ({err}). "
                "Reply with JSON only."
            )
            return parse(self.ask(role, tag=tag, system=system, prompt=retry, images=images))

    def ask_json(self, role: Role, *, tag: str, system: str, prompt: str) -> dict[str, Any]:
        return self._ask_parsed(role, tag, system, prompt, _parse_json)

    def ask_model(
        self, role: Role, *, schema: type[T], tag: str, system: str, prompt: str,
        images: Sequence[Path] = (),
        validation_context: Mapping[str, Any] | None = None,
    ) -> T:
        return self._ask_parsed(
            role, tag, system, prompt,
            lambda text: schema.model_validate(_parse_json(text), context=validation_context), images,
        )
