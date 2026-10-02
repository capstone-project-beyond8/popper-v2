import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest

from popper.communicate.paper import compile_pdf
from popper.coordinator.run import resume, run
from popper.harness.config import Config, load_config
from popper.harness.llm import Completion, FakeLLM, LLMRequest, ToolCall
from popper.harness.recovery import load_state, read_events, recorded_spend
from popper.harness.research import parse_research
from popper.harness.store import RunStore

pytestmark = pytest.mark.integration

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "student_performance"

FRAMING = {
    "title": "Study hours and exam scores",
    "problem": "Does study time relate to exam performance?",
    "questions": [
        {
            "id": "hours_score",
            "text": "How do study hours relate to exam_score?",
            "objective": "What drives exam performance among secondary students?",
            "outcome_candidate": "exam_score",
        }
    ],
    "scope": {"inside": ["secondary students"], "outside": []},
    "unknowns": [],
    "directions": [
        {
            "id": "log_trend",
            "text": "Fit a log-linear trend",
            "origin": "diminishing returns",
            "competing_explanations": ["ability"],
        }
    ],
}
HYPOTHESIS = {
    "statement": "Scores rise with the log of weekly study hours.",
    "rationale": "Diminishing returns.",
    "primary_estimand": {
        "outcome": "exam_score",
        "exposure": "study_hours_week",
        "contrast": "study hours 10 to 11",
        "population": "eligible students",
        "unit": "exam score points",
        "comparison": "difference",
    },
    "methods": ["linear_regression", "log_transform", "bootstrap"],
    "expected_direction": "positive",
    "refuting_result": "a nonpositive contrast",
    "planned_test": "Regress score on log1p(study hours); bootstrap the 10 to 11 contrast",
}
WRITEUP = {
    "title": "Study hours and exam scores",
    "abstract": "a",
    "introduction": "i",
    "data": "d",
    "exploration": "e",
    "hypothesis": "h",
    "methods": "m",
    "results": r"Contrast \R{main.primary_estimate} and unknown \R{main.nope}.",
    "robustness": "sensitivity",
    "discussion": "limitations",
    "conclusion": "association",
    "figures": [
        {
            "node_id": "explore-000",
            "file": "scatter.png",
            "caption": "Scatter",
            "section": "exploratory",
        }
    ],
}
FEEDBACK = {"node_buggy": False, "goal_met": True, "node_score": 7, "analysis": "ok"}
ROBUSTNESS = {
    "attempts": [
        {
            "id": f"choice-{i}",
            "kind": "adversarial" if dim == "adversarial" else "variant",
            "dimension": dim,
            "choice": "permutation" if dim == "adversarial" else f"alternative {i}",
            "result_key": "placebo_estimate" if dim == "adversarial" else "primary_estimate",
            "seed": 7,
            **({"population": "students with high attendance"} if dim == "subgroup" else {}),
        }
        for i, dim in enumerate(("cleaning", "model", "subgroup", "resampling", "adversarial"))
    ],
    "inapplicable": {},
}

