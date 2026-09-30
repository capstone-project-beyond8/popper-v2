"""Executable ownership boundaries for production imports, including relative imports."""

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "src" / "popper"
PHASES = {"understand", "ground", "discover", "communicate", "verify"}


def violations(source: str, module: str, *, package: bool = False) -> list[str]:
    owner = module.split(".")[1]
    allowed = (
        {owner, "harness", "treesearch"}
        if owner in PHASES or owner == "treesearch"
        else {"harness"}
    )
    context = module if package else module.rsplit(".", 1)[0]
    failures = []
    for node in ast.walk(ast.parse(source)):
        targets = []
        if isinstance(node, ast.Import):
            targets = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            target = (
                resolve_name("." * node.level + (node.module or ""), context)
                if node.level
                else (node.module or "")
            )
            targets = [target, *(f"{target}.{alias.name}" for alias in node.names)]
        for target in targets:
            parts = target.split(".")
            if parts[0] == "evals" or (
                len(parts) > 1
                and parts[0] == "popper"
                and owner in PHASES | {"harness", "treesearch"}
                and parts[1] not in allowed
            ):
                failures.append(target)
    return failures


@pytest.mark.parametrize(
    ("source", "module", "bad"),
    [
        ("from popper.harness.session import Harness", "popper.discover.experiment", False),
        ("from ..treesearch import engine", "popper.ground.data", False),
        ("from . import hypothesis", "popper.discover.experiment", False),
        ("from popper.ground.data import prepare", "popper.discover.experiment", True),
        ("from ..ground import data", "popper.discover.experiment", True),
        ("from popper import discover", "popper.harness.session", True),
        ("from ..discover import experiment", "popper.treesearch.engine", True),
        ("import evals.suite", "popper.coordinator.run", True),
        ("from popper.treesearch import engine", "popper.harness.session", True),
    ],
)
def test_checker_handles_absolute_and_relative_imports(source: str, module: str, bad: bool) -> None:
    assert bool(violations(source, module)) is bad


def test_production_import_boundaries() -> None:
    errors: list[str] = []
    for path in ROOT.rglob("*.py"):
        parts = path.relative_to(ROOT.parent).with_suffix("").parts
        if len(parts) == 2 and parts[-1] != "__init__":
            continue  # CLI and entry point compose the public workflow.
        module = ".".join(parts[:-1] if parts[-1] == "__init__" else parts)
        if module == "popper":
            continue
        errors.extend(
            f"{path}: {target}"
            for target in violations(
                path.read_text("utf-8"), module, package=path.name == "__init__.py"
            )
        )
    assert not errors, "\n".join(errors)
