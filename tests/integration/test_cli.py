import subprocess
import sys

import pytest


@pytest.mark.integration
def test_version_flag_prints_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "popper", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "0.1.0" in result.stdout
