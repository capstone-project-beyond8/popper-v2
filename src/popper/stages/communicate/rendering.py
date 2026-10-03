"""Validate prose and figures, render reports and commit publication artifacts."""

import re
import shutil
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader

from popper.harness.session import Harness
from popper.stages.communicate import compiler
from popper.stages.communicate.evidence import (
    artifact_path,
)
from popper.stages.communicate.numbers import (
    explain_missing,
    fill_numbers,
    latex_escape,
)
from popper.stages.communicate.schema import FigureRef, Writeup
from popper.strategies.treesearch.engine import Node
from popper.strategies.treesearch.judge import validate_image

_SYSTEM = "You are a careful scientific writer."


_CODE_STAGES = ("baseline", "main", "robustness")


_WRITER_RETRIES = 2  # re-asks when the prose cites numbers that have no value


_ENV = Environment(
    loader=PackageLoader("popper.stages.communicate", "templates"),
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


_LABELS = re.compile(r"\b(stable|fragile|confirmed)\b", re.IGNORECASE)


_STRUCTURE = re.compile(r"\\(?:section|subsection|includegraphics|label)(?![A-Za-z])")


_PRIMITIVES = re.compile(
    r"\\(?:input|include|InputIfFileExists|openin|openout|read|write|immediate|verbatiminput"
    r"|lstinputlisting|catcode|csname|def|let|newcommand|renewcommand)(?![A-Za-z])"
)


def _known_figure(ref: FigureRef, nodes: list[Node]) -> Node | None:
    if Path(ref.file).name != ref.file:
        return None
    return next((n for n in nodes if n.id == ref.node_id and ref.file in n.figures), None)


def _select_figures(refs: list[FigureRef], nodes: list[Node]) -> list[tuple[Node, FigureRef]]:
    """Known figures only, deduplicated, ordered by stage and capped at three."""
    selected: list[tuple[Node, FigureRef]] = []
    seen = set()
    for ref in refs:
        node = _known_figure(ref, nodes)
        if node is not None and (node.id, ref.file) not in seen:
            selected.append((node, ref))
            seen.add((node.id, ref.file))
    order = {"explore": 0, "baseline": 1, "main": 2, "robustness": 3}
    return sorted(selected, key=lambda item: order[item[0].stage])[:3]


def _copy_figures(
    h: Harness, writeup: Writeup, nodes: list[Node], report_dir: Path
) -> list[dict[str, str]]:
    placed: list[dict[str, str]] = []
    for i, (node, ref) in enumerate(_select_figures(writeup.figures, nodes)):
        name = f"{node.id}-{ref.file}"
        target = report_dir / "figures" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        source = artifact_path(
            h.run.root,
            (node.execution_dir / "figures" / ref.file).relative_to(h.run.root).as_posix(),
        )
        shutil.copyfile(validate_image(source), target)
        placed.append(
            {
                "id": f"{node.id}-{i}",
                "path": f"figures/{name}",
                "caption": ref.caption,
                "section": ref.section,
            }
        )
    return placed


def _texts(writeup: Writeup) -> dict[str, str]:
    texts = {k: str(v) for k, v in writeup.model_dump().items() if k != "figures"}
    texts.update({f"caption-{i}": f.caption for i, f in enumerate(writeup.figures)})
    return texts


def _violations(writeup: Writeup) -> list[str]:
    """Evidence labels, structure commands and file primitives, which code alone may supply."""
    lines = []
    for name, text in _texts(writeup).items():
        if found := _LABELS.search(text):
            lines.append(
                f"{name}: the word '{found.group(0)}' is an evidence label inserted by code; "
                "rephrase without stable, fragile or confirmed"
            )
        if found := _STRUCTURE.search(text):
            lines.append(f"{name}: {found.group(0)} is supplied by code; remove it")
        if found := _PRIMITIVES.search(text):
            lines.append(f"{name}: {found.group(0)} is not allowed in prose; remove it")
    return lines


def _unknown_figures(writeup: Writeup, nodes: list[Node]) -> list[FigureRef]:
    return [ref for ref in writeup.figures if _known_figure(ref, nodes) is None]


def _problems(writeup: Writeup, values: dict[str, Any], nodes: list[Node]) -> str:
    """Numbers without a value, unbalanced math, forbidden commands and unknown figures."""
    texts = _texts(writeup)
    _, unresolved = fill_numbers("\n".join(texts.values()), values)
    lines = [explain_missing(ref, values) for ref in unresolved]
    lines += [
        f"{name}: odd number of $ signs; close every inline formula"
        for name, text in texts.items()
        if len(re.findall(r"(?<!\\)\$", text)) % 2
    ]
    lines += _violations(writeup)
    lines += [
        f"figure {ref.node_id}/{ref.file} does not exist; choose only listed files"
        for ref in _unknown_figures(writeup, nodes)
    ]
    return "\n".join(f"- {line}" for line in lines)


def _best_attempt(
    candidates: list[tuple[int, int, Writeup, Path]], violations: list[str]
) -> tuple[int, int, Writeup, Path]:
    """The violation-free attempt with the fewest problem lines; the later one on a tie."""
    if not candidates:
        raise ValueError("writer kept forbidden content:\n" + "\n".join(violations))
    return min(candidates, key=lambda c: (c[0], -c[1]))


def _section_content(text: str, figures: list[dict[str, str]]) -> str:
    paragraphs = text.split("\n\n")
    for f in figures:
        reference = rf"\ref{{fig:{f['id']}}}"
        index = next((i for i, p in enumerate(paragraphs) if reference in p), 0)
        if reference not in paragraphs[index]:
            paragraphs[index] += f" See Figure~{reference}."
        paragraphs[index] += "\n" + (
            "\\begin{figure}[ht]\n\\centering\n"
            rf"\includegraphics[width=0.8\textwidth]{{{f['path']}}}" + "\n"
            rf"\caption{{{f['caption']}}}\label{{fig:{f['id']}}}" + "\n\\end{figure}"
        )
    return "\n\n".join(paragraphs)


def _render_report(
    w: Writeup,
    changes: list[dict[str, Any]],
    nodes: list[Node],
    rows: list[dict[str, Any]],
    manifest: dict[str, Any],
    figures: list[dict[str, str]],
    values: dict[str, Any],
    limitations: list[str],
    operationalization: list[dict[str, Any]],
    steered: bool,
) -> tuple[str, list[str]]:
    sections = {
        "data_methods": "\n\n".join((w.data, w.hypothesis, w.methods)),
        "exploratory": w.exploration,
        "main": w.results,
        "robustness": w.robustness,
    }
    sections = {
        name: _section_content(text, [f for f in figures if f["section"] == name])
        for name, text in sections.items()
    }
    failures = [
        f"{n['id']}: no successful committed evaluation"
        for n in manifest["nodes"]
        if n["status"] != "ok"
    ]
    failures += [
        f"{a['id']}: no successful specification result"
        for a in manifest["specifications"]
        if a["node"] is None
    ]
    study = manifest.get("study")
    if study:
        study = {
            **study,
            "stop_reason": latex_escape(study["stop_reason"]),
            "candidates": [
                {**c, "id": latex_escape(c["id"]), "statement": latex_escape(c["statement"])}
                for c in study["candidates"]
            ],
            "attempt_history": [
                {
                    **a,
                    "id": latex_escape(a["id"]),
                    "hypothesis_id": latex_escape(a["hypothesis_id"]),
                }
                for a in study["attempt_history"]
            ],
            "diagnoses": [
                {**d, "record": {**d["record"], "reason": latex_escape(d["record"]["reason"])}}
                for d in study["diagnoses"]
            ],
            "dispositions": [
                {**d, "record": {**d["record"], "reason": latex_escape(d["record"]["reason"])}}
                for d in study["dispositions"]
            ],
            "selection_history": [
                {
                    **s,
                    "rationale": latex_escape(s["rationale"]),
                    "proposal_id": latex_escape(s["proposal_id"]),
                }
                for s in study["selection_history"]
            ],
            "measurement_history": [
                {
                    **m,
                    "support": latex_escape(m["support"]),
                    "fidelity_reason": latex_escape(m["fidelity_reason"]),
                    "ref": {**m["ref"], "test_id": latex_escape(m["ref"]["test_id"])},
                }
                for m in study["measurement_history"]
            ],
            "challenges": [
                {
                    **c,
                    "record": {
                        **c["record"],
                        "author": latex_escape(c["record"]["author"]),
                        "assessments": [
                            {
                                **a,
                                "hypothesis_id": latex_escape(a["hypothesis_id"]),
                                "assessment": latex_escape(a["assessment"]),
                                **{
                                    key: [latex_escape(text) for text in a[key]]
                                    for key in ("concerns", "rivals", "discriminating_checks")
                                },
                            }
                            for a in c["record"]["assessments"]
                        ],
                    },
                }
                for c in study.get("challenges", [])
            ],
            "interpretations": [
                {
                    **i,
                    "stale": i["ref"] in study.get("stale_interpretations", []),
                    "record": {
                        **i["record"],
                        **{
                            key: latex_escape(i["record"][key])
                            for key in ("author", "hypothesis_id", "summary")
                        },
                        **{
                            key: [latex_escape(text) for text in i["record"][key]]
                            for key in ("rivals", "limitations", "questions")
                        },
                    },
                }
                for i in study.get("interpretations", [])
            ],
        }
    tex = _ENV.get_template("paper.tex.j2").render(
        w=w,
        sections=sections,
        stability=manifest["stability"],
        reasons=[latex_escape(r) for r in manifest["reasons"]],
        failures=[latex_escape(f) for f in failures],
        rows=[
            {
                **row,
                "identity": latex_escape(row["id"]),
                "specification": latex_escape(row.get("attempt_id") or row["stage"]),
                "marker": "placebo" if row["adversarial"] else "ordinary",
            }
            for row in rows
        ],
        changes=[
            {
                "step": latex_escape(str(c["step"])),
                "reason": latex_escape(str(c["reason"])),
                "rows_affected": rf"\R{{data.{c['rows_affected']}}}",
            }
            for c in changes
        ],
        operationalization=[
            {
                "concept": latex_escape(str(o.get("concept") or o["concept_id"])),
                "columns": latex_escape(", ".join(o["columns"])),
                "strength": latex_escape(o["proxy_strength"]),
            }
            for o in operationalization
        ],
        limitations=[latex_escape(item) for item in limitations],
        steered=steered,
        experiment_nodes=[n for n in nodes if n.stage in _CODE_STAGES and n.status == "ok"],
        adaptive=manifest.get("adaptive", False),
        study=study,
    )
    return fill_numbers(tex, values)


def _commit_report(
    h: Harness,
    report_dir: Path,
    tex: str,
    missing: list[str],
    *,
    identity: str | None = None,
) -> tuple[Path, Path | None, list[str]]:
    prefix = report_dir.relative_to(h.run.root).as_posix()
    path = h.run.write_text(f"{prefix}/paper.tex", tex)
    pdf = compiler.compile_pdf(path)
    record_path = h.run.write_json(
        f"{prefix}/report.json",
        {
            "tex": path.relative_to(h.run.root).as_posix(),
            "pdf": pdf.relative_to(h.run.root).as_posix() if pdf else None,
            "missing": missing,
            **({"study_identity": identity} if identity else {}),
        },
    )
    h.run.commit_artifact("report", record_path)
    if identity:
        h.run.commit_artifact(f"report:{identity}", record_path)
    return path, pdf, missing
