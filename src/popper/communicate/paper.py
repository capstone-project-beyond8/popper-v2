"""Write the LaTeX report: prose from the model, numbers from results.json, the rest from code."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader
from pydantic import BaseModel, ConfigDict

from popper.communicate.numbers import collect_values, fill_numbers, format_value, latex_escape
from popper.harness.prompts import load_prompt
from popper.harness.session import Harness
from popper.treesearch.engine import Node

_SYSTEM = "You are a careful scientific writer. Reply with JSON only."
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


def compile_pdf(tex: Path) -> Path | None:
    tectonic = shutil.which("tectonic")
    if tectonic is None:
        return None
    try:
        done = subprocess.run(
            [tectonic, str(tex)], cwd=tex.parent, capture_output=True, timeout=300, check=False
        )
    except subprocess.TimeoutExpired:
        return None
    pdf = tex.with_suffix(".pdf")
    return pdf if done.returncode == 0 and pdf.exists() else None


def _copy_figures(h: Harness, writeup: Writeup, nodes: list[Node]) -> list[dict[str, str]]:
    placed: list[dict[str, str]] = []
    for ref in writeup.figures:
        node = next((n for n in nodes if ref.file in n.figures), None)
        if node is None:
            h.journal.write("figure_missing", file=ref.file)
            continue
        name = f"{node.stage}-{ref.file}"
        target = h.run.path("report", "figures", name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(node.dir / "figures" / ref.file, target)
        placed.append({"path": f"figures/{name}", "caption": ref.caption})
    return placed


def write_paper(
    h: Harness,
    framing: dict[str, Any],
    changes: list[dict[str, Any]],
    explore: Node,
    hypothesis: dict[str, Any],
    experiment: Node,
    data_node: Node,
) -> tuple[Path, Path | None, list[str]]:
    values = collect_values([data_node, explore, experiment])
    figures = {n.stage: n.figures for n in (explore, experiment)}
    reply = h.ask_json(
        "writeup",
        tag="writeup",
        system=_SYSTEM,
        prompt=load_prompt(
            "popper.communicate",
            "writeup.md",
            keys="\n".join(f"- {k} = {format_value(v)}" for k, v in values.items()),
            framing=json.dumps(framing, indent=2),
            hypothesis=json.dumps(hypothesis, indent=2),
            analyses=f"Exploration:\n{explore.analysis}\n\nExperiment:\n{experiment.analysis}",
            figures=json.dumps(figures),
        ),
    )
    writeup = Writeup.model_validate(reply)
    placed = _copy_figures(h, writeup, [explore, experiment])
    tex, missing = fill_numbers(
        _ENV.get_template("paper.tex.j2").render(
            w=writeup,
            figures=placed,
            changes=[
                {k: latex_escape(str(c.get(k, ""))) for k in ("step", "rows_affected", "reason")}
                for c in changes
            ],
            data_code=data_node.code,
            experiment_code=experiment.code,
        ),
        values,
    )
    if missing:
        h.journal.write("numbers_missing", keys=missing)
    path = h.run.write_text("report/paper.tex", tex)
    return path, compile_pdf(path), missing