DATA = """
import json, os
import pandas as pd
df = pd.read_csv(os.environ["POPPER_INPUT_RAW"])
n0 = len(df)
df = df.drop_duplicates()
df["exam_score"] = pd.to_numeric(df["exam_score"], errors="coerce")
df["family_income"] = df["family_income"].str.lower().replace({"medium": "mid"})
df = df[df["study_hours_week"].between(0, 60) & ~(df["attendance_rate"] > 1)]
df = df.dropna()
df.to_parquet("processed.parquet")
json.dump([{"step": "clean", "rows_affected": "rows_removed", "reason": "quality"}],
          open("changes.json", "w"))
json.dump({"rows_before": {"value": n0}, "rows_after": {"value": len(df)}, "rows_removed": {"value": n0-len(df)}},
          open("results.json", "w"))
"""
PNG = r"""
import struct, zlib
def write_png(path):
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    rows = b"".join(b"\x00" + bytes(range(0, 256, 32)) for _ in range(8))
    header = struct.pack(">IIBBBBB", 8, 8, 8, 0, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
"""
EXPLORE = (
    """
import json, os
import numpy as np
import pyarrow.parquet as pq
"""
    + PNG
    + """
table = pq.read_table(os.environ["POPPER_INPUT_DATA"])
hours, score = table.column("study_hours_week").to_numpy(), table.column("exam_score").to_numpy()
os.makedirs("figures", exist_ok=True)
write_png("figures/scatter.png")
write_png("figures/hist.png")
corr = float(np.corrcoef(hours, score)[0, 1])
json.dump({"corr_study_score": {"value": corr}}, open("results.json", "w"))
"""
)
EXPERIMENT = (
    """
import json, os
import numpy as np
import pyarrow.parquet as pq
"""
    + PNG
    + """
table = pq.read_table(os.environ["POPPER_INPUT_DATA"])
hours, score = table.column("study_hours_week").to_numpy(), table.column("exam_score").to_numpy()
x, y = np.log1p(hours), score
slope = np.polyfit(x, y, 1)[0]
rng = np.random.default_rng(0)
boots = []
for _ in range(200):
    i = rng.integers(0, len(x), len(x))
    boots.append(np.polyfit(x[i], y[i], 1)[0])
ci = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]
os.makedirs("figures", exist_ok=True)
write_png("figures/fit.png")
scale = float(np.log(12) - np.log(11))
json.dump({"primary_estimate": {"value": float(slope) * scale, "ci": [c * scale for c in ci], "n": len(x)}}, open("results.json", "w"))
"""
)
EXPERIMENT += f"\njson.dump({HYPOTHESIS['primary_estimand']!r}, open('estimand.json','w'))\n"


def _submit_ground(code: str) -> tuple[ToolCall, ...]:
    mapping = [
        {
            "concept_id": "study_effort",
            "columns": ["study_hours_week"],
            "proxy_strength": "direct",
            "rationale": "Weekly study hours measure the time invested.",
        }
    ]
    args = {"code": code, "operationalization": mapping, "concerns": []}
    return (ToolCall("ground-1", "submit_ground", args),)


def _submit(code: str) -> tuple[ToolCall, ...]:
    return (ToolCall("submit-1", "submit", {"code": code}),)


