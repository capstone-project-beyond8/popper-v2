"""Run the five phases in order and record the outcome."""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from popper.communicate.paper import write_paper
from popper.discover.experiment import experiment
from popper.discover.explore import explore, propose_hypothesis
from popper.ground.data import prepare
from popper.harness.config import Config
from popper.harness.llm import LLM
from popper.harness.recovery import load_state, recorded_spend
from popper.harness.session import BudgetExceeded, Harness
from popper.harness.store import RunStore
from popper.treesearch.engine import StageFailed
from popper.understand.framing import frame
from popper.understand.profile import profile_csv


@dataclass(frozen=True)
class RunOutcome:
    run_dir: Path
    status: Literal["completed", "failed", "budget_exceeded"]
    tex: Path | None
    pdf: Path | None
    message: str
    missing: list[str]


def _phase(h: Harness, name: str) -> None:
    h.journal.write("phase", name=name)
    h.progress(f"[{name}] start · ${h.spent_usd:.2f}")


def run(
    brief: Path,
    data: Path,
    *,
    config: Config,
    llm: LLM,
    runs_dir: Path,
    progress: Callable[[str], None] | None = None,
) -> RunOutcome:
    store = RunStore.create(runs_dir, brief, data, config=config)
    h = Harness(config, llm, store)
    if progress is not None:
        h.progress = progress
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
    return RunOutcome(store.root, state["status"], tex, pdf, state.get("message", ""), missing)


def resume(
    run_dir: Path, *, llm: LLM, progress: Callable[[str], None] | None = None,
) -> RunOutcome:
    store = RunStore(run_dir)
    metadata = json.loads(store.path("run.json").read_text("utf-8"))
    if metadata.get("format_version") != 2:
        raise ValueError("unsupported run format; older runs cannot reserve unseen data or resume")
    state = load_state(store)
    if state["status"] == "completed":
        return _outcome(store)
    config = Config.model_validate(metadata["config"])
    h = Harness(config, llm, store, spent_usd=recorded_spend(store))
    if progress is not None:
        h.progress = progress
    h.journal.write("resume", spent_usd=h.spent_usd)
    return _continue(h)


def _continue(h: Harness) -> RunOutcome:
    store = h.run
    failed_stage: str | None = None
    status: Literal["completed", "failed", "budget_exceeded"] = "failed"
    message = ""
    tex = pdf = None
    missing: list[str] = []
    try:
        if h.spent_usd >= h.config.budget.max_usd:
            raise BudgetExceeded(f"spent ${h.spent_usd:.4f} of ${h.config.budget.max_usd:.2f}")
        _phase(h, "framing")
        framing = frame(
            h, store.path("brief.md").read_text("utf-8"), profile_csv(store.path("data", "raw.csv"))
        )
        _phase(h, "data")
        data_node = prepare(h, framing)
        _phase(h, "explore")
        explore_node = explore(h, framing)
        hypothesis = propose_hypothesis(h, framing, explore_node)
        _phase(h, "experiment")
        evidence = experiment(h, framing, hypothesis, data_node)
        _phase(h, "publication")
        changes = json.loads((data_node.execution_dir / "changes.json").read_text("utf-8"))
        tex, pdf, missing = write_paper(
            h, framing, changes, explore_node, hypothesis, evidence, data_node
        )
        status = "completed"
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
            },
        )
    return _outcome(store)
