"""Run generated scripts in isolated subprocesses."""

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SECRET_MARKERS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD", "CREDENTIAL")


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


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _kill_tree(proc: "subprocess.Popen[bytes]") -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False
        )
    else:
        os.killpg(proc.pid, signal.SIGKILL)


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
    workdir = workdir.resolve()
    with (workdir / "code.py").open("x", encoding="utf-8") as source:
        source.write(code)
    env = {
        k: v
        for k, v in os.environ.items()
        if not _is_credential(k)
        and not k.upper().startswith("POPPER_")
        and k.upper() not in {"PYTHONPATH", "PYTHONHOME", "PWD", "OLDPWD"}
    }
    env["MPLBACKEND"] = "Agg"
    env["PYTHONUTF8"] = "1"
    for key in ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TMP", "TEMP", "MPLCONFIGDIR"):
        env[key] = str(workdir)
    env["AWS_SHARED_CREDENTIALS_FILE"] = os.devnull
    env["AWS_CONFIG_FILE"] = os.devnull
    env["AWS_EC2_METADATA_DISABLED"] = "true"
    for name, path in inputs.items():
        env[f"POPPER_INPUT_{name.upper()}"] = str(path.resolve())
    group: dict[str, Any] = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if sys.platform == "win32"
        else {"start_new_session": True}
    )

    start = time.perf_counter()
    exit_code: int | None
    with (workdir / "stdout.txt").open("xb") as out_f, (workdir / "stderr.txt").open("xb") as err_f:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-X",
                "utf8",
                str(Path(__file__).with_name("worker.py")),
                json.dumps([str(p.resolve()) for p in inputs.values()]),
            ],
            cwd=workdir,
            env=env,
            stdout=out_f,
            stderr=err_f,
            **group,
        )
        try:
            exit_code, timed_out = proc.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.wait()
            exit_code, timed_out = None, True
        except BaseException:
            _kill_tree(proc)
            proc.wait()
            raise
    seconds = time.perf_counter() - start

    out, err = _read(workdir / "stdout.txt"), _read(workdir / "stderr.txt")
    return ExecResult(
        exit_code=exit_code,
        timed_out=timed_out,
        stdout=_tail(out, max_output_chars),
        stderr=_tail(err, max_output_chars),
        seconds=seconds,
    )