def _respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
    tag = req.tag
    if tag == "candidates":
        methods = [{"family": "linear_regression", "description": "Log exposure contrast", "inputs": ["exam_score", "study_hours_week"], "outputs": ["primary_estimate"], "effect_scale": "exam score points", "parameters": {"bootstrap": 200, "seed": 0}, "diagnostics": ["finite interval"], "assumptions": []}]
        return json.dumps({"candidates": [{**HYPOTHESIS, "statement": f"Candidate {i}: scores and hours", "methods": methods} for i in (1, 2, 3)]})
    if tag == "research_moves":
        state = json.loads(req.messages[0].text.split("Sourced state: ", 1)[1].split("\nRead omitted", 1)[0])
        omitted = {"hypothesis-002": "Retain competing explanation for later", "hypothesis-003": "Retain uncertainty"}
        if state["results"]:
            move = {"action": "stop", "objective": "retain observed contrast and alternatives", "trigger_refs": [state["results"][-1]["ref"]], "cost_usd": 0, "stopping_condition": "bounded informative test completed"}
            omitted["hypothesis-001"] = "completed test"
        else:
            intent = next(ref for ref in state["frontier"] if "intent" in ref["path"])
            candidate = state["candidates"][0]["record"]
            if len(req.messages) == 1:
                return (ToolCall("read-intent", "read_artifact", {"path": intent["path"]}),)
            intent_data = json.loads(req.messages[-1].tool_results[0].text.split("<untrusted>\n", 1)[1].split("\n</untrusted>", 1)[0])
            test = {
                "primary_estimand": candidate["primary_estimand"], "selection": {"slice": "all discovery rows", "assumptions": []},
                "preparation": intent_data["preparation"], "methods": candidate["methods"],
                "inference": {"bootstrap": 200, "interval_level": .95}, "adjustment": [],
                "requested_coverage": {"seeds": [0], "alternatives": [{"inference": {"bootstrap": 200, "interval_level": .95}, "selection": {"slice": "all discovery rows", "assumptions": ["alternative model"]}}]},
                "outputs": ["primary_estimate", "estimand.json"],
                "support_rule": {"kind": "directional_ci", "result_key": "primary_estimate", "interval_level": .95, "null": 0, "direction": "positive"},
                "sources": [intent],
            }
            move = {"action": "test", "objective": "resolve exploration uncertainty", "hypothesis_id": "hypothesis-001", "trigger_refs": [state["candidates"][0]["ref"]], "test_proposal": test, "discriminating_outcomes": ["positive", "negative", "inconclusive"], "cost_usd": .1, "stopping_condition": "one informative test"}
        return (ToolCall("submit-moves", "submit_moves", {"moves": [move], "omitted": omitted}),)
    if tag == "select_move":
        proposals = json.loads(req.prompt.split("Retained proposals: ", 1)[1])
        return json.dumps({"proposal_id": proposals["moves"][0]["id"], "rationale": "Exploration uncertainty motivates an informative contrast"})
    if tag == "theorist":
        return (ToolCall("frame-1", "submit_frame", {"framing": FRAMING}),)
    if tag == "steward":
        return _submit_ground(DATA)
    if tag.startswith("analyst:"):
        if "hypothesis-" in tag:
            return _submit(EXPERIMENT + "\njson.dump({'seeds':[0], 'interval_level':.95, 'effect_scale':'exam score points'},open('coverage.json','w'))")
        if tag == "analyst:robustness":
            choice = next(
                item for item in ROBUSTNESS["attempts"] if f": {item['choice']}. " in req.prompt
            )
            estimand: dict[str, Any] = dict(cast(dict[str, Any], HYPOTHESIS["primary_estimand"]))
            estimand.update({k: choice[k] for k in ("population",) if k in choice})
            code = EXPERIMENT.replace(repr(HYPOTHESIS["primary_estimand"]), repr(estimand))
            if choice["kind"] == "adversarial":
                code = code.replace('"primary_estimate"', '"placebo_estimate"')
                code = code.replace(
                    "x, y =",
                    "hours = np.random.default_rng(7).permutation(hours)\nx, y =",
                )
            return _submit(code)
        return _submit(EXPLORE if tag == "analyst:explore" else EXPERIMENT)
    if tag.startswith("judge:"):
        return json.dumps({**FEEDBACK, **({"fidelity_status": "consistent", "fidelity_reason": "Declared log contrast implemented with resampling", "fidelity_requirements": ["contrast", "interval"], "fidelity_evidence": ["code: bootstrap", "output: contrast"]} if "hypothesis-" in tag else {})})
    if tag == "writeup" and "committed study" in req.prompt:
        names, _ = json.JSONDecoder().raw_decode(req.prompt.split("Named numbers: ", 1)[1])
        key = next(k for k in names if ".main.primary_estimate" in k and not k.endswith((".ci", ".n")))
        return json.dumps({**WRITEUP, "results": rf"Contrast \R{{{key}}} and unknown \R{{main.nope}}.", "figures": []})
    return json.dumps(
        {"hypothesis": HYPOTHESIS, "writeup": WRITEUP, "robustness_plan": ROBUSTNESS}[tag]
    )


def _config() -> Config:
    cfg = load_config(env={"POPPER_MODEL": "fake-sonnet"})
    cfg.search.num_drafts = 1
    return cfg


