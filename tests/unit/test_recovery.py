import json
from pathlib import Path

import pytest

from popper.harness.recovery import Journal, load_state, read_events, recorded_spend
from popper.harness.store import RunStore


def test_only_committed_snapshots_are_loaded(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    first = store.checkpoint({"status": "running"})
    store.write_json("state/000099.json", {"status": "completed"})
    assert load_state(store)["status"] == "running"
    original = first.read_bytes()
    second = store.checkpoint({"status": "failed"})
    assert first.read_bytes() == original
    assert load_state(store)["status"] == "failed"
    assert json.loads(second.read_text())["previous"] == str(first.relative_to(tmp_path)).replace("\\", "/")


def test_all_recorded_cost_survives_checkpoint(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    journal = Journal(tmp_path / "journal.jsonl")
    journal.write("llm_call", usd=0.1)
    store.checkpoint({"spent_usd": 0.1})
    journal.write("llm_call", usd=0.2)
    assert recorded_spend(store) == pytest.approx(0.3)


def test_truncated_tail_is_preserved_before_new_events(tmp_path: Path) -> None:
    path = tmp_path / "journal.jsonl"
    before = b'{"event":"llm_call","usd":0.1}\n{"event":'
    path.write_bytes(before)
    journal = Journal(path)
    journal.write("llm_call", usd=0.2)
    assert path.read_bytes() == before
    events = read_events(tmp_path)
    assert sum(e.get("usd", 0) for e in events) == pytest.approx(0.3)


def test_interior_corruption_is_not_silently_ignored(tmp_path: Path) -> None:
    (tmp_path / "journal.jsonl").write_text('broken\n{"event":"llm_call","usd":1}\n')
    with pytest.raises(ValueError, match="journal"):
        read_events(tmp_path)


def test_uncommitted_artifacts_are_preserved_and_never_loaded(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    abandoned = store.new_attempt("understand")
    saved = store.write_json(f"{abandoned.relative_to(tmp_path).as_posix()}/framing.json", {"title": "old"})
    assert store.committed("framing") is None
    next_attempt = store.new_attempt("understand")
    assert next_attempt != abandoned and saved.is_file()
    target = store.write_json(f"{next_attempt.relative_to(tmp_path).as_posix()}/framing.json", {"title": "new"})
    store.commit_artifact("framing", target)
    assert store.committed("framing") == target


def test_export_reuse_checks_source_and_preserves_destination(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    source = store.write_text('execution/clean.csv', 'x\n1\n')
    target = store.copy_once(source, 'data/clean.csv')
    assert store.copy_once(source, 'data/clean.csv') == target
    different = store.write_text('other/clean.csv', 'x\n2\n')
    with pytest.raises(ValueError, match='differs'):
        store.copy_once(different, 'data/clean.csv')
    assert target.read_text('utf-8') == 'x\n1\n'
