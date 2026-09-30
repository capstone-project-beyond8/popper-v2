"""Figure validation and effect-blind projections for independent judging."""

import ast
import json
from pathlib import Path
from typing import TYPE_CHECKING

from popper.harness.context import ARTIFACT_CHARS, CODE_CHARS, part
from popper.harness.interpreter import ExecResult
from popper.harness.prompts import load_prompt

if TYPE_CHECKING:
    from popper.harness.session import Harness
    from popper.treesearch.engine import Node, StageSpec


def validate_image(path: Path) -> Path:
    if not path.is_file() or path.suffix.lower() != ".png":
        raise ValueError("Judge image must be an existing PNG")
    if path.stat().st_size > 3_750_000:
        raise ValueError("Judge image is larger than 3.75 MB")
    if not path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Judge image has invalid PNG contents")
    from matplotlib.image import imread

    try:
        imread(path)
    except (OSError, ValueError, SyntaxError) as exc:
        raise ValueError("Judge image cannot be decoded") from exc
    return path


class _MaskLiterals(ast.NodeTransformer):
    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        return ast.copy_location(ast.Constant(value="<withheld>"), node)


def _blinded_code(code: str) -> str:
    try:
        return ast.unparse(_MaskLiterals().visit(ast.parse(code)))
    except (ValueError, SyntaxError):
        return "Source could not be projected."


def make_diagnostic(h: "Harness", node: "Node") -> None:
    # Only sample counts enter this image; no model-written pixels or labels are forwarded.
    counts = [entry["n"] for entry in node.results.values() if isinstance(entry.get("n"), int)]
    code = (
        "import matplotlib.pyplot as plt\n"
        f"counts = {counts or [0]!r}\n"
        "plt.bar(range(len(counts)), counts)\n"
        "plt.xlabel('Result index'); plt.ylabel('Sample count')\n"
        "plt.title('Reported sample sizes; estimates withheld')\n"
        "plt.tight_layout(); plt.savefig('samples.png')\n"
    )
    result = h.execute(code, node.dir / "judge_figures", inputs={}, node=node.id, purpose="plot")
    if result.exit_code != 0 or result.timed_out:
        raise ValueError(f"could not create blinded diagnostic: {result.stderr}")


def judge_input(
    spec: "StageSpec",
    node: "Node",
    execution: ExecResult,
) -> tuple[str, tuple[Path, ...]]:
    images: tuple[Path, ...]
    if spec.blind_estimates:
        goal = "Assess analysis validity, completeness and method fidelity; estimates are withheld."
        code = _blinded_code(node.code)
        stdout = "Execution passed code checks. Numerical logs withheld."
        projected = {
            key: {
                "value": "withheld",
                "ci": "withheld" if "ci" in entry else None,
                **({"n": entry["n"]} if "n" in entry else {}),
            }
            for key, entry in node.results.items()
        }
        summary = (
            "Only structural diagnostics are attached. No inference from sign or significance."
        )
        images = (node.dir / "judge_figures" / "samples.png",)
    else:
        goal, code, stdout, projected = spec.goal, node.code, execution.stdout, node.results
        summary = spec.describe(node.execution_dir) if spec.describe else "(none)"
        images = tuple(node.execution_dir / "figures" / name for name in node.figures)
    prompt = load_prompt(
        "popper.treesearch",
        "judge.md",
        goal=goal,
        code=part("Code", code, CODE_CHARS, untrusted=True),
        stdout=part("Output", stdout, ARTIFACT_CHARS, keep="tail", untrusted=True),
        results=part("results.json", json.dumps(projected), ARTIFACT_CHARS, untrusted=True),
        summary=part("Independent summary", summary, ARTIFACT_CHARS, untrusted=True),
    )
    return prompt, tuple(validate_image(path) for path in images)
