import os
from collections.abc import Mapping
from pathlib import Path

import pytest

from popper.harness import interpreter
from popper.harness.config import load_config
from popper.harness.interpreter import ExecResult, run_script
from popper.harness.store import RunStore

pytestmark = pytest.mark.integration


def _run(
    code: str, workdir: Path, *, timeout: float = 30, inputs: Mapping[str, Path] | None = None
) -> ExecResult:
    return run_script(code, workdir, timeout=timeout, inputs=inputs or {}, max_output_chars=10_000)


def test_success_captures_stdout(tmp_path: Path) -> None:
    result = _run('print("hi")', tmp_path)
    assert result.exit_code == 0
    assert "hi" in result.stdout
    assert (tmp_path / "stdout.txt").exists()


def test_error_returns_traceback(tmp_path: Path) -> None:
    result = _run('raise ValueError("boom")', tmp_path)
    assert result.exit_code != 0
    assert "boom" in result.stderr


def test_timeout_kills_script(tmp_path: Path) -> None:
    result = _run("import time; time.sleep(60)", tmp_path, timeout=1)
    assert result.timed_out
    assert result.exit_code is None


def test_credentials_are_not_passed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("MY_TOKEN", "y")
    result = _run("import os; print(sorted(os.environ))", tmp_path)
    assert "AWS_SECRET_ACCESS_KEY" not in result.stdout
    assert "MY_TOKEN" not in result.stdout


def test_inputs_are_exposed_as_env(tmp_path: Path) -> None:
    data = tmp_path / "d.csv"
    data.write_text("a\n1\n")
    result = _run(
        'import os; print(os.environ["POPPER_INPUT_DATA"])', tmp_path, inputs={"data": data}
    )
    assert result.stdout.strip() == str(data.resolve())


def test_non_ascii_output_survives(tmp_path: Path) -> None:
    result = _run('print("\u00b1 \u2713 \u1edd")', tmp_path)
    assert result.exit_code == 0
    assert "± ✓ ờ" in result.stdout


def test_script_cannot_launch_a_subprocess(tmp_path: Path) -> None:
    marker = tmp_path / "launched.txt"
    child = "open('launched.txt', 'w').write('started')"
    code = f"import subprocess, sys\nsubprocess.run([sys.executable, '-c', {child!r}])"
    result = _run(code, tmp_path)
    assert result.exit_code != 0 and not result.timed_out
    assert "subprocess launch denied" in result.stderr
    assert not marker.exists()


@pytest.mark.parametrize("operation", ["read", "write", "list"])
def test_script_cannot_access_sibling_evidence(tmp_path: Path, operation: str) -> None:
    private = tmp_path / "private"
    private.mkdir()
    secret = private / "holdout.csv"
    secret.write_text("secret-row")
    code = {
        "read": f"print(open({str(secret)!r}).read())",
        "write": f"open({str(secret)!r}, 'w').write('changed')",
        "list": f"import os; print(os.listdir({str(private)!r}))",
    }[operation]
    result = _run(code, tmp_path / "execution")
    assert result.exit_code != 0
    assert "secret-row" not in result.stdout
    assert secret.read_text() == "secret-row"


@pytest.mark.parametrize("launch", ["os.spawnv", "os.startfile", "os.forkpty"])
def test_script_cannot_launch_processes_through_os_helpers(tmp_path: Path, launch: str) -> None:
    if not hasattr(os, launch.split(".")[1]):
        pytest.skip(f"{launch} is unavailable on this platform")
    marker = tmp_path / "launched.txt"
    child = f"open({str(marker)!r}, 'w').close()"
    code = {
        "os.spawnv": f"import os, sys; os.spawnv(os.P_WAIT, sys.executable, [sys.executable, '-c', {child!r}])",
        "os.startfile": f"import os; os.startfile({str(marker)!r})",
        "os.forkpty": "import os; os.forkpty()",
    }[launch]
    result = _run(code, tmp_path / "execution")
    assert result.exit_code != 0 and "denied" in result.stderr
    assert not marker.exists()


