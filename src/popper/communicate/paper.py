"""Write the LaTeX report: prose from the model, numbers from results.json, the rest from code."""

import json
import re
import shutil
import subprocess
import tempfile
from functools import partial
from pathlib import Path
from typing import Any, Literal

from jinja2 import Environment, PackageLoader
from pydantic import BaseModel, ConfigDict

from popper.communicate.evidence import artifact_path, evidence_rows, load_evidence, render_curve
from popper.communicate.numbers import (
    collect_values,
    entry_values,
    explain_missing,
    fill_numbers,
    latex_escape,
)
from popper.harness.context import ARTIFACT_CHARS, part
from popper.harness.prompts import load_prompt
from popper.harness.records import ArtifactRef, StudyOutput, resolve_artifact, resolve_measurement
from popper.harness.results import validate_results
from popper.harness.session import BudgetExceeded, Harness
from popper.harness.store import next_sequence
from popper.treesearch.engine import Node, load_nodes
from popper.treesearch.judge import validate_image

_SYSTEM = "You are a careful scientific writer."
_CODE_STAGES = ("baseline", "main", "robustness")
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

    node_id: str
    file: str
    caption: str
    section: Literal["data_methods", "exploratory", "main", "robustness"]


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
    robustness: str
    discussion: str
    conclusion: str
    figures: list[FigureRef]


_LABELS = re.compile(r"\b(stable|fragile|confirmed)\b", re.IGNORECASE)
_STRUCTURE = re.compile(r"\\(?:section|subsection|includegraphics|label)(?![A-Za-z])")
_PRIMITIVES = re.compile(
    r"\\(?:input|include|InputIfFileExists|openin|openout|read|write|immediate|verbatiminput"
    r"|lstinputlisting|catcode|csname|def|let|newcommand|renewcommand)(?![A-Za-z])"
)

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
    sequence = next_sequence(tex.parent, prefix="build-")
    build = tex.parent / f"build-{sequence:06d}"
    with tempfile.TemporaryDirectory(prefix="popper-latex-") as directory:
        scratch = Path(directory)
        shutil.copyfile(tex, scratch / tex.name)
        for folder in ("figures", "code"):
            if (tex.parent / folder).exists():
                shutil.copytree(tex.parent / folder, scratch / folder)
        ok, output = _compile(scratch / tex.name, found)
        (scratch / "compile.log").write_text(
            output.decode("utf-8", errors="replace"), encoding="utf-8"
        )
        shutil.copytree(scratch, build)
    pdf = build / tex.with_suffix(".pdf").name
    return pdf if ok and pdf.exists() else None


def _compile(tex: Path, found: tuple[str, tuple[str, ...], int]) -> tuple[bool, bytes]:
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
            return False, output + (exc.stdout or b"")
        output += done.stdout or b""
        if done.returncode != 0:
            ok = False
            break
    return ok, output


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


