"""Ground: one Data Steward session prepares the data; the harness re-runs and checks its script."""
import json
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal, get_args

import pandas as pd
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

from popper.harness.agents.loop import Tool, agent_loop
from popper.harness.context.prompts import load_prompt
from popper.harness.context.rendering import (
    ARTIFACT_CHARS,
    RESEARCH_CHARS,
    fence,
    part,
    valid_names,
)
from popper.harness.session import Harness
from popper.harness.storage.records import ArtifactRef, resolve_artifact
from popper.harness.storage.store import next_sequence
from popper.scientific.runtime.data.descriptive import (
    DescriptiveReport,
    describe_input,
    describe_table,
    format_description,
)
from popper.scientific.runtime.data.research import ResearchContext, render_research
from popper.scientific.runtime.evidence.results import validate_results
from popper.scientific.runtime.lifecycle.contracts import StageAdmission
from popper.scientific.runtime.lifecycle.transitions import bind_stage_output
from popper.scientific.runtime.settings import Ground, load_options
from popper.scientific.runtime.store import ScienceStore
from popper.strategies.treesearch.engine import StageFailed
from popper.strategies.treesearch.tools import node_tools

FrameConcern = Literal[
    "unmeasured_concept", "weak_proxy", "unit_mismatch", "missing_variable", "scope_conflict"
]
DataConcern = Literal["quality", "sample", "structure", "other"]
_FRAME_CONCERNS = set(get_args(FrameConcern))
_OUTPUTS = ("processed.parquet", "changes.json", "results.json")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Operationalization(_Model):
    concept_id: str
    columns: list[str]
    proxy_strength: Literal["direct", "proxy", "weak", "none"]
    rationale: str


class Concern(_Model):
    type: FrameConcern | DataConcern
    kind: Literal["frame", "data"] = Field(
        description="Use frame for unmeasured_concept, weak_proxy, unit_mismatch, "
        "missing_variable or scope_conflict; use data for quality, sample, structure or other.",
    )
    description: str
    evidence: list[str] = Field(
        description="Exact names of existing results.json entries, changes.json steps or raw "
        "descriptive result keys. Never use research-body quotes, prose, column names or "
        "invented keys. For example, use rows_after only if your script reports that entry.",
    )

    @model_validator(mode="after")
    def _kind_matches_type(self) -> "Concern":
        expected = "frame" if self.type in _FRAME_CONCERNS else "data"
        if self.kind != expected:
            raise ValueError(f"concern type {self.type} has kind {expected}, not {self.kind}")
        return self


class SubmitGroundInput(_Model):
    code: str = Field(
        pattern=r"\S",
        description="Complete Python preparation script writing processed.parquet, changes.json "
        "and results.json. Every result is an object with a value field, for example "
        '{"rows_before": {"value": 10}, "rows_after": {"value": 8}}, not bare numbers. '
        "changes.json rows_affected names one of these reported integer count entries.",
    )
    operationalization: list[Operationalization]
    concerns: list[Concern]

class Change(_Model):
    step: str
    rows_affected: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


@dataclass
class Foundation:
    """The accepted preparation and what the data agent concluded about it."""

    preparation: Path
    operationalization: list[Operationalization]
    concerns: list[Concern]
    readiness: dict[str, Any]
    attempt: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "operationalization": [o.model_dump() for o in self.operationalization],
            "concerns": [c.model_dump() for c in self.concerns],
            "readiness": self.readiness,
            "attempt": self.attempt,
        }


def _check_changes(workdir: Path, results: dict[str, dict[str, Any]]) -> list[Change]:
    try:
        changes = TypeAdapter(list[Change]).validate_json((workdir / "changes.json").read_bytes())
    except (OSError, ValueError) as exc:
        raise ValueError(f"invalid changes.json: {exc}") from exc
    for change in changes:
        if change.rows_affected not in results:
            raise ValueError(
                f"rows_affected {change.rows_affected!r} has no entry in results.json; "
                "report that count there under the same key; "
                + valid_names(results, "results.json")
            )
        value = results[change.rows_affected]["value"]
        if type(value) is not int or value < 0:
            raise ValueError(
                f"{change.rows_affected} must be a nonnegative integer count in results.json"
            )
    return changes


def _check_mapping(
    processed: pd.DataFrame, research: ResearchContext, operationalization: list[Operationalization]
) -> None:
    concepts = {c.id for c in research.concepts}
    unknown = sorted({o.concept_id for o in operationalization} - concepts)
    if unknown:
        raise ValueError(
            f"operationalization names unknown concepts: {', '.join(unknown)}; "
            f"the frame's concept ids are: {', '.join(sorted(concepts))}"
        )
    uncovered = sorted(concepts - {o.concept_id for o in operationalization})
    if uncovered:
        raise ValueError(
            f"operationalization misses concepts: {', '.join(uncovered)} (use proxy_strength none)"
        )
    seen: set[str] = set()
    for item in operationalization:
        if item.concept_id in seen:
            raise ValueError(f"operationalization lists concept {item.concept_id} more than once")
        seen.add(item.concept_id)
        if (item.proxy_strength == "none") != (not item.columns):
            raise ValueError(
                f"operationalization of {item.concept_id}: proxy_strength none goes with "
                "no columns, and any other strength needs columns"
            )
        missing = [c for c in item.columns if c not in processed.columns]
        if missing:
            raise ValueError(
                f"operationalization of {item.concept_id} uses columns not in "
                f"processed.parquet: {', '.join(missing)}; "
                + valid_names(processed.columns, "processed.parquet columns")
            )


