from types import SimpleNamespace
from typing import cast

from popper.communicate.paper import (
    FigureRef,
    Writeup,
    _problems,
    _render_report,
    _select_figures,
)
from popper.treesearch.engine import Node
from tests.integration.test_run import WRITEUP


def test_fixed_structure_computed_labels_and_all_experiment_code() -> None:
    w = Writeup.model_validate(
        {
            **WRITEUP,
            "robustness": "sensitivity",
            "discussion": "limitations",
            "conclusion": "association",
            "figures": [],
        }
    )
    rows = [
        {
            "id": "main-000",
            "stage": "main",
            "attempt_id": None,
            "adversarial": False,
            "key": "main-000.primary_estimate",
        }
    ]
    node = cast(
        Node, SimpleNamespace(id="main-000", stage="main", status="ok", code="EXPERIMENT_CODE")
    )
    tex, missing = _render_report(
        w,
        [{"step": "drop", "rows_affected": "rows_removed", "reason": "missing"}],
        [node],
        rows,
        {
            "stability": "fragile",
            "reasons": ["failed variant"],
            "nodes": [{"id": "robustness-001", "status": "buggy"}],
            "specifications": [{"id": "not-run", "node": None}],
        },
        [
            {
                "id": "specification-curve",
                "path": "figures/curve.png",
                "section": "robustness",
                "caption": r"All \R{summary.variant_count} variants",
            }
        ],
        {
            "main.primary_estimate": 1,
            "main-000.primary_estimate": 1,
            "main-000.primary_estimate.ci": [0, 2],
            "main-000.primary_estimate.n": 10,
            "summary.variant_count": 4,
            "summary.supporting_count": 2,
            "summary.supporting_share": 0.5,
            "summary.adversarial_count": 1,
            "data.rows_removed": 73,
        },
    )
    headings = [
        r"\section{Introduction}",
        r"\section{Data and Methods}",
        r"\section{Results}",
        r"\subsection{Exploratory}",
        r"\subsection{Main}",
        r"\subsection{Robustness}",
        r"\section{Discussion}",
        r"\section{Conclusion}",
        r"\appendix",
    ]
    assert [tex.index(h) for h in headings] == sorted(tex.index(h) for h in headings)
    assert "fragile" in tex and "failed variant" in tex and "robustness-001" in tex
    assert r"\lstinputlisting{code/main-000.py}" in tex
    assert "EXPERIMENT_CODE" not in tex and r"\begin{lstlisting}" not in tex
    label = r"\label{fig:specification-curve}"
    ref = r"\ref{fig:specification-curve}"
    assert label in tex and ref in tex and 0 < tex.index(label) - tex.index(ref) < 400
    assert "All 4 variants" in tex and missing == [r"\R{main.nope}"]
    assert tex.index("Step & Rows") < tex.index(r"\section{Results}")
    assert "drop & 73 & missing" in tex


def test_figure_references_are_identity_based_bounded_known_and_exploration_first() -> None:
    nodes = [
        cast(Node, SimpleNamespace(id=f"main-{i:03d}", stage="main", figures=["fit.png"]))
        for i in range(4)
    ]
    explore = cast(Node, SimpleNamespace(id="explore-000", stage="explore", figures=["raw.png"]))
    refs = [FigureRef(node_id=n.id, file="fit.png", caption="fit", section="main") for n in nodes]
    assert len(_select_figures(refs + refs, nodes)) == 3
    raw = FigureRef(node_id="explore-000", file="raw.png", caption="raw", section="data_methods")
    assert _select_figures([*refs, raw], [*nodes, explore])[0][0] is explore
    escape = FigureRef(node_id="main-000", file="../secret.png", caption="x", section="main")
    assert _select_figures([escape], nodes) == []


def test_writer_cannot_set_evidence_labels() -> None:
    w = Writeup.model_validate({**WRITEUP, "conclusion": "The evidence is confirmed."})
    assert "evidence label inserted by code" in _problems(w, {}, [])
