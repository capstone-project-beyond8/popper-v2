"""Resolve experiment artifacts and plot every successful recorded attempt."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from popper.harness.results import ResultEntry
from popper.harness.session import Harness


def artifact_path(root: Path, reference: str) -> Path:
    path = (root / reference).resolve()
    if (
        Path(reference).is_absolute()
        or not path.is_relative_to(root.resolve())
        or not path.is_file()
    ):
        raise ValueError(f"invalid evidence reference: {reference}")
    return path


def load_evidence(path: Path, run_root: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = json.loads(path.read_text("utf-8"))
    if evidence.get("format_version") != 1:
        raise ValueError("unsupported evidence version")
    if evidence.get("standing") != "exploratory" or evidence.get("stability") not in (
        "stable",
        "fragile",
    ):
        raise ValueError("invalid computed evidence labels")
    for key in ("hypothesis", "plan", "summary"):
        artifact_path(run_root, evidence[key])
    identities = set()
    for node in evidence["nodes"]:
        if (
            node["id"] in identities
            or node["stage"] not in ("baseline", "main", "robustness")
            or node["status"] not in ("ok", "buggy")
        ):
            raise ValueError("invalid experiment node identity or status")
        identities.add(node["id"])
        for key in ("results", "code", "analysis"):
            if node.get(key):
                artifact_path(run_root, node[key])
        if node["status"] == "ok" and not node.get("results"):
            raise ValueError("successful experiment lacks results reference")
        for figure in node["figures"]:
            artifact_path(run_root, figure)
    if any(identity not in identities for identity in evidence["selected"].values()):
        raise ValueError("selected experiment is absent from evidence")
    return evidence


def evidence_rows(evidence: Mapping[str, Any], run_root: Path) -> list[dict[str, Any]]:
    schedule = json.loads(artifact_path(run_root, evidence["plan"]).read_text("utf-8"))["schedule"]
    specifications = {item["id"]: item for item in schedule["attempts"]}
    rows = []
    for order, node in enumerate(evidence["nodes"]):
        if node["status"] != "ok":
            continue
        specification = (
            specifications[node["attempt_id"]] if node["stage"] == "robustness" else None
        )
        adversarial = specification is not None and specification["kind"] == "adversarial"
        result_key = specification["result_key"] if specification else "primary_estimate"
        results = json.loads(artifact_path(run_root, node["results"]).read_text("utf-8"))
        entry = ResultEntry.model_validate_json(json.dumps(results[result_key]))
        if not isinstance(entry.value, (int, float)) or entry.ci is None or entry.n is None:
            raise ValueError("experiment result is missing its estimate, interval or sample size")
        rows.append(
            {
                **node,
                "key": f"{node['id']}.{result_key}",
                "result_key": result_key,
                "value": entry.value,
                "ci": entry.ci,
                "n": entry.n,
                "adversarial": adversarial,
                "order": order,
            }
        )
    return sorted(rows, key=lambda row: (row["value"], row["order"]))


_CURVE_CODE = """
import json, os
import matplotlib.pyplot as plt
rows = json.load(open(os.environ['POPPER_INPUT_INDEX']))
fig, ax = plt.subplots(figsize=(8, max(3, len(rows) * .4)))
for i, row in enumerate(rows):
    entry = json.load(open(os.environ['POPPER_INPUT_' + row['input'].upper()]))[row['result_key']]
    lo, hi = entry['ci']
    color = 'darkorange' if row['adversarial'] else 'steelblue'
    ax.plot([lo, hi], [i, i], color=color)
    ax.scatter([entry['value']], [i], color=color, marker='x' if row['adversarial'] else 'o')
ax.set_yticks(range(len(rows)), [row['id'] + (' [placebo]' if row['adversarial'] else '') for row in rows])
ax.axvline(0, color='grey', linestyle='--')
ax.set_xlabel('Primary contrast; placebo marked separately')
ax.set_title('All successful experiment attempts and reported intervals')
fig.tight_layout(); fig.savefig('curve.png', dpi=140)
"""


def render_curve(h: Harness, rows: Sequence[Mapping[str, Any]], report_dir: Path) -> Path:
    prefix = report_dir.relative_to(h.run.root).as_posix()
    inputs = {f"r{i}": artifact_path(h.run.root, row["results"]) for i, row in enumerate(rows)}
    index = h.run.write_json(
        f"{prefix}/curve-input.json",
        [
            {
                "input": f"r{i}",
                "id": row["id"],
                "result_key": row["result_key"],
                "adversarial": row["adversarial"],
            }
            for i, row in enumerate(rows)
        ],
    )
    result = h.execute(
        _CURVE_CODE,
        report_dir / "curve",
        inputs={**inputs, "index": index},
        node="publication-curve",
        purpose="plot",
    )
    if result.exit_code != 0 or result.timed_out:
        raise ValueError(f"specification curve failed: {result.stderr}")
    return report_dir / "curve" / "curve.png"