@pytest.mark.slow
def test_end_to_end_survives_interruptions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupt(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        if req.tag.startswith("analyst:") and req.tag.endswith("-main"):
            raise KeyboardInterrupt("interrupted during analyst")
        return _respond(req)

    class MeteredFake(FakeLLM):
        def complete(self, req: LLMRequest, max_tokens: int) -> Completion:
            return replace(super().complete(req, max_tokens), input_tokens=1)

    llm = MeteredFake(interrupt)
    lines: list[str] = []
    config = _config()
    config.budget.max_usd = 0.000003
    stopped = run(
        EXAMPLE / "research.md",
        EXAMPLE / "data.csv",
        config=config,
        auto=True,
        llm=llm,
        runs_dir=tmp_path,
        progress=lines.append,
    )
    assert stopped.status == "budget_exceeded"
    store = RunStore(stopped.run_dir)
    from popper.harness.recovery import Journal
    # A publication stop belongs to this source, never to a later resumed study.
    Journal(store.path("journal.jsonl")).write("publication_budget_stop", study_identity=store.artifact_ref("study").sha256)
    prior_spend = recorded_spend(store)
    assert prior_spend > 0
    with pytest.raises(KeyboardInterrupt):
        resume(stopped.run_dir, llm=llm, max_usd=1, progress=lines.append)
    root = next(p for p in tmp_path.iterdir() if p.is_dir())
    prefix = {
        p: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file() and p.name != "journal.jsonl"
    }

    def interrupted_compile(tex: Path) -> Path | None:
        raise KeyboardInterrupt("publication interrupted")

    fake = FakeLLM(_respond)
    monkeypatch.setattr("popper.communicate.paper.compile_pdf", interrupted_compile)
    with pytest.raises(KeyboardInterrupt):
        resume(root, llm=fake)
    assert all(hashlib.sha256(p.read_bytes()).hexdigest() == digest for p, digest in prefix.items())
    assert not any(
        req.tag
        in {
            "theorist",
            "candidates",
            "steward",
            "analyst:explore",
            "analyst:hypothesis-001-attempt-000-baseline",
            "judge:hypothesis-001-attempt-000-baseline",
        }
        for req in fake.calls
    )
    main_instance = "hypothesis-001-attempt-000-main"
    assert (root / "tree" / main_instance / f"{main_instance}-001" / "meta.json").is_file()
    assert not (root / "tree" / main_instance / f"{main_instance}-000" / "meta.json").exists()
    original = {
        p: p.read_bytes() for p in root.rglob("*") if p.is_file() and p.name != "journal.jsonl"
    }

    monkeypatch.setattr("popper.communicate.paper.compile_pdf", compile_pdf)
    # The scientific frontier is unchanged by a publication-only resource stop.
    Journal(store.path("journal.jsonl")).write("publication_budget_stop", study_identity=store.artifact_ref("study").sha256)
    no_calls = FakeLLM(lambda req: pytest.fail("completed publication inputs must not replay"))
    out = resume(root, llm=no_calls, max_usd=2)
    assert all(p.read_bytes() == contents for p, contents in original.items())
    assert out.status == "completed" and out.tex is not None
    assert recorded_spend(store) > prior_spend
    assert load_state(store)["spent_usd"] == recorded_spend(store)
    assert load_state(store)["max_usd"] == 2
    assert len([e for e in read_events(root) if e["event"] == "budget_raise"]) == 2
    tex = out.tex.read_text(encoding="utf-8")
    results = next((out.run_dir / "tree" / main_instance).glob("*/execution/results.json"))
    slope = json.loads(results.read_text(encoding="utf-8"))["primary_estimate"]["value"]
    assert f"{slope:.3g}" in tex and r"\textbf{??}" in tex
    assert "exploratory --- autonomously generated" in tex and "\\usepackage{amsmath}" in tex
    framing_path = RunStore(out.run_dir).committed("frame")
    assert framing_path is not None
    assert json.loads(framing_path.read_text(encoding="utf-8"))["title"] == FRAMING["title"]
    hypotheses_path = RunStore(out.run_dir).committed("science:candidates:initial")
    assert hypotheses_path is not None
    hypotheses = json.loads(hypotheses_path.read_text(encoding="utf-8"))["candidates"]
    assert len(hypotheses) == 3 and all(x["origins"] for x in hypotheses)
    from popper.discover.state import rebuild_state
    from popper.harness.session import Harness
    state = rebuild_state(Harness(config, no_calls, store))
    assert len(state.attempts) == 1 and state.observations
    assert all(m.record.ref.test_id and m.record.ref.execution_id for m in state.observations)
    body = parse_research((EXAMPLE / "research.md").read_text(encoding="utf-8")).body
    request = next(r for r in llm.calls if r.tag == "theorist")
    assert f"<untrusted>\n{body}\n</untrusted>" in request.prompt
    assert (out.run_dir / "data" / "processed.parquet").exists()
    record = load_state(RunStore(out.run_dir))
    assert record["status"] == "completed" and record["missing"] == [r"\R{main.nope}"]
    writer = [r for r in fake.calls if r.tag == "writeup"]
    assert len(writer) == 3 and r"\R{main.nope}: no key main.nope" in writer[1].prompt
    journal_lines = (out.run_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line)["event"] for line in journal_lines]
    assert events.count("phase") >= 16 and "exec" in events
    data = out.run_dir / "data"
    raw_ids = set(pd.read_csv(data / "raw.csv").student_id)
    held_only = set(RunStore(out.run_dir).read_holdout().student_id) - raw_ids
    assert held_only  # duplicated source rows may share ids across the split; the rest may not
    assert set(pd.read_parquet(data / "processed.parquet").student_id) <= raw_ids
    assert not any("holdout" in req.prompt for req in (*llm.calls, *fake.calls))
    assert not any("holdout" in p.read_text("utf-8") for p in out.run_dir.glob("tree/*/*/code.py"))
    assert lines[0] == "[framing] start · $0.00"
    assert any(re.match(r"^\[ground\] start · \$\d+\.\d\d$", x) for x in lines)
    assert not (out.run_dir / "tree" / "data").exists()
    assert (out.run_dir / "data" / "ida.json").exists()
    assert resume(root, llm=no_calls).tex == out.tex


