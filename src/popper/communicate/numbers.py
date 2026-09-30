"""Numbers in the report come from results.json files, never from the model."""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from popper.treesearch.engine import Node

_REF = re.compile(r"\\R\{([^}]*)\}")
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


def format_value(entry: Mapping[str, Any]) -> str:
    text = _number(entry["value"])
    if "ci" in entry:
        lo, hi = entry["ci"]
        text += f" [{_number(lo)}, {_number(hi)}]"
    if "n" in entry:
        text += f" (n = {_number(entry['n'])})"
    return text


def fill_numbers(tex: str, values: Mapping[str, Mapping[str, Any]]) -> tuple[str, list[str]]:
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in values:
            return format_value(values[key])
        if key not in missing:
            missing.append(key)
        return r"\textbf{??}"

    return _REF.sub(replace, tex), missing
