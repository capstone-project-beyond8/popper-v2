"""Append-only journal segments and committed run state."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from popper.harness.store import RunStore


def _segments(root: Path) -> list[Path]:
    first = root / "journal.jsonl"
    return ([first] if first.exists() else []) + sorted(root.glob("journal-*.jsonl"))


def read_events(root: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in _segments(root):
        lines = path.read_bytes().splitlines(keepends=True)
        for index, raw in enumerate(lines):
            try:
                entry = json.loads(raw)
            except (ValueError, UnicodeDecodeError) as exc:
                if index == len(lines) - 1 and not raw.endswith(b"\n"):
                    break
                raise ValueError(f"corrupt journal {path.name} line {index + 1}") from exc
            if not isinstance(entry, dict) or not isinstance(entry.get("event"), str):
                raise ValueError(f"invalid journal event {path.name} line {index + 1}")
            events.append(entry)
    return events


class Journal:
    def __init__(self, path: Path) -> None:
        read_events(path.parent)
        segments = _segments(path.parent)
        self._path = segments[-1] if segments else path
        if self._path.exists():
            contents = self._path.read_bytes()
            if contents and not contents.endswith(b"\n"):
                old = self._path
                self._path = path.with_name(f"journal-{len(segments):06d}.jsonl")
                self.write("journal_recovered", source=old.name, bytes=len(contents))

    def write(self, event: str, **fields: object) -> None:
        entry = {"ts": datetime.now(UTC).isoformat(), "event": event, **fields}
        with self._path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, default=str) + "\n")


def load_state(store: "RunStore") -> dict[str, Any]:
    commits = [event for event in read_events(store.root) if event["event"] == "state_commit"]
    if not commits:
        return {"status": "running", "spent_usd": recorded_spend(store)}
    path = store.path(str(commits[-1]["path"])).resolve()
    if not path.is_relative_to(store.path("state").resolve()):
        raise ValueError("state checkpoint is outside the state directory")
    state: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return state


def recorded_spend(store: "RunStore") -> float:
    return sum(float(e["usd"]) for e in read_events(store.root) if e["event"] == "llm_call")
