"""Write the LaTeX report: prose from the model, numbers from results.json, the rest from code."""

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, PackageLoader
from pydantic import BaseModel, ConfigDict

from popper.communicate.numbers import (
    collect_values,
    explain_missing,
    fill_numbers,
    latex_escape,
)
from popper.harness.context import ARTIFACT_CHARS, part
from popper.harness.prompts import load_prompt
from popper.harness.session import Harness
from popper.treesearch.engine import Node, load_nodes

_SYSTEM = "You are a careful scientific writer. Reply with JSON only."
_WRITER_RETRIES = 2  # re-asks when the prose cites numbers that have no value
_ENV = Environment(
    loader=PackageLoader("popper.communicate", "templates"),
    block_start_string=r"\BLOCK{",
    block_end_string="}",
    variable_start_string=r"\VAR{",
    variable_end_string="}",
    comment_start_string=r"\#{",
    comment_end_string="}",
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


class FigureRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["explore", "baseline", "main", "robustness"]
    file: str
    caption: str


class Writeup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    abstract: str
    introduction: str
    data: str
    exploration: str
    hypothesis: str
    methods: str
    results: str
    limitations: str
    figures: list[FigureRef]


def _write_log(tex: Path, output: bytes | None) -> None:
    text = (output or b"").decode("utf-8", errors="replace")
    (tex.parent / "compile.log").write_text(text, encoding="utf-8")


_NONSTOP = ("-interaction=nonstopmode", "-halt-on-error")
# (engine, arguments before the file name, runs); pdflatex runs twice to resolve references
_ENGINES: tuple[tuple[str, tuple[str, ...], int], ...] = (
    ("tectonic", (), 1),
    ("latexmk", ("-pdf", *_NONSTOP), 1),
    ("pdflatex", _NONSTOP, 2),
)


def compile_pdf(tex: Path) -> Path | None:
    """Compile with the first installed LaTeX engine; None if none is found or the build fails."""
    found = next(
        ((path, args, runs) for name, args, runs in _ENGINES if (path := shutil.which(name))),
        None,
    )
    if found is None:
        return None
    path, args, runs = found
    output = b""
    ok = True
    for _ in range(runs):
        try:
            done = subprocess.run(
                [path, *args, tex.name],
                cwd=tex.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=900,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            _write_log(tex, output + (exc.stdout or b""))
            return None
        output += done.stdout or b""
        if done.returncode != 0:
            ok = False
            break
    _write_log(tex, output)
    pdf = tex.with_suffix(".pdf")
    return pdf if ok and pdf.exists() else None


def _copy_figures(h: Harness, writeup: Writeup, nodes: list[Node]) -> list[dict[str, str]]:
    placed: list[dict[str, str]] = []
    for ref in writeup.figures:
        node = next((n for n in nodes if n.stage == ref.stage and ref.file in n.figures), None)
        if node is None:
            h.journal.write("figure_missing", file=ref.file)
            continue
        name = f"{node.stage}-{ref.file}"
        target = h.run.path("report", "figures", name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(node.execution_dir / "figures" / ref.file, target)
        placed.append({"path": f"figures/{name}", "caption": ref.caption})
    return placed


def _problems(writeup: Writeup, values: dict[str, Any]) -> str:
    """Numbers without a value and unbalanced inline math, one line per problem."""
    sections = {k: str(v) for k, v in writeup.model_dump().items() if k != "figures"}
    _, unresolved = fill_numbers("\n".join(sections.values()), values)
    lines = [explain_missing(ref, values) for ref in unresolved]
    lines += [
        f"{name}: odd number of $ signs; close every inline formula"
        for name, text in sections.items()
        if len(re.findall(r"(?<!\\)\$", text)) % 2
    ]
    return "\n".join(f"- {line}" for line in lines)


def write_paper(
    h: Harness,
    framing: dict[str, Any],
    changes: list[dict[str, Any]],
    explore: Node,
    hypothesis: dict[str, Any],
    evidence: Path,
    data_node: Node,
) -> tuple[Path, Path | None, list[str]]:
    manifest = json.loads(evidence.read_text("utf-8"))
    experiment = next(n for n in load_nodes(h, "main") if n.id == manifest["selected"]["main"])
    values = collect_values([data_node, explore, experiment])
    figures = {n.stage: n.figures for n in (explore, experiment)}
    prompt = load_prompt(
        "popper.communicate",
        "writeup.md",
        keys="\n".join(f"- {k} = {v}" for k, v in values.items()),
        framing=part("Framing", json.dumps(framing, indent=2), ARTIFACT_CHARS),
        hypothesis=json.dumps(hypothesis, indent=2),
        analyses=part(
            "Analyses",
            f"Exploration:\n{explore.analysis}\n\nExperiment:\n{experiment.analysis}",
            ARTIFACT_CHARS,
            untrusted=True,
        ),
        figures=json.dumps(figures),
    )
    writeup = h.ask_model("writer", schema=Writeup, tag="writeup", system=_SYSTEM, prompt=prompt)
    for _ in range(_WRITER_RETRIES):
        problems = _problems(writeup, values)
        if not problems:
            break
        retry = (
            f"{prompt}\n\nYour previous reply had these problems:\n{problems}\n"
            "Fix them and reply again with the full JSON."
        )
        writeup = h.ask_model("writer", schema=Writeup, tag="writeup", system=_SYSTEM, prompt=retry)
    placed = _copy_figures(h, writeup, [explore, experiment])
    tex, missing = fill_numbers(
        _ENV.get_template("paper.tex.j2").render(
            w=writeup,
            figures=placed,
            changes=[
                {
                    "step": latex_escape(str(c.get("step", ""))).replace(r"\_", r"\_\allowbreak{}"),
                    "rows_affected": latex_escape(str(c.get("rows_affected", ""))),
                    "reason": latex_escape(str(c.get("reason", ""))),
                }
                for c in changes
            ],
            data_code=data_node.code,
            experiment_code=experiment.code,
            stability=manifest["stability"],
        ),
        values,
    )
    if missing:
        h.journal.write("numbers_missing", keys=missing)
    path = h.run.write_text("report/paper.tex", tex)
    return path, compile_pdf(path), missing
