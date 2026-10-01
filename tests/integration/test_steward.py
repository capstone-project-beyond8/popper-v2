import json
import os
from pathlib import Path

import pytest

from popper.coordinator.run import run
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.store import RunStore
from tests.integration.test_run import (
    DATA,
    EXAMPLE,
    WRITEUP,
    _config,
    _respond,
    _submit_ground,
)

pytestmark = pytest.mark.integration

FAILING = """
import os
raise RuntimeError(sorted(k for k in os.environ if k.startswith("POPPER_INPUT")))
"""


def test_failed_submit_returns_the_reason_and_the_corrected_one_is_accepted(
    tmp_path: Path,
) -> None:
    steward: list[LLMRequest] = []

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        if req.tag == "steward":
            steward.append(req)
            return _submit_ground(FAILING if len(steward) == 1 else DATA)
        if req.tag == "writeup":
            return json.dumps({**WRITEUP, "data": r"Rows kept: \R{data.rows_after}."})
        return _respond(req)

    out = run(
        EXAMPLE / "research.md",
        EXAMPLE / "data.csv",
        config=_config(),
        auto=True,
        llm=FakeLLM(respond),
        runs_dir=tmp_path,
    )
    assert out.status == "completed" and out.tex is not None
    verdict = steward[1].messages[-1].tool_results[0]
    assert verdict.status == "error" and "['POPPER_INPUT_RAW']" in verdict.text
    root = out.run_dir
    for name in ("processed.parquet", "ida.json"):
        assert (root / "data" / name).exists()
        assert not os.access(root / "data" / name, os.W_OK)
    assert not (root / "tree" / "data").exists()
    accepted = RunStore(root).committed("foundation")
    assert accepted is not None
    attempt = accepted.parent
    results = json.loads((attempt / "submit-01" / "execution" / "results.json").read_text("utf-8"))
    assert (attempt / "submit-00" / "execution" / "code.py").exists()
    assert f"Rows kept: {results['rows_after']['value']}." in out.tex.read_text("utf-8")
    assert not any("holdout" in r.prompt for r in steward)
