from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError

from popper.communicate.paper import FigureRef, Writeup, _render_report, _select_figures
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
        [{"step": "drop", "rows_affected": 1, "reason": "missing"}],
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
    assert "EXPERIMENT_CODE" in tex and "Data preparation" not in tex
    label = r"\label{fig:specification-curve}"
    ref = r"\ref{fig:specification-curve}"
    assert label in tex and ref in tex and 0 < tex.index(label) - tex.index(ref) < 400
    assert "All 4 variants" in tex and missing == [r"\R{main.nope}"]
    assert tex.index("Step & Rows") < tex.index(r"\section{Results}")


def test_figure_references_are_identity_based_bounded_and_known(tmp_path: Path) -> None:
    nodes = [
        cast(Node, SimpleNamespace(id=f"main-{i:03d}", stage="main", figures=["fit.png"]))
        for i in range(4)
    ]
    refs = [FigureRef(node_id=n.id, file="fit.png", caption="fit", section="main") for n in nodes]
    assert len(_select_figures(refs + refs, nodes)) == 3
    with pytest.raises(ValueError, match="unknown figure"):
        _select_figures(
            [FigureRef(node_id="main-000", file="../secret.png", caption="x", section="main")],
            nodes,
        )


def test_writer_cannot_set_evidence_labels() -> None:
    with pytest.raises(ValidationError, match="computed"):
        Writeup.model_validate({**WRITEUP, "conclusion": "The evidence is confirmed."})
