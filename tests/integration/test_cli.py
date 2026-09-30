import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from popper.cli import main


@pytest.mark.integration
def test_version_flag_prints_version() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "popper", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "0.1.0" in result.stdout


@pytest.mark.parametrize(("flags", "silent"), [(["--quiet"], True), ([], False)])
def test_quiet_controls_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: list[str], silent: bool
) -> None:
    (tmp_path / "brief.md").write_text("b", encoding="utf-8")
    (tmp_path / "data.csv").write_text("a\n1\n", encoding="utf-8")
    fake = MagicMock(
        return_value=SimpleNamespace(run_dir=tmp_path, status="completed", missing=[], pdf=tmp_path)
    )
    monkeypatch.setattr("popper.cli.run", fake)
    monkeypatch.setattr("popper.cli.BedrockLLM", MagicMock())
    assert main(["run", str(tmp_path), *flags]) == 0
    assert (fake.call_args.kwargs["progress"] is None) is silent
