"""Run the five phases in order and record the outcome."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from popper.communicate.paper import write_paper
from popper.discover.experiment import experiment
from popper.discover.explore import explore, propose_hypothesis
from popper.ground.steward import ground
from popper.harness.config import Config
from popper.harness.descriptive import describe_table, read_table
from popper.harness.llm import LLM
from popper.harness.recovery import load_state, read_events, recorded_spend
from popper.harness.research import parse_research
from popper.harness.session import BudgetExceeded, Harness
from popper.harness.store import RunStore
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
    store = RunStore.create(runs_dir, research, data, config=config, auto=auto)
    h = Harness(config, llm, store, researcher=researcher)
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
    progress: Callable[[str], None] | None = None,
) -> RunOutcome:
    store = RunStore(run_dir)
    with store.lock():
        return _resume_locked(store, llm, review, progress)


def _answer(store: RunStore, review: Path | None) -> ReviewOutcome | None:
    """The researcher's signals applied to the committed frame; no model call, errors raise."""
    committed = store.committed("frame")
    if committed is None or store.committed("frame_reviewed"):
        return None
    columns = list(read_table(store.path("data", "raw.csv")).columns)
    frame = load_frame(committed)
    return apply_review(frame, load_review(review) if review else approve_all(frame), columns)


def _resume_locked(
    store: RunStore, llm: LLM, review: Path | None, progress: Callable[[str], None] | None
) -> RunOutcome:
    metadata = json.loads(store.path("run.json").read_text("utf-8"))
    if metadata.get("format_version") == 3:
        raise ValueError("run format 3 is no longer supported; start a new run")
    if metadata.get("format_version") != 4:
        raise ValueError("unsupported run format; older runs cannot reserve unseen data or resume")
    state = load_state(store)
    if review is not None and state["status"] != "awaiting_review":
        raise ValueError("the run is not awaiting review")
    if state["status"] == "completed":
        return _outcome(store)
    outcome = _answer(store, review) if state["status"] == "awaiting_review" else None
    config = Config.model_validate(metadata["config"])
    h = Harness(config, llm, store, spent_usd=recorded_spend(store))
    if progress is not None:
        h.progress = progress
    h.journal.write("resume", spent_usd=h.spent_usd)
    return _continue(h, outcome)


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
        _phase(h, "framing")
        research = parse_research(store.path("research.md").read_text("utf-8"))
        report = describe_table(read_table(store.path("data", "raw.csv")), research)
        if not store.path("data", "ida-raw.json").exists():
            store.write_json(
                "data/ida-raw.json", {"results": report.results, "layout": report.layout}
            )
        reviewed = store.committed("frame_reviewed")
        if reviewed:
            frame = load_frame(reviewed)
        else:
            frame = understand(h, research, report)
            if json.loads(store.path("run.json").read_text("utf-8")).get("auto"):
                store.commit_artifact(
                    "frame_reviewed", store.path("understand", frame.attempt, "framing.json")
                )
            elif answered is None:
                raise _AwaitingReview(write_review(frame, store))
            else:
                frame = commit_review(h, answered, report)
        framing = frame.framing.model_dump()
        _phase(h, "ground")
        foundation = ground(h, frame.research, framing)
        _phase(h, "explore")
        explore_node = explore(h, framing)
        hypothesis = propose_hypothesis(h, framing, explore_node)
        _phase(h, "experiment")
        evidence = experiment(h, framing, hypothesis, foundation.preparation)
        _phase(h, "publication")
        changes = json.loads((foundation.preparation / "changes.json").read_text("utf-8"))
        tex, pdf, missing = write_paper(
            h, framing, changes, explore_node, hypothesis, evidence, foundation.preparation
        )
        status = "completed"
    except _AwaitingReview as waiting:
        status, review_path = "awaiting_review", waiting.review
    except StageFailed as exc:
        failed_stage = exc.stage
        message = f"stage {exc.stage} produced no working node"
    except BudgetExceeded as exc:
        status, message = "budget_exceeded", str(exc)
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
