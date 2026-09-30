import json
import re
from pathlib import Path

import pytest

from popper.coordinator.run import run
from popper.harness.config import Config, load_config
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall

pytestmark = pytest.mark.integration

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "student_performance"

FRAMING = {
    "title": "Study hours and exam scores",
    "problem": "Does study time relate to exam performance?",
    "questions": ["How do study hours relate to exam_score?"],
    "key_variables": ["study_hours_week", "exam_score"],
    "directions": ["Fit a log-linear trend"],
    "data_concerns": ["duplicates", "impossible values"],
}
HYPOTHESIS = {
    "statement": "Scores rise with the log of weekly study hours.",
    "rationale": "Diminishing returns.",
    "variables": ["study_hours_week", "exam_score"],
    "planned_experiments": ["Regress score on log1p(study hours)"],
}
WRITEUP = {
    "title": "Study hours and exam scores",
    "abstract": "a",
    "introduction": "i",
    "data": "d",
    "exploration": "e",
    "hypothesis": "h",
    "methods": "m",
    "results": r"Slope \R{experiment.slope} and unknown \R{experiment.nope}.",
    "limitations": "l",
    "figures": [{"stage": "explore", "file": "scatter.png", "caption": "Scatter"}],
}
FEEDBACK = {"node_buggy": False, "goal_met": True, "node_score": 7, "analysis": "ok"}

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
json.dump([{"step": "clean", "rows_affected": n0 - len(df), "reason": "quality"}],
          open("changes.json", "w"))
json.dump({"rows_before": {"value": n0}, "rows_after": {"value": len(df)}},
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
json.dump({"slope": {"value": float(slope), "ci": ci, "n": len(x)}}, open("results.json", "w"))
"""


def _submit(code: str) -> tuple[ToolCall, ...]:
    return (ToolCall("submit-1", "submit", {"code": code}),)


def _respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
    tag = req.tag
    if tag.startswith("framing"):
        return json.dumps(FRAMING)
    if tag.startswith("analyst:"):
        return _submit({"analyst:data": DATA, "analyst:explore": EXPLORE}.get(tag, EXPERIMENT))
    if tag.startswith("judge:"):
        return json.dumps(FEEDBACK)
    return json.dumps({"hypothesis": HYPOTHESIS, "writeup": WRITEUP}[tag])


def _config() -> Config:
    cfg = load_config(env={"POPPER_MODEL": "fake-sonnet"})
    cfg.search.num_drafts = 1
    return cfg


def test_end_to_end(tmp_path: Path) -> None:
    llm = FakeLLM(_respond)
    out = run(
        EXAMPLE / "brief.md", EXAMPLE / "data.csv", config=_config(), llm=llm, runs_dir=tmp_path
    )
    assert out.status == "completed" and out.tex is not None
    tex = out.tex.read_text(encoding="utf-8")
    results = next((out.run_dir / "tree" / "experiment").glob("*/results.json"))
    slope = json.loads(results.read_text(encoding="utf-8"))["slope"]["value"]
    assert f"{slope:.3g}" in tex and r"\textbf{??}" in tex
    assert "exploratory --- autonomously generated" in tex and "\\usepackage{amsmath}" in tex
    framing = json.loads((out.run_dir / "understand" / "framing.json").read_text(encoding="utf-8"))
    assert framing["supplied_by"] == "agent"
    hypotheses = json.loads((out.run_dir / "hypotheses.json").read_text(encoding="utf-8"))
    assert hypotheses and all(x["supplied_by"] == "agent" for x in hypotheses)
    brief = (EXAMPLE / "brief.md").read_text(encoding="utf-8")
    request = next(r for r in llm.calls if r.tag == "framing")
    assert f"<untrusted>\n{brief}\n</untrusted>" in request.prompt
    assert (out.run_dir / "data" / "processed.parquet").exists()
    record = json.loads((out.run_dir / "run.json").read_text(encoding="utf-8"))
    assert record["status"] == "completed" and record["missing"] == [r"\R{experiment.nope}"]
    writer = [r for r in llm.calls if r.tag == "writeup"]
    assert len(writer) == 2 and r"no value: \R{experiment.nope}" in writer[1].prompt
    lines = (out.run_dir / "journal.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(line)["event"] for line in lines]
    assert events.count("phase") == 5 and "exec" in events


def test_progress_lines(tmp_path: Path) -> None:
    lines: list[str] = []
    run(
        EXAMPLE / "brief.md",
        EXAMPLE / "data.csv",
        config=_config(),
        llm=FakeLLM(_respond),
        runs_dir=tmp_path,
        progress=lines.append,
    )
    assert lines[0] == "[framing] start · $0.00"
    assert any(re.match(r"^\[data\] data-000 draft → ok score 7 · \$\d+\.\d\d$", x) for x in lines)


def test_failed_stage_recorded(tmp_path: Path) -> None:
    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        return _submit("raise RuntimeError('boom')") if req.tag == "analyst:data" else _respond(req)

    cfg = _config()
    cfg.search.steps_per_stage = 2
    out = run(
        EXAMPLE / "brief.md",
        EXAMPLE / "data.csv",
        config=cfg,
        llm=FakeLLM(respond),
        runs_dir=tmp_path,
    )
    assert out.status == "failed" and "data" in out.message
    record = json.loads((out.run_dir / "run.json").read_text(encoding="utf-8"))
    assert record["status"] == "failed" and record["failed_stage"] == "data"


def test_budget_exceeded_recorded(tmp_path: Path) -> None:
    cfg = _config()
    cfg.budget.max_usd = 0
    out = run(
        EXAMPLE / "brief.md",
        EXAMPLE / "data.csv",
        config=cfg,
        llm=FakeLLM(_respond),
        runs_dir=tmp_path,
    )
    assert out.status == "budget_exceeded"
    assert (
        json.loads((out.run_dir / "run.json").read_text(encoding="utf-8"))["status"]
        == "budget_exceeded"
    )
