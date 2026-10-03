"""Dispatch admitted experiment requests to the execution capability."""

import json

from popper.harness.session import Harness
from popper.harness.storage.records import IntegrityError, resolve_artifact
from popper.scientific.runtime.compatibility import decode_policy
from popper.scientific.runtime.data.research import render_fields
from popper.scientific.runtime.lifecycle.contracts import Attempt
from popper.scientific.runtime.lifecycle.requests import CapabilityRequest, ExperimentRequest
from popper.scientific.runtime.lifecycle.transitions import (
    EligibilityError,
    schedule_attempt,
    selected_move,
)
from popper.scientific.runtime.projections.state import rebuild_state
from popper.scientific.runtime.projections.views import (
    foundation_view,
    reviewed_frame,
    validate_intent_inputs,
)
from popper.scientific.runtime.settings import load_options
from popper.scientific.runtime.store import ScienceStore
from popper.scientific.scientist.episode import unavailable
from popper.stages.discover.candidates import generate_candidates, propose_hypothesis
from popper.stages.discover.challenge import challenge_candidates
from popper.stages.discover.experiment import experiment
from popper.workflow.resources import admit_move, resource_view


def dispatch_discovery(h: Harness, request: CapabilityRequest) -> CapabilityRequest | None:
    if request.kind not in {"candidates", "challenge", "experiment"}:
        raise ValueError("request is not a Discover capability")
    science = ScienceStore(h.run)
    assert request.subject is not None
    resolve_artifact(h.run, request.subject)
    if request.schedule:
        resolve_artifact(h.run, request.schedule)
    if request.strategy == "adaptive":
        if h.run.committed("science:intent:initial") is None:
            raise IntegrityError("adaptive dispatch requires a committed intent")
        intent = h.run.artifact_ref("science:intent:initial")
        validate_intent_inputs(science, intent)
        if request.kind == "candidates" and request.subject != intent:
            raise IntegrityError("candidate request subject differs from committed intent")
    if request.kind == "candidates":
        if request.strategy == "historical":
            propose_hypothesis(h, science, request.subject)
        else:
            policy = decode_policy(json.loads(h.run.path("run.json").read_text("utf-8")))
            generate_candidates(h, science, request.subject, policy)
        return None
    if request.kind == "challenge":
        assert request.snapshot is not None
        challenge_candidates(h, science, request.subject, request.snapshot)
        return None
    if request.strategy == "historical":
        frame, prepared = reviewed_frame(science), foundation_view(science)
        hypothesis = json.loads(h.run.path(request.subject.path).read_text("utf-8"))[0]
        experiment(
            h,
            frame.framing,
            hypothesis,
            prepared.preparation,
            frame.research.notes.get("experiment", ""),
            render_fields(frame.research, "design"),
            plan=h.run.path(request.schedule.path) if request.schedule else None,
            implementation_only=request.implementation_only,
        )
        return None
    state = rebuild_state(science)
    subject = request.subject
    if request.selection:
        move = selected_move(science, request.selection)
        if move.test != request.subject:
            raise IntegrityError("request subject differs from the selected test")
        try:
            admit_move(resource_view(h, load_options(h.run), state), state, move)
            parent = next(
                (
                    a.ref
                    for a in reversed(state.attempts)
                    if a.record.hypothesis_id == move.hypothesis_id
                ),
                None,
            )
            subject = schedule_attempt(science, move, parent)
        except EligibilityError as exc:
            return unavailable(science, request, str(exc))
        state = rebuild_state(science)
    frame, prepared = reviewed_frame(science), foundation_view(science)
    attempt = Attempt.model_validate(science.read(subject))
    hypothesis = next(c.record for c in state.candidates if c.record.id == attempt.hypothesis_id)
    experiment(
        h,
        frame.framing,
        hypothesis.model_dump(mode="json"),
        prepared.preparation,
        frame.research.notes.get("experiment", ""),
        render_fields(frame.research, "design"),
        request=ExperimentRequest(attempt.test, subject),
    )

    return None
