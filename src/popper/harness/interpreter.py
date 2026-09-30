"""Run generated scripts in isolated subprocesses."""

import os
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_SECRET_MARKERS = ("KEY", "SECRET", "TOKEN")


@dataclass(frozen=True)
class ExecResult:
    exit_code: int | None
    timed_out: bool
    stdout: str
    stderr: str
    seconds: float


def _is_credential(name: str) -> bool:
    upper = name.upper()
    return upper.startswith("AWS_") or any(marker in upper for marker in _SECRET_MARKERS)


def _decode(data: str | bytes | None) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace")
    return data


def _tail(text: str, limit: int) -> str:
    return text[max(len(text) - limit, 0) :]


def run_script(
    code: str,
    workdir: Path,
    *,
    timeout: float,
    inputs: Mapping[str, Path],
    max_output_chars: int,
) -> ExecResult:
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "code.py").write_text(code, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not _is_credential(k)}
    env["MPLBACKEND"] = "Agg"
    for name, path in inputs.items():
        env[f"POPPER_INPUT_{name.upper()}"] = str(path.resolve())

    start = time.perf_counter()
    exit_code: int | None
    try:
        proc = subprocess.run(
            [sys.executable, "code.py"],
            cwd=workdir,
            env=env,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
        exit_code, timed_out = proc.returncode, False
        out, err = _decode(proc.stdout), _decode(proc.stderr)
    except subprocess.TimeoutExpired as exc:
        exit_code, timed_out = None, True
        out, err = _decode(exc.stdout), _decode(exc.stderr)
    seconds = time.perf_counter() - start

    (workdir / "stdout.txt").write_text(out, encoding="utf-8")
    (workdir / "stderr.txt").write_text(err, encoding="utf-8")
    return ExecResult(
        exit_code=exit_code,
        timed_out=timed_out,
        stdout=_tail(out, max_output_chars),
        stderr=_tail(err, max_output_chars),
        seconds=seconds,
    )
