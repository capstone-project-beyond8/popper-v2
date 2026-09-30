"""Analyst node tools: inspect data, run scratch snippets, view figures, read artifacts."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from popper.harness.agent import Tool
from popper.harness.context import ARTIFACT_CHARS, fence, head
from popper.harness.interpreter import run_script
from popper.harness.session import Harness

ARTIFACTS = {"results.json", "analysis.md", "changes.json", "framing.json", "hypotheses.json"}


def _schema(**props: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
        "required": list(props),
    }


def _describe_table(path: Path) -> str:
    df = pd.read_csv(path) if path.suffix == ".csv" else pd.read_parquet(path)
    return (
        f"dtypes:\n{df.dtypes.to_string()}\n\nhead(5):\n{df.head(5).to_string()}\n\n"
        f"describe:\n{df.describe(include='all').to_string()}\n\n"
        f"missing:\n{df.isna().sum().to_string()}"
    )


def node_tools(h: Harness, inputs: Mapping[str, Path], node_dir: Path) -> list[Tool]:
    root = h.run.root.resolve()
    scratch = 0

    def inside(rel: str) -> Path:
        if Path(rel).is_absolute():
            raise ValueError("absolute paths are not allowed")
        resolved = (h.run.root / rel).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("path is outside the run directory")
        return resolved

    def inspect_data(args: dict[str, Any]) -> str:
        name = str(args.get("name"))
        if name not in inputs:
            raise ValueError(f"unknown input {name!r}; available: {', '.join(inputs)}")
        path = inputs[name]
        if path.suffix in (".csv", ".parquet"):
            text = _describe_table(path)
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
        return fence(head(text, ARTIFACT_CHARS))

    def run_python(args: dict[str, Any]) -> str:
        nonlocal scratch
        workdir = node_dir / "scratch" / f"{scratch:02d}"
        scratch += 1
        r = run_script(
            str(args["code"]),
            workdir,
            timeout=h.config.execution.timeout_seconds,
            inputs=inputs,
            max_output_chars=h.config.execution.max_output_chars,
        )
        timed = " (timed out)" if r.timed_out else ""
        return fence(f"exit code {r.exit_code}{timed}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")

    def view_figure(args: dict[str, Any]) -> Path:
        path = inside(str(args.get("path", "")))
        if path.suffix != ".png":
            raise ValueError("only .png figures can be viewed")
        if not path.is_file():
            raise ValueError("figure does not exist")
        return path

    def read_artifact(args: dict[str, Any]) -> str:
        path = inside(str(args.get("path", "")))
        if path.name not in ARTIFACTS:
            raise ValueError(f"only these files can be read: {', '.join(sorted(ARTIFACTS))}")
        if not path.is_file():
            raise ValueError("artifact does not exist")
        text = path.read_text(encoding="utf-8", errors="replace")
        return fence(head(text, ARTIFACT_CHARS))

    return [
        Tool(
            "inspect_data",
            "Show dtypes, first rows, summary statistics and missing counts of an input file.",
            _schema(name="Input name."),
            inspect_data,
        ),
        Tool(
            "run_python",
            "Run a throwaway Python snippet in a scratch folder and return its output.",
            _schema(code="Python source."),
            run_python,
        ),
        Tool(
            "view_figure",
            "View a PNG figure produced earlier in this run.",
            _schema(path="PNG path relative to the run directory."),
            view_figure,
        ),
        Tool(
            "read_artifact",
            "Read a results, analysis, framing or hypotheses file from this run.",
            _schema(path="File path relative to the run directory."),
            read_artifact,
        ),
        Tool(
            "submit",
            "Submit the final analysis script; it is re-run to produce the node's outputs.",
            _schema(code="Complete Python script."),
            None,
            terminal=True,
        ),
    ]
