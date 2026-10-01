from typing import Any

from evals.run_metrics import summarize


def test_metrics_keep_sessions_costs_and_failures_separate() -> None:
    events: list[dict[str, Any]] = [
        {"event": "phase", "name": "ground"},
        {
            "event": "llm_call",
            "role": "theorist",
            "tag": "ground",
            "session": "a",
            "input_tokens": 10,
            "cache_read_tokens": 80,
            "cache_write_tokens": 10,
            "output_tokens": 5,
            "usd": 0.2,
        },
        {
            "event": "tool_call",
            "tag": "ground",
            "session": "a",
            "tool": "submit_ground",
            "status": "error",
            "result": "invalid evidence",
        },
        {
            "event": "tool_call",
            "tag": "ground",
            "session": "a",
            "tool": "read_artifact",
            "status": "error",
            "result": "error: artifact does not exist",
        },
        {
            "event": "tool_call",
            "tag": "ground",
            "session": "a",
            "tool": "run_python",
            "status": "error",
            "result": "exit code 1",
        },
        {
            "event": "tool_call",
            "tag": "ground",
            "session": "a",
            "tool": "ask_researcher",
            "status": "success",
            "result": "No researcher is available",
        },
        {
            "event": "tool_call",
            "tag": "ground",
            "session": "a",
            "tool": "submit_ground",
            "status": "success",
        },
        {
            "event": "llm_call",
            "role": "theorist",
            "tag": "ground",
            "session": "b",
            "input_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 0,
            "usd": 0.1,
        },
        {"event": "context_cut", "tag": "ground", "title": "data", "length": 20, "limit": 10},
        {"event": "phase", "name": "communicate"},
        {"event": "llm_call", "role": "writer", "tag": "writeup", "usd": 0.1},
        {"event": "state_commit", "path": "state/000001.json"},
    ]
    report = summarize(events)
    assert report["total"]["usd"] == 0.4
    assert report["total"]["cache_read_ratio"] == 0.8
    assert report["roles"]["theorist"]["calls"] == 2
    assert report["tags"]["ground"]["input_tokens"] == 10
    assert report["sessions"]["a"]["rejected_submits"] == 1
    assert report["sessions"]["a"]["accepted_submits"] == 1
    assert report["sessions"]["b"]["cache_read_ratio"] == 0
    assert report["tool_errors"] == {"avoidable": 2, "code": 1, "other": 0}
    assert report["sessions"]["a"]["role"] == "theorist"
    assert report["sessions"]["a"]["tag"] == "ground"
    assert len(report["context_cuts"]) == 1
    assert report["phases"]["ground"]["usd"] == 0.3
    assert report["phases"]["communicate"]["cumulative_usd"] == 0.4
