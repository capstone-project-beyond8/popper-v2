"""Dispatch Scientist requests and record operational outcomes."""

import json
import math
import secrets
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from popper.config import Config, load_config, scientific_options
from popper.harness.llm import LLM
from popper.harness.session import BudgetExceeded, Harness
from popper.harness.storage.records import ArtifactRef, resolve_artifact
from popper.harness.storage.recovery import load_state, read_events, recorded_spend
from popper.harness.storage.store import RunStore
from popper.scientific.runtime.data.descriptive import read_table
from popper.scientific.runtime.data.inputs import (
    ingest,
    load_episode,
    prepare_description,
    promote_foundation,
    require_current_format,
)
from popper.scientific.runtime.lifecycle.contracts import Disposition, StageAdmission
from popper.scientific.runtime.lifecycle.requests import CapabilityRequest
from popper.scientific.runtime.lifecycle.transitions import (
    EligibilityError,
    admit_stage,
    bind_stage_output,
    complete_stage,
    defer_stage,
    selected_move,
    stage_outputs,
)
from popper.scientific.runtime.projections.output import StudyOutput, build_study
from popper.scientific.runtime.projections.state import rebuild_state
from popper.scientific.runtime.projections.views import (
    foundation_view,
    node_ref,
    record_exploration,
    reviewed_frame,
)
from popper.scientific.runtime.settings import load_options
from popper.scientific.runtime.store import ScienceStore
from popper.scientific.scientist.episode import EpisodeContext, finish_episode, next_step
from popper.scientific.scientist.feedback import synthesize_state, update_direction
from popper.stages.communicate.paper import publish_study
from popper.stages.discover.explore import explore
from popper.stages.discover.ideas import evolve_ideas
from popper.stages.ground.steward import ground
from popper.stages.understand.frame import load_frame, understand
from popper.stages.understand.review import (
    ReviewOutcome,
    apply_review,
    approve_all,
    commit_review,
    load_review,
    write_review,
)
from popper.stages.verify.audit import audit_evidence
from popper.strategies.treesearch.engine import StageFailed
from popper.workflow.discovery import dispatch_discovery
from popper.workflow.resources import admit_move, resource_view


@dataclass(frozen=True)
class RunOutcome:
    run_dir: Path
    status: Literal["completed", "failed", "budget_exceeded", "awaiting_review"]
    tex: Path | None
    pdf: Path | None
    message: str
    missing: list[str]
    review: Path | None = None


class _AwaitingReview(Exception):
    def __init__(self, review: Path) -> None:
        self.review = review


def _phase(h: Harness, name: str) -> None:
    h.journal.write("phase", name=name)
    h.progress(f"[{name}] start · ${h.spent_usd:.2f}")


def run(
    research: Path,
    data: Path,
    *,
    config: Config,
    auto: bool = False,
    llm: LLM,
    researcher: Callable[[str, str], str | None] | None = None,
    runs_dir: Path,
    progress: Callable[[str], None] | None = None,
) -> RunOutcome:
    store = create_run(runs_dir, research, data, config=config, auto=auto)
    h = Harness(config, llm, store, researcher=None if auto else researcher)
    if progress is not None:
        h.progress = progress
    with store.lock():
        return _continue(h)


def _outcome(store: RunStore) -> RunOutcome:
    state = load_state(store)
    tex = pdf = None
    missing = state.get("missing", [])
    report = store.committed("report")
    if report:
        record = json.loads(report.read_text("utf-8"))
        tex = store.path(record["tex"])
        pdf = store.path(record["pdf"]) if record["pdf"] else None
        missing = record["missing"]
    review = store.path(state["review"]) if state.get("review") else None
    return RunOutcome(
        store.root, state["status"], tex, pdf, state.get("message", ""), missing, review
    )


def resume(
    run_dir: Path,
    *,
    llm: LLM,
    review: Path | None = None,
    researcher: Callable[[str, str], str | None] | None = None,
    progress: Callable[[str], None] | None = None,
    max_usd: float | None = None,
) -> RunOutcome:
    store = RunStore(run_dir)
    with store.lock():
        return _resume_locked(store, llm, review, progress, researcher, max_usd)


