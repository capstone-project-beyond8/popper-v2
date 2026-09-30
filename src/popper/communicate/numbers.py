"""Numbers in the report come from results.json files, never from the model."""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from popper.treesearch.engine import Node

_REF = re.compile(r"\\(R|CI|N)\{([^}]*)\}")
_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


def latex_escape(text: str) -> str:
    return "".join(_ESCAPES.get(c, c) for c in text)


def collect_values(nodes: Sequence[Node]) -> dict[str, dict[str, Any]]:
    return {f"{n.stage}.{name}": entry for n in nodes for name, entry in n.results.items()}


def _number(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.3g}"
    if isinstance(v, str):
        return latex_escape(v)
    return str(v)


def _render(kind: str, entry: Mapping[str, Any]) -> str | None:
    if kind == "R":
        return _number(entry["value"])
    if kind == "CI" and "ci" in entry:
        lo, hi = entry["ci"]
        return f"{_number(lo)}--{_number(hi)}"
    if kind == "N" and "n" in entry:
        return _number(entry["n"])
    return None


def fill_numbers(tex: str, values: Mapping[str, Mapping[str, Any]]) -> tuple[str, list[str]]:
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        entry = values.get(match.group(2))
        text = None if entry is None else _render(match.group(1), entry)
        if text is not None:
            return text
        if match.group(0) not in missing:
            missing.append(match.group(0))
        return r"\textbf{??}"

    return _REF.sub(replace, tex), missing
