"""Compile LaTeX in fresh build directories and retain failed build logs."""

import shutil
import subprocess
import tempfile
from pathlib import Path

from popper.harness.storage.store import next_sequence

_NONSTOP = ("-interaction=nonstopmode", "-halt-on-error")


def compile_pdf(tex: Path) -> Path | None:
    """Compile with pdflatex; None if it is unavailable or the build fails."""
    executable = shutil.which("pdflatex")
    if executable is None:
        return None
    sequence = next_sequence(tex.parent, prefix="build-")
    build = tex.parent / f"build-{sequence:06d}"
    with tempfile.TemporaryDirectory(prefix="popper-latex-") as directory:
        scratch = Path(directory)
        shutil.copyfile(tex, scratch / tex.name)
        for folder in ("figures", "code"):
            if (tex.parent / folder).exists():
                shutil.copytree(tex.parent / folder, scratch / folder)
        ok, output = _compile(scratch / tex.name, executable)
        (scratch / "compile.log").write_text(
            output.decode("utf-8", errors="replace"), encoding="utf-8"
        )
        shutil.copytree(scratch, build)
    pdf = build / tex.with_suffix(".pdf").name
    return pdf if ok and pdf.exists() else None


def _compile(tex: Path, executable: str) -> tuple[bool, bytes]:
    output = b""
    ok = True
    for _ in range(2):
        try:
            done = subprocess.run(
                [executable, *_NONSTOP, tex.name],
                cwd=tex.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=900,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return False, output + (exc.stdout or b"")
        output += done.stdout or b""
        if done.returncode != 0:
            ok = False
            break
    return ok, output
