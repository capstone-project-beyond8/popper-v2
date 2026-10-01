import csv
from pathlib import Path

import pandas as pd
import pytest

from popper.harness.config import DataConfig
from popper.harness.store import RunStore, split_rows


def test_split_is_seeded_and_preserves_rows() -> None:
    data = pd.DataFrame({"id": range(10), "value": range(10)})
    discovery, holdout = split_rows(data, DataConfig())
    repeat = split_rows(data, DataConfig())
    assert len(discovery) == 8 and len(holdout) == 2
    assert set(discovery.id).isdisjoint(holdout.id)
    assert set(discovery.id) | set(holdout.id) == set(range(10))
    pd.testing.assert_frame_equal(holdout, repeat[1])


def test_group_split_keeps_duplicates_together() -> None:
    data = pd.DataFrame({"id": ["a", "a", "b", "c", "d", "e"]})
    discovery, holdout = split_rows(data, DataConfig(group_column="id"))
    assert set(discovery.id).isdisjoint(holdout.id)
    assert holdout.id.nunique() == 1
    assert len(discovery) + len(holdout) == 6


@pytest.mark.parametrize("ids", [["a"], ["a", None], ["a", ""], ["a", " "]])
def test_invalid_groups_fail_before_analysis(ids: list[str | None]) -> None:
    with pytest.raises(ValueError):
        split_rows(pd.DataFrame({"id": ids}), DataConfig(group_column="id"))


def test_missing_column_and_empty_partition_fail() -> None:
    with pytest.raises(ValueError, match="column"):
        split_rows(pd.DataFrame({"x": [1, 2]}), DataConfig(group_column="id"))
    with pytest.raises(ValueError):
        split_rows(pd.DataFrame({"x": [1]}), DataConfig())


def test_zero_fraction_keeps_all_rows() -> None:
    data = pd.DataFrame({"id": [1, 2]})
    discovery, holdout = split_rows(data, DataConfig(holdout_fraction=0))
    pd.testing.assert_frame_equal(discovery, data)
    assert holdout.empty


@pytest.mark.parametrize("fraction", [-0.1, 1.0])
def test_invalid_fraction_is_rejected(fraction: float) -> None:
    with pytest.raises(ValueError):
        DataConfig(holdout_fraction=fraction)


def test_discovery_files_keep_source_cells_exactly(tmp_path: Path) -> None:
    header = ["zip", "flag", "n", "note"]
    rows = [["02134", "NA", "7", "x"], ["00501", "1.50", "8", ""]] * 5
    source = tmp_path / "data.csv"
    source.write_bytes(("\r\n".join(",".join(r) for r in [header, *rows]) + "\r\n").encode())
    research = tmp_path / "research.md"
    research.write_text("study")
    store = RunStore.create(tmp_path / "runs", research, source)
    cells = []
    for name in ("raw.csv", "holdout.csv"):
        raw = store.path("data", name).read_bytes()
        assert b"\r" not in raw
        cells += list(csv.reader(raw.decode().splitlines()))[1:]
    assert sorted(cells) == sorted(rows)
