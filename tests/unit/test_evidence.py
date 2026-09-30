import json
from pathlib import Path
from typing import Any

import pytest

from popper.communicate.evidence import evidence_rows, load_evidence


def _manifest(root: Path) -> Path:
    nodes: list[dict[str, Any]] = []
    for i, (stage, kind) in enumerate(
        (("main", "draft"), ("main", "improve"), ("robustness", "adversarial"))
    ):
        node_id = f"{stage}-{i:03d}"
        result = root / f"{node_id}.json"
        result.write_text(
            json.dumps(
                {
                    ("placebo_estimate" if kind == "adversarial" else "primary_estimate"): {
                        "value": 1.0,
                        "ci": [0.5, 1.5],
                        "n": 20,
                    }
                }
            )
        )
        nodes.append(
            {
                "id": node_id,
                "stage": stage,
                "kind": kind,
                "attempt_id": None,
                "status": "ok",
                "results": result.name,
                "code": None,
                "analysis": None,
                "figures": [],
            }
        )
    nodes.append(
        {
            "id": "robustness-003",
            "stage": "robustness",
            "kind": "debug",
            "attempt_id": "placebo",
            "status": "buggy",
            "results": None,
            "code": None,
            "analysis": None,
            "figures": [],
        }
    )
    for name in ("hypothesis.json", "schedule.json", "results.json"):
        (root / name).write_text("{}")
    path = root / "evidence.json"
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "nodes": nodes,
                "selected": {"main": "main-000"},
                "hypothesis": "hypothesis.json",
                "plan": "schedule.json",
                "summary": "results.json",
                "standing": "exploratory",
                "stability": "fragile",
                "reasons": ["failed"],
                "specifications": [{"id": "untried", "node": None}],
            }
        )
    )
    return path


def test_all_successful_attempts_keep_equal_estimates_and_unique_keys(tmp_path: Path) -> None:
    evidence = load_evidence(_manifest(tmp_path), tmp_path)
    rows = evidence_rows(evidence, tmp_path)
    assert [row["id"] for row in rows] == ["main-000", "main-001", "robustness-002"]
    assert rows[-1]["adversarial"]
    assert len({row["key"] for row in rows}) == 3
    (tmp_path / "main-001.json").write_text('{"primary_estimate":{"value":-2,"ci":[-3,-1],"n":21}}')
    updated = evidence_rows(evidence, tmp_path)
    assert updated[0]["id"] == "main-001" and updated[0]["value"] == -2


def test_evidence_rejects_escaped_reference_and_unknown_version(tmp_path: Path) -> None:
    path = _manifest(tmp_path)
    manifest = json.loads(path.read_text())
    manifest["nodes"][0]["results"] = "../outside.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="reference"):
        load_evidence(path, tmp_path)
    manifest["format_version"] = 99
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="version"):
        load_evidence(path, tmp_path)
