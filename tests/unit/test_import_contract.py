"""Executable ownership boundaries for production imports, including relative imports."""

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "src" / "popper"
PHASES = {"understand", "ground", "discover", "communicate", "verify"}
OWNERS = {
    "popper.harness": "harness",
    "popper.strategies.treesearch": "treesearch",
    "popper.scientific.runtime": "runtime",
    "popper.scientific.scientist": "scientist",
    "popper.workflow": "workflow",
    **{f"popper.stages.{phase}": phase for phase in PHASES},
}


def owners(target: str) -> set[str]:
    matches = [prefix for prefix in OWNERS if target == prefix or target.startswith(prefix + ".")]
    if matches:
        return {OWNERS[max(matches, key=len)]}
    return {owner for prefix, owner in OWNERS.items() if prefix.startswith(target + ".")}


def violations(source: str, module: str, *, package: bool = False) -> list[str]:
    source_owners = owners(module)
    owner = next(iter(source_owners)) if len(source_owners) == 1 else "container"
    allowed = (
        {owner, "harness", "treesearch", "runtime"}
        if owner in PHASES
        else {"scientist", "runtime", "harness"}
        if owner == "scientist"
        else {"runtime", "harness"}
        if owner == "runtime"
        else {owner}
        if owner in {"harness", "container"}
        else {owner, "harness"}
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
            targets = [f"{target}.{alias.name}" for alias in node.names]
            if not owners(target) or any(not owners(child) for child in targets):
                targets.append(target)
        for target in targets:
            if target == "evals" or target.startswith("evals.") or (
                target.startswith("popper.")
                and owner != "workflow"
                and (
                    not owners(target) or not owners(target) <= allowed
                    or owner == "runtime" and any(
                        target == forbidden or target.startswith(forbidden + ".")
                        for forbidden in (
                            "popper.harness.session", "popper.harness.llm",
                            "popper.harness.agents", "popper.harness.context.prompts",
                        )
                    )
                )
            ):
                failures.append(target)
    return failures


@pytest.mark.parametrize(
    ("source", "module", "bad"),
    [
        ("from popper.harness.session import Harness", "popper.stages.discover.experiment", False),
        ("from ...strategies.treesearch import engine", "popper.stages.ground.steward", False),
        ("from . import hypothesis", "popper.stages.discover.experiment", False),
        ("from popper.stages.ground.steward import ground", "popper.stages.discover.experiment", True),
        ("from ..ground import steward", "popper.stages.discover.experiment", True),
        ("from popper.stages import discover", "popper.harness.session", True),
        ("from ...stages.discover import experiment", "popper.strategies.treesearch.engine", True),
        ("import evals.suite", "popper.workflow.run", True),
        ("from popper.strategies.treesearch import engine", "popper.harness.session", True),
        ("from popper.scientific.runtime import contracts", "popper.harness.storage.records", True),
        ("from ...scientific.runtime.lifecycle import contracts", "popper.strategies.treesearch.engine", True),
        ("from popper.harness.session import Harness", "popper.scientific.runtime.projections.state", True),
        ("from popper.harness.llm import LLM", "popper.scientific.runtime.store", True),
        ("from popper.harness.storage.records import ArtifactRef", "popper.scientific.runtime.lifecycle.contracts", False),
        ("from ...scientific.runtime.lifecycle import contracts", "popper.stages.discover.experiment", False),
        ("from ...stages.discover import experiment", "popper.scientific.scientist.episode", True),
        ("from popper.scientific.runtime import contracts", "popper.scientific.scientist.moves", False),
        ("from popper import stages", "popper.harness.session", True),
        ("from popper.scientific import scientist", "popper.harness.session", True),
        ("from popper.harness.agents import loop", "popper.scientific.runtime.store", True),
        ("from popper.harness.context import prompts", "popper.scientific.runtime.store", True),
        ("from popper.harness.storage import records", "popper.scientific.runtime.store", False),
        ("from popper.strategies import treesearch", "popper.scientific.scientist.episode", True),
        ("from ...stages.discover import experiment", "popper.scientific.scientist.episode", True),
        ("from ..ground import steward", "popper.stages.discover.experiment", True),
        ("from ...scientific.runtime import store", "popper.stages.discover.experiment", False),
        ("from . import experiment", "popper.stages.discover.candidates", False),
        ("if TYPE_CHECKING:\n    from popper.stages import discover", "popper.harness.session", True),
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
