import pytest

from popper.science.research import (
    ResearchContext,
    ResearchError,
    check_columns,
    parse_research,
    render_research,
)


def _doc(front: str, body: str = "Why do scores differ?") -> str:
    return f"---\n{front}\n---\n{body}"


def test_body_only_parses() -> None:
    ctx = parse_research("Why do scores differ?\n")
    assert ctx.body == "Why do scores differ?\n" and ctx.variables == {}


def test_bare_value_is_confirmed_and_null_unknown() -> None:
    ctx = parse_research(_doc("domain: schools\nvariables:\n  score: {unit: null, role: outcome}"))
    assert ctx.domain.status == "confirmed" and ctx.domain.value == "schools"
    assert ctx.variables["score"].role.status == "confirmed"
    assert ctx.variables["score"].unit.status == "unknown"


def test_dashes_in_body_are_kept() -> None:
    body = "Intro\n---\nmore\n"
    assert parse_research(_doc("domain: x", body)).body == body


@pytest.mark.parametrize(
    "front",
    [
        "domain: {value: x, status: proposed}",
        "domain: {value: x, status: unknown}",
        "domain: {value: null, status: confirmed}",
        "variables: {a: {type: number}}",
        "variables: {a: {role: boss}}",
        "variables: {a: {role: {value: outcome, status: maybe}}}",
        "variables: {a: {range: [5, 1]}}",
        "variables: {a: {range: [0, .inf]}}",
        "variables: {a: {levels: [x, x]}}",
        "variables: {a: {levels: [1, 2]}}",
        "colour: red",
        "variables: {a: {shade: red}}",
    ],
)
def test_invalid_front_matter_is_rejected(front: str) -> None:
    with pytest.raises(ResearchError):
        parse_research(_doc(front))


def test_empty_body_is_rejected() -> None:
    with pytest.raises(ResearchError):
        parse_research("---\ndomain: x\n---\n  \n")


def test_all_missing_columns_are_reported_together() -> None:
    ctx = parse_research(
        _doc(
            "variables: {a: {role: outcome}, b: {role: ignore}}\n"
            "design: {cluster_column: c}\n"
            "constraints: {excluded: [d]}"
        )
    )
    problems = check_columns(ctx, ["a"])
    assert len(problems) == 3 and not check_columns(ctx, ["a", "b", "c", "d"])


def test_column_match_is_exact() -> None:
    ctx = parse_research(_doc("variables: {Score: {role: outcome}}"))
    assert check_columns(ctx, ["score"])


def test_render_round_trips() -> None:
    ctx = parse_research(
        _doc(
            "domain: schools\n"
            "variables:\n  score: {range: [0, 100], role: outcome}\n"
            "  grade: {levels: [a, b], order: 2}\n"
            "design: {kind: observational, cluster_column: school}\n"
            "assumptions: [{id: a1, description: ages differ, confounder: true}]\n"
            "concepts: [{id: c1, name: effort, definition: {value: time, status: proposed, evidence: [q]}}]\n"
            "notes: {writing: be concise}",
            "Body\n---\nend\n",
        )
    )
    assert parse_research(render_research(ctx)) == ctx
    assert isinstance(ctx, ResearchContext)
