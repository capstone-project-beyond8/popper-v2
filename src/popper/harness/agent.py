"""Tool-use loop: the model calls tools until it calls the terminal one."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from popper.harness.config import Role
from popper.harness.context import head
from popper.harness.llm import Message, ToolCall, ToolResult, ToolSpec
from popper.harness.session import Harness

_JOURNAL_LIMIT = 2000
_TRUNCATED = "Your reply was cut off at the token limit. Keep it shorter."


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], str | Path] | None
    terminal: bool = False


def _args(call: ToolCall) -> str:
    return head(json.dumps(call.input, default=str), _JOURNAL_LIMIT)


def _run(h: Harness, tag: str, turn: int, tool: Tool | None, call: ToolCall) -> ToolResult:
    out: str | Path
    if tool is None or tool.handler is None:
        out = f"error: unknown tool {call.name}"
    else:
        try:
            out = tool.handler(call.input)
        except Exception as exc:
            out = f"error: {exc}"
    h.journal.write(
        "tool_call",
        tag=tag,
        turn=turn,
        tool=call.name,
        args=_args(call),
        result=str(out) if isinstance(out, Path) else head(out, _JOURNAL_LIMIT),
    )
    return ToolResult(call.id, image=out) if isinstance(out, Path) else ToolResult(call.id, out)


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
    max_tokens: int = 16000,
) -> dict[str, Any] | None:
    by_name = {t.name: t for t in tools}
    terminal = next(t.name for t in tools if t.terminal)
    specs = [ToolSpec(t.name, t.description, t.schema) for t in tools]
    history = [Message("user", task)]
    for turn in range(1, max_turns + 1):
        done = h.converse(
            role, tag=tag, system=system, messages=history, tools=specs, max_tokens=max_tokens
        )
        if done.stop_reason == "max_tokens":
            _extend(history, Message("assistant", done.text), Message("user", _TRUNCATED))
            continue
        submitted = next((c for c in done.tool_calls if c.name == terminal), None)
        if submitted:
            h.journal.write(
                "tool_call",
                tag=tag,
                turn=turn,
                tool=terminal,
                args=_args(submitted),
            )
            return submitted.input
        assistant = Message("assistant", done.text, tool_calls=done.tool_calls)
        if done.tool_calls:
            results = tuple(_run(h, tag, turn, by_name.get(c.name), c) for c in done.tool_calls)
            _extend(history, assistant, Message("user", tool_results=results))
        else:
            nudge = f"Use a tool. Finish by calling {terminal}."
            _extend(history, assistant, Message("user", nudge))
    return None
