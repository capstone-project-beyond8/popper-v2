"""Staged tree search adapted from AI-Scientist-v2: one node is one script run in a subprocess."""

import json
import random
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from popper.harness.agent import agent_loop
from popper.harness.config import Search
from popper.harness.context import ARTIFACT_CHARS, CODE_CHARS, part
from popper.harness.execution import ExecutionBinding
from popper.harness.llm import LLMError
from popper.harness.prompts import load_prompt
from popper.harness.records import ArtifactRef
from popper.harness.recovery import read_events
from popper.harness.session import Harness
from popper.harness.store import file_hash
from popper.treesearch.judge import JudgeReference, judge_input, make_diagnostic
from popper.treesearch.tools import node_tools

NodeKind = Literal["draft", "debug", "improve", "variant", "adversarial"]

_SYSTEM = "You are a careful data scientist."


def _validate_execution_id(value: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", value) or re.fullmatch(
        r"con|prn|aux|nul|com[1-9]|lpt[1-9]", value
    ):
        raise ValueError(f"unsafe stage execution identity: {value!r}")


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
    reason: str
    attempt_id: str | None = None
    seed_node: str | None = None
    stage_instance: str | None = None
    test_ref: ArtifactRef | None = None
    hypothesis_id: str | None = None
    test_id: str | None = None
    implementation_id: str | None = None
    execution_id: str | None = None
    outputs: dict[str, str] = field(default_factory=dict)
    fidelity: dict[str, Any] = field(default_factory=dict)
    check_observations: list[dict[str, Any]] = field(default_factory=list)

    @property
    def execution_dir(self) -> Path:
        return self.dir / "execution"


@dataclass(frozen=True)
class AttemptSpec:
    id: str
    kind: Literal["variant", "adversarial"]
    goal: str
    context: str
    check: Callable[[Path], str | Mapping[str, Any] | None] | None = None
    judge_reference: JudgeReference | None = None
    binding: ExecutionBinding | None = None


@dataclass(frozen=True)
class StageSpec:
    name: str
    goal: str
    context: str
    inputs: Mapping[str, Path]
    required_outputs: tuple[str, ...]
    seed_code: str | None = None
    min_figures: int = 0
    check: Callable[[Path], str | Mapping[str, Any] | None] | None = None
    describe: Callable[[Path], str] | None = None
    describe_input: Callable[[Path], str] | None = None
    validate_results: Callable[[object], dict[str, dict[str, Any]]] | None = None
    blind_estimates: bool = False
    steps: int | None = None
    seed_node: str | None = None
    attempts: tuple[AttemptSpec, ...] = ()
    judge_reference: JudgeReference | None = None
    instance_id: str | None = None
    binding: ExecutionBinding | None = None

    def __post_init__(self) -> None:
        _validate_execution_id(self.execution_id)

    @property
    def execution_id(self) -> str:
        return self.name if self.instance_id is None else self.instance_id


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_buggy: bool
    goal_met: bool
    node_score: float
    analysis: str
    figure_issues: list[str] = Field(default_factory=list)
    fidelity_status: Literal["consistent", "defect", "unresolved"] | None = None
    fidelity_reason: str = ""
    fidelity_requirements: list[str] = Field(default_factory=list)
    fidelity_evidence: list[str] = Field(default_factory=list)

    # Checked here, not in the schema: structured outputs reject numeric bounds.
    @field_validator("node_score")
    @classmethod
    def _in_range(cls, v: float) -> float:
        if not 1 <= v <= 10:
            raise ValueError("node_score must be between 1 and 10")
        return v


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


def _draft_limit(search: Search, steps: int) -> int:
    """Drafts allowed in a stage, keeping at least one step for debug/improve."""
    return max(1, min(search.num_drafts, steps - 1))


def choose_action(
    nodes: Sequence[Node], search: Search, rng: random.Random, steps: int
) -> tuple[NodeKind, Node | None]:
    if sum(n.parent is None for n in nodes) < _draft_limit(search, steps):
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


def _task(h: Harness, spec: StageSpec, kind: NodeKind, parent: Node | None) -> str:
    if parent is None:
        if spec.seed_code:
            return f"Starting point to adapt:\n```python\n{spec.seed_code}\n```"
        return "Draft a new approach."
    code = part(
        "Previous code",
        parent.code,
        CODE_CHARS,
        journal=h.journal,
        tag=f"analyst:{spec.execution_id}",
    )
    analysis = part(
        "Analysis of its output",
        parent.analysis,
        ARTIFACT_CHARS,
        untrusted=True,
        journal=h.journal,
        tag=f"analyst:{spec.execution_id}",
    )
    if kind == "improve":
        return f"Improve this working script.\n{code}\n{analysis}"
    return f"Fix this script.\n{code}\n{analysis}"


