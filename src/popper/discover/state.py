"""Deterministic scientific projection over immutable committed records."""

import json
import math
from typing import Any

from pydantic import Field

from popper.discover.contracts import (
    AcceptedMeasurement,
    Attempt,
    AttemptResult,
    Candidate,
    Diagnosis,
    Disposition,
    Invalidation,
    Question,
    Standing,
    SupportRule,
    commit_record,
)
from popper.harness.records import ArtifactRef, Record, resolve_artifact, resolve_measurement
from popper.harness.recovery import read_events
from popper.harness.results import ResultEntry
from popper.harness.session import Harness


class Sourced[T](Record):
    ref: ArtifactRef
    record: T


class ResearchState(Record):
    version: int = 1
    frontier: list[ArtifactRef] = Field(default_factory=list)
    candidates: list[Sourced[Candidate]] = Field(default_factory=list)
    attempts: list[Sourced[Attempt]] = Field(default_factory=list)
    results: list[Sourced[AttemptResult]] = Field(default_factory=list)
    observations: list[Sourced[AcceptedMeasurement]] = Field(default_factory=list)
    history: list[Sourced[AcceptedMeasurement]] = Field(default_factory=list)
    diagnoses: list[Sourced[Diagnosis]] = Field(default_factory=list)
    questions: list[Sourced[Question]] = Field(default_factory=list)
    dispositions: list[Sourced[Disposition]] = Field(default_factory=list)
    exposure: list[ArtifactRef] = Field(default_factory=list)
    budget: dict[str, float] = Field(default_factory=dict)
    counters: dict[str, int] = Field(default_factory=dict)


def compute_support(
    rule: SupportRule | None,
    result: ResultEntry | None,
    *,
    fidelity: str,
    rule_precedes_execution: bool,
) -> Standing:
    if rule is None or result is None or fidelity != "consistent" or result.ci is None:
        return "unavailable"
    lo, hi = result.ci
    if not all(math.isfinite(v) for v in (lo, hi)) or lo > hi:
        return "unavailable"
    if not rule_precedes_execution or rule.kind == "descriptive":
        return "post_hoc"
    if rule.kind == "directional_ci":
        assert rule.null is not None
        if rule.direction == "positive":
            return (
                "supported"
                if lo > rule.null
                else "not_supported"
                if hi < rule.null
                else "inconclusive"
            )
        return (
            "supported" if hi < rule.null else "not_supported" if lo > rule.null else "inconclusive"
        )
    assert rule.lower is not None and rule.upper is not None
    return (
        "supported"
        if rule.lower < lo <= hi < rule.upper
        else "not_supported"
        if hi < rule.lower or lo > rule.upper
        else "inconclusive"
    )


def validate_sources(h: Harness, value: Any) -> None:
    """Validate nested explicit references without interpreting scientific semantics."""
    if isinstance(value, dict):
        if {"path", "sha256", "producer", "record_id"} <= value.keys():
            resolve_artifact(h.run, ArtifactRef.model_validate(value))
        else:
            for item in value.values():
                validate_sources(h, item)
    elif isinstance(value, list):
        for item in value:
            validate_sources(h, item)


def scientific_commits(h: Harness) -> list[tuple[str, ArtifactRef]]:
    items = []
    for event in read_events(h.run.root):
        if event["event"] != "artifact_commit" or "record_id" not in event:
            continue
        name = str(event["name"])
        ref = ArtifactRef(
            path=event["path"],
            sha256=event["sha256"],
            producer=event.get("producer", name),
            record_id=event["record_id"],
        )
        items.append((name, ref))
    return items


def rebuild_state(h: Harness) -> ResearchState:
    frontier: list[ArtifactRef] = []
    candidates: list[Sourced[Candidate]] = []
    attempts: list[Sourced[Attempt]] = []
    results: list[Sourced[AttemptResult]] = []
    history: list[Sourced[AcceptedMeasurement]] = []
    seen_measurements: set[str] = set()
    diagnoses: list[Sourced[Diagnosis]] = []
    questions: list[Sourced[Question]] = []
    dispositions: list[Sourced[Disposition]] = []
    invalidated: set[str] = set()
    exposure: list[ArtifactRef] = []
    kinds = {
        "intent",
        "candidates",
        "attempt",
        "result",
        "diagnosis",
        "question",
        "invalidation",
        "disposition",
    }
    for name, ref in scientific_commits(h):
        kind = name.split(":")[1] if name.startswith("science:") else ""
        if kind not in kinds:
            continue
        path = resolve_artifact(h.run, ref)
        payload = json.loads(path.read_text("utf-8"))
        validate_sources(h, payload)
        frontier.append(ref)
        if kind == "candidates":
            candidates.extend(
                Sourced(ref=ref, record=Candidate.model_validate(c)) for c in payload["candidates"]
            )
            exposure = candidates[0].record.exposure if candidates else []
        elif kind == "attempt":
            attempts.append(Sourced(ref=ref, record=Attempt.model_validate(payload)))
        elif kind == "result":
            result = AttemptResult.model_validate(payload)
            results.append(Sourced(ref=ref, record=result))
            for measurement in result.measurements:
                resolve_measurement(h.run, measurement.ref)
                identity = measurement.ref.model_dump_json()
                if identity in seen_measurements:
                    continue
                seen_measurements.add(identity)
                history.append(Sourced(ref=ref, record=measurement))
        elif kind == "diagnosis":
            diagnoses.append(Sourced(ref=ref, record=Diagnosis.model_validate(payload)))
        elif kind == "question":
            questions.append(Sourced(ref=ref, record=Question.model_validate(payload)))
        elif kind == "disposition":
            dispositions.append(Sourced(ref=ref, record=Disposition.model_validate(payload)))
        elif kind == "invalidation":
            invalidation = Invalidation.model_validate(payload)
            invalidated.update(r.model_dump_json() for r in invalidation.measurements)
    observations = [
        m
        for m in history
        if m.record.fidelity.status == "consistent"
        and m.record.ref.model_dump_json() not in invalidated
    ]
    counters = {"moves": len(attempts)}
    for attempt in attempts:
        key = attempt.record.hypothesis_id
        counters[key] = counters.get(key, 0) + 1
    return ResearchState(
        frontier=frontier,
        candidates=candidates,
        attempts=attempts,
        results=results,
        observations=observations,
        history=history,
        diagnoses=diagnoses,
        questions=questions,
        dispositions=dispositions,
        exposure=exposure,
        budget={"spent_usd": h.spent_usd, "max_usd": h.config.budget.max_usd},
        counters=counters,
    )


def commit_snapshot(h: Harness, state: ResearchState) -> ArtifactRef:
    return commit_record(h, "snapshot", state)


def compact_state(state: ResearchState, max_chars: int = 16000) -> dict[str, Any]:
    view = state.model_dump(mode="json")
    omitted: list[dict[str, Any]] = []
    for key in ("history", "results", "candidates", "observations", "diagnoses", "questions"):
        if len(json.dumps(view)) <= max_chars:
            break
        entries = view[key]
        omitted.extend(entry["ref"] for entry in entries)
        view[key] = [
            {"ref": entry["ref"], "contents": "omitted; retrieve with read_artifact"}
            for entry in entries
        ]
    view["omitted_refs"] = omitted
    return view
