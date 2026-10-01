"""Run the five phases in order and record the outcome."""

import json
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from popper.communicate.paper import write_paper
from popper.coordinator.limitations import limitations
from popper.discover.experiment import experiment
from popper.discover.explore import explore, propose_hypothesis
from popper.ground.steward import Concern, Foundation, ground, load_foundation
from popper.harness.config import Config
from popper.harness.descriptive import DescriptiveReport, describe_table, read_table
from popper.harness.llm import LLM
from popper.harness.recovery import load_state, read_events, recorded_spend
from popper.harness.research import ResearchContext, parse_research
from popper.harness.session import BudgetExceeded, Harness
from popper.harness.store import RunStore
from popper.treesearch.engine import StageFailed
from popper.understand.frame import Frame, load_frame, understand
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


def _reviewed_frame(
    h: Harness, research: ResearchContext, report: DescriptiveReport, answered: ReviewOutcome | None
) -> Frame:
    """The latest frame once reviewed: asks the Theorist when none exists, else stops for review."""
    store = h.run
    if _latest(store, "frame", "frame_reviewed") is None:
        understand(h, research, report)
    pending = _pending_frame(store)
    if pending is not None:
        if json.loads(store.path("run.json").read_text("utf-8")).get("auto"):
            store.commit_artifact("frame_reviewed", pending)
        elif answered is None:
            raise _AwaitingReview(write_review(load_frame(pending), store))
        else:
            return commit_review(h, answered, report)
    reviewed = store.committed("frame_reviewed")
    assert reviewed is not None
    return load_frame(reviewed)


def _foundation(h: Harness, frame: Frame) -> Foundation:
    """The foundation of the reviewed frame; Ground runs again whenever the frame is newer."""
    if _latest(h.run, "foundation", "frame_reviewed") == "foundation":
        existing = load_foundation(h)
        assert existing is not None
        return existing
    return ground(h, frame.research, frame.framing.model_dump())


def _reframes(store: RunStore) -> int:
    return max(_commits(store).count("frame") - 1, 0)


def _guidance(concerns: list[Concern], frame: Frame) -> str:
    lines = ["The data steward found that the data cannot represent the current frame:"]
    lines += [f"- {c.type}: {c.description} (evidence: {', '.join(c.evidence)})" for c in concerns]
    lines.append(
        "Revise the frame so the study stays answerable with this data: narrow the scope, "
        "reword questions or concepts, or state what is unmeasured."
    )
    lines.append(f"Current framing:\n{json.dumps(frame.framing.model_dump(), indent=2)}")
    return "\n".join(lines)


def _promote(store: RunStore, foundation: Foundation) -> None:
    """Publish the final foundation's table and description as the run's data files."""
    for name in ("processed.parquet", "ida.json"):
        store.copy_once(foundation.preparation / name, f"data/{name}").chmod(stat.S_IREAD)


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
        frame = _reviewed_frame(h, research, report, answered)
        while True:
            _phase(h, "ground")
            foundation = _foundation(h, frame)
            concerns = [c for c in foundation.concerns if c.kind == "frame"]
            if not concerns or _reframes(store) >= h.config.understand.max_reframes:
                break
            h.journal.write("reframe", concerns=[c.type for c in concerns])
            understand(h, frame.research, report, guidance=_guidance(concerns, frame))
            frame = _reviewed_frame(h, research, report, None)
        _promote(store, foundation)
        framing = frame.framing.model_dump()
        facts = foundation.as_dict()
        notes = frame.research.notes
        _phase(h, "explore")
        explore_node = explore(h, frame.research, framing, facts)
        hypothesis = propose_hypothesis(h, frame.research, framing, facts, explore_node)
        _phase(h, "experiment")
        evidence = experiment(
            h, framing, hypothesis, foundation.preparation, notes.get("experiment", "")
        )
        _phase(h, "publication")
        changes = json.loads((foundation.preparation / "changes.json").read_text("utf-8"))
        committed = store.committed("hypothesis")
        assert committed is not None
        warnings = json.loads((committed.parent / "warnings.json").read_text("utf-8"))
        reviewed = store.committed("frame_reviewed")
        assert reviewed is not None
        names = {c.id: c.name.value for c in frame.research.concepts}
        tex, pdf, missing = write_paper(
            h,
            framing,
            changes,
            explore_node,
            hypothesis,
            evidence,
            foundation.preparation,
            limitations=limitations(facts, warnings),
            operationalization=[
                {**o, "concept": names.get(o["concept_id"]) or o["concept_id"]}
                for o in facts["operationalization"]
            ],
            steered=(reviewed.parent / "provenance.json").exists(),
            notes=notes.get("writing", ""),
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