def write_paper(
    h: Harness,
    framing: dict[str, Any],
    changes: list[dict[str, Any]],
    explore: Node,
    hypothesis: dict[str, Any],
    evidence: Path,
    preparation: Path,
    *,
    limitations: list[str],
    operationalization: list[dict[str, Any]],
    steered: bool = False,
    notes: str = "",
    research: str = "",
) -> tuple[Path, Path | None, list[str]]:
    committed = h.run.committed("report")
    if committed:
        record = json.loads(committed.read_text("utf-8"))
        return (
            h.run.path(record["tex"]),
            h.run.path(record["pdf"]) if record["pdf"] else None,
            record["missing"],
        )
    report_dir = h.run.new_attempt("report")
    manifest = load_evidence(evidence, h.run.root)
    experiments = [n for stage in ("baseline", "main", "robustness") for n in load_nodes(h, stage)]
    nodes = [explore, *experiments]
    values = collect_values(nodes, selected={**manifest["selected"], "explore": explore.id})
    prepared = validate_results(json.loads((preparation / "results.json").read_text("utf-8")))
    for name, entry in prepared.items():
        values.update(entry_values(f"data.{name}", entry))
    summary = json.loads(artifact_path(h.run.root, manifest["summary"]).read_text("utf-8"))
    values.update({f"summary.{key}": entry["value"] for key, entry in summary.items()})
    rows = evidence_rows(manifest, h.run.root)
    curve = h.run.committed("curve")
    if curve is None:
        curve = render_curve(h, rows, report_dir)
        h.run.commit_artifact("curve", curve)
    figures = {n.id: n.figures for n in nodes if n.figures}
    context_part = partial(part, journal=h.journal, tag="writeup")
    prompt = load_prompt(
        "popper.communicate",
        "writeup.md",
        keys="\n".join(f"- {k} = {v}" for k, v in values.items()),
        framing=context_part(
            "Framing", json.dumps(framing, indent=2), ARTIFACT_CHARS, untrusted=True
        ),
        research=context_part(
            "Research context", research or "(none)", ARTIFACT_CHARS, untrusted=True
        ),
        hypothesis=json.dumps(hypothesis, indent=2),
        analyses=context_part(
            "Analyses",
            f"Exploration:\n{explore.analysis}\n\nExperiments:\n"
            + "\n".join(f"{n.id}: {n.analysis}" for n in experiments),
            ARTIFACT_CHARS,
            untrusted=True,
        ),
        figures=json.dumps(figures),
        notes=context_part("Researcher notes", notes or "(none)", ARTIFACT_CHARS, untrusted=True),
    )
    prompt += "\nRecorded evidence and failed attempts:\n" + json.dumps(manifest)
    saved_writeup = h.run.committed("writeup")
    if saved_writeup:
        writeup = Writeup.model_validate_json(saved_writeup.read_bytes())
    else:
        writeup = h.ask_model(
            "writer", schema=Writeup, tag="writeup", system=_SYSTEM, prompt=prompt
        )
        candidates: list[tuple[int, int, Writeup, Path]] = []
        for i in range(_WRITER_RETRIES + 1):
            prefix = report_dir.relative_to(h.run.root).as_posix()
            saved_writeup = h.run.write_json(
                f"{prefix}/writeup-{i:03d}.json", writeup.model_dump(mode="json")
            )
            problems = _problems(writeup, values, nodes)
            violations = _violations(writeup)
            if not violations:
                candidates.append((len(problems.splitlines()), i, writeup, saved_writeup))
            if not problems or i == _WRITER_RETRIES:
                _, _, writeup, saved_writeup = _best_attempt(candidates, violations)
                if unknown := _unknown_figures(writeup, nodes):
                    h.journal.write(
                        "figures_dropped", refs=[f"{r.node_id}/{r.file}" for r in unknown]
                    )
                h.run.commit_artifact("writeup", saved_writeup)
                break
            retry = (
                f"{prompt}\n\nYour previous reply had these problems:\n{problems}\n"
                "Fix them and reply again with the full JSON."
            )
            writeup = h.ask_model(
                "writer", schema=Writeup, tag="writeup", system=_SYSTEM, prompt=retry
            )
    placed = _copy_figures(h, writeup, nodes, report_dir)
    curve_target = report_dir / "figures" / "specification-curve.png"
    curve_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(curve, curve_target)
    placed.append(
        {
            "id": "specification-curve",
            "path": "figures/specification-curve.png",
            "caption": "Every successful recorded attempt; placebo estimates use distinct markers.",
            "section": "robustness",
        }
    )
    prefix = report_dir.relative_to(h.run.root).as_posix()
    for node in experiments:
        if node.status == "ok" and node.stage in _CODE_STAGES:
            h.run.write_text(f"{prefix}/code/{node.id}.py", node.code)
    tex, missing = _render_report(
        writeup,
        changes,
        experiments,
        rows,
        manifest,
        placed,
        values,
        limitations,
        operationalization,
        steered,
    )
    if missing:
        h.journal.write("numbers_missing", keys=missing)
    return _commit_report(h, report_dir, tex, missing)


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
    pdf = compile_pdf(path)
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


def diagnostic_writeup(study: StudyOutput) -> Writeup:
    findings = []
    for measurement in study.usable_measurements:
        ref = measurement.ref
        key = f"{ref.test_id}.{measurement.role}.{ref.result_key}"
        findings.append(
            latex_escape(f"{ref.hypothesis_id}, {measurement.role}: ")
            + rf"\R{{{key}}} (interval \R{{{key}.ci}}). "
            + latex_escape(f"Fidelity {measurement.fidelity}; support {measurement.support}.")
        )
    return Writeup(
        title="Exploratory research study" if findings else "Research diagnostic report",
        abstract="Available committed observations and remaining uncertainty.",
        introduction="Sequential discovery on the reviewed research frame.",
        data="Only discovery inputs were provided to analysis.",
        exploration="Candidate origins cite committed exploration and framing records.",
        hypothesis="All selected and untested candidate hypotheses are retained below.",
        methods="Intended tests and actual implementations have distinct recorded identities.",
        results="\n\n".join(findings)
        if findings
        else "No accepted usable measurements. No empirical findings are available.",
        robustness="Coverage, fidelity, sensitivity and support are reported separately. Missing work is unavailable evidence.",
        discussion=latex_escape(study.stop_reason),
        conclusion="These observations remain exploratory; no held-back verification standing is granted.",
        figures=[],
    )


