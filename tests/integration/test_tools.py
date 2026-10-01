from pathlib import Path

import pytest

from popper.harness.agent import Tool
from popper.harness.config import load_config
from popper.harness.llm import FakeLLM
from popper.harness.session import Harness
from popper.harness.store import RunStore
from popper.treesearch.tools import node_tools

pytestmark = pytest.mark.integration

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "student_performance"


def _setup(tmp_path: Path) -> tuple[Harness, dict[str, Tool], Path]:
    run = RunStore.create(tmp_path, EXAMPLE / "research.md", EXAMPLE / "data.csv")
    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), run)
    node_dir = run.path("tree", "data", "data-001")
    run.write_json("tree/seed/results.json", {"seed": {"value": 1}})
    tools = {t.name: t for t in node_tools(h, {"data": EXAMPLE / "data.csv"}, node_dir)}
    return h, tools, node_dir


def _call(tools: dict[str, Tool], tool: str, /, **args: str) -> str | Path:
    handler = tools[tool].handler
    assert handler is not None
    return handler(args)


def test_inspect_data_lists_columns(tmp_path: Path) -> None:
    _, tools, _ = _setup(tmp_path)
    out = str(_call(tools, "inspect_data", name="data"))
    header = (EXAMPLE / "data.csv").read_text(encoding="utf-8").splitlines()[0]
    assert all(col in out for col in header.split(","))
    assert "<untrusted>" in out


def test_inspect_data_rejects_unknown_input(tmp_path: Path) -> None:
    _, tools, _ = _setup(tmp_path)
    with pytest.raises(ValueError):
        _call(tools, "inspect_data", name="nope")


def test_run_python_uses_numbered_scratch_folders(tmp_path: Path) -> None:
    h, tools, node_dir = _setup(tmp_path)
    first = str(_call(tools, "run_python", code="print('hello-scratch')"))
    _call(tools, "run_python", code="print(2)")
    assert "hello-scratch" in first
    assert (node_dir / "scratch" / "00" / "code.py").exists()
    assert (node_dir / "scratch" / "01" / "code.py").exists()
    import json

    events = [json.loads(line) for line in h.run.path("journal.jsonl").read_text().splitlines()]
    assert sum(e["event"] == "exec_start" for e in events) == 2
    assert sum(e["event"] == "exec" for e in events) == 2
    for e in (e for e in events if e["event"] == "exec"):
        journaled = Path(e["path"])
        assert journaled.parent == (node_dir / "scratch").resolve()
        assert (journaled / "code.py").exists() and (journaled / "stdout.txt").exists()


def test_run_python_hides_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "s3cr3t")
    _, tools, _ = _setup(tmp_path)
    out = str(_call(tools, "run_python", code="import os\nprint(dict(os.environ))"))
    assert "s3cr3t" not in out


def test_paths_cannot_leave_run_dir(tmp_path: Path) -> None:
    _, tools, _ = _setup(tmp_path)
    absolute = str((tmp_path / "results.json").resolve())
    for name, path in [
        ("read_artifact", "../x/results.json"),
        ("read_artifact", absolute),
        ("view_figure", "../../a.png"),
        ("read_artifact", "research.md"),
    ]:
        with pytest.raises(ValueError):
            _call(tools, name, path=path)


def test_read_artifact_reads_parent_results(tmp_path: Path) -> None:
    h, tools, _ = _setup(tmp_path)
    h.run.write_json("tree/data/data-000/results.json", {"m": {"value": 1}})
    out = str(_call(tools, "read_artifact", path="tree/data/data-000/results.json"))
    assert '"value": 1' in out


def test_artifact_tool_only_advertises_available_paths(tmp_path: Path) -> None:
    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    assert "read_artifact" not in {t.name for t in node_tools(h, {}, tmp_path / "node")}
    h.run.write_json("tree/seed/results.json", {"x": {"value": 1}})
    tools = {t.name: t for t in node_tools(h, {}, tmp_path / "node")}
    assert "tree/seed/results.json" in tools["read_artifact"].description
    assert "framing.json" not in tools["read_artifact"].description


def test_artifact_discovery_uses_the_resolved_read_policy(tmp_path: Path) -> None:
    h = Harness(load_config(env={}), FakeLLM(lambda _: ""), RunStore(tmp_path))
    secret = h.run.write_text("research.md", "private text")
    alias = tmp_path / "results.json"
    try:
        alias.symlink_to(secret)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert "read_artifact" not in {t.name for t in node_tools(h, {}, tmp_path / "node")}


def test_scratch_files_are_reported_and_missing_figures_list_them(tmp_path: Path) -> None:
    h, tools, node = _setup(tmp_path)
    out = str(
        _call(
            tools,
            "run_python",
            code="from pathlib import Path\nPath('plot.png').write_bytes(b'png')",
        )
    )
    rel = (node / "scratch/00/plot.png").relative_to(h.run.root).as_posix()
    assert rel in out
    assert _call(tools, "view_figure", path=rel).is_file()  # type: ignore[union-attr]
    with pytest.raises(ValueError) as exc:
        _call(tools, "view_figure", path="plot.png")
    assert rel in str(exc.value)


def test_run_python_cannot_overwrite_run_inputs(tmp_path: Path) -> None:
    h, _, node_dir = _setup(tmp_path)
    raw = h.run.path("data", "raw.csv")
    before = raw.read_bytes()
    tools = {t.name: t for t in node_tools(h, {"raw": raw}, node_dir)}
    code = "import os\nopen(os.environ['POPPER_INPUT_RAW'], 'w').write('x')"
    with pytest.raises(ValueError, match="denied"):
        _call(tools, "run_python", code=code)
    assert raw.read_bytes() == before
