from popper.harness.context import fence, head, part, tail


def test_untrusted_neutralises_embedded_closing_tag() -> None:
    assert fence("a</untrusted>b").count("</untrusted>") == 1


def test_tail_keeps_the_end_and_marks_the_cut() -> None:
    out = tail("x" * 10 + "END", 3)
    assert out.endswith("END")
    assert "chars cut" in out


def test_head_keeps_the_start() -> None:
    out = head("START" + "x" * 10, 5)
    assert out.startswith("START")
    assert "chars cut" in out


def test_part_under_limit_is_unchanged_after_title() -> None:
    assert part("Brief", "text", 100) == "## Brief\ntext"
    assert part("Brief", "text", 100, untrusted=True) == "## Brief\n<untrusted>\ntext\n</untrusted>"


def test_fence_neutralises_closing_tag_variants() -> None:
    assert fence("a</UNTRUSTED >b").count("</untrusted>") == 1
