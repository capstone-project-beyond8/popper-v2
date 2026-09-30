"""Load a prompt template shipped inside a package and fill its fields."""

from importlib.resources import files


def load_prompt(package: str, name: str, **fields: str) -> str:
    return (files(package) / "prompts" / name).read_text("utf-8").format(**fields)