def check_submission(
    workdir: Path,
    research: ResearchContext,
    operationalization: list[Operationalization],
    concerns: list[Concern],
    ida_raw: DescriptiveReport,
) -> str | None:
    """The first problem in a submitted preparation run, or None when it is acceptable."""
    try:
        try:
            results = validate_results(json.loads((workdir / "results.json").read_bytes()))
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid results.json: {exc}") from exc
        if not {"rows_before", "rows_after"} <= results.keys():
            raise ValueError("results.json must report rows_before and rows_after")
        try:
            processed = pd.read_parquet(workdir / "processed.parquet")
        except (OSError, ValueError) as exc:
            raise ValueError(f"processed.parquet is unreadable: {exc}") from exc
        if processed.empty:
            raise ValueError("processed.parquet has no rows")
        reported = results["rows_after"]["value"]
        if reported != len(processed):
            raise ValueError(
                f"rows_after {reported} does not match processed.parquet ({len(processed)} rows)"
            )
        changes = _check_changes(workdir, results)
        lost = [
            name
            for name, v in research.variables.items()
            if v.role.status == "confirmed"
            and v.role.value == "outcome"
            and name not in processed.columns
        ]
        if lost:
            raise ValueError(
                "outcome column(s) the researcher confirmed are missing from "
                f"processed.parquet: {', '.join(lost)}"
            )
        _check_mapping(processed, research, operationalization)
        known = {*results, *(c.step for c in changes), *ida_raw.results}
        for concern in concerns:
            stray = [e for e in concern.evidence if e not in known]
            if stray:
                raise ValueError(
                    f"concern evidence {', '.join(map(repr, stray))} is not a result key, "
                    "change step or descriptive result key; "
                    + valid_names(results, "results.json")
                    + "; "
                    + valid_names((c.step for c in changes), "changes.json steps")
                    + "; "
                    + valid_names(ida_raw.results, "Raw data description")
                )
    except ValueError as exc:
        return str(exc)
    return None


def readiness(processed: pd.DataFrame, research: ResearchContext) -> dict[str, Any]:
    """Facts about each declared or proposed outcome and exposure; they never block."""
    report = describe_table(processed, research)
    keys = {c["name"]: c["key"] for c in report.layout["columns"]}
    facts: dict[str, Any] = {"rows": len(processed), "columns": {}}
    if "cluster_count" in report.results:
        facts["cluster_count"] = report.results["cluster_count"]["value"]
    for name, variable in research.variables.items():
        role = variable.role.value
        if role not in ("outcome", "exposure"):
            continue
        fact: dict[str, Any] = {"role": role, "present": name in keys}
        if name in keys:
            for field in ("constant", "missing_share", "floor_share", "ceiling_share"):
                entry = report.results.get(f"{keys[name]}_{field}")
                if entry is not None:
                    fact[field] = bool(entry["value"]) if field == "constant" else entry["value"]
        facts["columns"][name] = fact
    return facts


def describe_submission(
    path: Path, research: ResearchContext
) -> tuple[DescriptiveReport, dict[str, Any]]:
    """The description and readiness of an accepted table; any failure is a rejection."""
    try:
        processed = pd.read_parquet(path)
        return describe_table(processed, research), readiness(processed, research)
    except Exception as exc:  # the agent can fix its table, so no failure may crash the run
        raise ValueError(f"Check failed: processed data could not be described: {exc}") from exc


def _tools(
    h: Harness,
    attempt: Path,
    research: ResearchContext,
    inputs: dict[str, Path],
    ida_raw: DescriptiveReport,
    accepted: dict[str, Any],
) -> list[Tool]:
    def submit_ground(args: SubmitGroundInput) -> str:
        code, operationalization, concerns = args.code, args.operationalization, args.concerns
        folder = attempt / f"submit-{next_sequence(attempt, prefix='submit-'):02d}"
        workdir = folder / "execution"
        res = h.execute(
            code,
            workdir,
            inputs=inputs,
            node=f"{attempt.name}/{folder.name}",
            purpose="submitted",
        )
        failed = ""
        if res.timed_out:
            failed = "timed out"
        elif res.exit_code != 0:
            failed = f"exit code {res.exit_code}"
        else:
            absent = [o for o in _OUTPUTS if not (workdir / o).exists()]
            if absent:
                failed = f"missing required output {', '.join(absent)}"
        if failed:
            log = (workdir / "stderr.txt").relative_to(h.run.root).as_posix()
            raise ValueError(
                f"Check failed: {failed}.\n{res.stderr}\n"
                f'Full stderr: read_artifact({{"path": "{log}", "offset": 0}}).'
            )
        problem = check_submission(workdir, research, operationalization, concerns, ida_raw)
        if problem:
            raise ValueError(f"Check failed: {problem}.")
        report, facts = describe_submission(workdir / "processed.parquet", research)
        accepted.update(
            preparation=workdir,
            operationalization=operationalization,
            concerns=concerns,
            report=report,
            readiness=facts,
        )
        return "Preparation accepted."

    return [
        *(t for t in node_tools(h, inputs, attempt, describe_input=describe_input, artifact_roots={name: h.run.root for name in ("results.json", "analysis.md", "changes.json", "framing.json", "hypotheses.json")}) if not t.terminal),
        Tool.from_model(
            "submit_ground",
            "Submit the complete preparation script with the operationalization and concerns. "
            "The harness re-runs the script from scratch; only that run counts. A rejected "
            "submit returns the reason. Call it once the preparation is complete.",
            SubmitGroundInput,
            submit_ground,
            terminal=True,
        ),
    ]


