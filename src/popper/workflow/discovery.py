"""Dispatch admitted experiment requests to the execution capability."""

from popper.harness.session import BudgetExceeded, Harness
from popper.harness.storage.records import IntegrityError, resolve_artifact
from popper.scientific.runtime.data.research import render_fields
from popper.scientific.runtime.lifecycle.contracts import Attempt
from popper.scientific.runtime.lifecycle.requests import CapabilityRequest, ExperimentRequest
from popper.scientific.runtime.lifecycle.transitions import (
    EligibilityError,
    bind_stage_output,
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
from popper.stages.discover.candidates import generate_candidates
from popper.stages.discover.challenge import challenge_candidates
from popper.stages.discover.experiment import experiment
from popper.workflow.resources import admit_move, resource_view


def dispatch_discovery(h: Harness, request: CapabilityRequest) -> CapabilityRequest | None:
    if request.kind not in {"candidates", "challenge", "experiment"}:
        raise ValueError("request is not a Discover capability")
    science = ScienceStore(h.run)
    assert request.subject is not None
    resolve_artifact(h.run, request.subject)
    if h.run.committed("science:intent:initial") is None:
        raise IntegrityError("discovery dispatch requires a committed intent")
    intent = h.run.artifact_ref("science:intent:initial")
    validate_intent_inputs(science, intent)
    if request.kind == "candidates" and request.subject != intent:
        raise IntegrityError("candidate request subject differs from committed intent")
    if request.kind == "candidates":
        output = generate_candidates(h, science, request.subject, admission=request.admission)
        if request.admission:
            bind_stage_output(science, request.admission, [output])
        return None
    if request.kind == "challenge":
        assert request.snapshot is not None
        challenge_output = challenge_candidates(h, science, request.subject, request.snapshot, admission=request.admission)
        if challenge_output and request.admission:
            bind_stage_output(science, request.admission, [challenge_output])
        return None
    state = rebuild_state(science)
    subject = request.subject
    if request.selection:
        move = selected_move(science, request.selection)
        if move.test != request.subject:
            raise IntegrityError("request subject differs from the selected test")
        try:
            if request.admission is None:
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
        except (EligibilityError, BudgetExceeded) as exc:
            return unavailable(science, request, str(exc))
        state = rebuild_state(science)
    frame, prepared = reviewed_frame(science), foundation_view(science)
    attempt = Attempt.model_validate(science.read(subject))
    hypothesis = next(c.record for c in state.candidates if c.record.id == attempt.hypothesis_id)
    output_path = experiment(
        h,
        frame.framing,
        hypothesis.model_dump(mode="json"),
        prepared.preparation,
        frame.research.notes.get("experiment", ""),
        render_fields(frame.research, "design"),
        request=ExperimentRequest(attempt.test, subject, request.admission),
    )
    if request.admission:
        output = h.run.artifact_ref(f"science:result:{attempt.id}")
        if resolve_artifact(h.run, output) != output_path:
            raise IntegrityError("experiment output differs from its accepted result")
        bind_stage_output(science, request.admission, [output])

    return None