def _reason(
    kind: NodeKind, parent: Node | None, nodes: Sequence[Node], search: Search, steps: int
) -> str:
    if parent is None:
        drafts = sum(n.parent is None for n in nodes) + 1
        return f"draft {drafts} of {_draft_limit(search, steps)}"
    if kind == "debug":
        first = (parent.analysis.splitlines() or [""])[0]
        return f"debug {parent.id}: {first}"[:120]
    return f"improve {parent.id} (score {parent.score:g})"


def _read_results(workdir: Path, validator: Callable[[object], dict[str, dict[str, Any]]] | None = None) -> dict[str, dict[str, Any]]:
    """Validated results.json content; raises ValueError describing the first problem."""
    try:
        raw = json.loads((workdir / "results.json").read_bytes())
    except OSError as exc:
        raise ValueError(f"results.json unreadable: {exc}") from exc
    if validator:
        return validator(raw)
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, dict) for k,v in raw.items()):
        raise ValueError("results.json must contain named JSON objects")
    return raw


def _step(
    h: Harness,
    spec: StageSpec,
    i: int,
    kind: NodeKind,
    parent: Node | None,
    reason: str,
    attempt: AttemptSpec | None = None,
    rng_state: tuple[Any, ...] | None = None,
) -> Node:
    node_id = f"{spec.execution_id}-{i:03d}"
    limit = h.config.execution.max_output_chars
    max_turns = h.config.search.max_turns
    node = Node(
        id=node_id,
        stage=spec.name,
        parent=parent.id if parent else None,
        kind=kind,
        debug_depth=parent.debug_depth + 1 if kind == "debug" and parent else 0,
        dir=h.run.path("tree", spec.execution_id, node_id),
        code="",
        status="buggy",
        score=None,
        goal_met=False,
        analysis="",
        results={},
        figures=[],
        reason=reason,
        attempt_id=attempt.id if attempt else None,
        seed_node=spec.seed_node,
        stage_instance=spec.execution_id,
        test_ref=spec.binding.source if spec.binding else None,
    )
    node.dir.mkdir(parents=True)
    h.journal.write(
        "node_start",
        stage=spec.name,
        stage_instance=spec.execution_id,
        node=node.id,
        kind=kind,
        parent=node.parent,
        attempt_id=node.attempt_id,
        debug_depth=node.debug_depth,
        rng_state=rng_state,
        seed_node=node.seed_node,
    )
    prompt = load_prompt(
        "popper.treesearch",
        "node.md",
        goal=spec.goal,
        context=spec.context,
        inputs="\n".join(
            f"- {n}: POPPER_INPUT_{n.upper()} ({p.name})" for n, p in spec.inputs.items()
        )
        or "- (none)",
        outputs="\n".join(f"- {o}" for o in spec.required_outputs),
        task=_task(h, spec, kind, parent),
    )
    try:
        submitted = agent_loop(
            h,
            "analyst",
            tag=f"analyst:{spec.execution_id}",
            system=_SYSTEM,
            task=prompt,
            tools=node_tools(h, spec.inputs, node.dir, describe_input=spec.describe_input, binding=spec.binding, stage_instance=spec.execution_id),
            max_turns=max_turns,
        )
    except LLMError as exc:
        submitted, failure = None, f"model call failed: {exc}"
    else:
        failure = f"no submit within {max_turns} turns"
    if submitted is None:
        node.analysis = failure
    elif not isinstance(submitted.get("code"), str) or not submitted["code"]:
        node.analysis = "submit without code"
    else:
        node.code = submitted["code"]
        _execute(h, spec, node, limit)
    node.outputs = {p.relative_to(h.run.root).as_posix(): file_hash(p) for p in node.execution_dir.rglob("*") if p.is_file()}
    meta = {k: v for k, v in asdict(node).items() if k not in ("code", "results", "dir")}
    if spec.binding:
        meta.update(spec.binding.metadata)
    meta["test_ref"] = node.test_ref.model_dump(mode="json") if node.test_ref else None
    h.run.write_json(f"tree/{spec.execution_id}/{node_id}/meta.json", meta)
    h.run.write_text(f"tree/{spec.execution_id}/{node_id}/analysis.md", node.analysis)
    meta_path = node.dir / "meta.json"
    h.journal.write("node_commit", stage=spec.name, stage_instance=spec.execution_id, node=node_id,
                    path=meta_path.relative_to(h.run.root).as_posix(), sha256=file_hash(meta_path), record_id=f"node-{node_id}")
    return node


def _stage_events(h: Harness, stage: str) -> list[dict[str, Any]]:
    _validate_execution_id(stage)
    return [
        e for e in read_events(h.run.root) if (e.get("stage_instance") or e.get("stage")) == stage
    ]


