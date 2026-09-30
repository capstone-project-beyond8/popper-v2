from pathlib import Path

import pytest

from popper.harness.interpreter import run_script

pytestmark = pytest.mark.integration


def _run(code: str, workdir: Path, **kwargs: object):  # type: ignore[no-untyped-def]
    options: dict[str, object] = {"timeout": 30, "inputs": {}, "max_output_chars": 10_000}
    options.update(kwargs)
    return run_script(code, workdir, **options)  # type: ignore[arg-type]


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
    result = _run("import time; time.sleep(10)", tmp_path, timeout=1)
    assert result.timed_out
    assert result.exit_code is None
    assert result.seconds < 5


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
