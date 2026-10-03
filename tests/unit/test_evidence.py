import json
from pathlib import Path
from typing import Any

import pytest

from popper.communicate.evidence import evidence_rows, load_evidence


def _manifest(root: Path, *, scoped: bool = False) -> Path:
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
                "attempt_id": "permuted" if kind == "adversarial" else None,
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
    if scoped:
        for node in nodes:
            node["stage_instance"] = f"h001-s001-{node['stage']}"
            node["seed_node"] = "baseline-000"
    for name in ("hypothesis.json", "schedule.json", "results.json"):
        (root / name).write_text("{}")
    (root / "schedule.json").write_text(
        json.dumps(
            {
                "schedule": {
                    "attempts": [
                        {"id": "permuted", "kind": "adversarial", "result_key": "placebo_estimate"}
                    ]
                }
            }
        )
    )
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


@pytest.mark.parametrize("scoped", [False, True])
def test_all_successful_attempts_keep_equal_estimates_and_unique_keys(tmp_path: Path, scoped: bool) -> None:
    evidence = load_evidence(_manifest(tmp_path, scoped=scoped), tmp_path)
    assert evidence["format_version"] == 1
    assert evidence["stability"] == "fragile" and evidence["standing"] == "exploratory"
    assert evidence["selected"] == {"main": "main-000"}
    rows = evidence_rows(evidence, tmp_path)
    assert [row["id"] for row in rows] == ["main-000", "main-001", "robustness-002"]
    assert rows[-1]["adversarial"]
    assert rows[-1]["attempt_id"] == "permuted"
    assert rows[0]["value"] == 1.0 and rows[0]["ci"] == (0.5, 1.5)
    assert len({row["key"] for row in rows}) == 3
    (tmp_path / "main-001.json").write_text('{"primary_estimate":{"value":-2,"ci":[-3,-1],"n":21}}')
    updated = evidence_rows(evidence, tmp_path)
    assert updated[0]["id"] == "main-001" and updated[0]["value"] == -2


def test_evidence_rejects_escaped_reference_and_unknown_version(tmp_path: Path) -> None:
    root = tmp_path / "run"
    root.mkdir()
    (tmp_path / "outside.json").write_text("{}")
    path = _manifest(root)
    manifest = json.loads(path.read_text())
    for reference in ("../outside.json", str((root / "main-000.json").resolve())):
        manifest["nodes"][0]["results"] = reference
        path.write_text(json.dumps(manifest))
        with pytest.raises(ValueError, match="reference"):
            load_evidence(path, root)
    manifest["nodes"][0]["results"] = "main-000.json"
    manifest["format_version"] = 99
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="version"):
        load_evidence(path, root)


@pytest.mark.parametrize("scoped", [False, True])
def test_secondary_placebo_cannot_replace_primary_and_repair_keeps_identity(tmp_path: Path, scoped: bool) -> None:
    evidence = load_evidence(_manifest(tmp_path, scoped=scoped), tmp_path)
    primary = {"value": 2, "ci": [1, 3], "n": 20}
    placebo = {"value": 0, "ci": [-1, 1], "n": 20}
    (tmp_path / "main-000.json").write_text(
        json.dumps({"primary_estimate": primary, "placebo_estimate": placebo})
    )
    repaired = evidence["nodes"][2]
    repaired["kind"] = "debug"
    (tmp_path / repaired["results"]).write_text(
        json.dumps({"primary_estimate": primary, "placebo_estimate": placebo})
    )
    rows = {row["id"]: row for row in evidence_rows(evidence, tmp_path)}
    assert rows["main-000"]["value"] == 2 and not rows["main-000"]["adversarial"]
    assert rows["robustness-002"]["value"] == 0 and rows["robustness-002"]["adversarial"]
