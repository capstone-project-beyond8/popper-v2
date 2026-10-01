"""Analyst node tools: inspect data, run scratch snippets, view figures, read artifacts."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from popper.harness.agent import Tool
from popper.harness.context import ARTIFACT_CHARS, fence, head
from popper.harness.descriptive import describe_table, format_description, read_table
from popper.harness.session import Harness

ARTIFACTS = {"results.json", "analysis.md", "changes.json", "framing.json", "hypotheses.json"}


def _schema(**props: str) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
        "required": list(props),
    }


def node_tools(h: Harness, inputs: Mapping[str, Path], node_dir: Path) -> list[Tool]:
    root = h.run.root.resolve()
    scratch = 0

    def inside(rel: str) -> Path:
        if Path(rel).is_absolute():
            raise ValueError("absolute paths are not allowed")
        resolved = (h.run.root / rel).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("path is outside the run directory")
        if resolved.is_relative_to(root / "data") or resolved.name in {"run.json", "split.json"}:
            raise ValueError("private input metadata and holdout cannot be read")
        return resolved

    def inspect_data(args: dict[str, Any]) -> str:
        name = str(args.get("name"))
        if name not in inputs:
            raise ValueError(f"unknown input {name!r}; available: {', '.join(inputs)}")
        path = inputs[name]
        if path.suffix in (".csv", ".parquet"):
            text = format_description(describe_table(read_table(path)))
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
        return fence(head(text, ARTIFACT_CHARS))

    def run_python(args: dict[str, Any]) -> str:
        nonlocal scratch
        evidence = node_dir / "scratch" / f"{scratch:02d}"
        scratch += 1
        evidence.mkdir(parents=True)
        r = h.execute(
            str(args["code"]),
            evidence,
            inputs=inputs,
            node=node_dir.name,
            purpose="scratch",
        )
        timed = " (timed out)" if r.timed_out else ""
        output = fence(f"exit code {r.exit_code}{timed}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")
        if r.exit_code != 0 or r.timed_out:
            raise ValueError(
                f"{output}\nFix the snippet and try again; submitted results are separate."
            )
        return output

    def view_figure(args: dict[str, Any]) -> Path:
        path = inside(str(args.get("path", "")))
        if path.suffix != ".png":
            raise ValueError("only .png figures can be viewed")
        if not path.is_file():
            raise ValueError("figure does not exist")
        if path.stat().st_size > 3_750_000:
            raise ValueError("figure is larger than 3.75 MB")
        return path

    def read_artifact(args: dict[str, Any]) -> str:
        path = inside(str(args.get("path", "")))
        if path.name not in ARTIFACTS:
            raise ValueError(f"only these files can be read: {', '.join(sorted(ARTIFACTS))}")
        if not path.is_file():
            raise ValueError("artifact does not exist")
        text = path.read_text(encoding="utf-8", errors="replace")
        return fence(head(text, ARTIFACT_CHARS))

    artifact_list = ", ".join(sorted(ARTIFACTS))
    return [
        Tool(
            "inspect_data",
            "Describe one stage input. For CSV or Parquet: structure, missing values, distribution "
            f"and design statistics per column; other files are returned as text. Output is cut at {ARTIFACT_CHARS} "
            "characters.",
            _schema(name="Input name: the part before the colon in the task's Inputs list."),
            inspect_data,
        ),
        Tool(
            "run_python",
            "Run a throwaway Python snippet and return exit code, stdout and stderr. Each call "
            "starts a fresh process in a new empty folder: variables and files do not persist "
            "between calls. Inputs are available through the same environment variables as the "
            "final script. Calls time out and long output is truncated. Nothing here counts "
            "toward the node's outputs.",
            _schema(code="Python source."),
            run_python,
        ),
        Tool(
            "view_figure",
            "View a PNG figure produced earlier in this run (PNG only, at most 3.75 MB).",
            _schema(path="PNG path relative to the run directory."),
            view_figure,
        ),
        Tool(
            "read_artifact",
            f"Read an artifact of this run: {artifact_list}. Other files are refused. "
            f"Output is cut at {ARTIFACT_CHARS} characters.",
            _schema(path="File path relative to the run directory."),
            read_artifact,
        ),
        Tool(
            "submit",
            "Submit the complete analysis script. It is re-run from scratch in the node folder, "
            "and only that run's files and results.json count. Call it exactly once, last.",
            _schema(code="Complete Python script."),
            None,
            terminal=True,
        ),
    ]
