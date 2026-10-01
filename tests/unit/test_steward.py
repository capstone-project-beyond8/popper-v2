import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from pydantic import ValidationError

from popper.ground.steward import Concern, Operationalization, check_submission, readiness
from popper.harness.descriptive import DescriptiveReport
from popper.harness.research import ResearchContext

IDA = DescriptiveReport({"c000_mean": {"value": 1.0}}, {})
MAPPING = [
    Operationalization(
        concept_id="effort", columns=["hours"], proxy_strength="direct", rationale="r"
    )
]
RESULTS: dict[str, Any] = {
    "rows_before": {"value": 3},
    "rows_after": {"value": 2},
    "rows_removed": {"value": 1},
}
CHANGES: list[dict[str, Any]] = [
    {"step": "drop", "rows_affected": "rows_removed", "reason": "invalid"}
]


def _research(outcome_status: str = "confirmed") -> ResearchContext:
    outcome: dict[str, Any] = {"value": "outcome", "status": outcome_status, "evidence": ["q"]}
    return ResearchContext.model_validate(
        {
            "body": "body",
            "variables": {
                "score": {"role": outcome},
                "hours": {"role": "exposure"},
            },
            "concepts": [{"id": "effort"}],
        }
    )


def _run(
    tmp_path: Path,
    *,
    frame: pd.DataFrame | None = None,
    results: dict[str, Any] = RESULTS,
    changes: Any = CHANGES,
    research: ResearchContext | None = None,
    mapping: list[Operationalization] = MAPPING,
    concerns: tuple[Concern, ...] = (),
) -> str | None:
    table = frame if frame is not None else pd.DataFrame({"score": [1, 2], "hours": [3, 4]})
    table.to_parquet(tmp_path / "processed.parquet")
    (tmp_path / "results.json").write_text(json.dumps(results), encoding="utf-8")
    (tmp_path / "changes.json").write_text(json.dumps(changes), encoding="utf-8")
    return check_submission(tmp_path, research or _research(), mapping, list(concerns), IDA)


def test_valid_submission_is_accepted(tmp_path: Path) -> None:
    assert _run(tmp_path) is None


def test_row_counts_must_match_the_table(tmp_path: Path) -> None:
    assert "rows_before and rows_after" in str(
        _run(tmp_path, results={"rows_before": {"value": 3}})
    )
    wrong = {**RESULTS, "rows_after": {"value": 5}}
    assert "rows_after 5 does not match processed.parquet (2 rows)" == _run(tmp_path, results=wrong)


@pytest.mark.parametrize("reference", [1, "missing", "rows_removed"])
def test_change_counts_name_a_result_key(tmp_path: Path, reference: object) -> None:
    changes = [{"step": "drop", "rows_affected": reference, "reason": "invalid"}]
    assert (_run(tmp_path, changes=changes) is None) is (reference == "rows_removed")


def test_change_count_must_be_nonnegative(tmp_path: Path) -> None:
    results = {**RESULTS, "rows_removed": {"value": -1}}
    assert "nonnegative" in str(_run(tmp_path, results=results))


@pytest.mark.parametrize("reason", ["", "   "])
def test_every_change_needs_a_reason(tmp_path: Path, reason: str) -> None:
    changes = [{"step": "drop", "rows_affected": "rows_removed", "reason": reason}]
    assert "invalid changes.json" in str(_run(tmp_path, changes=changes))


def test_zero_rows_are_rejected(tmp_path: Path) -> None:
    empty = pd.DataFrame({"score": [], "hours": []})
    results = {**RESULTS, "rows_after": {"value": 0}}
    assert _run(tmp_path, frame=empty, results=results) == "processed.parquet has no rows"


def test_only_a_confirmed_outcome_must_survive(tmp_path: Path) -> None:
    frame = pd.DataFrame({"hours": [3, 4]})
    assert "score" in str(_run(tmp_path, frame=frame))
    assert _run(tmp_path, frame=frame, research=_research("proposed")) is None
    facts = readiness(frame, _research("proposed"))
    assert facts["columns"]["score"] == {"role": "outcome", "present": False}


def test_every_concept_needs_an_operationalization(tmp_path: Path) -> None:
    assert "misses concepts: effort" in str(_run(tmp_path, mapping=[]))
    unknown = [
        Operationalization(concept_id="other", columns=[], proxy_strength="none", rationale="r")
    ]
    assert "unknown concepts: other" in str(_run(tmp_path, mapping=[*MAPPING, *unknown]))


def test_operationalization_columns_must_exist(tmp_path: Path) -> None:
    item = Operationalization(
        concept_id="effort", columns=["nope"], proxy_strength="weak", rationale="r"
    )
    assert "nope" in str(_run(tmp_path, mapping=[item]))


@pytest.mark.parametrize("evidence", ["rows_removed", "drop", "c000_mean"])
def test_concern_evidence_resolves(tmp_path: Path, evidence: str) -> None:
    concern = Concern(type="quality", kind="data", description="d", evidence=[evidence])
    assert _run(tmp_path, concerns=(concern,)) is None


def test_concern_evidence_must_resolve(tmp_path: Path) -> None:
    concern = Concern(type="quality", kind="data", description="d", evidence=["made_up"])
    assert "made_up" in str(_run(tmp_path, concerns=(concern,)))


def test_concern_type_must_match_its_kind() -> None:
    with pytest.raises(ValidationError, match="has kind frame"):
        Concern(type="weak_proxy", kind="data", description="d", evidence=[])
    Concern(type="weak_proxy", kind="frame", description="d", evidence=[])


def test_readiness_reports_facts_without_blocking() -> None:
    frame = pd.DataFrame(
        {
            "score": [0.0, 5.0, None, 10.0],
            "hours": [2, 2, 2, 2],
            "school": ["a", "a", "b", "b"],
        }
    )
    research = ResearchContext.model_validate(
        {
            "body": "body",
            "variables": {
                "score": {"role": "outcome", "range": [0, 10]},
                "hours": {"role": "exposure"},
                "school": {"role": "cluster"},
            },
            "design": {"cluster_column": "school"},
        }
    )
    facts = readiness(frame, research)
    assert facts["rows"] == 4 and facts["cluster_count"] == 2
    assert facts["columns"]["hours"]["constant"] is True
    score = facts["columns"]["score"]
    assert score["constant"] is False and score["missing_share"] == 0.25
    assert score["ceiling_share"] == pytest.approx(1 / 3)
    assert "school" not in facts["columns"]
