"""Model access: provider-neutral messages, a Bedrock implementation and a scripted fake."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    text: str = ""
    image: Path | None = None
    status: Literal["success", "error"] = "success"


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    schema: dict[str, Any]


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    text: str = ""
    images: tuple[Path, ...] = ()
    tool_calls: tuple[ToolCall, ...] = ()
    tool_results: tuple[ToolResult, ...] = ()
    # Raw provider content of an assistant reply; when set, _to_converse sends it verbatim for
    # this message instead of rebuilding from text and tool_calls (keeps reasoning blocks intact).
    content: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class LLMRequest:
    model: str
    tag: str
    system: str
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()
    output_schema: dict[str, Any] | None = None

    @property
    def prompt(self) -> str:
        """Text of the last user message."""
        return next((m.text for m in reversed(self.messages) if m.role == "user"), "")


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int
    stop_reason: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    content: tuple[dict[str, Any], ...] = ()


class LLMError(Exception):
    """A provider call failed."""


class TransientLLMError(LLMError):
    """A provider failure worth retrying (throttling, timeouts, server errors)."""


class LLM(Protocol):
    def complete(self, req: LLMRequest, max_tokens: int) -> Completion: ...


_TRANSIENT_CODES = {
    "ThrottlingException",
    "ServiceUnavailableException",
    "InternalServerException",
    "ModelNotReadyException",
    "ModelTimeoutException",
}


_CACHE_POINT = {"cachePoint": {"type": "default"}}


def _to_converse(messages: Sequence[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.content:
            out.append({"role": m.role, "content": list(m.content)})
            continue
        # Tool results must come first in a user turn; empty text blocks are rejected.
        content: list[dict[str, Any]] = []
        for r in m.tool_results:
            body: dict[str, Any] = (
                {"image": {"format": "png", "source": {"bytes": r.image.read_bytes()}}}
                if r.image
                else {"text": r.text}
            )
            content.append(
                {
                    "toolResult": {
                        "toolUseId": r.call_id,
                        "content": [body],
                        "status": r.status,
                    }
                }
            )
        if m.text.strip():
            content.append({"text": m.text})
        content += [
            {"image": {"format": "png", "source": {"bytes": p.read_bytes()}}} for p in m.images
        ]
        content += [
            {"toolUse": {"toolUseId": c.id, "name": c.name, "input": c.input}} for c in m.tool_calls
        ]
        out.append({"role": m.role, "content": content})
    return out


def _from_converse(resp: dict[str, Any]) -> Completion:
    blocks = resp["output"]["message"]["content"]
    text = "".join(b["text"] for b in blocks if "text" in b)
    calls = tuple(
        ToolCall(u["toolUseId"], u["name"], u["input"]) for b in blocks if (u := b.get("toolUse"))
    )
    usage = resp["usage"]
    return Completion(
        text,
        usage["inputTokens"],
        usage["outputTokens"],
        resp.get("stopReason", ""),
        calls,
        usage.get("cacheReadInputTokens", 0),
        usage.get("cacheWriteInputTokens", 0),
        tuple(blocks),
    )


class BedrockLLM:
    def __init__(self, region: str) -> None:
        import boto3
        from botocore.config import Config

        self._client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(read_timeout=900, retries={"mode": "standard", "total_max_attempts": 1}),
        )

    def complete(self, req: LLMRequest, max_tokens: int) -> Completion:
        from botocore.exceptions import (
            ClientError,
            ConnectionClosedError,
            ConnectTimeoutError,
            EndpointConnectionError,
            ReadTimeoutError,
        )

        # Cache sessions through their rolling tail. One-shot prompts have no reusable prefix.
        cache = "anthropic" in req.model and (bool(req.tools) or len(req.messages) > 1)
        kwargs: dict[str, Any] = {}
        tools = req.tools
        if req.output_schema is not None:
            if tools:
                raise ValueError("structured replies cannot also request execution tools")
            tools = (
                ToolSpec(
                    "structured_reply", "Return the complete requested response.", req.output_schema
                ),
            )
        if tools:
            specs: list[dict[str, Any]] = [
                {
                    "toolSpec": {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": {"json": t.schema},
                    }
                }
                for t in tools
            ]
            if cache:
                specs.append(_CACHE_POINT)
            kwargs["toolConfig"] = {"tools": specs}
        if req.output_schema is not None:
            kwargs["toolConfig"]["toolChoice"] = {"tool": {"name": "structured_reply"}}
        messages = _to_converse(req.messages)
        if cache:
            messages[-1]["content"].append(_CACHE_POINT)
        try:
            resp = self._client.converse(
                modelId=req.model,
                system=[{"text": req.system}, *([_CACHE_POINT] if cache else [])],
                messages=messages,
                inferenceConfig={"maxTokens": max_tokens},
                **kwargs,
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
            if code in _TRANSIENT_CODES or status >= 500:
                raise TransientLLMError(str(exc)) from exc
            raise LLMError(str(exc)) from exc
        except (
            ReadTimeoutError,
            ConnectTimeoutError,
            ConnectionClosedError,
            EndpointConnectionError,
        ) as exc:
            raise TransientLLMError(str(exc)) from exc
        done = _from_converse(resp)
        if req.output_schema is not None:
            # An absent or ambiguous reply fails the caller's normal JSON validation, after
            # usage is charged. Do not turn provider shape failures into unbilled exceptions.
            calls = done.tool_calls
            text = (
                json.dumps(calls[0].input)
                if len(calls) == 1 and calls[0].name == "structured_reply"
                else ""
            )
            return replace(done, text=text, tool_calls=())
        return done


class FakeLLM:
    def __init__(self, respond: Callable[[LLMRequest], str | tuple[ToolCall, ...]]) -> None:
        self._respond = respond
        self.calls: list[LLMRequest] = []

    def complete(self, req: LLMRequest, max_tokens: int) -> Completion:
        self.calls.append(req)
        reply = self._respond(req)
        if isinstance(reply, str):
            return Completion(reply, 0, 0, "end_turn")
        return Completion("", 0, 0, "tool_use", reply)
