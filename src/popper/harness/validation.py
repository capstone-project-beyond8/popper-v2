"""Compact, field-addressed validation feedback."""

from pydantic import ValidationError


def format_errors(exc: ValidationError) -> str:
    """Keep every location and cause, without repeating input values or documentation URLs."""
    errors = exc.errors(include_input=False, include_url=False, include_context=False)
    lines = [f"{len(errors)} validation issues:"]
    lines.extend(
        f"- {'.'.join(str(p) for p in e['loc']) or '$'}: {e['msg']} [{e['type']}]"
        for e in errors
    )
    return "\n".join(lines)
