"""Write historical reports using their original evidence and stability meanings."""

import json
import shutil
from functools import partial
from pathlib import Path
from typing import Any

from popper.harness.context.prompts import load_prompt
from popper.harness.context.rendering import ARTIFACT_CHARS, fence, part
from popper.harness.session import Harness
from popper.scientific.runtime.evidence.results import validate_results
from popper.stages.communicate.evidence import (
    artifact_path,
    evidence_rows,
    load_evidence,
    render_curve,
)
from popper.stages.communicate.numbers import (
    collect_values,
    entry_values,
)
from popper.stages.communicate.rendering import (
    _CODE_STAGES,
    _SYSTEM,
    _WRITER_RETRIES,
    _best_attempt,
    _commit_report,
    _copy_figures,
    _problems,
    _render_report,
    _unknown_figures,
    _violations,
)
from popper.stages.communicate.schema import Writeup
from popper.strategies.treesearch.engine import Node, load_nodes


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
        "popper.stages.communicate",
        "writeup.md",
        rules=load_prompt("popper.stages.communicate", "writeup_rules.md"),
        keys=fence("\n".join(f"- {k} = {v}" for k, v in values.items())),
        framing=context_part(
            "Framing", json.dumps(framing, indent=2), ARTIFACT_CHARS, untrusted=True
        ),
        research=context_part(
            "Research context", research or "(none)", ARTIFACT_CHARS, untrusted=True
        ),
        hypothesis=fence(json.dumps(hypothesis, indent=2)),
        analyses=context_part(
            "Analyses",
            f"Exploration:\n{explore.analysis}\n\nExperiments:\n"
            + "\n".join(f"{n.id}: {n.analysis}" for n in experiments),
            ARTIFACT_CHARS,
            untrusted=True,
        ),
        figures=fence(json.dumps(figures)),
        notes=context_part("Researcher notes", notes or "(none)", ARTIFACT_CHARS, untrusted=True),
    )
    prompt += "\nRecorded evidence and failed attempts:\n" + fence(json.dumps(manifest))
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
