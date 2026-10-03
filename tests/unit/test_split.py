import csv
from pathlib import Path

import pandas as pd
import pytest

from popper.coordinator.run import create_run
from popper.harness.store import RunStore
from popper.science.inputs import read_holdout, split_rows
from popper.science.settings import DataConfig


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
    store = create_run(tmp_path / "runs", research, source)
    from popper.science.inputs import load_episode
    program, episode = load_episode(store)
    assert program.binding == "single_run"
    assert episode.program_id == program.id
    assert episode.id == store.root.name
    assert program.intent.path == "research.md" and program.intent.backing == store.artifact_ref("inputs")
    cells = []
    raw = store.path("data", "raw.csv").read_bytes()
    assert b"\r" not in raw
    cells += list(csv.reader(raw.decode().splitlines()))[1:]
    cells += read_holdout(store).values.tolist()
    assert sorted(cells) == sorted(rows)


def _sealed_store(tmp_path: Path) -> RunStore:
    source = tmp_path / "data.csv"
    source.write_text("id,v\n" + "".join(f"{i},val-{i}-unique\n" for i in range(10)))
    research = tmp_path / "research.md"
    research.write_text("study")
    return create_run(tmp_path / "runs", research, source)


def test_holdout_is_sealed_and_round_trips(tmp_path: Path) -> None:
    store = _sealed_store(tmp_path)
    held = read_holdout(store)
    assert len(held) == 2
    sealed = store.path("data", "holdout.sealed").read_bytes()
    assert not store.path("data", "holdout.csv").exists()
    assert all(v.encode() not in sealed for v in held["v"])
    assert not list(store.root.rglob("*.key"))


def test_missing_key_is_a_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _sealed_store(tmp_path)
    monkeypatch.setenv("POPPER_KEY_DIR", str(tmp_path / "elsewhere"))
    with pytest.raises(FileNotFoundError, match="holdout key not found at .*elsewhere"):
        read_holdout(store)
