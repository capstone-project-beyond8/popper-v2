"""Run the five phases in order and record the outcome."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from popper.communicate.paper import write_paper
from popper.discover.experiment import experiment
from popper.discover.explore import explore
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


def run(brief: Path, data: Path, *, config: Config, llm: LLM, runs_dir: Path) -> RunOutcome:
    store = RunStore.create(runs_dir, brief, data)
    h = Harness(config, llm, store)
    status: Literal["completed", "failed", "budget_exceeded"] = "failed"
    message = ""
    tex = pdf = None
    missing: list[str] = []
    try:
        h.journal.write("phase", name="framing")
        framing = frame(
            h, store.path("brief.md").read_text("utf-8"), profile_csv(store.path("data", "raw.csv"))
        )
        h.journal.write("phase", name="data")
        data_node = prepare(h, framing)
        h.journal.write("phase", name="explore")
        explore_node, hypothesis = explore(h, framing)
        h.journal.write("phase", name="experiment")
        experiment_node = experiment(h, framing, hypothesis, explore_node.code)
        h.journal.write("phase", name="publication")
        changes = json.loads((data_node.dir / "changes.json").read_text("utf-8"))
        tex, pdf, missing = write_paper(
            h, framing, changes, explore_node, hypothesis, experiment_node, data_node
        )
        status = "completed"
    except StageFailed as exc:
        message = f"stage {exc.stage} produced no working node"
    except BudgetExceeded as exc:
        status, message = "budget_exceeded", str(exc)
    except Exception as exc:
        message = repr(exc)
        raise
    finally:
        store.write_json(
            "run.json",
            {
                "status": status,
                "message": message,
                "config": config.model_dump(mode="json"),
                "inputs": {"brief": str(brief), "data": str(data)},
                "spent_usd": h.spent_usd,
                "missing": missing,
            },
        )
    return RunOutcome(store.root, status, tex, pdf, message, missing)
