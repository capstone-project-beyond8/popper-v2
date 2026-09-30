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
    failed_stage: str | None = None
    status: Literal["completed", "failed", "budget_exceeded"] = "failed"
    message = ""
    tex = pdf = None
    missing: list[str] = []
    try:
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
    return RunOutcome(store.root, status, tex, pdf, message, missing)
