"""Summarize recorded run costs and session behavior without provider calls."""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import JsonValue, TypeAdapter

from popper.harness.storage.recovery import load_state, read_events
from popper.harness.storage.store import RunStore
from popper.scientific.runtime.data.inputs import require_current_format
from popper.scientific.runtime.projections.output import episode_summary
from popper.scientific.runtime.store import ScienceStore

_TOKENS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")


def _totals(calls: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, Any] = {key: sum(c.get(key, 0) for c in calls) for key in _TOKENS}
    totals.update(calls=len(calls), usd=round(sum(c.get("usd", 0) for c in calls), 10))
    denominator = sum(totals[key] for key in _TOKENS if key != "output_tokens")
    totals["cache_read_ratio"] = totals["cache_read_tokens"] / denominator if denominator else 0
    return totals


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure aggregation. Legacy session boundaries are estimates, explicitly labeled."""
    calls: list[dict[str, Any]] = []
    groups: dict[str, dict[str, list[dict[str, Any]]]] = {
        key: defaultdict(list) for key in ("roles", "tags", "phases", "sessions")
    }
    submits: dict[str, dict[str, int]] = defaultdict(
        lambda: {"accepted_submits": 0, "rejected_submits": 0}
    )
    errors = {"avoidable": 0, "code": 0, "other": 0}
    inferred: set[str] = set()
    active: dict[str, str] = {}
    phase = "unknown"
    phase_costs: dict[str, float] = {}
    cumulative = 0.0
    for event in events:
        kind, tag = event["event"], str(event.get("tag", "unknown"))
        if kind == "phase":
            phase = str(event["name"])
        elif kind == "llm_call":
            session = event.get("session")
            if session is None:
                if tag not in active or event.get("input_tokens", 0) <= 1:
                    active[tag] = f"inferred:{tag}:{len(inferred)}"
                    inferred.add(active[tag])
                session = active[tag]
            active[tag] = str(session)
            calls.append(event)
            cumulative += event.get("usd", 0)
            phase_costs[phase] = round(cumulative, 10)
            for group, key in (
                ("roles", event.get("role", "unknown")),
                ("tags", tag),
                ("phases", phase),
                ("sessions", session),
            ):
                groups[group][str(key)].append(event)
        elif kind == "tool_call":
            if event.get("status") == "skipped":
                continue
            tool = event["tool"]
            session = str(event.get("session", active.get(tag, f"unknown:{tag}")))
            if event.get("terminal") or tool in {"submit", "submit_frame", "submit_ground"}:
                key = "rejected_submits" if event.get("status") == "error" else "accepted_submits"
                submits[session][key] += 1
            else:
                result = str(event.get("result", "")).lower()
                avoidable = tool in {"read_artifact", "view_figure"} and any(
                    s in result for s in ("does not exist", "no such file", "not found")
                )
                avoidable |= tool == "ask_researcher" and "no researcher" in result
                category = "avoidable" if avoidable else "code" if tool == "run_python" else "other"
                if avoidable or event.get("status") == "error":
                    errors[category] += 1
    report = {
        group: {key: _totals(value) for key, value in values.items()}
        for group, values in groups.items()
    }
    for session in report["sessions"].keys() | submits.keys():
        record = report["sessions"].setdefault(session, _totals([]))
        record.update(submits[session], inferred=session in inferred)
        session_calls = groups["sessions"].get(session, [])
        if session_calls:
            record.update(role=session_calls[0].get("role"), tag=session_calls[0].get("tag"))
    for name, value in report["phases"].items():
        value["cumulative_usd"] = phase_costs[name]
    return {
        **report,
        "total": _totals(calls),
        "tool_errors": errors,
        "context_cuts": [e for e in events if e["event"] == "context_cut"],
    }


def scientific_trace(run: RunStore) -> dict[str, JsonValue]:
    require_current_format(json.loads(run.path("run.json").read_text("utf-8")))
    return TypeAdapter(dict[str, JsonValue]).validate_python(episode_summary(ScienceStore(run)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    args = parser.parse_args(argv)
    for root in args.runs:
        store = RunStore(root)
        report = summarize(read_events(store.root))
        report.update(run=str(store.root), status=load_state(store).get("status", "unknown"))
        report["scientific"] = scientific_trace(store)
        print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
