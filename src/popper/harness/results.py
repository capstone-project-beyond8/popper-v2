"""The named-entry schema of `results.json` and its validation."""

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, TypeAdapter


class ResultEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: float | int | str
    ci: tuple[float, float] | None = None
    n: int | None = None
    note: str | None = None


_RESULTS = TypeAdapter(dict[str, ResultEntry])
_RESULT_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def validate_results(obj: object) -> dict[str, dict[str, Any]]:
    """Validated results mapping; raises pydantic ValidationError or ValueError for the first problem."""
    entries = _RESULTS.validate_json(json.dumps(obj))
    for key in entries:
        if not _RESULT_KEY.match(key):
            raise ValueError(f"results.json key {key!r} must match [A-Za-z][A-Za-z0-9_]*")
    return {k: v.model_dump(mode="json", exclude_none=True) for k, v in entries.items()}
