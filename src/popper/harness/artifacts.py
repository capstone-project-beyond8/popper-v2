"""Read-only tool over an explicit reachable committed artifact set."""


from pydantic import Field

from popper.harness.agent import Tool
from popper.harness.context import ARTIFACT_CHARS, fence
from popper.harness.records import ArtifactRef, Record, resolve_artifact
from popper.harness.session import Harness


class ReadRequest(Record):
    path: str
    offset: int = Field(default=0, ge=0)


def read_artifact_tool(h: Harness, refs: list[ArtifactRef]) -> Tool:
    allowed = {ref.path: ref for ref in refs}

    def read(request: ReadRequest) -> str:
        ref = allowed.get(request.path)
        if ref is None or request.path.startswith("data/") or request.path == "run.json":
            raise ValueError("artifact is private or unreachable from this snapshot")
        text = resolve_artifact(h.run, ref).read_text("utf-8", errors="replace")
        end = min(len(text), request.offset + ARTIFACT_CHARS)
        return fence(text[request.offset : end]) + (
            f"\nNext offset: {end}" if end < len(text) else ""
        )

    return Tool.from_model(
        "read_artifact",
        "Read exact cited records; permitted paths: " + ", ".join(allowed),
        ReadRequest,
        read,
    )
