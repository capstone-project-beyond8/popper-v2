"""Numbers in the report come from results.json files, never from the model."""

import difflib
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


def collect_values(
    nodes: Sequence[Node], *, selected: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Canonical node keys; stage aliases only identify explicitly selected or unique nodes."""
    values: dict[str, Any] = {}
    aliases = (
        dict(selected)
        if selected is not None
        else {
            node.stage: node.id for node in nodes if sum(n.stage == node.stage for n in nodes) == 1
        }
    )
    for node in nodes:
        for name, entry in node.results.items():
            keys = [f"{node.id}.{name}"]
            if aliases.get(node.stage) == node.id:
                keys.append(f"{node.stage}.{name}")
            for key in keys:
                values[key] = entry["value"]
                for part in ("ci", "n"):
                    if part in entry:
                        values[f"{key}.{part}"] = entry[part]
    return values


def _number(v: Any) -> str:
    if isinstance(v, list):
        return f"{_number(v[0])}--{_number(v[1])}"
    if isinstance(v, float):
        return f"{v:.3g}"
    if isinstance(v, str):
        return latex_escape(v)
    return str(v)


def explain_missing(ref: str, values: Mapping[str, Any]) -> str:
    """Name the closest known key for a macro from `fill_numbers`' missing list."""
    match = _REF.fullmatch(ref)
    key = match.group(1) if match else ref
    close = difflib.get_close_matches(key, list(values), n=1)
    return f"{ref}: no key {key}" + (f" (did you mean {close[0]}?)" if close else "")


def fill_numbers(tex: str, values: Mapping[str, Any]) -> tuple[str, list[str]]:
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        if match.group(1) in values:
            return _number(values[match.group(1)])
        if match.group(0) not in missing:
            missing.append(match.group(0))
        return r"\textbf{??}"

    return _REF.sub(replace, tex), missing
