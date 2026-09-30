"""Staged tree search adapted from AI-Scientist-v2: one node is one script run in a subprocess."""

import json
import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from popper.harness.config import Search
from popper.harness.interpreter import run_script
from popper.harness.prompts import load_prompt
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
    min_figures: int = 0
    check: Callable[[Path], str | None] | None = None
    describe: Callable[[Path], str] | None = None


class ResultEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: float | int | str
    ci: tuple[float, float] | None = None
    n: int | None = None
    note: str | None = None


_RESULTS = TypeAdapter(dict[str, ResultEntry])
_RESULT_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_CODE_MAX_TOKENS = 16000


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


def _task(spec: StageSpec, kind: NodeKind, parent: Node | None) -> str:
    if parent is None:
        if spec.seed_code:
            return f"Starting point to adapt:\n```python\n{spec.seed_code}\n```"
        return "Draft a new approach."
    head = f"Previous code:\n```python\n{parent.code}\n```"
    if kind == "improve":
        return f"Improve this working script.\n{head}\nAnalysis of its output:\n{parent.analysis}"
    return f"Fix this script.\n{head}\nWhat went wrong:\n{parent.analysis}"


def _read_results(workdir: Path) -> dict[str, dict[str, Any]]:
    """Validated results.json content; raises ValueError describing the first problem."""
    try:
        entries = _RESULTS.validate_json((workdir / "results.json").read_bytes())
    except OSError as exc:
        raise ValueError(f"results.json unreadable: {exc}") from exc
    for key in entries:
        if not _RESULT_KEY.match(key):
            raise ValueError(f"results.json key {key!r} must match [A-Za-z][A-Za-z0-9_]*")
    return {k: v.model_dump(mode="json", exclude_none=True) for k, v in entries.items()}


def _step(h: Harness, spec: StageSpec, i: int, kind: NodeKind, parent: Node | None) -> Node:
    node_id = f"{spec.name}-{i:03d}"
    limit = h.config.execution.max_output_chars
    prompt = load_prompt(
        "popper.treesearch",
        "node.md",
        goal=spec.goal,
        context=spec.context,
        inputs="\n".join(f"- POPPER_INPUT_{n.upper()} ({p.name})" for n, p in spec.inputs.items())
        or "- (none)",
        outputs="\n".join(f"- {o}" for o in spec.required_outputs),
        task=_task(spec, kind, parent),
    )
    try:
        reply = h.ask(
            "analyst",
            tag=f"code:{spec.name}",
            system=_SYSTEM,
            prompt=prompt,
            max_tokens=_CODE_MAX_TOKENS,
        )
        problem = ""
    except ValueError as exc:  # truncated reply
        reply, problem = "", str(exc)
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
    if problem:
        node.analysis = problem
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
    if len(list((node.dir / "figures").glob("*.png"))) < spec.min_figures:
        return f"expected at least {spec.min_figures} figure(s) in figures/"
    try:
        node.results = _read_results(node.dir)
    except ValueError as exc:
        return f"invalid results.json: {exc}"
    return (spec.check(node.dir) if spec.check else None) or ""


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
    if failed:
        node.results = {}
        node.analysis = f"Check failed: {failed}.\n{res.stderr}"
        return
    try:
        summary = spec.describe(node.dir) if spec.describe else "(none)"
    except Exception as exc:  # describe runs harness code over model-written outputs
        node.analysis = f"Check failed: could not summarise outputs: {exc}"
        return
    try:
        fb = h.ask_model(
            "judge",
            schema=Feedback,
            tag=f"feedback:{spec.name}",
            system=_SYSTEM,
            prompt=load_prompt(
                "popper.treesearch",
                "feedback.md",
                goal=spec.goal,
                code=node.code,
                stdout=res.stdout,
                results=json.dumps(node.results, indent=2),
                summary=summary,
            ),
        )
    except ValueError as exc:
        node.analysis = f"Invalid feedback reply: {exc}"
        return
    node.analysis = fb.analysis
    if not fb.is_buggy:
        node.status, node.score, node.goal_met = "ok", fb.score, fb.goal_met


def _plateaued(nodes: Sequence[Node], search: Search) -> bool:
    best = select_best(nodes)
    if best is None or best.score is None or best.score < search.good_score:
        return False
    before = select_best(nodes[: -search.patience])
    return len(nodes) > search.patience and before is not None and best is before


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
        if _plateaued(nodes, h.config.search):
            break
    best = select_best(nodes)
    h.journal.write("stage_end", stage=spec.name, best=best.id if best else None, steps=len(nodes))
    if best is None:
        raise StageFailed(spec.name)
    return best