def _commits(store: RunStore) -> list[str]:
    """Artifact names in commit order; a later commit of a name supersedes the earlier one."""
    return [e["name"] for e in read_events(store.root) if e["event"] == "artifact_commit"]


def _latest(store: RunStore, *names: str) -> str | None:
    """Which of `names` was committed last, or None when none was."""
    return next((n for n in reversed(_commits(store)) if n in names), None)


def _pending_frame(store: RunStore) -> Path | None:
    """The committed frame the researcher has not reviewed yet."""
    return (
        store.committed("frame") if _latest(store, "frame", "frame_reviewed") == "frame" else None
    )


def _answer(store: RunStore, review: Path | None) -> ReviewOutcome | None:
    """The researcher's signals applied to the pending frame; no model call, errors raise."""
    committed = _pending_frame(store)
    if committed is None:
        return None
    columns = list(read_table(store.path("data", "raw.csv")).columns)
    frame = load_frame(committed)
    return apply_review(frame, load_review(review) if review else approve_all(frame), columns)


def _resume_locked(
    store: RunStore,
    llm: LLM,
    review: Path | None,
    progress: Callable[[str], None] | None,
    researcher: Callable[[str, str], str | None] | None,
    max_usd: float | None,
) -> RunOutcome:
    metadata = json.loads(store.path("run.json").read_text("utf-8"))
    require_current_format(metadata)
    state = load_state(store)
    config = Config.model_validate(metadata["config"])
    # The journal is authoritative; checkpoints project the latest explicit raise.
    raises = [e for e in read_events(store.root) if e["event"] == "budget_raise"]
    if raises:
        config.budget.max_usd = float(raises[-1]["max_usd"])
    spent = recorded_spend(store)
    if max_usd is not None and (
        not math.isfinite(max_usd)
        or max_usd <= max(config.budget.max_usd, spent)
        or state["status"] == "completed"
    ):
        raise ValueError(
            "money cap must be finite, above the current cap and recorded spend, on an unfinished run"
        )
    if review is not None and state["status"] != "awaiting_review":
        raise ValueError("the run is not awaiting review")
    if state["status"] == "completed":
        return _outcome(store)
    outcome = _answer(store, review) if state["status"] == "awaiting_review" else None
    h = Harness(
        config,
        llm,
        store,
        spent_usd=spent,
        researcher=None if metadata.get("auto") else researcher,
    )
    if max_usd is not None:
        h.journal.write(
            "budget_raise", old_max_usd=config.budget.max_usd, max_usd=max_usd, spent_usd=spent
        )
        config.budget.max_usd = max_usd
        store.checkpoint({**state, "max_usd": max_usd, "spent_usd": spent})
    if progress is not None:
        h.progress = progress
    h.journal.write("resume", spent_usd=h.spent_usd)
    return _continue(h, outcome)


def _accept_review(h: Harness, answered: ReviewOutcome | None, source: ArtifactRef) -> None:
    pending = resolve_artifact(h.run, source)
    if json.loads(h.run.path("run.json").read_text("utf-8")).get("auto"):
        h.run.commit_artifact("frame_reviewed", pending)
    elif answered is None:
        raise _AwaitingReview(write_review(load_frame(pending), h.run))
    else:
        _, report = prepare_description(ScienceStore(h.run))
        commit_review(h, answered, report)