def load_nodes(h: Harness, stage: str, *, include_abandoned: bool = False) -> list[Node]:
    """Load nodes for an exact execution identity, falling back to roles in old records."""
    nodes: list[Node] = []
    events = _stage_events(h, stage)
    committed = {e["node"] for e in events if e["event"] == "node_commit"}
    for event in events:
        if event["event"] == "node_start" and event["node"] not in committed and include_abandoned:
            node_dir = h.run.path("tree", stage, str(event["node"]))
            source = node_dir / "execution" / "code.py"
            nodes.append(
                Node(
                    id=event["node"],
                    stage=event["stage"],
                    parent=event.get("parent"),
                    kind=event["kind"],
                    debug_depth=event.get("debug_depth", 0),
                    dir=node_dir,
                    code=source.read_text("utf-8") if source.exists() else "",
                    status="buggy",
                    score=None,
                    goal_met=False,
                    analysis="Interrupted attempt; no committed evaluation.",
                    results={},
                    figures=[],
                    reason="interrupted",
                    attempt_id=event.get("attempt_id"),
                    seed_node=event.get("seed_node"),
                    stage_instance=stage,
                )
            )
        if event["event"] != "node_commit":
            continue
        node_dir = h.run.path("tree", stage, str(event["node"]))
        metadata = json.loads((node_dir / "meta.json").read_text("utf-8"))
        metadata.setdefault("stage_instance", metadata["stage"])
        if event.get("sha256") and file_hash(node_dir / "meta.json") != event["sha256"]:
            raise ValueError("committed node metadata hash mismatch")
        if any(file_hash(h.run.path(path)) != expected for path, expected in metadata.get("outputs", {}).items()):
            raise ValueError("committed node output hash mismatch")
        if metadata.get("test_ref"):
            metadata["test_ref"] = ArtifactRef.model_validate(metadata["test_ref"])
        code_file = node_dir / "execution" / "code.py"
        nodes.append(
            Node(
                **metadata,
                dir=node_dir,
                code=code_file.read_text("utf-8") if code_file.exists() else "",
                results=_read_results(node_dir / "execution") if metadata["status"] == "ok" else {},
            )
        )
    return nodes


def _tuple_state(value: Any) -> Any:
    return tuple(_tuple_state(part) for part in value) if isinstance(value, list) else value


def _failed_check(spec: StageSpec, node: Node, exit_code: int | None, timed_out: bool) -> str:
    if timed_out:
        return "timed out"
    if exit_code != 0:
        return f"exit code {exit_code}"
    for output in spec.required_outputs:
        if not (node.execution_dir / output).exists():
            return f"missing required output {output}"
    if len(list((node.execution_dir / "figures").glob("*.png"))) < spec.min_figures:
        return f"expected at least {spec.min_figures} figure(s) in figures/"
    try:
        node.results = _read_results(node.execution_dir, spec.validate_results)
    except ValueError as exc:
        return f"invalid results.json: {exc}"
    observed = spec.check(node.execution_dir) if spec.check else None
    if isinstance(observed, Mapping):
        node.check_observations.append(dict(observed))
        return "" if observed["passed"] else str(observed["reason"])
    return observed or ""


def _execute(h: Harness, spec: StageSpec, node: Node, limit: int) -> None:
    res = h.execute(
        node.code,
        node.execution_dir,
        inputs=spec.inputs,
        node=node.id,
        purpose="submitted",
        binding=spec.binding, stage_instance=spec.execution_id,
    )
    node.execution_id = res.execution_id
    node.implementation_id = f"impl-{res.execution_id}"
    if spec.binding:
        for key, value in spec.binding.metadata.items():
            setattr(node, key, value)
    node.figures = sorted(p.name for p in (node.execution_dir / "figures").glob("*.png"))
    failed = _failed_check(spec, node, res.exit_code, res.timed_out)
    if failed:
        node.results = {}
        feedback = "\n".join(
            part(
                title,
                text,
                ARTIFACT_CHARS // 3,
                keep="tail" if title == "stderr" else "head",
                untrusted=True,
                journal=h.journal,
                tag=f"analyst:{spec.execution_id}",
            )
            for title, text in (
                ("stderr", res.stderr),
                ("stdout", res.stdout),
            )
        )
        node.analysis = f"Check failed: {failed}.\n{feedback}"
        return
    try:
        if spec.blind_estimates:
            make_diagnostic(h, node)
        prompt, images = judge_input(spec, node, res, journal=h.journal)
        verdict = h.ask_model(
            "judge",
            schema=Verdict,
            tag=f"judge:{spec.execution_id}",
            system=_SYSTEM,
            prompt=prompt,
            images=images,
        )
    except ValueError as exc:
        node.analysis = f"Invalid judge reply: {exc}"
        return
    except LLMError as exc:
        node.analysis = f"judge call failed: {exc}"
        return
    node.analysis = "\n".join([verdict.analysis, *verdict.figure_issues])
    if spec.binding and spec.binding.source:
        evidenced = bool(verdict.fidelity_requirements and verdict.fidelity_evidence and verdict.fidelity_reason)
        node.fidelity = {
            "status": verdict.fidelity_status if evidenced and verdict.fidelity_status else "unresolved",
            "reason": verdict.fidelity_reason or "No cited specification-to-code assessment.",
            "requirements": verdict.fidelity_requirements or ["Declared procedure and output"],
            "evidence": verdict.fidelity_evidence,
        }
    if not verdict.node_buggy:
        node.status, node.score, node.goal_met = "ok", verdict.node_score, verdict.goal_met


