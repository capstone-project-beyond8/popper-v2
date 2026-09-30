"""Staged tree search adapted from AI-Scientist-v2: one node is one script run in a subprocess."""

import json
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from popper.harness.config import Search
from popper.harness.interpreter import run_script
from popper.harness.session import Harness

NodeKind = Literal["draft", "debug", "improve"]

_CODE_BLOCK = re.compile(r"```python\s*(.*?)```", re.DOTALL)
_SYSTEM = "You are a careful data scientist. Follow the format instructions exactly."


@dataclass
class Node:
    id: str
    stage: str
    parent: str | None
    kind: NodeKind
    debug_depth: int
    dir: Path
    code: str
    status: Literal["ok", "buggy"]
    score: float | None
    goal_met: bool
    analysis: str
    results: dict[str, dict[str, Any]]
    figures: list[str]


@dataclass(frozen=True)
class StageSpec:
    name: str
    goal: str
    context: str
    inputs: Mapping[str, Path]
    required_outputs: tuple[str, ...]
    seed_code: str | None = None


class Feedback(BaseModel):
    is_buggy: bool
    analysis: str
    score: float = Field(ge=1, le=10)
    goal_met: bool


class StageFailed(Exception):
    def __init__(self, stage: str) -> None:
        super().__init__(f"stage {stage!r} produced no working node")
        self.stage = stage


def select_best(nodes: Sequence[Node]) -> Node | None:
    best: Node | None = None
    for node in nodes:
        if node.status == "ok" and node.score is not None:
            if best is None or best.score is None or node.score > best.score:
                best = node
    return best


def choose_action(
    nodes: Sequence[Node], search: Search, rng: random.Random
) -> tuple[NodeKind, Node | None]:
    if sum(n.parent is None for n in nodes) < search.num_drafts:
        return "draft", None
    parents = {n.parent for n in nodes}
    debuggable = [
        n
        for n in nodes
        if n.status == "buggy" and n.debug_depth < search.max_debug_depth and n.id not in parents
    ]
    best = select_best(nodes)
    if debuggable and (best is None or rng.random() < search.debug_prob):
        return "debug", rng.choice(debuggable)
    if best:
        return "improve", best
    return "draft", None


def _prompt(name: str, **fields: str) -> str:
    return (files("popper.treesearch") / "prompts" / name).read_text("utf-8").format(**fields)


def _task(spec: StageSpec, kind: NodeKind, parent: Node | None) -> str:
    if parent is None:
        if spec.seed_code:
            return f"Starting point to adapt:\n```python\n{spec.seed_code}\n```"
        return "Draft a new approach."
    head = f"Previous code:\n```python\n{parent.code}\n```"
    if kind == "improve":
        return f"Improve this working script.\n{head}\nAnalysis of its output:\n{parent.analysis}"
    return f"Fix this script.\n{head}\nWhat went wrong:\n{parent.analysis}"


def _read_results(workdir: Path) -> dict[str, dict[str, Any]] | None:
    try:
        data = json.loads((workdir / "results.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and all(isinstance(v, dict) and "value" in v for v in data.values()):
        return data
    return None


def _step(h: Harness, spec: StageSpec, i: int, kind: NodeKind, parent: Node | None) -> Node:
    node_id = f"{spec.name}-{i:03d}"
    limit = h.config.execution.max_output_chars
    reply = h.ask(
        "code",
        tag=f"code:{spec.name}",
        system=_SYSTEM,
        prompt=_prompt(
            "node.md",
            goal=spec.goal,
            context=spec.context,
            inputs="\n".join(f"- POPPER_INPUT_{n.upper()}" for n in spec.inputs) or "- (none)",
            outputs="\n".join(f"- {o}" for o in spec.required_outputs),
            task=_task(spec, kind, parent),
        ),
    )
    node = Node(
        id=node_id,
        stage=spec.name,
        parent=parent.id if parent else None,
        kind=kind,
        debug_depth=parent.debug_depth + 1 if kind == "debug" and parent else 0,
        dir=h.run.path("tree", spec.name, node_id),
        code="",
        status="buggy",
        score=None,
        goal_met=False,
        analysis="no code block in reply",
        results={},
        figures=[],
    )
    match = _CODE_BLOCK.search(reply)
    if match:
        node.code = match.group(1)
        _execute(h, spec, node, limit)
    meta = {k: v for k, v in asdict(node).items() if k not in ("code", "results", "dir")}
    h.run.write_json(f"tree/{spec.name}/{node_id}/meta.json", meta)
    h.run.write_text(f"tree/{spec.name}/{node_id}/analysis.md", node.analysis)
    return node


def _failed_check(spec: StageSpec, node: Node, exit_code: int | None, timed_out: bool) -> str:
    if timed_out:
        return "timed out"
    if exit_code != 0:
        return f"exit code {exit_code}"
    for output in spec.required_outputs:
        if not (node.dir / output).exists():
            return f"missing required output {output}"
    return ""


def _execute(h: Harness, spec: StageSpec, node: Node, limit: int) -> None:
    res = run_script(
        node.code,
        node.dir,
        timeout=h.config.execution.timeout_seconds,
        inputs=spec.inputs,
        max_output_chars=limit,
    )
    h.journal.write(
        "exec",
        node=node.id,
        exit_code=res.exit_code,
        timed_out=res.timed_out,
        seconds=res.seconds,
    )
    node.figures = sorted(p.name for p in (node.dir / "figures").glob("*.png"))
    failed = _failed_check(spec, node, res.exit_code, res.timed_out)
    results = _read_results(node.dir)
    if not failed and results is None:
        failed = "results.json is not an object of objects with a value"
    if failed or results is None:
        node.analysis = f"Check failed: {failed}.\n{res.stderr}"
        return
    node.results = results
    reply = h.ask_json(
        "feedback",
        tag=f"feedback:{spec.name}",
        system=_SYSTEM,
        prompt=_prompt(
            "feedback.md",
            goal=spec.goal,
            code=node.code,
            stdout=res.stdout,
            results=json.dumps(results, indent=2),
        ),
    )
    try:
        fb = Feedback.model_validate(reply)
    except ValidationError as exc:
        node.analysis = f"Invalid feedback reply: {exc}"
        return
    node.analysis = fb.analysis
    if not fb.is_buggy:
        node.status, node.score, node.goal_met = "ok", fb.score, fb.goal_met


def run_stage(h: Harness, spec: StageSpec, rng: random.Random | None = None) -> Node:
    rng = rng or random.Random()
    steps = h.config.search.steps_per_stage
    h.journal.write("stage_start", stage=spec.name, steps=steps)
    nodes: list[Node] = []
    for i in range(steps):
        kind, parent = choose_action(nodes, h.config.search, rng)
        nodes.append(_step(h, spec, i, kind, parent))
        if nodes[-1].status == "ok" and nodes[-1].goal_met:
            break
    best = select_best(nodes)
    h.journal.write("stage_end", stage=spec.name, best=best.id if best else None, steps=len(nodes))
    if best is None:
        raise StageFailed(spec.name)
    return best