def write_study(
    h: Harness, study: Path, *, notes: str = "", research: str = ""
) -> tuple[Path, Path | None, list[str]]:
    output = StudyOutput.model_validate_json(study.read_text("utf-8"))
    ref = h.run.artifact_ref("study")
    if resolve_artifact(h.run, ref) != study:
        raise ValueError("publication must cite the exact committed study output")
    identity = ref.sha256
    committed = h.run.committed(f"report:{identity}")
    if committed:
        record = json.loads(committed.read_text("utf-8"))
        return (
            h.run.path(record["tex"]),
            h.run.path(record["pdf"]) if record["pdf"] else None,
            record["missing"],
        )
    report_dir = h.run.new_attempt("report")
    values: dict[str, Any] = {}
    nodes: dict[str, Node] = {}
    changes: list[dict[str, Any]] = []
    for source, alias in ((output.preparation, "data"), (output.exploration, "explore")):
        if source is None:
            continue
        manifest = json.loads(resolve_artifact(h.run, source).read_text("utf-8"))
        for rel, digest in manifest.get("files", {}).items():
            if Path(rel).name not in {"results.json", "changes.json"}:
                continue
            child = ArtifactRef(
                path=rel,
                sha256=digest,
                producer=source.producer,
                record_id=source.record_id,
                backing=source,
            )
            content = json.loads(resolve_artifact(h.run, child).read_text("utf-8"))
            if Path(rel).name == "changes.json" and alias == "data":
                changes = content
            elif Path(rel).name == "results.json":
                for name, entry in validate_results(content).items():
                    values.update(entry_values(f"{alias}.{name}", entry))
    rows = []
    for item in output.usable_measurements:
        measurement = resolve_measurement(h.run, item.ref)
        assert item.ref.artifact.backing is not None
        metadata = json.loads(resolve_artifact(h.run, item.ref.artifact.backing).read_text("utf-8"))
        if metadata["id"] not in nodes:
            nodes[metadata["id"]] = next(
                n for n in load_nodes(h, metadata["stage_instance"]) if n.id == metadata["id"]
            )
        entry = measurement.model_dump(mode="json", exclude_none=True)
        key = f"{item.ref.test_id}.{item.role}.{item.ref.result_key}"
        if key in values:
            raise ValueError("ambiguous active scientific measurement")
        values.update(entry_values(key, entry))
        node_id = Path(item.ref.artifact.path).parent.parent.name
        values.update(entry_values(f"{node_id}.{item.ref.result_key}", entry))
        rows.append(
            {
                "id": item.ref.execution_id,
                "stage": item.role,
                "attempt_id": item.ref.test_id,
                "key": key,
                "adversarial": item.ref.result_key == "placebo_estimate",
            }
        )
    writeup_name = f"writeup:{identity}"
    saved = h.run.committed(writeup_name)
    writeup = Writeup.model_validate_json(saved.read_bytes()) if saved else None
    if writeup is None:
        writeup = diagnostic_writeup(output)
        if h.spent_usd < h.config.budget.max_usd and output.usable_measurements:
            try:
                prompt = (
                    "Write an exploratory report using this committed study. Preserve untested, failed, "
                    "negative and invalidated work; distinguish fidelity, support, coverage and sensitivity. "
                    "All empirical numbers use \\R{key} macros. No legacy stability label.\n"
                    f"Study: {output.model_dump_json()}\nNamed numbers: {json.dumps(values)}\n"
                    f"Available figures: {json.dumps({n.id: n.figures for n in nodes.values()})}\n"
                    f"Notes: {notes}\nResearch: {research}"
                )
                candidate = h.ask_model(
                    "writer", schema=Writeup, tag="writeup", system=_SYSTEM, prompt=prompt
                )
                for _ in range(_WRITER_RETRIES):
                    problems = _problems(candidate, values, list(nodes.values()))
                    if not problems:
                        break
                    candidate = h.ask_model(
                        "writer",
                        schema=Writeup,
                        tag="writeup",
                        system=_SYSTEM,
                        prompt=prompt + "\nCorrect: " + problems,
                    )
                if not _violations(candidate):
                    writeup = candidate
            except BudgetExceeded:
                h.journal.write("publication_budget_stop", study_identity=identity)
                writeup = diagnostic_writeup(output)
        prefix = report_dir.relative_to(h.run.root).as_posix()
        saved = h.run.write_json(f"{prefix}/writeup.json", writeup.model_dump(mode="json"))
        h.run.commit_artifact(writeup_name, saved)
    manifest = {
        "adaptive": True,
        "study": output.model_dump(mode="json"),
        "nodes": [],
        "specifications": [],
        "stability": "",
        "reasons": [],
    }
    placed = _copy_figures(h, writeup, list(nodes.values()), report_dir)
    prefix = report_dir.relative_to(h.run.root).as_posix()
    for node in nodes.values():
        h.run.write_text(f"{prefix}/code/{node.id}.py", node.code)
    tex, missing = _render_report(writeup, changes, list(nodes.values()), rows, manifest, placed, values, [], [], False)
    return _commit_report(h, report_dir, tex, missing, identity=identity)
