import pytest

from popper.discover.compatibility import decode_policy


def test_historical_policy_ignores_new_defaults() -> None:
    old = decode_policy({"format_version": 4, "config": {"discovery": {"hypotheses": 3}}})
    assert (old.hypothesis_count, old.adaptive, old.legacy_labels) == (1, False, True)


@pytest.mark.parametrize("count", [2, 3])
def test_current_policy_uses_saved_count(count: int) -> None:
    policy = decode_policy({"format_version": 5, "config": {"discovery": {"hypotheses": count}}})
    assert (policy.hypothesis_count, policy.adaptive, policy.legacy_labels) == (count, True, False)


@pytest.mark.parametrize("version", [3, 99, None])
def test_unsupported_policy_rejected(version: int | None) -> None:
    with pytest.raises(ValueError):
        decode_policy({"format_version": version})
