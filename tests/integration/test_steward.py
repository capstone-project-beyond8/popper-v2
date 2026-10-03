from pathlib import Path

import pytest

from popper.ground.steward import ground
from popper.harness.descriptive import describe_table, read_table
from popper.harness.llm import FakeLLM, LLMRequest, ToolCall
from popper.harness.research import parse_research
from popper.harness.session import Harness
from popper.harness.store import RunStore
from tests.integration.test_run import (
    DATA,
    EXAMPLE,
    FRAMING,
    _config,
    _submit_ground,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]

FAILING = """
import os
raise RuntimeError(sorted(k for k in os.environ if k.startswith("POPPER_INPUT")))
"""


def test_failed_submit_returns_the_reason_and_the_corrected_one_is_accepted(
    tmp_path: Path,
) -> None:
    steward: list[LLMRequest] = []

    def respond(req: LLMRequest) -> str | tuple[ToolCall, ...]:
        assert req.tag == "steward"
        steward.append(req)
        return _submit_ground(FAILING if len(steward) == 1 else DATA)

    config = _config()
    store = RunStore.create(
        tmp_path,
        EXAMPLE / "research.md",
        EXAMPLE / "data.csv",
        config=config,
    )
    research = parse_research(store.path("research.md").read_text("utf-8"))
    report = describe_table(read_table(store.path("data", "raw.csv")), research)
    store.write_json("data/ida-raw.json", {"results": report.results, "layout": report.layout})
    foundation = ground(Harness(config, FakeLLM(respond), store), research, FRAMING)
    assert len(steward) == 2
    verdict = steward[1].messages[-1].tool_results[0]
    assert verdict.status == "error" and "['POPPER_INPUT_RAW']" in verdict.text
    accepted = store.committed("foundation")
    assert accepted is not None
    attempt = accepted.parent
    assert foundation.preparation == attempt / "submit-01" / "execution"
    assert (foundation.preparation / "processed.parquet").is_file()
    assert (attempt / "ida.json").is_file()
    assert (attempt / "submit-00" / "execution" / "code.py").exists()
    assert not any("holdout" in r.prompt for r in steward)
