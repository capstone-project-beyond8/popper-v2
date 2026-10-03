"""Deterministic scientific projection over immutable committed records."""

import json
from typing import Any, Literal

from pydantic import Field

from popper.harness.storage.records import ArtifactRef, Record, resolve_artifact
from popper.scientific.runtime.evidence.references import resolve_measurement
from popper.scientific.runtime.lifecycle.contracts import (
    AcceptedMeasurement,
    Attempt,
    AttemptResult,
    Candidate,
    Challenge,
    Diagnosis,
    Disposition,
    Interpretation,
    Invalidation,
    MoveSelection,
    Question,
)
from popper.scientific.runtime.store import ScienceStore


class Sourced[T](Record):
    ref: ArtifactRef
    record: T


class ResearchState(Record):
    version: Literal[2] = 2
    frontier: list[ArtifactRef] = Field(default_factory=list)
    candidates: list[Sourced[Candidate]] = Field(default_factory=list)
    challenges: list[Sourced[Challenge]] = Field(default_factory=list)
    interpretations: list[Sourced[Interpretation]] = Field(default_factory=list)
    stale_interpretations: list[ArtifactRef] = Field(default_factory=list)
    attempts: list[Sourced[Attempt]] = Field(default_factory=list)
    results: list[Sourced[AttemptResult]] = Field(default_factory=list)
    observations: list[Sourced[AcceptedMeasurement]] = Field(default_factory=list)
    history: list[Sourced[AcceptedMeasurement]] = Field(default_factory=list)
    diagnoses: list[Sourced[Diagnosis]] = Field(default_factory=list)
    questions: list[Sourced[Question]] = Field(default_factory=list)
    dispositions: list[Sourced[Disposition]] = Field(default_factory=list)
    exposure: list[ArtifactRef] = Field(default_factory=list)
    counters: dict[str, int] = Field(default_factory=dict)


def validate_sources(science: ScienceStore, value: Any) -> None:
    """Validate nested explicit references without interpreting scientific semantics."""
    if isinstance(value, dict):
        if {"path", "sha256", "producer", "record_id"} <= value.keys():
            resolve_artifact(science.run, ArtifactRef.model_validate(value))
        else:
            for item in value.values():
                validate_sources(science, item)
    elif isinstance(value, list):
        for item in value:
            validate_sources(science, item)


def rebuild_state(science: ScienceStore) -> ResearchState:
    frontier: list[ArtifactRef] = []
    candidates: list[Sourced[Candidate]] = []
    challenges: list[Sourced[Challenge]] = []
    interpretations: list[Sourced[Interpretation]] = []
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
        "challenge",
        "interpretation",
        "attempt",
        "result",
        "diagnosis",
        "question",
        "invalidation",
        "disposition",
    }
    for name, ref in science.commits():
        kind = name.split(":")[1] if name.startswith("science:") else ""
        if kind not in kinds:
            continue
        path = resolve_artifact(science.run, ref)
        payload = json.loads(path.read_text("utf-8"))
        validate_sources(science, payload)
        frontier.append(ref)
        if kind == "candidates":
            candidates.extend(
                Sourced(ref=ref, record=Candidate.model_validate(c)) for c in payload["candidates"]
            )
            exposure = candidates[0].record.exposure if candidates else []
        elif kind == "attempt":
            attempts.append(Sourced(ref=ref, record=Attempt.model_validate(payload)))
        elif kind == "challenge":
            challenges.append(Sourced(ref=ref, record=Challenge.model_validate(payload)))
        elif kind == "interpretation":
            interpretations.append(Sourced(ref=ref, record=Interpretation.model_validate(payload)))
        elif kind == "result":
            result = AttemptResult.model_validate(payload)
            results.append(Sourced(ref=ref, record=result))
            for measurement in result.measurements:
                resolve_measurement(science.run, measurement.ref)
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
    stale_sources = {
        result.ref
        for result in results
        if any(m.ref.model_dump_json() in invalidated for m in result.record.measurements)
    }
    stale_sources.update(
        m.record.ref.artifact for m in history if m.record.ref.model_dump_json() in invalidated
    )
    stale_interpretations = []
    for interpretation in interpretations:
        if any(source in stale_sources for source in interpretation.record.sources):
            stale_interpretations.append(interpretation.ref)
            stale_sources.add(interpretation.ref)
        else:
            questions.extend(
                Sourced(
                    ref=interpretation.ref,
                    record=Question(
                        hypothesis_id=interpretation.record.hypothesis_id,
                        text=text,
                        author=interpretation.record.author,
                        sources=interpretation.record.sources,
                    ),
                )
                for text in interpretation.record.questions
            )
    counters = {"moves": len(attempts)}
    for attempt in attempts:
        key = attempt.record.hypothesis_id
        counters[key] = counters.get(key, 0) + 1
    return ResearchState(
        frontier=frontier,
        candidates=candidates,
        challenges=challenges,
        interpretations=interpretations,
        stale_interpretations=stale_interpretations,
        attempts=attempts,
        results=results,
        observations=observations,
        history=history,
        diagnoses=diagnoses,
        questions=questions,
        dispositions=dispositions,
        exposure=exposure,
        counters=counters,
    )


def commit_snapshot(science: ScienceStore, state: ResearchState) -> ArtifactRef:
    return science.commit("snapshot", state)


def compact_state(state: ResearchState, max_chars: int = 16000) -> dict[str, Any]:
    view = state.model_dump(mode="json")
    omitted: list[dict[str, Any]] = []
    for key in (
        "history",
        "results",
        "candidates",
        "observations",
        "diagnoses",
        "questions",
        "challenges",
        "interpretations",
    ):
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


def load_snapshot(science: ScienceStore, ref: ArtifactRef) -> ResearchState:
    payload = science.read(ref)
    version = payload.get("version", 1)
    if version == 1:
        payload.pop("budget", None)
        payload["version"] = 2
    elif version != 2:
        raise ValueError(f"unsupported scientific snapshot version: {version!r}")
    return ResearchState.model_validate(payload)


def current_frontier(
    science: ScienceStore, snapshot: ArtifactRef, frontier: list[ArtifactRef]
) -> bool:
    return load_snapshot(science, snapshot).frontier == frontier


def pending_selection(science: ScienceStore, state: ResearchState) -> ArtifactRef | None:
    used = {attempt.record.move_id for attempt in state.attempts}
    for name, ref in reversed(science.commits()):
        if name.startswith("science:selection:"):
            selection = MoveSelection.model_validate(science.read(ref))
            if selection.proposal_id not in used and current_frontier(science, selection.snapshot, state.frontier):
                return ref
    return None


def pending_proposal(science: ScienceStore, state: ResearchState) -> tuple[ArtifactRef, ArtifactRef] | None:
    commits = science.commits()
    selected = [
        MoveSelection.model_validate(science.read(ref)).proposals
        for name, ref in commits if name.startswith("science:selection:")
    ]
    for name, ref in reversed(commits):
        if name.startswith("science:proposals:") and ref not in selected:
            proposal = science.read(ref)
            snapshot = ArtifactRef.model_validate(proposal["snapshot"])
            if current_frontier(science, snapshot, state.frontier):
                return ref, snapshot
    return None
