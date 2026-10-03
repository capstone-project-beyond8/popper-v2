"""Dispatch Scientist requests and record operational outcomes."""

import json
import math
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from popper.communicate.paper import publish_study
from popper.config import Config, load_config, scientific_options
from popper.coordinator.discovery import dispatch_experiment
from popper.coordinator.resources import resource_view
from popper.discover.explore import explore
from popper.ground.steward import ground
from popper.harness.llm import LLM
from popper.harness.records import ArtifactRef, resolve_artifact
from popper.harness.recovery import load_state, read_events, recorded_spend
from popper.harness.session import BudgetExceeded, Harness
from popper.harness.store import RunStore
from popper.science.compatibility import decode_policy
from popper.science.descriptive import read_table
from popper.science.inputs import ingest, load_episode, prepare_description, promote_foundation
from popper.science.output import StudyOutput, partial_study
from popper.science.requests import CapabilityRequest
from popper.science.settings import load_options
from popper.science.state import rebuild_state
from popper.science.store import ScienceStore
from popper.science.views import foundation_view, node_ref, record_exploration, reviewed_frame
from popper.scientist.episode import EpisodeContext, next_step
from popper.treesearch.engine import StageFailed
from popper.understand.frame import load_frame, understand
from popper.understand.review import (
    ReviewOutcome,
    apply_review,
    approve_all,
    commit_review,
    load_review,
    write_review,
)


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
    if metadata.get("format_version") == 3:
        raise ValueError("run format 3 is no longer supported; start a new run")
    decode_policy(metadata)
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


def _continue(h: Harness, answered: ReviewOutcome | None = None) -> RunOutcome:
    store = h.run
    failed_stage: str | None = None
    status: Literal["completed", "failed", "budget_exceeded", "awaiting_review"] = "failed"
    message = ""
    review_path: Path | None = None
    tex = pdf = None
    missing: list[str] = []
    try:
        if h.spent_usd >= h.config.budget.max_usd:
            raise BudgetExceeded(f"spent ${h.spent_usd:.4f} of ${h.config.budget.max_usd:.2f}")
        science = ScienceStore(store)
        program, episode = load_episode(store)
        policy = decode_policy(json.loads(store.path("run.json").read_text("utf-8")))
        options = load_options(store)
        pending: CapabilityRequest | None = None
        while True:
            context = EpisodeContext(
                program, episode, resource_view(h, options, rebuild_state(science)), policy, options
            )
            request = pending if pending is not None else next_step(h, science, context)
            pending = None
            if request is not None and request.subject is not None:
                resolve_artifact(store, request.subject)
            if request is None:
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
                    pending = dispatch_experiment(h, request)
                case "publish" | "finish":
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
        if partial := partial_study(ScienceStore(h.run), message, "failed"):
            tex, pdf, missing = publish_study(h, partial)
    except BudgetExceeded as exc:
        status, message = "budget_exceeded", str(exc)
        if partial := partial_study(ScienceStore(h.run), message, status):
            tex, pdf, missing = publish_study(h, partial)
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
