import json
import re
from pathlib import Path
from typing import Any, cast

import pandas as pd
import pytest

from popper.communicate.paper import compile_pdf
from popper.coordinator.run import resume, run
from popper.harness.config import Config, load_config
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.recovery import load_state
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
EXPLORE = """
import json, os
import matplotlib.pyplot as plt
import pandas as pd
df = pd.read_parquet(os.environ["POPPER_INPUT_DATA"])
os.makedirs("figures", exist_ok=True)
plt.scatter(df["study_hours_week"], df["exam_score"])
plt.savefig("figures/scatter.png")
plt.figure()
plt.hist(df["exam_score"])
plt.savefig("figures/hist.png")
corr = float(df["study_hours_week"].corr(df["exam_score"]))
json.dump({"corr_study_score": {"value": corr}}, open("results.json", "w"))
"""
EXPERIMENT = """
import json, os
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
df = pd.read_parquet(os.environ["POPPER_INPUT_DATA"])
x, y = np.log1p(df["study_hours_week"].to_numpy()), df["exam_score"].to_numpy()
slope = np.polyfit(x, y, 1)[0]
rng = np.random.default_rng(0)
boots = []
for _ in range(200):
    i = rng.integers(0, len(x), len(x))
    boots.append(np.polyfit(x[i], y[i], 1)[0])
ci = [float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))]
os.makedirs("figures", exist_ok=True)
plt.scatter(x, y)
plt.savefig("figures/fit.png")
scale = float(np.log(12) - np.log(11))
json.dump({"primary_estimate": {"value": float(slope) * scale, "ci": [c * scale for c in ci], "n": len(x)}}, open("results.json", "w"))
"""
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
    if tag == "theorist":
        return (ToolCall("frame-1", "submit_frame", {"framing": FRAMING}),)
    if tag == "steward":
        return _submit_ground(DATA)
    if tag.startswith("analyst:"):
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
                    'df["study_hours_week"] = np.random.default_rng(7).permutation(df["study_hours_week"])\nx, y =',
                )
            return _submit(code)
        return _submit(EXPLORE if tag == "analyst:explore" else EXPERIMENT)
    if tag.startswith("judge:"):
        return json.dumps(FEEDBACK)
    return json.dumps(
        {"hypothesis": HYPOTHESIS, "writeup": WRITEUP, "robustness_plan": ROBUSTNESS}[tag]
    )


def _config() -> Config:
    cfg = load_config(env={"POPPER_MODEL": "fake-sonnet"})
    cfg.search.num_drafts = 1
    return cfg


def test_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    llm = FakeLLM(_respond)
    lines: list[str] = []

    def interrupted_compile(tex: Path) -> Path | None:
        raise KeyboardInterrupt("publication interrupted")

    monkeypatch.setattr("popper.communicate.paper.compile_pdf", interrupted_compile)
    with pytest.raises(KeyboardInterrupt):
        run(
            EXAMPLE / "research.md",
            EXAMPLE / "data.csv",
            config=_config(),
            auto=True,
            llm=llm,
            runs_dir=tmp_path,
            progress=lines.append,
        )
    root = next(tmp_path.iterdir())
    original = {
        p: p.read_bytes() for p in root.rglob("*") if p.is_file() and p.name != "journal.jsonl"
    }
    monkeypatch.setattr("popper.communicate.paper.compile_pdf", compile_pdf)
    no_calls = FakeLLM(lambda req: pytest.fail("completed publication inputs must not replay"))
    out = resume(root, llm=no_calls)
    assert all(p.read_bytes() == contents for p, contents in original.items())
    assert out.status == "completed" and out.tex is not None
    tex = out.tex.read_text(encoding="utf-8")
    results = next((out.run_dir / "tree" / "main").glob("*/execution/results.json"))
    slope = json.loads(results.read_text(encoding="utf-8"))["primary_estimate"]["value"]
    assert f"{slope:.3g}" in tex and r"\textbf{??}" in tex
    assert "exploratory --- autonomously generated" in tex and "\\usepackage{amsmath}" in tex
    framing_path = RunStore(out.run_dir).committed("frame")
    assert framing_path is not None
    assert json.loads(framing_path.read_text(encoding="utf-8"))["title"] == FRAMING["title"]
    hypotheses_path = RunStore(out.run_dir).committed("hypothesis")
    assert hypotheses_path is not None
    hypotheses = json.loads(hypotheses_path.read_text(encoding="utf-8"))
    assert hypotheses and all(x["supplied_by"] == "agent" for x in hypotheses)
    body = parse_research((EXAMPLE / "research.md").read_text(encoding="utf-8")).body
    request = next(r for r in llm.calls if r.tag == "theorist")
    assert f"<untrusted>\n{body}\n</untrusted>" in request.prompt
    assert (out.run_dir / "data" / "processed.parquet").exists()
    record = load_state(RunStore(out.run_dir))
    assert record["status"] == "completed" and record["missing"] == [r"\R{main.nope}"]
    writer = [r for r in llm.calls if r.tag == "writeup"]
    assert len(writer) == 3 and r"\R{main.nope}: no key main.nope" in writer[1].prompt
    journal_lines = (out.run_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line)["event"] for line in journal_lines]
    assert events.count("phase") == 10 and "exec" in events
    data = out.run_dir / "data"
    raw_ids = set(pd.read_csv(data / "raw.csv").student_id)
    held_only = set(pd.read_csv(data / "holdout.csv").student_id) - raw_ids
    assert held_only  # duplicated source rows may share ids across the split; the rest may not
    assert set(pd.read_parquet(data / "processed.parquet").student_id) <= raw_ids
    assert not any("holdout" in req.prompt for req in llm.calls)
    assert not any("holdout" in p.read_text("utf-8") for p in out.run_dir.glob("tree/*/*/code.py"))
    assert lines[0] == "[framing] start · $0.00"
    assert any(re.match(r"^\[ground\] start · \$\d+\.\d\d$", x) for x in lines)
    assert not (out.run_dir / "tree" / "data").exists()
    assert (out.run_dir / "data" / "ida.json").exists()


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
