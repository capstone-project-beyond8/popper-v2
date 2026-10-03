"""Dispatch admitted experiment requests to the execution capability."""

import json

from popper.coordinator.resources import admit_move, resource_view
from popper.discover.experiment import experiment
from popper.harness.records import IntegrityError, resolve_artifact
from popper.harness.session import Harness
from popper.science.contracts import Attempt
from popper.science.requests import CapabilityRequest, ExperimentRequest
from popper.science.research import render_fields
from popper.science.settings import load_options
from popper.science.state import rebuild_state
from popper.science.store import ScienceStore
from popper.science.transitions import EligibilityError, schedule_attempt, selected_move
from popper.science.views import foundation_view, reviewed_frame
from popper.scientist.episode import unavailable


def dispatch_experiment(h: Harness, request: CapabilityRequest) -> CapabilityRequest | None:
    science = ScienceStore(h.run)
    assert request.subject is not None
    resolve_artifact(h.run, request.subject)
    if request.schedule:
        resolve_artifact(h.run, request.schedule)
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
