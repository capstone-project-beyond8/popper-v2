from typing import Any

import pandas as pd

from popper.coordinator.limitations import PREPARATION_ACCESS, limitations
from popper.discover.warnings import hypothesis_warnings
from popper.harness.research import ResearchContext, parse_research

GOOD = """---
variables:
  score: {role: outcome, type: continuous, meaning: exam score, unit: points}
  hours: {role: exposure, type: continuous, meaning: study time, unit: hours}
design:
  cluster_column: school
---
body
"""
HYPOTHESIS = {
    "statement": "Hours raise score",
    "rationale": "see a1",
    "planned_test": "regression",
    "primary_estimand": {"outcome": "score", "exposure": "hours"},
}
MAPPING = [{"concept_id": "effort", "columns": ["hours"], "proxy_strength": "direct"}]


def _data(clusters: int) -> pd.DataFrame:
    return pd.DataFrame({"school": range(clusters), "score": 1.0, "hours": 2.0})


def _warn(front: str, mapping: list[dict[str, Any]] = MAPPING, clusters: int = 40) -> list[str]:
    research: ResearchContext = parse_research(front)
    return hypothesis_warnings(HYPOTHESIS, research, mapping, _data(clusters))


def test_good_frame_is_silent() -> None:
    assert _warn(GOOD) == []


def test_each_rule_fires_on_a_bad_frame() -> None:
    bad = GOOD.replace("role: exposure, type: continuous", "role: post_outcome, type: id")
    bad = bad.replace(
        "design:", "constraints: {excluded: [hours], protected: [score]}\ndesign:"
    ).replace("exam score, unit: points}", "exam score, unit: points, order: ['1']}")
    bad = bad.replace("study time, unit: hours}", "study time, unit: hours, order: ['2']}")
    joined = "\n".join(_warn(bad, [{**MAPPING[0], "proxy_strength": "weak"}], clusters=5))
    for expected in (
        "exposure hours is declared as id",
        "exposure hours is an excluded column",
        "outcome score is a protected column",
        "exposure is measured after the outcome",
        "weak or absent proxies",
        "Only 5 clusters in school",
    ):
        assert expected in joined


def test_proposed_unknown_and_assumption_entries_are_reported() -> None:
    front = GOOD.replace(
        "unit: points}", "unit: {value: points, status: proposed, evidence: [body]}}"
    ).replace("meaning: study time,", "")
    front = front.replace(
        "design:",
        "assumptions:\n  - {id: a1, description: {value: x, status: proposed, evidence: [q]}}\ndesign:",
    )
    joined = "\n".join(_warn(front))
    assert "unit of score is proposed" in joined
    assert "meaning of hours is unknown" in joined
    assert "assumption a1, which is proposed" in joined


def test_limitations_list_concerns_readiness_and_fixed_sentence() -> None:
    foundation = {
        "concerns": [
            {"kind": "frame", "type": "unmeasured_concept", "description": "no effort"},
            {"kind": "data", "type": "quality", "description": "dirty"},
        ],
        "readiness": {
            "columns": {
                "score": {"role": "outcome", "present": True, "missing_share": 0.25},
                "hours": {"role": "exposure", "present": True, "missing_share": 0.0},
                "x": {"role": "exposure", "present": False},
            }
        },
    }
    items = limitations(foundation, ["warned"])
    assert items[0] == "warned" and items[-1] == PREPARATION_ACCESS
    joined = "\n".join(items)
    assert "Unresolved frame concern (unmeasured_concept): no effort" in joined
    assert "Data concern (quality): dirty" in joined
    assert "outcome score is missing in 25.0%" in joined
    assert "hours" not in joined and "exposure x is missing from" in joined
