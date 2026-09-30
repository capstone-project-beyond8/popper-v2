import json
from pathlib import Path

from popper.ground.data import _check_data


def test_data_check_requires_row_counts(tmp_path: Path) -> None:
    (tmp_path / "changes.json").write_text("[]", encoding="utf-8")
    (tmp_path / "results.json").write_text(json.dumps({"rows_before": 3}), encoding="utf-8")
    assert _check_data(tmp_path) == "results.json must report rows_before and rows_after"
    (tmp_path / "results.json").write_text(
        json.dumps({"rows_before": 3, "rows_after": 2}), encoding="utf-8"
    )
    assert _check_data(tmp_path) is None
