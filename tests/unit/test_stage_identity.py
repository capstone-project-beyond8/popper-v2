from pathlib import Path

import pytest

from popper.treesearch.engine import StageSpec


def test_stage_identity_defaults_to_role() -> None:
    assert StageSpec("main", "g", "", {}, ()).execution_id == "main"
    assert (
        StageSpec("main", "g", "", {}, (), instance_id="h001-s001-main").execution_id
        == "h001-s001-main"
    )


@pytest.mark.parametrize(
    "instance_id",
    [
        "",
        "../main",
        "a/b",
        "a\\b",
        "C:main",
        "Main",
        "main.",
        "con",
        "com1",
        "prn",
        "aux",
        "nul",
        "com9",
        "lpt1",
        "lpt9",
        "main ",
        "a:b",
        ".",
        "..",
    ],
)
def test_stage_identity_rejects_unsafe_component(tmp_path: Path, instance_id: str) -> None:
    with pytest.raises(ValueError):
        StageSpec("main", "g", "", {}, (), instance_id=instance_id)
    assert list(tmp_path.iterdir()) == []
