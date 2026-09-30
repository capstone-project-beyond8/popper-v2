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


@pytest.mark.integration
@pytest.mark.parametrize(("flags", "silent"), [(["--quiet"], True), ([], False)])
def test_quiet_controls_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: list[str], silent: bool
) -> None:
    (tmp_path / "brief.md").write_text("b", encoding="utf-8")
    (tmp_path / "data.csv").write_text("a\n1\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("data: {group_column: student_id}")
    fake = MagicMock(
        return_value=SimpleNamespace(run_dir=tmp_path, status="completed", missing=[], pdf=tmp_path)
    )
    monkeypatch.setattr("popper.cli.run", fake)
    monkeypatch.setattr("popper.cli.BedrockLLM", MagicMock())
    assert main(["run", str(tmp_path), *flags]) == 0
    assert (fake.call_args.kwargs["progress"] is None) is silent
    assert fake.call_args.kwargs["config"].data.group_column == "student_id"


def test_pdf_reads_legacy_source_without_replacing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tex = tmp_path / "report" / "paper.tex"
    tex.parent.mkdir()
    tex.write_text("original")
    fake = MagicMock(return_value=tmp_path / "build-000000" / "paper.pdf")
    monkeypatch.setattr("popper.cli.compile_pdf", fake)
    assert main(["pdf", str(tmp_path)]) == 0
    fake.assert_called_once_with(tex)
    assert tex.read_text() == "original"


def test_resume_rejects_legacy_without_provider_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "run.json").write_text('{"status":"completed"}')
    provider = MagicMock()
    monkeypatch.setattr("popper.cli.BedrockLLM", lambda **kwargs: provider)
    assert main(["resume", str(tmp_path)]) == 1
    assert "format" in capsys.readouterr().err
    provider.complete.assert_not_called()
