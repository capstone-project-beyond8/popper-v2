"""Tool-use loop: the model calls tools until it calls the terminal one."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from popper.harness.config import Role
from popper.harness.diagnostics import error_feedback
from popper.harness.llm import Message, ToolCall, ToolResult, ToolSpec
from popper.harness.session import Harness
from popper.harness.validation import format_errors

_TRUNCATED = "Your reply was cut off at the token limit. Keep it shorter."


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], str | Path] | None
    terminal: bool = False

    @classmethod
    def from_model[T: BaseModel](
        cls,
        name: str,
        description: str,
        model: type[T],
        handler: Callable[[T], str | Path],
        *,
        terminal: bool = False,
    ) -> "Tool":
        """Publish and validate the same input contract before invoking the handler."""
        def invoke(args: dict[str, Any]) -> str | Path:
            return handler(model.model_validate(args))

        return cls(name, description, model.model_json_schema(), invoke, terminal)


def _args(call: ToolCall) -> str:
    return json.dumps(call.input, default=str)


def _skip(h: Harness, tag: str, turn: int, call: ToolCall, reason: str) -> None:
    h.journal.write(
        "tool_call", tag=tag, turn=turn, tool=call.name, call_id=call.id,
        args=_args(call), result=reason, status="skipped",
    )


def _run(h: Harness, tag: str, turn: int, by_name: dict[str, Tool], call: ToolCall) -> ToolResult:
    tool = by_name.get(call.name)
    out: str | Path
    status = "success"
    if tool is None or (tool.handler is None and not tool.terminal):
        out = f"error: unknown tool {call.name}; available: {', '.join(by_name)}"
        status = "error"
    elif tool.handler is None:
        out = "Submission accepted."
    else:
        try:
            out = tool.handler(call.input)
        except ValidationError as exc:
            out = f"error: {format_errors(exc)}\nCorrect these fields and resubmit the complete input."
            status = "error"
        except Exception as exc:
            out = f"error: {exc}"
            status = "error"
    feedback, diagnostic = (
        error_feedback(h.run, out, tag=tag) if status == "error" and isinstance(out, str) else (out, None)
    )
    h.journal.write(
        "tool_call",
        tag=tag,
        turn=turn,
        tool=call.name,
        call_id=call.id,
        args=_args(call),
        result=str(out),
        status=status,
        **({"diagnostic": diagnostic} if diagnostic else {}),
    )
    return (
        ToolResult(call.id, image=out)
        if isinstance(out, Path)
        else ToolResult(call.id, str(feedback), status="error" if status == "error" else "success")
    )


def _extend(history: list[Message], assistant: Message, user: Message) -> None:
    """Append a turn. An empty assistant message is skipped and the user text merged."""
    if assistant.text or assistant.tool_calls:
        history += [assistant, user]
    else:
        last = history[-1]
        history[-1] = replace(last, text=f"{last.text}\n\n{user.text}".strip())


def agent_loop(
    h: Harness,
    role: Role,
    *,
    tag: str,
    system: str,
    task: str,
    tools: Sequence[Tool],
    max_turns: int,
    max_tokens: int = 32000,
    max_submits: int | None = None,
) -> dict[str, Any] | None:
    """Run until the terminal tool is called; None when turns or rejected submits run out.

    Calls run in order until the first accepted terminal call or `max_submits` rejected
    terminal calls. Remaining calls are recorded as skipped without invoking their handlers.
    """
    by_name = {t.name: t for t in tools}
    terminal = next(t.name for t in tools if t.terminal)
    specs = [ToolSpec(t.name, t.description, t.schema) for t in tools]
    rejected = 0
    history = [Message("user", task)]
    for turn in range(1, max_turns + 1):
        done = h.converse(
            role, tag=tag, system=system, messages=history, tools=specs, max_tokens=max_tokens
        )
        if done.stop_reason == "max_tokens":
            for call in done.tool_calls:
                _skip(h, tag, turn, call, "Skipped: the reply was cut off at the token limit.")
            _extend(history, Message("assistant", done.text), Message("user", _TRUNCATED))
            continue
        assistant = Message(
            "assistant", done.text, tool_calls=done.tool_calls, content=done.content
        )
        if done.tool_calls:
            results: list[ToolResult] = []
            accepted = None
            stopped = None
            for call in done.tool_calls:
                if stopped is not None:
                    _skip(h, tag, turn, call, stopped)
                    continue
                result = _run(h, tag, turn, by_name, call)
                results.append(result)
                if call.name == terminal:
                    if result.status == "success":
                        accepted = call
                        stopped = "Skipped: a terminal submission was already accepted."
                    else:
                        rejected += 1
                        if max_submits is not None and rejected >= max_submits:
                            stopped = "Skipped: the rejected submission limit was reached."
            if stopped is not None:
                return accepted.input if accepted is not None else None
            _extend(history, assistant, Message("user", tool_results=tuple(results)))
        else:
            nudge = f"Use a tool. Finish by calling {terminal}."
            _extend(history, assistant, Message("user", nudge))
    return None
