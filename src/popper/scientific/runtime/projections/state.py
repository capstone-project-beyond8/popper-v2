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
    StageAdmission,
    StageWork,
    Synthesis,
)
from popper.scientific.runtime.lifecycle.ideas import IdeaChallenge, IdeaRevision, ResearchDirection
from popper.scientific.runtime.store import ScienceStore


class Sourced[T](Record):
    ref: ArtifactRef
    record: T


class ResearchState(Record):
    version: Literal[4] = 4
    stage_admissions: list[Sourced[StageAdmission]] = Field(default_factory=list)
    stage_history: list[Sourced[StageWork]] = Field(default_factory=list)
    pending_admissions: list[Sourced[StageAdmission]] = Field(default_factory=list)
    syntheses: list[Sourced[Synthesis]] = Field(default_factory=list)
    frontier: list[ArtifactRef] = Field(default_factory=list)
    candidates: list[Sourced[Candidate]] = Field(default_factory=list)
    challenges: list[Sourced[Challenge]] = Field(default_factory=list)
    ideas: list[Sourced[IdeaRevision]] = Field(default_factory=list)
    idea_challenges: list[Sourced[IdeaChallenge]] = Field(default_factory=list)
    directions: list[Sourced[ResearchDirection]] = Field(default_factory=list)
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
    admissions: list[Sourced[StageAdmission]] = []
    work: list[Sourced[StageWork]] = []
    syntheses: list[Sourced[Synthesis]] = []
    ideas: list[Sourced[IdeaRevision]] = []
    idea_challenges: list[Sourced[IdeaChallenge]] = []
    directions: list[Sourced[ResearchDirection]] = []
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
        "admission",
        "work",
        "synthesis",
        "audit",
        "idea",
        "idea_challenge",
        "direction",
    }
    for name, ref in science.commits():
        kind = name.split(":")[1] if name.startswith("science:") else ""
        if kind not in kinds:
            continue
        path = resolve_artifact(science.run, ref)
        payload = json.loads(path.read_text("utf-8"))
        validate_sources(science, payload)
        if kind != "admission":
            frontier.append(ref)
        if kind == "admission":
            admissions.append(Sourced(ref=ref, record=StageAdmission.model_validate(payload)))
        elif kind == "work":
            work.append(Sourced(ref=ref, record=StageWork.model_validate(payload)))
        elif kind == "synthesis":
            synthesis = Synthesis.model_validate(payload)
            syntheses.append(Sourced(ref=ref, record=synthesis))
            questions.extend(Sourced(ref=ref, record=Question(text=text, author=synthesis.author, sources=synthesis.sources)) for text in synthesis.questions)
        elif kind == "candidates":
            added: list[Sourced[Candidate]] = [Sourced(ref=ref, record=Candidate.model_validate(c)) for c in payload["candidates"]]
            candidates.extend(added)
            exposure = list(dict.fromkeys([*exposure, *(r for c in added for r in c.record.exposure)]))
        elif kind == "idea":
            ideas.append(Sourced(ref=ref, record=IdeaRevision.model_validate(payload)))
        elif kind == "idea_challenge":
            idea_challenges.append(Sourced(ref=ref, record=IdeaChallenge.model_validate(payload)))
        elif kind == "direction":
            directions.append(Sourced(ref=ref, record=ResearchDirection.model_validate(payload)))
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
        stage_admissions=admissions,
        syntheses=syntheses,
        stage_history=work,
        pending_admissions=[a for a in admissions if not any(w.record.admission == a.ref for w in work)],
        frontier=frontier,
        candidates=candidates,
        challenges=challenges,
        ideas=ideas,
        idea_challenges=idea_challenges,
        directions=directions,
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
    for key in ("stage_admissions", "pending_admissions"):
        view[key] = [{"ref": item.ref.model_dump(mode="json"), "record": {"id": item.record.id, "stage": item.record.stage, "move": item.record.move.model_dump(mode="json")}}
                     for item in getattr(state, key)]
    omitted: list[dict[str, Any]] = []
    for key in (
        "history",
        "results",
        "candidates",
        "observations",
        "diagnoses",
        "questions",
        "challenges",
        "ideas",
        "idea_challenges",
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
    return ResearchState.model_validate(science.read(ref))


def current_frontier(
    science: ScienceStore, snapshot: ArtifactRef, frontier: list[ArtifactRef]
) -> bool:
    return load_snapshot(science, snapshot).frontier == frontier


def pending_selection(science: ScienceStore, state: ResearchState) -> ArtifactRef | None:
    used = {attempt.record.move_id for attempt in state.attempts}
    used.update(science.read(a.record.move)["id"] for a in state.stage_admissions)
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
