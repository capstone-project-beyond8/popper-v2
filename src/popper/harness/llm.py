"""Model access: provider-neutral messages, a Bedrock implementation and a scripted fake."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
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


@dataclass(frozen=True)
class LLMRequest:
    model: str
    tag: str
    system: str
    messages: tuple[Message, ...]
    tools: tuple[ToolSpec, ...] = ()

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


class TransientLLMError(Exception):
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


def _to_converse(messages: Sequence[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        content: list[dict[str, Any]] = [{"text": m.text}] if m.text else []
        content += [
            {"image": {"format": "png", "source": {"bytes": p.read_bytes()}}} for p in m.images
        ]
        content += [
            {"toolUse": {"toolUseId": c.id, "name": c.name, "input": c.input}} for c in m.tool_calls
        ]
        for r in m.tool_results:
            body: dict[str, Any] = (
                {"image": {"format": "png", "source": {"bytes": r.image.read_bytes()}}}
                if r.image
                else {"text": r.text}
            )
            content.append({"toolResult": {"toolUseId": r.call_id, "content": [body]}})
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
        text, usage["inputTokens"], usage["outputTokens"], resp.get("stopReason", ""), calls
    )


class BedrockLLM:
    def __init__(self, region: str) -> None:
        import boto3
        from botocore.config import Config

        self._client = boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(read_timeout=600, retries={"mode": "standard", "total_max_attempts": 1}),
        )

    def complete(self, req: LLMRequest, max_tokens: int) -> Completion:
        from botocore.exceptions import (
            ClientError,
            ConnectTimeoutError,
            EndpointConnectionError,
            ReadTimeoutError,
        )

        kwargs: dict[str, Any] = {}
        if req.tools:
            kwargs["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": {"json": t.schema},
                        }
                    }
                    for t in req.tools
                ]
            }
        try:
            resp = self._client.converse(
                modelId=req.model,
                system=[{"text": req.system}],
                messages=_to_converse(req.messages),
                inferenceConfig={"maxTokens": max_tokens},
                **kwargs,
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
            if code in _TRANSIENT_CODES or status >= 500:
                raise TransientLLMError(str(exc)) from exc
            raise
        except (ReadTimeoutError, ConnectTimeoutError, EndpointConnectionError) as exc:
            raise TransientLLMError(str(exc)) from exc
        return _from_converse(resp)


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
