import math
from pathlib import Path

import pandas as pd
import pytest

from popper.scientific.runtime.data.descriptive import (
    DescriptiveReport,
    describe_table,
    format_description,
    read_table,
)
from popper.scientific.runtime.data.research import ResearchContext, parse_research
from popper.scientific.runtime.evidence.results import validate_results


def research(front: str) -> ResearchContext:
    return parse_research(f"---\n{front}---\nBody\n")


def value(report: DescriptiveReport, key: str) -> float | int | str:
    found: float | int | str = report.results[key]["value"]
    return found


SCORES = research("variables:\n  score:\n    range: [0, 100]\ndesign:\n  cluster_column: school\n")


def scores_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"score": ["0", "50", "100", ""], "school": ["a", "a", "b", "b"], "x": ["1", "", "", "4"]}
    )


def test_scores_with_declared_range() -> None:
    report = describe_table(scores_frame(), SCORES)
    assert value(report, "c000_mean") == 50
    assert value(report, "c000_sd") == 50
    assert value(report, "c000_missing_share") == 0.25
    assert value(report, "c000_floor_count") == 1
    assert value(report, "c000_ceiling_count") == 1
    assert value(report, "c000_floor_share") == pytest.approx(1 / 3)
    assert value(report, "c000_ceiling_share") == pytest.approx(1 / 3)
    assert report.layout["columns"][0]["bounds"] == "declared"
    validate_results(report.results)


def test_bounds_are_observed_without_declaration() -> None:
    report = describe_table(scores_frame())
    assert report.layout["columns"][0]["bounds"] == "observed"


def test_cluster_sizes_and_missing_share_by_cluster() -> None:
    report = describe_table(scores_frame(), SCORES)
    assert value(report, "cluster_count") == 2
    assert value(report, "cluster_size_min") == value(report, "cluster_size_max") == 2
    assert value(report, "c000_missing_share_cluster_min") == 0
    assert value(report, "c000_missing_share_cluster_max") == 0.5


def test_co_missing_pattern_counts() -> None:
    frame = pd.DataFrame({"a": ["", "", "1"], "b": ["", "", "2"], "c": ["", "3", "4"]})
    report = describe_table(frame)
    counts = {
        tuple(report.layout["comissing"][k]): value(report, k) for k in report.layout["comissing"]
    }
    assert counts == {("a", "b", "c"): 1, ("a", "b"): 1}


def test_one_row_column_omits_undefined_statistics() -> None:
    report = describe_table(pd.DataFrame({"a": ["5"]}))
    assert "c000_sd" not in report.results and "c000_skewness" not in report.results
    assert "c000_sd" in report.layout["omitted"]
    assert all(
        isinstance(e["value"], str) or math.isfinite(e["value"]) for e in report.results.values()
    )


def test_strings_failed_conversions_and_inconsistent_coding() -> None:
    frame = pd.DataFrame(
        {
            "id": ["S0001", "S0002"],
            "code": ["001", "002"],
            "n": ["1", "absent"],
            "g": ["A", "a "],
            "w": ["yes", "yes "],
        }
    )
    report = describe_table(frame)
    assert (
        value(report, "c000_n_unique") == 2 and report.layout["columns"][0]["kind"] == "categorical"
    )
    assert value(report, "c002_failed_conversions") == 1
    assert value(report, "c003_inconsistent_codes") == 1
    assert value(report, "c004_inconsistent_codes") == 1


def test_read_table_keeps_identifiers_as_strings(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    path.write_text("id,v\n001,1\nS0001,\n", encoding="utf-8")
    frame = read_table(path)
    assert frame["id"].tolist() == ["001", "S0001"] and frame["v"].tolist() == ["1", ""]


def test_distinct_keys_for_similar_names_and_input_unchanged() -> None:
    frame = pd.DataFrame({"a-b": ["1", "2"], "a_b": ["3", "4"]})
    before = frame.copy()
    report = describe_table(frame)
    assert value(report, "c000_mean") == 1.5 and value(report, "c001_mean") == 3.5
    pd.testing.assert_frame_equal(frame, before)
    assert "mean=1.5" in format_description(report)
