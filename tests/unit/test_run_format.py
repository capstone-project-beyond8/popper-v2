import pytest

from popper.scientific.runtime.data.inputs import RUN_FORMAT, require_current_format


def test_only_the_current_run_format_is_accepted() -> None:
    require_current_format({"format_version": RUN_FORMAT})
    for metadata in ({"format_version": 6}, {"format_version": RUN_FORMAT + 1}, {}):
        with pytest.raises(ValueError, match="no longer supported; start a new run"):
            require_current_format(metadata)
