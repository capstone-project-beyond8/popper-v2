"""Scientific identity and transition contracts."""

import json

from popper.harness.records import ArtifactRef, resolve_artifact
from popper.science.contracts import MoveSelection, ResearchMove
from popper.science.store import ScienceStore


def selected_move(science: ScienceStore, selection: ArtifactRef) -> ResearchMove:
    choice = MoveSelection.model_validate_json(
        resolve_artifact(science.run, selection).read_text("utf-8")
    )
    data = json.loads(resolve_artifact(science.run, choice.proposals).read_text("utf-8"))
    return next(
        ResearchMove.model_validate(m) for m in data["moves"] if m["id"] == choice.proposal_id
    )


