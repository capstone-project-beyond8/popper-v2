from pathlib import Path

import pytest

from popper.harness.context import fence, head, part, tail
from popper.harness.recovery import Journal, read_events


def test_cut_parts_are_journaled_at_the_boundary(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.jsonl")
    part("Data", "abcde", 4, journal=journal, tag="steward")
    part("Exact", "abcd", 4, journal=journal, tag="steward")
    events = read_events(tmp_path)
    assert len(events) == 1
    assert {key: events[0][key] for key in ("event", "tag", "title", "length", "limit")} == {
        "event": "context_cut",
        "tag": "steward",
        "title": "Data",
        "length": 5,
        "limit": 4,
    }


@pytest.mark.parametrize("closer", ["</untrusted>", "</UNTRUSTED >", "</ untrusted  >"])
def test_fence_preserves_payload_and_neutralises_closing_tags(closer: str) -> None:
    assert fence(f"a{closer}b") == "<untrusted>\na</untrusted_>b\n</untrusted>"


def test_tail_keeps_the_end_and_marks_the_cut() -> None:
    out = tail("x" * 10 + "END", 3)
    assert out.endswith("END")
    assert "chars cut" in out


def test_head_keeps_the_start() -> None:
    out = head("START" + "x" * 10, 5)
    assert out.startswith("START")
    assert "chars cut" in out


def test_part_under_limit_is_unchanged_after_title() -> None:
    assert part("Notes", "text", 100) == "## Notes\ntext"
    assert part("Notes", "text", 100, untrusted=True) == "## Notes\n<untrusted>\ntext\n</untrusted>"