def load_foundation(h: Harness) -> Foundation | None:
    """The committed foundation, rebuilt from its attempt folder; None before acceptance."""
    committed = h.run.committed("foundation")
    if committed is None:
        return None
    folder = committed.parent
    record = json.loads(committed.read_text("utf-8"))
    return Foundation(
        h.run.path(record["preparation"]),
        TypeAdapter(list[Operationalization]).validate_json(
            (folder / "operationalization.json").read_bytes()
        ),
        TypeAdapter(list[Concern]).validate_json((folder / "concerns.json").read_bytes()),
        json.loads((folder / "readiness.json").read_text("utf-8")),
        folder.name,
    )


def ground(h: Harness, research: ResearchContext, framing: dict[str, Any], *, limits: Ground | None = None, admission: ArtifactRef | None = None) -> Foundation:
    run = h.run
    science = ScienceStore(run)
    if admission:
        work = StageAdmission.model_validate(science.read(admission))
        name = f"science:accepted:{work.id}:ground"
        if run.committed(name):
            ref = run.artifact_ref(name)
            bind_stage_output(science, admission, [ref])
            if run.committed("foundation") != resolve_artifact(run, ref):
                run.commit_artifact("foundation", resolve_artifact(run, ref))
            accepted_foundation = load_foundation(h)
            assert accepted_foundation is not None
            return accepted_foundation
    attempt = run.new_attempt("ground")
    ida_raw = DescriptiveReport(**json.loads(run.path("data", "ida-raw.json").read_text("utf-8")))
    inputs = {"raw": run.path("data", "raw.csv")}
    context_part = partial(part, journal=h.journal, tag="steward")
    task = load_prompt(
        "popper.stages.ground",
        "steward.md",
        research=context_part("Research context", render_research(research), RESEARCH_CHARS, untrusted=True),
        framing=context_part("Framing", json.dumps(framing, indent=2), RESEARCH_CHARS, untrusted=True),
        description=context_part(
            "Raw data description", format_description(ida_raw), ARTIFACT_CHARS, untrusted=True
        ),
        notes=context_part(
            "Researcher notes", research.notes.get("ground", "(none)"), RESEARCH_CHARS, untrusted=True
        ),
    )  # fmt: skip
    task += "\nValid concept ids, columns and evidence keys:\n" + fence(
        json.dumps(
            {
                "concept_ids": [c.id for c in research.concepts],
                "columns": [
                    {"name": c["name"], "key": c["key"]} for c in ida_raw.layout["columns"]
                ],
                "result_keys": list(ida_raw.results),
            }
        )
    )
    accepted: dict[str, Any] = {}
    config = limits or load_options(h.run).ground
    submitted = agent_loop(
        h,
        "steward",
        tag="steward",
        system="You prepare discovery data and assess measurement validity before relationship-seeking exploration.",
        task=task,
        tools=_tools(h, attempt, research, inputs, ida_raw, accepted),
        max_turns=config.max_turns,
        max_submits=config.max_submits,
    )
    if submitted is None:
        raise StageFailed("ground")
    preparation: Path = accepted["preparation"]
    report: DescriptiveReport = accepted["report"]
    foundation = Foundation(
        preparation,
        accepted["operationalization"],
        accepted["concerns"],
        accepted["readiness"],
        attempt.name,
    )
    rel = attempt.relative_to(run.root).as_posix()
    ida = json.dumps({"results": report.results, "layout": report.layout}, indent=2, default=str)
    run.write_text(f"{rel}/ida.json", ida)
    body = foundation.as_dict()
    run.write_json(f"{rel}/operationalization.json", body["operationalization"])
    run.write_json(f"{rel}/concerns.json", body["concerns"])
    run.write_json(f"{rel}/readiness.json", body["readiness"])
    path = run.write_json(
        f"{rel}/foundation.json", {"preparation": preparation.relative_to(run.root).as_posix(), **({"admission": admission.model_dump(mode="json")} if admission else {})}
    )
    if admission:
        run.commit_artifact(name, path)
        bind_stage_output(science, admission, [run.artifact_ref(name)])
    run.commit_artifact("foundation", path)
    return foundation
