"""Model access: a protocol, a Bedrock implementation and a scripted fake."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class LLMRequest:
    model: str
    tag: str
    system: str
    prompt: str
    images: tuple[Path, ...] = ()


@dataclass(frozen=True)
class Completion:
    text: str
    input_tokens: int
    output_tokens: int


class LLM(Protocol):
    def complete(self, req: LLMRequest, max_tokens: int) -> Completion: ...


class BedrockLLM:
    def __init__(self, region: str) -> None:
        import boto3

        self._client = boto3.client("bedrock-runtime", region_name=region)

    def complete(self, req: LLMRequest, max_tokens: int) -> Completion:
        content: list[dict[str, Any]] = [{"text": req.prompt}]
        content += [
            {"image": {"format": "png", "source": {"bytes": p.read_bytes()}}} for p in req.images
        ]
        resp = self._client.converse(
            modelId=req.model,
            system=[{"text": req.system}],
            messages=[{"role": "user", "content": content}],
            inferenceConfig={"maxTokens": max_tokens},
        )
        blocks = resp["output"]["message"]["content"]
        text = "".join(b["text"] for b in blocks if "text" in b)
        usage = resp["usage"]
        return Completion(text, usage["inputTokens"], usage["outputTokens"])


class FakeLLM:
    def __init__(self, respond: Callable[[LLMRequest], str]) -> None:
        self._respond = respond
        self.calls: list[LLMRequest] = []

    def complete(self, req: LLMRequest, max_tokens: int) -> Completion:
        self.calls.append(req)
        return Completion(self._respond(req), 0, 0)
