"""Idea evolution: revising, challenging and promoting scientific ideas."""

from popper.harness.session import Harness
from popper.harness.storage.records import ArtifactRef
from popper.scientific.runtime.lifecycle.transitions import EligibilityError
from popper.scientific.runtime.store import ScienceStore


def evolve_ideas(h: Harness, science: ScienceStore, admission: ArtifactRef) -> list[ArtifactRef]:
    """Run one admitted idea round and return the committed idea records it produced."""
    raise EligibilityError("idea evolution is unavailable")