def dispatch_selected(h: Harness, request: CapabilityRequest) -> CapabilityRequest | None:
    science = ScienceStore(h.run)
    assert request.selection is not None
    move = selected_move(science, request.selection)
    if move.action == "stop":
        disposition = science.commit("disposition", Disposition(kind="stopped", reason=move.stopping_condition, sources=[request.selection]), key=move.id)
        return finish_episode(science, move.stopping_condition, key=f"finish:{disposition.record_id}")
    deferred_name = f"science:disposition:admission:{request.selection.record_id}"
    if h.run.committed(deferred_name):
        ref = h.run.artifact_ref(deferred_name)
        disposition_record = Disposition.model_validate(science.read(ref))
        return finish_episode(science, disposition_record.reason, "budget_exceeded" if disposition_record.resource else "completed", key=f"finish:{ref.record_id}")
    admission = request.admission
    if admission is None and h.run.committed(f"science:admission:{request.selection.record_id}"):
        admission = h.run.artifact_ref(f"science:admission:{request.selection.record_id}")
    if admission is None:
        try:
            state = rebuild_state(science)
            admit_move(resource_view(h, load_options(h.run), state), state, move)
            admission = admit_stage(science, request.selection)
        except (BudgetExceeded, EligibilityError) as exc:
            disposition = defer_stage(science, request.selection, str(exc))
            return finish_episode(science, str(exc), "budget_exceeded" if isinstance(exc, BudgetExceeded) else "completed", key=f"finish:{disposition.record_id}")
    request = replace(request, admission=admission)
    work = StageAdmission.model_validate(science.read(admission))
    outputs = stage_outputs(science, admission)
    options = load_options(h.run)
    if outputs is None:
        _phase(h, {"frame": "framing", "publish": "publication"}.get(request.kind, request.kind))
        try:
            match request.kind:
                case "audit":
                    outputs = [audit_evidence(science, work.snapshot)]
                case "synthesize":
                    outputs = [synthesize_state(h, science, work.snapshot)]
                case "evolve":
                    outputs = evolve_ideas(h, science, admission)
                case "direct":
                    outputs = [update_direction(h, science, work.snapshot)]
                case "publish":
                    study = build_study(science, move.stopping_condition, key=f"publication:{admission.record_id}")
                    study_ref = h.run.artifact_ref("study")
                    publish_study(h, study)
                    outputs = [h.run.artifact_ref(f"report:{study_ref.sha256}")]
                case "frame":
                    research, report = prepare_description(science)
                    if request.guidance:
                        research = reviewed_frame(science).research
                        prepared = foundation_view(science, request.subject)
                        h.journal.write("reframe", concerns=[c["type"] for c in prepared.facts["concerns"] if c["kind"] == "frame"])
                    understand(h, research, report, limits=options.understand, guidance=request.guidance, admission=admission)
                    outputs = [h.run.artifact_ref("frame")]
                case "ground":
                    frame = reviewed_frame(science, request.subject)
                    ground(h, frame.research, frame.framing, limits=options.ground, admission=admission)
                    outputs = [h.run.artifact_ref("foundation")]
                case "explore":
                    promote_foundation(science, request.subject)
                    frame, prepared = reviewed_frame(science), foundation_view(science, request.subject)
                    node = explore(h, frame.research, frame.framing, prepared.facts, admission=admission)
                    outputs = [record_exploration(science, node_ref(science, node.dir / "meta.json"), admission=admission)]
                case "candidates" | "challenge" | "experiment":
                    dispatch_discovery(h, request)
                    outputs = stage_outputs(science, admission)
                    if outputs is None:
                        complete_stage(science, admission, "deferred", [], "Scientific feedback unavailable")
                        return finish_episode(science, "Scientific feedback unavailable")
                case _:
                    raise ValueError("selected request has no capability")
            if stage_outputs(science, admission) is None:
                bind_stage_output(science, admission, outputs)
            outputs = stage_outputs(science, admission)
            assert outputs is not None
        except EligibilityError as exc:
            complete_stage(science, admission, "deferred", [], str(exc))
            return finish_episode(science, str(exc), key=f"finish:{admission.record_id}")
        except StageFailed:
            complete_stage(science, admission, "failed", [], f"No accepted {request.kind} output")
            raise
    if request.kind in {"frame", "ground"}:
        alias = "frame" if request.kind == "frame" else "foundation"
        accepted = resolve_artifact(h.run, outputs[0])
        if h.run.committed(alias) != accepted:
            h.run.commit_artifact(alias, accepted)
    completed_status: Literal["completed", "failed"] = "failed" if request.kind == "experiment" and science.read(outputs[0]).get("status") == "failed" else "completed"
    complete_stage(science, admission, completed_status, outputs, f"Accepted {request.kind} output")
    if request.kind == "publish":
        return finish_episode(science, move.stopping_condition, key=f"finish:{admission.record_id}")
    return None