def _plateaued(nodes: Sequence[Node], search: Search) -> bool:
    best = select_best(nodes)
    if best is None or best.score is None or best.score < search.good_score:
        return False
    before = select_best(nodes[: -search.patience])
    return len(nodes) > search.patience and before is not None and best is before


def run_stage(h: Harness, spec: StageSpec, rng: random.Random | None = None) -> Node:
    rng = rng or random.Random(7)
    steps = spec.steps or h.config.search.steps_for(spec.name)
    if len(spec.attempts) > steps:
        raise ValueError("scheduled attempts exceed stage step budget")
    events = _stage_events(h, spec.execution_id)
    if any(e.get("stage") != spec.name for e in events if e["event"] == "stage_start"):
        raise ValueError(f"stage instance {spec.execution_id!r} is bound to a different role")
    nodes = load_nodes(h, spec.execution_id, include_abandoned=True)
    ends = [e for e in events if e["event"] == "stage_end"]
    if ends:
        best = next((n for n in nodes if n.id == ends[-1]["best"]), None)
        if best is None:
            raise StageFailed(spec.name)
        return best
    states = [e["rng_state"] for e in events if e.get("rng_state") is not None]
    if states:
        rng.setstate(cast(tuple[Any, ...], _tuple_state(states[-1])))
    if not any(e["event"] == "stage_start" for e in events):
        h.journal.write(
            "stage_start",
            stage=spec.name,
            stage_instance=spec.execution_id,
            steps=steps,
            seed=7,
            rng_state=rng.getstate(),
        )
    folders = [
        p
        for p in h.run.path("tree", spec.execution_id).glob(f"{spec.execution_id}-*")
        if p.is_dir()
    ]
    next_id = max((int(p.name.rsplit("-", 1)[1]) for p in folders), default=-1) + 1
    remaining = steps - len(folders)
    if not spec.attempts and (
        any(n.status == "ok" and n.goal_met for n in nodes) or _plateaued(nodes, h.config.search)
    ):
        remaining = 0
    for i in range(next_id, next_id + max(remaining, 0)):
        kind: NodeKind
        attempt = None
        effective = spec
        if spec.attempts:
            tried = {n.attempt_id for n in nodes}
            attempt = next((a for a in spec.attempts if a.id not in tried), None)
            if attempt is not None:
                kind, parent = attempt.kind, None
            else:
                successful = {n.attempt_id for n in nodes if n.status == "ok"}
                parents = {n.parent for n in nodes}
                parent = next(
                    (
                        n
                        for n in nodes
                        if n.status == "buggy"
                        and n.id not in parents
                        and n.attempt_id not in successful
                        and n.debug_depth < h.config.search.max_debug_depth
                    ),
                    None,
                )
                if parent is None:
                    break
                kind = "debug"
                attempt = next(a for a in spec.attempts if a.id == parent.attempt_id)
            effective = replace(
                spec,
                goal=attempt.goal,
                context=f"{spec.context}\n{attempt.context}",
                check=attempt.check or spec.check,
                judge_reference=attempt.judge_reference or spec.judge_reference,
                binding=attempt.binding or spec.binding,
            )
            reason = f"{kind} specification {attempt.id}"
        else:
            kind, parent = choose_action(nodes, h.config.search, rng, steps)
            reason = _reason(kind, parent, nodes, h.config.search, steps)
        node = _step(h, effective, i, kind, parent, reason, attempt, rng.getstate())
        nodes.append(node)
        score = f" score {node.score:g}" if node.status == "ok" else ""
        h.progress(
            f"[{spec.execution_id}] {node.id} {node.kind} → {node.status}{score} · ${h.spent_usd:.2f}"
        )
        if not spec.attempts and node.status == "ok" and node.goal_met:
            break
        if not spec.attempts and _plateaued(nodes, h.config.search):
            break
    best = select_best(nodes)
    h.journal.write(
        "stage_end",
        stage=spec.name,
        stage_instance=spec.execution_id,
        best=best.id if best else None,
        steps=len(nodes),
    )
    if best is None:
        raise StageFailed(spec.name)
    return best
