import pytest

from popper.discover.robustness import compute_stability
from popper.harness.results import ResultEntry


def estimate(value: float, interval: tuple[float, float] = (1, 3)) -> ResultEntry:
    return ResultEntry(value=value, ci=interval, n=100)


@pytest.mark.parametrize(
    ("variants", "placebos", "want"),
    [
        ([estimate(2)] * 4 + [estimate(-2, (-3, -1))], [estimate(0, (-1, 1))], "stable"),
        ([estimate(2)] * 3 + [None] * 2, [estimate(0, (-1, 1))], "fragile"),
        ([estimate(1, (0, 2))] * 4, [estimate(0, (-1, 1))], "fragile"),
        ([estimate(-2, (-3, -1))] * 4, [estimate(0, (-1, 1))], "fragile"),
        ([estimate(2)] * 4, [None], "fragile"),
        ([estimate(2)] * 4, [], "fragile"),
        ([estimate(2)] * 4, [estimate(2)], "fragile"),
        ([estimate(2)] * 4, [estimate(0, (0, 1))], "stable"),
        ([estimate(2)] * 2, [estimate(0, (-1, 1))], "fragile"),
    ],
    ids=[
        "boundary",
        "failed-variants",
        "touches-zero",
        "opposite",
        "failed-placebo",
        "missing-placebo",
        "significant-placebo",
        "placebo-zero-endpoint",
        "too-few",
    ],
)
def test_stability_is_computed_conservatively(
    variants: list[ResultEntry | None],
    placebos: list[ResultEntry | None],
    want: str,
) -> None:
    label, reasons = compute_stability(estimate(2), variants, placebos)
    assert label == want
    assert bool(reasons) is (want == "fragile")


def test_stability_does_not_test_expected_direction_or_main_significance() -> None:
    main = estimate(-2, (-4, 1))
    label, _ = compute_stability(main, [estimate(-2, (-3, -1))] * 4, [estimate(0, (-1, 1))])
    assert label == "stable"
    assert (
        compute_stability(estimate(0, (-1, 1)), [estimate(2)] * 4, [estimate(0, (-1, 1))])[0]
        == "fragile"
    )
