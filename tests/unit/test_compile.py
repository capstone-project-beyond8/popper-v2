import shutil
import sys
from pathlib import Path

import pytest

from popper.communicate.paper import compile_pdf


def test_compile_returns_none_without_tectonic(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert compile_pdf(tmp_path / "p.tex") is None


def test_compile_returns_none_on_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: sys.executable)
    tex = tmp_path / "p.tex"
    tex.write_text("x", encoding="utf-8")
    assert compile_pdf(tex) is None
