"""Publish committed studies."""

import json
from pathlib import Path
from typing import Any

from popper.harness.context.prompts import load_prompt
from popper.harness.context.rendering import fence
from popper.harness.session import BudgetExceeded, Harness
from popper.harness.storage.records import ArtifactRef, resolve_artifact
from popper.scientific.runtime.data.research import render_fields
from popper.scientific.runtime.evidence.references import resolve_measurement
from popper.scientific.runtime.evidence.results import validate_results
from popper.scientific.runtime.projections.output import StudyOutput, publication_inputs
from popper.scientific.runtime.projections.views import (
    exploration_view,
    foundation_view,
    reviewed_frame,
)
from popper.scientific.runtime.store import ScienceStore
from popper.stages.communicate.limitations import audit_limitations
from popper.stages.communicate.numbers import (
    entry_values,
    latex_escape,
)
from popper.stages.communicate.rendering import (
    _SYSTEM,
    _WRITER_RETRIES,
    _best_attempt,
    _commit_report,
    _copy_figures,
    _problems,
    _render_report,
    _violations,
)
from popper.stages.communicate.schema import Writeup
from popper.strategies.treesearch.engine import Node, load_nodes


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
        committed = resolve_artifact(h.run, h.run.artifact_ref(f"report:{identity}"))
        if h.run.committed("report") != committed:
            h.run.commit_artifact("report", committed)
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
        for child in publication_inputs(ScienceStore(h.run), source, alias):
            rel = child.path
            content = json.loads(resolve_artifact(h.run, child).read_text("utf-8"))
            if Path(rel).name == "changes.json" and alias == "data":
                changes = content
            elif Path(rel).name == "results.json":
                for name, entry in validate_results(content).items():
                    values.update(entry_values(f"{alias}.{name}", entry))
    rows = []
    test_sources: dict[str, ArtifactRef] = {}
    for item in output.usable_measurements:
        measurement = resolve_measurement(h.run, item.ref)
        assert item.ref.artifact.backing is not None
        metadata = json.loads(resolve_artifact(h.run, item.ref.artifact.backing).read_text("utf-8"))
        if metadata.get("test_ref"):
            source = ArtifactRef.model_validate(metadata["test_ref"])
            test_sources[source.model_dump_json()] = source
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
                science = ScienceStore(h.run)
                source_context: dict[str, Any] = {}
                if output.frame:
                    frame = reviewed_frame(science, output.frame)
                    source_context["reviewed_frame"] = {
                        "source": output.frame.model_dump(mode="json"),
                        "framing": frame.framing,
                        "research": frame.research.model_dump(mode="json"),
                    }
                if output.foundation:
                    source_context["foundation"] = {
                        "source": output.foundation.model_dump(mode="json"),
                        "facts": foundation_view(science, output.foundation).facts,
                    }
                if output.exploration:
                    exploration = exploration_view(science, output.exploration)
                    source_context["exploration"] = {
                        "source": output.exploration.model_dump(mode="json"),
                        "analysis": exploration.analysis,
                    }
                candidate_sources = {c.source.model_dump_json(): c.source for c in output.candidates}
                source_context["candidate_sets"] = [
                    {"source": ref.model_dump(mode="json"), "record": science.read(ref)}
                    for ref in candidate_sources.values()
                ]
                for ref in output.attempts:
                    attempt_record = science.read(ref)
                    test_ref = ArtifactRef.model_validate(attempt_record["test"])
                    test_sources[test_ref.model_dump_json()] = test_ref
                source_context["test_declarations"] = [
                    {"source": ref.model_dump(mode="json"), "record": science.read(ref)}
                    for ref in test_sources.values()
                ]
                prompt = load_prompt(
                    "popper.stages.communicate", "study_writeup.md",
                    rules=load_prompt("popper.stages.communicate", "writeup_rules.md"),
                    study=fence(output.model_dump_json()),
                    source_context=fence(json.dumps(source_context)),
                    numbers=fence(json.dumps(values)),
                    figures=fence(json.dumps({n.id: n.figures for n in nodes.values()})),
                    notes=fence(notes or "(none)"), research=fence(research or "(none)"),
                )
                candidate = h.ask_model(
                    "writer", schema=Writeup, tag="writeup", system=_SYSTEM, prompt=prompt
                )
                candidates: list[tuple[int, int, Writeup, Path]] = []
                for i in range(_WRITER_RETRIES + 1):
                    prefix = report_dir.relative_to(h.run.root).as_posix()
                    trial = h.run.write_json(
                        f"{prefix}/writeup-{i:03d}.json", candidate.model_dump(mode="json")
                    )
                    problems = _problems(candidate, values, list(nodes.values()))
                    if not _violations(candidate):
                        candidates.append((len(problems.splitlines()), i, candidate, trial))
                    if not problems or i == _WRITER_RETRIES:
                        break
                    candidate = h.ask_model(
                        "writer",
                        schema=Writeup,
                        tag="writeup",
                        system=_SYSTEM,
                        prompt=prompt + "\nCorrect: " + problems,
                    )
                if candidates:
                    _, _, writeup, saved = _best_attempt(candidates, [])
            except BudgetExceeded:
                h.journal.write("publication_budget_stop", study_identity=identity)
                writeup = diagnostic_writeup(output)
        prefix = report_dir.relative_to(h.run.root).as_posix()
        if saved is None:
            saved = h.run.write_json(f"{prefix}/writeup.json", writeup.model_dump(mode="json"))
        h.run.commit_artifact(writeup_name, saved)
    placed = _copy_figures(h, writeup, list(nodes.values()), report_dir)
    prefix = report_dir.relative_to(h.run.root).as_posix()
    for node in nodes.values():
        h.run.write_text(f"{prefix}/code/{node.id}.py", node.code)
    steered = output.frame is not None and (
        resolve_artifact(h.run, output.frame).parent / "provenance.json"
    ).exists()
    tex, missing = _render_report(writeup, changes, list(nodes.values()), rows, output.model_dump(mode="json"), placed, values, audit_limitations(output.audits), [], steered)
    return _commit_report(h, report_dir, tex, missing, identity=identity)


def publish_study(h: Harness, study: Path) -> tuple[Path, Path | None, list[str]]:
    """Render the committed study behind one publication capability."""
    science = ScienceStore(h.run)
    output = StudyOutput.model_validate_json(study.read_text("utf-8"))
    notes = research = ""
    if output.frame:
        frame = reviewed_frame(science, output.frame)
        notes = frame.research.notes.get("writing", "")
        research = render_fields(frame.research, "domain", "objectives", "assumptions")
    return write_study(h, study, notes=notes, research=research)
