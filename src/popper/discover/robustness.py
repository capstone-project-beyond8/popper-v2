"""Select code implementations within exact historical specification instances."""

from pathlib import Path
from typing import Any

from popper.harness.session import Harness
from popper.science.historical import collect_historical_evidence, load_robustness_plan
from popper.science.settings import load_options
from popper.science.store import ScienceStore
from popper.science.views import node_ref
from popper.treesearch.engine import Node, load_nodes, select_best


def collect_evidence(
    h: Harness, hypothesis: dict[str, Any], selected: dict[str, Node], plan: Path
) -> Path:
    science = ScienceStore(h.run)
    policy = load_options(h.run).robustness
    schedule = load_robustness_plan(plan, h.config.search, policy)
    nodes = [
        n
        for stage in ("baseline", "main", "robustness")
        for n in load_nodes(h, stage, include_abandoned=True)
    ]
    representatives = {
        a.id: select_best([n for n in nodes if n.attempt_id == a.id]) for a in schedule.attempts
    }
    return collect_historical_evidence(
        science,
        hypothesis,
        {stage: node_ref(science, n.dir / "meta.json") for stage, n in selected.items()},
        h.run.artifact_ref("robustness_plan"),
        {
            key: node_ref(science, n.dir / "meta.json") if n else None
            for key, n in representatives.items()
        },
        [node_ref(science, n.dir / "meta.json") for n in nodes],
        h.config.search,
        policy,
    )
