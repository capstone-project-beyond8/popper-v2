"""Command-line entry point."""

import argparse

from popper import __version__


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="popper", description="AI scientist for tabular data.")
    parser.add_argument("--version", action="version", version=f"popper {__version__}")
    parser.parse_args(argv)
    parser.print_help()
    return 0
