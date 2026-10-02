from pathlib import Path

from popper.communicate.paper import write_study
from popper.coordinator.discovery import commit_study
from popper.harness.config import load_config
from popper.harness.llm import FakeLLM
from popper.harness.records import CandidateView, StudyOutput
from popper.harness.session import Harness
from popper.harness.store import RunStore


def test_no_budget_diagnostic_uses_common_template_and_exact_cache(tmp_path: Path) -> None:
    config = load_config(env={})
    config.budget.max_usd = 0
    h = Harness(
        config,
        FakeLLM(lambda _: (_ for _ in ()).throw(AssertionError("no model calls"))),
        RunStore(tmp_path),
    )
    study = commit_study(h, "Budget exhausted before findings", "budget_exceeded")
    tex, _, missing = write_study(h, study)
    contents = tex.read_text("utf-8")
    assert "No accepted usable measurements" in contents
    assert "Budget exhausted before findings" in contents
    assert "Computed stability" not in contents and "non-supporting" not in contents
    assert missing == []
    assert write_study(h, study)[0] == tex
    assert h.run.committed("report") is not None


def test_diagnostic_history_text_is_escaped(tmp_path: Path) -> None:
    config = load_config(env={})
    config.budget.max_usd = 0
    h = Harness(config, FakeLLM(lambda _: ""), RunStore(tmp_path))
    source = h.run.write_json("source.json", {})
    h.run.commit_artifact("source", source)
    candidate = CandidateView(
        id="h_1",
        statement=r"50% & \input{secret}",
        rationale="origin",
        source=h.run.artifact_ref("source"),
        warnings=[],
        selected=False,
        attempted=False,
    )
    output = StudyOutput(
        adaptive=True,
        frontier=[],
        candidates=[candidate],
        stop_reason=r"Stop \input{secret}",
        operational_status="budget_exceeded",
    )
    study = h.run.write_json("study.json", output.model_dump(mode="json"))
    h.run.commit_artifact("study", study)
    tex, _, _ = write_study(h, study)
    rendered = tex.read_text("utf-8")
    assert r"\input{secret}" not in rendered
    assert r"50\% \&" in rendered