def _continue(h: Harness, answered: ReviewOutcome | None = None) -> RunOutcome:
    store = h.run
    failed_stage: str | None = None
    status: Literal["completed", "failed", "budget_exceeded", "awaiting_review"] = "failed"
    message = ""
    review_path: Path | None = None
    tex = pdf = None
    missing: list[str] = []
    try:
        science = ScienceStore(store)
        program, episode = load_episode(store)
        options = load_options(store)
        pending: CapabilityRequest | None = None
        while True:
            context = EpisodeContext(
                program, episode, resource_view(h, options, rebuild_state(science))
            )
            request = pending if pending is not None else next_step(h, science, context)
            pending = None
            if request is not None and request.subject is not None:
                resolve_artifact(store, request.subject)
            if request is None:
                continue
            if request.selection is not None:
                pending = dispatch_selected(h, request)
                continue
            match request.kind:
                case "frame":
                    _phase(h, "framing")
                    research, report = prepare_description(science)
                    if request.guidance:
                        frame = reviewed_frame(science)
                        research = frame.research
                        prepared = foundation_view(science, request.subject)
                        h.journal.write(
                            "reframe",
                            concerns=[
                                c["type"]
                                for c in prepared.facts["concerns"]
                                if c["kind"] == "frame"
                            ],
                        )
                    understand(
                        h, research, report, limits=options.understand, guidance=request.guidance
                    )
                case "await_review":
                    assert request.subject is not None
                    _accept_review(h, answered, request.subject)
                    answered = None
                case "ground":
                    _phase(h, "ground")
                    frame = reviewed_frame(science, request.subject)
                    ground(h, frame.research, frame.framing, limits=options.ground)
                case "explore":
                    _phase(h, "explore")
                    promote_foundation(science, request.subject)
                    frame, prepared = (
                        reviewed_frame(science),
                        foundation_view(science, request.subject),
                    )
                    node = explore(h, frame.research, frame.framing, prepared.facts)
                    record_exploration(science, node_ref(science, node.dir / "meta.json"))
                case "experiment":
                    _phase(h, "experiment")
                    pending = dispatch_discovery(h, request)
                case "candidates" | "challenge":
                    pending = dispatch_discovery(h, request)
                case "finish":
                    assert request.subject is not None and request.outcome is not None
                    output = StudyOutput.model_validate(science.read(request.subject))
                    status, message = request.outcome, output.stop_reason
                    if report_path := store.committed("report"):
                        record = json.loads(report_path.read_text("utf-8"))
                        missing = record["missing"]
                    break
                case "publish":
                    assert request.subject is not None
                    study = store.path(request.subject.path)
                    output = StudyOutput.model_validate_json(study.read_text("utf-8"))
                    _phase(h, "publication")
                    tex, pdf, missing = publish_study(h, study)
                    status = output.operational_status
                    message = output.stop_reason if status != "completed" else ""
                    if h.spent_usd >= h.config.budget.max_usd and any(
                        e["event"] == "publication_budget_stop"
                        and e.get("study_identity") == request.subject.sha256
                        for e in read_events(store.root)
                    ):
                        status = "budget_exceeded"
                    break
    except _AwaitingReview as waiting:
        status, review_path = "awaiting_review", waiting.review
    except StageFailed as exc:
        failed_stage = exc.stage
        message = f"stage {exc.stage} produced no working node"
        build_study(ScienceStore(h.run), message, "failed")
    except BudgetExceeded as exc:
        status, message = "budget_exceeded", str(exc)
        build_study(ScienceStore(h.run), message, status)
    except Exception as exc:
        message = repr(exc)
        raise
    finally:
        store.checkpoint(
            {
                "status": status,
                "message": message,
                "failed_stage": failed_stage,
                "spent_usd": h.spent_usd,
                "max_usd": h.config.budget.max_usd,
                "missing": missing,
                "review": review_path.relative_to(store.root).as_posix() if review_path else None,
                "artifacts": {
                    e["name"]: e["path"]
                    for e in read_events(store.root)
                    if e["event"] == "artifact_commit"
                },
            },
        )
    return _outcome(store)


def create_run(
    runs_dir: Path, research: Path, data: Path, *, config: Config | None = None, auto: bool = False
) -> RunStore:
    snapshot = config or load_config(env={})
    run_id = f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    store = RunStore(runs_dir / run_id)
    ingest(
        store,
        research,
        data,
        options=scientific_options(snapshot),
        config_payload=snapshot.model_dump(mode="json"),
        auto=auto,
    )
    return store