@pytest.mark.slow
def test_reviewed_frame_run_never_exposes_holdout_rows(tmp_path: Path) -> None:
    llm = FakeLLM(_respond)
    stopped = run(
        EXAMPLE / "research.md",
        EXAMPLE / "data.csv",
        config=_config(),
        llm=llm,
        runs_dir=tmp_path,
    )
    assert stopped.status == "awaiting_review" and stopped.review is not None
    assert [r.tag for r in llm.calls] == ["theorist"]
    out = resume(stopped.run_dir, llm=llm)
    assert out.status == "completed"
    tags = [r.tag for r in llm.calls]
    assert tags.count("theorist") == 1 and "steward" in tags
    assert tags.index("steward") < tags.index("candidates")
    data = out.run_dir / "data"
    raw = pd.read_csv(data / "raw.csv")
    held = RunStore(out.run_dir).read_holdout()
    only = sorted({f"{v}" for v in held.student_id} - {f"{v}" for v in raw.student_id})
    assert only, "no holdout-only value to look for; the check would pass vacuously"
    seen = "\n".join(r.prompt for r in llm.calls)
    seen += (out.run_dir / "journal.jsonl").read_text(encoding="utf-8")
    seen += "".join(p.read_text("utf-8") for p in out.run_dir.glob("tree/*/*/code.py"))
    assert not [v for v in only if re.search(rf"(?<![\w-]){re.escape(v)}(?![\w-])", seen)]


def test_failed_stage_recorded(tmp_path: Path) -> None:
    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        return (
            _submit_ground("raise RuntimeError('boom')") if req.tag == "steward" else _respond(req)
        )

    cfg = _config()
    out = run(
        EXAMPLE / "research.md",
        EXAMPLE / "data.csv",
        config=cfg,
        auto=True,
        llm=FakeLLM(respond),
        runs_dir=tmp_path,
    )
    assert out.status == "failed" and "ground" in out.message
    record = load_state(RunStore(out.run_dir))
    assert record["status"] == "failed" and record["failed_stage"] == "ground"


def test_budget_exceeded_recorded(tmp_path: Path) -> None:
    cfg = _config()
    cfg.budget.max_usd = 0
    out = run(
        EXAMPLE / "research.md",
        EXAMPLE / "data.csv",
        config=cfg,
        auto=True,
        llm=FakeLLM(_respond),
        runs_dir=tmp_path,
    )
    assert out.status == "budget_exceeded"
    assert load_state(RunStore(out.run_dir))["status"] == "budget_exceeded"
