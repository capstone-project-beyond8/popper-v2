from pathlib import Path

import pytest

from popper.config import load_config
from popper.harness.llm import FakeLLM
from popper.harness.session import Harness
from popper.harness.storage.store import RunStore
from popper.scientific.runtime.lifecycle.contracts import Challenge, Interpretation
from popper.scientific.runtime.projections.output import CandidateView, StudyOutput, build_study
from popper.scientific.runtime.store import ScienceStore
from popper.stages.communicate.paper import write_study


def test_report_numbers_exclude_scratch_results(tmp_path: Path) -> None:
    from popper.harness.storage.recovery import Journal
    from popper.harness.storage.store import file_hash
    from popper.scientific.runtime.projections.views import node_ref, record_exploration
    from popper.stages.communicate.paper import diagnostic_writeup

    config = load_config(env={})
    config.budget.max_usd = 0
    h = Harness(config, FakeLLM(lambda _: pytest.fail("saved writeup requires no model")), RunStore(tmp_path))
    accepted = h.run.write_json("tree/explore/explore-000/execution/results.json", {"accepted": {"value": 1}})
    h.run.write_json("tree/explore/explore-000/scratch/00/results.json", {"scratch_only": {"value": 999}})
    meta = h.run.write_json("tree/explore/explore-000/meta.json", {"id": "explore-000", "status": "ok", "outputs": {accepted.relative_to(tmp_path).as_posix(): file_hash(accepted)}})
    Journal(h.run.path("journal.jsonl")).write("node_commit", stage="explore", node="explore-000", path=meta.relative_to(tmp_path).as_posix(), sha256=file_hash(meta), record_id="node-explore-000")
    science = ScienceStore(h.run)
    record_exploration(science, node_ref(science, meta))
    study = build_study(science, "Only accepted exploration is evidence")
    output = StudyOutput.model_validate_json(study.read_bytes())
    prose = diagnostic_writeup(output).model_copy(update={"results": r"Accepted \R{explore.accepted}; scratch \R{explore.scratch_only}."})
    h.run.commit_artifact(f"writeup:{h.run.artifact_ref('study').sha256}", h.run.write_json("saved-prose.json", prose.model_dump(mode="json")))
    tex, _, missing = write_study(h, study)
    assert missing == [r"\R{explore.scratch_only}"]
    assert "999" not in tex.read_text("utf-8")


@pytest.mark.parametrize("boundary", [None, "report", "identity"])
def test_no_budget_diagnostic_uses_common_template_and_exact_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str | None,
) -> None:
    import json

    from popper.stages.communicate import compiler

    config = load_config(env={})
    config.budget.max_usd = 0
    h = Harness(
        config,
        FakeLLM(lambda _: (_ for _ in ()).throw(AssertionError("no model calls"))),
        RunStore(tmp_path),
    )
    study = build_study(ScienceStore(h.run), "Budget exhausted before findings", "budget_exceeded")
    compile_calls = 0
    def compile_report(_: Path) -> None:
        nonlocal compile_calls
        compile_calls += 1
    monkeypatch.setattr(compiler, "compile_pdf", compile_report)
    identity = h.run.artifact_ref("study").sha256
    if boundary:
        original = RunStore.commit_artifact
        def interrupt(store: RunStore, name: str, path: Path) -> None:
            original(store, name, path)
            if name == ("report" if boundary == "report" else f"report:{identity}"):
                raise KeyboardInterrupt()
        monkeypatch.setattr(RunStore, "commit_artifact", interrupt)
        with pytest.raises(KeyboardInterrupt):
            write_study(h, study)
        accepted = h.run.committed("report") or h.run.committed(f"report:{identity}")
        assert accepted is not None
        accepted_tex = h.run.path(json.loads(accepted.read_text("utf-8"))["tex"])
        monkeypatch.setattr(RunStore, "commit_artifact", original)
    tex, _, missing = write_study(h, study)
    if boundary:
        assert tex == accepted_tex
    contents = tex.read_text("utf-8")
    assert "No accepted usable measurements" in contents
    assert "Budget exhausted before findings" in contents
    assert "Computed stability" not in contents and "non-supporting" not in contents
    assert missing == []
    assert write_study(h, study)[0] == tex
    assert compile_calls == 1
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
        frontier=[],
        candidates=[candidate],
        challenges=[{
            "ref": candidate.source.model_dump(mode="json"),
            "record": Challenge(
                snapshot=candidate.source, candidates=candidate.source, author="judge",
                assessments=[{
                    "hypothesis_id": candidate.id, "assessment": r"Challenge 50% & \input{secret}",
                    "concerns": [r"Concern \input{secret}"], "rivals": [r"Rival & uncertainty"],
                    "discriminating_checks": [r"Check \input{secret}"], "sources": [candidate.source],
                }],
            ).model_dump(mode="json"),
        }],
        interpretations=[{
            "ref": candidate.source.model_dump(mode="json"),
            "record": Interpretation(
                snapshot=candidate.source, result=candidate.source, hypothesis_id=candidate.id,
                author="theorist", summary=r"Summary 50% & \input{secret}",
                rivals=[r"Rival & uncertainty"], limitations=[r"Limits \input{secret}"],
                questions=[r"Question \input{secret}"], sources=[candidate.source],
            ).model_dump(mode="json"),
        }],
        stale_interpretations=[candidate.source],
        stop_reason=r"Stop \input{secret}",
        operational_status="budget_exceeded",
    )
    study = h.run.write_json("study.json", output.model_dump(mode="json"))
    h.run.commit_artifact("study", study)
    tex, _, _ = write_study(h, study)
    rendered = tex.read_text("utf-8")
    assert r"\input{secret}" not in rendered
    assert r"50\% \&" in rendered
    assert r"Challenge 50\% \&" in rendered and r"Summary 50\% \&" in rendered
    assert "Stale interpretation" in rendered
