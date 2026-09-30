"""Command-line entry point."""

import argparse
import os
import sys
from pathlib import Path

from popper import __version__
from popper.communicate.paper import compile_pdf
from popper.coordinator.run import run
from popper.harness.config import load_config
from popper.harness.llm import BedrockLLM

_NO_PDF = "PDF not built (install tectonic, latexmk or pdflatex, or see {log})"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="popper", description="AI scientist for tabular data.")
    parser.add_argument("--version", action="version", version=f"popper {__version__}")
    sub = parser.add_subparsers(dest="command")
    run_p = sub.add_parser("run", help="run all phases on a brief and a CSV file")
    run_p.add_argument("dir", nargs="?", type=Path, help="folder with brief.md and data.csv")
    run_p.add_argument("--brief", type=Path, help="path to the brief")
    run_p.add_argument("--data", type=Path, help="path to the CSV data")
    run_p.add_argument("--config", type=Path, help="YAML overrides for the default config")
    run_p.add_argument("--runs-dir", type=Path, default=Path("runs"), help="where runs are written")
    pdf_p = sub.add_parser("pdf", help="build the PDF for an existing run")
    pdf_p.add_argument("run_dir", type=Path, help="run folder containing report/paper.tex")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "pdf":
        tex = args.run_dir / "report" / "paper.tex"
        if not tex.is_file():
            parser.error(f"file not found: {tex}")
        pdf = compile_pdf(tex)
        if pdf is None:
            print(_NO_PDF.format(log=tex.parent / "compile.log"), file=sys.stderr)
            return 1
        print(pdf)
        return 0
    if args.command != "run":
        parser.print_help()
        return 0
    brief: Path | None = args.brief
    data: Path | None = args.data
    if args.dir is not None:
        brief, data = brief or args.dir / "brief.md", data or args.dir / "data.csv"
    if brief is None or data is None:
        parser.error("give DIR, or both --brief and --data")
    for path in (brief, data):
        if not path.is_file():
            parser.error(f"file not found: {path}")
    outcome = run(
        brief,
        data,
        config=load_config(args.config),
        llm=BedrockLLM(region=os.environ.get("AWS_REGION", "us-east-1")),
        runs_dir=args.runs_dir,
    )
    print(outcome.run_dir)
    if outcome.status != "completed":
        print(outcome.message, file=sys.stderr)
        return 1
    if outcome.missing:
        print(
            f"warning: numbers missing from results: {', '.join(outcome.missing)}", file=sys.stderr
        )
    if outcome.pdf is not None:
        print(outcome.pdf)
    else:
        print(outcome.tex)
        print(_NO_PDF.format(log=outcome.run_dir / "report" / "compile.log"), file=sys.stderr)
    return 0