def test_sqlite_cannot_touch_files_outside_work_but_memory_works(tmp_path: Path) -> None:
    outside = tmp_path / "outside.db"
    blocked = _run(
        f"import sqlite3; sqlite3.connect({str(outside)!r}).execute('create table t(x)')",
        tmp_path / "blocked",
    )
    assert blocked.exit_code != 0 and not outside.exists()
    memory = _run(
        "import sqlite3; print(sqlite3.connect(':memory:').execute('select 1').fetchone())",
        tmp_path / "memory",
    )
    assert memory.exit_code == 0 and "(1,)" in memory.stdout


def test_readonly_input_and_relative_escape(tmp_path: Path) -> None:
    raw = tmp_path / "raw.csv"
    raw.write_text("x\n1\n")
    result = _run(
        "import os; open(os.environ['POPPER_INPUT_DATA'], 'w').write('changed')",
        tmp_path / "execution",
        inputs={"data": raw},
    )
    assert result.exit_code != 0 and raw.read_text() == "x\n1\n"
    escape = _run("print(open('../raw.csv').read())", tmp_path / "scratch")
    assert escape.exit_code != 0


@pytest.mark.slow
def test_scientific_stack_can_execute(tmp_path: Path) -> None:
    code = """
import numpy as np, pandas as pd, statsmodels.api as sm
import matplotlib.pyplot as plt
df = pd.DataFrame({'x': np.arange(10), 'y': np.arange(10) * 2})
df.to_parquet('table.parquet')
fit = sm.OLS(df.y, sm.add_constant(df.x)).fit()
plt.plot(df.x, fit.fittedvalues)
plt.savefig('plot.png')
print(pd.read_parquet('table.parquet').shape)
"""
    result = _run(code, tmp_path, timeout=load_config(env={}).execution.timeout_seconds)
    assert result.exit_code == 0, result.stderr
    assert "(10, 2)" in result.stdout and (tmp_path / "plot.png").is_file()


def test_symlink_cannot_expand_file_access(tmp_path: Path) -> None:
    secret = tmp_path / "holdout.csv"
    secret.write_text("held-row")
    work = tmp_path / "execution"
    work.mkdir()
    try:
        (work / "alias.csv").symlink_to(secret)
    except OSError:
        pytest.skip("symlink creation requires OS permission")
    result = _run("print(open('alias.csv').read())", work)
    assert result.exit_code != 0 and "held-row" not in result.stdout


@pytest.mark.parametrize("name", ["code.py", "stdout.txt", "stderr.txt"])
def test_script_cannot_rewrite_execution_record(tmp_path: Path, name: str) -> None:
    code = f"open({name!r}, 'w').write('rewritten')"
    result = _run(code, tmp_path)
    assert result.exit_code != 0
    assert (tmp_path / "code.py").read_text("utf-8") == code


def test_script_cannot_write_into_shared_matplotlib_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = tmp_path / "mpl-cache"
    cache.mkdir()
    monkeypatch.setattr(interpreter, "_matplotlib_cache", lambda: cache)
    monkeypatch.setattr(interpreter, "_ensured_caches", {cache})
    target = cache / "planted.json"
    result = _run(f"open({str(target)!r}, 'w').write('x')", tmp_path / "execution")
    assert result.exit_code != 0
    assert not target.exists()


@pytest.mark.slow
def test_native_reader_cannot_recover_holdout_rows(tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    source.write_text("id,v\n" + "".join(f"{i},val-{i}-unique\n" for i in range(10)))
    research = tmp_path / "research.md"
    research.write_text("study")
    store = RunStore.create(tmp_path / "runs", research, source)
    held = store.read_holdout()["v"].tolist()
    assert held
    raw = store.path("data", "raw.csv").read_text("utf-8").splitlines()[1:]
    assert raw
    raw_value = raw[0].split(",")[1]
    code = """
import os
from pathlib import Path
from pyarrow import fs

local = fs.LocalFileSystem()
folder = Path(os.environ['POPPER_INPUT_RAW']).parent
for info in local.get_file_info(fs.FileSelector(str(folder), recursive=True)):
    if info.type != fs.FileType.File:
        continue
    with local.open_input_stream(info.path) as f:
        print(info.path, f.read())
"""
    result = _run(code, tmp_path / "execution", inputs={"raw": store.path("data", "raw.csv")})
    assert result.exit_code == 0 and not result.timed_out, result.stderr
    assert raw_value in result.stdout
    assert all(v not in result.stdout for v in held)
