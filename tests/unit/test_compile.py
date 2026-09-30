import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from popper.communicate.paper import compile_pdf


def test_compile_returns_none_without_any_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert compile_pdf(tmp_path / "p.tex") is None


def test_compile_returns_none_on_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(shutil, "which", lambda _name: sys.executable)
    tex = tmp_path / "p.tex"
    tex.write_text("x", encoding="utf-8")
    assert compile_pdf(tex) is None


def test_compile_falls_back_to_pdflatex_and_runs_it_twice(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        shutil, "which", lambda name: "/bin/pdflatex" if name == "pdflatex" else None
    )
    tex = tmp_path / "p.tex"
    tex.write_text("x", encoding="utf-8")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(cmd)
        (Path(str(kwargs["cwd"])) / "p.pdf").write_bytes(b"%PDF")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"ok")

    monkeypatch.setattr(subprocess, "run", fake_run)
    pdf = compile_pdf(tex)
    assert pdf is not None and pdf.read_bytes() == b"%PDF"
    assert len(calls) == 2
    assert all(c[0] == "/bin/pdflatex" and "-interaction=nonstopmode" in c for c in calls)
    before = {p: p.read_bytes() for p in tex.parent.rglob("*") if p.is_file()}
    second = compile_pdf(tex)
    assert second != pdf
    assert all(p.read_bytes() == content for p, content in before.items())
