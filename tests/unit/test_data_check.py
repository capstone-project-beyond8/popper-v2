import json
from pathlib import Path

import pandas as pd

from popper.ground.data import _check_data


def test_data_check_requires_row_counts(tmp_path: Path) -> None:
    (tmp_path / "changes.json").write_text("[]", encoding="utf-8")
    (tmp_path / "results.json").write_text(json.dumps({"rows_before": 3}), encoding="utf-8")
    assert _check_data(tmp_path) == "results.json must report rows_before and rows_after"
    pd.DataFrame({"a": [1, 2]}).to_parquet(tmp_path / "processed.parquet")
    rows = {"rows_before": {"value": 3}, "rows_after": {"value": 5}}
    (tmp_path / "results.json").write_text(json.dumps(rows), encoding="utf-8")
    assert _check_data(tmp_path) == "rows_after 5 does not match processed.parquet (2 rows)"
    rows["rows_after"]["value"] = 2
    (tmp_path / "results.json").write_text(json.dumps(rows), encoding="utf-8")
    assert _check_data(tmp_path) is None


def test_change_counts_require_valid_named_results(tmp_path: Path) -> None:
    pd.DataFrame({"a": [1, 2]}).to_parquet(tmp_path / "processed.parquet")
    results = {
        "rows_before": {"value": 3},
        "rows_after": {"value": 2},
        "rows_removed": {"value": 1},
    }
    (tmp_path / "results.json").write_text(json.dumps(results))
    for reference in (1, "missing", "rows_removed"):
        (tmp_path / "changes.json").write_text(
            json.dumps([{"step": "drop", "rows_affected": reference, "reason": "quality"}])
        )
        assert (_check_data(tmp_path) is None) is (reference == "rows_removed")
    results["rows_removed"]["value"] = -1
    (tmp_path / "results.json").write_text(json.dumps(results))
    assert _check_data(tmp_path) is not None
