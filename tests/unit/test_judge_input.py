import base64
from pathlib import Path

import pytest

from popper.harness.interpreter import ExecResult
from popper.treesearch.engine import Node, StageSpec
from popper.treesearch.judge import _blinded_code, judge_input, validate_image

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7XcAAAAASUVORK5CYII="
)


def test_estimates_are_removed_from_every_judge_channel(tmp_path: Path) -> None:
    node = Node(
        "main-000",
        "main",
        None,
        "draft",
        0,
        tmp_path,
        "# SECRET_EFFECT\nx=9876.543; print('SECRET_EFFECT'); print(x)",
        "ok",
        7,
        True,
        "SECRET_EFFECT",
        {
            "primary_estimate": {
                "value": 9876.543,
                "ci": [9870.0, 9880.0],
                "n": 50,
                "note": "SECRET_EFFECT",
            }
        },
        ["estimate.png"],
        "SECRET_EFFECT",
    )
    (node.execution_dir / "figures").mkdir(parents=True)
    (node.execution_dir / "figures" / "estimate.png").write_bytes(PNG)
    diagnostics = tmp_path / "judge_figures"
    diagnostics.mkdir()
    (diagnostics / "samples.png").write_bytes(PNG)
    spec = StageSpec(
        "main", "SECRET_EFFECT", "SECRET_EFFECT", {}, ("results.json",), blind_estimates=True
    )
    prompt, images = judge_input(
        spec, node, ExecResult(0, False, "9876.543 SECRET_EFFECT", "9870.0", 0.1)
    )
    assert all(s not in prompt for s in ("SECRET_EFFECT", "9876.543", "9870.0", "9880.0"))
    assert "primary_estimate" in prompt and "50" in prompt
    assert images == (diagnostics / "samples.png",)


@pytest.mark.parametrize(
    "contents", [b"not-png", PNG + b"x" * 3_750_000], ids=["invalid", "oversized"]
)
def test_bad_images_are_rejected_before_provider_call(tmp_path: Path, contents: bytes) -> None:
    path = tmp_path / "bad.png"
    path.write_bytes(contents)
    with pytest.raises(ValueError):
        validate_image(path)
    with pytest.raises(ValueError):
        validate_image(tmp_path / "missing.png")


def test_signed_estimate_literals_have_identical_blinded_projections() -> None:
    codes = [
        "primary_estimate = -0.731",
        "primary_estimate = +0.731",
        "primary_estimate = 0.731",
        "primary_estimate = -(0.731)",
        "primary_estimate = -(-0.731)",
    ]
    assert len({_blinded_code(code) for code in codes}) == 1
