"""Journal, budget and the single entry point for model calls."""

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ValidationError

from popper.harness.config import Config, Role
from popper.harness.context import UNTRUSTED_NOTE, fence
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
from popper.harness.validation import format_errors

T = TypeVar("T", bound=BaseModel)
_MAX_ATTEMPTS = 5
_BACKOFF_SECONDS = 2.0


class BudgetExceeded(Exception):
    pass


@dataclass
class Harness:
    config: Config
    llm: LLM
    run: RunStore
    journal: Journal = field(init=False)
    spent_usd: float = 0.0
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    progress: Callable[[str], None] = field(default=lambda _line: None, repr=False)
    # (question, proposed answer) -> answer; None means unknown
    researcher: Callable[[str, str], str | None] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.journal = Journal(self.run.path("journal.jsonl"))

    def execute(
        self,
        code: str,
        workdir: Path,
        *,
        inputs: Mapping[str, Path],
        node: str,
        purpose: Literal["scratch", "submitted", "plot"],
    ) -> ExecResult:
        fields = {"node": node, "purpose": purpose, "path": str(workdir.resolve())}
        self.journal.write("exec_start", **fields)
        try:
            result = run_script(
                code,
                workdir,
                timeout=self.config.execution.timeout_seconds,
                inputs=inputs,
                max_output_chars=self.config.execution.max_output_chars,
            )
        except Exception as exc:
            self.journal.write("exec", **fields, error=str(exc), exit_code=None, timed_out=False)
            raise
        self.journal.write(
            "exec",
            **fields,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            seconds=result.seconds,
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
        max_tokens: int = 32000,
        output_schema: dict[str, Any] | None = None,
        session: str | None = None,
    ) -> Completion:
        budget = self.config.budget
        if self.spent_usd >= budget.max_usd:
            raise BudgetExceeded(f"spent ${self.spent_usd:.4f} of ${budget.max_usd:.2f}")
        model: str = getattr(self.config.models, role)
        req = LLMRequest(
            model,
            tag,
            f"{system}\n\n{UNTRUSTED_NOTE}",
            tuple(messages),
            tuple(tools),
            output_schema,
        )
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
            session=session,
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

    def ask_model(
        self,
        role: Role,
        *,
        schema: type[T],
        tag: str,
        system: str,
        prompt: str,
        images: Sequence[Path] = (),
        validation_context: Mapping[str, Any] | None = None,
    ) -> T:
        previous = ""

        def attempt(text: str) -> T:
            nonlocal previous
            done = self.converse(
                role,
                tag=tag,
                system=system,
                messages=(Message("user", text, images=tuple(images)),),
                output_schema=schema.model_json_schema(),
            )
            previous = done.text
            if done.stop_reason == "max_tokens":
                raise ValueError("reply truncated at max_tokens")
            return schema.model_validate_json(previous, context=validation_context)

        try:
            return attempt(prompt)
        except ValueError as err:  # truncation and validation errors both derive from ValueError
            feedback = format_errors(err) if isinstance(err, ValidationError) else str(err)
            self.journal.write("schema_rejection", tag=tag, error=feedback)
            return attempt(
                f"{prompt}\n\nYour previous reply could not be used: {feedback}\n\n"
                f"Previous reply:\n{fence(previous)}\nCorrect it and return the complete response."
            )
