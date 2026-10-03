"""Bounded error feedback backed by complete, write-once reports."""

from typing import TYPE_CHECKING

from popper.harness.context.rendering import ARTIFACT_CHARS

if TYPE_CHECKING:
    from popper.harness.storage.store import RunStore


def error_feedback(run: "RunStore", text: str, *, tag: str) -> tuple[str, str | None]:
    """Return complete lines within the feedback budget, plus a full report when needed."""
    if len(text) <= ARTIFACT_CHARS:
        return text, None
    folder = run.new_attempt("diagnostics")
    rel = f"{folder.relative_to(run.root).as_posix()}/error.json"
    run.write_json(rel, {"tag": tag, "text": text})
    lines = text.splitlines(keepends=True)

    def notice(count: int) -> str:
        return (
            f"\n[{count} diagnostic lines omitted.] "
            f'Full report: read_artifact({{"path": "{rel}", "offset": 0}}).'
        )

    available = ARTIFACT_CHARS - len(notice(len(lines)))
    kept: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) > available:
            break
        kept.append(line)
        size += len(line)
    return "".join(kept) + notice(len(lines) - len(kept)), rel
