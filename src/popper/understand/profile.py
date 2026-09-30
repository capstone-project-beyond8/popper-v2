"""Structural profile of a CSV file."""

from pathlib import Path
from typing import Any

import pandas as pd


def profile_csv(path: Path, max_examples: int = 5) -> dict[str, Any]:
    df = pd.read_csv(path)
    columns = {
        str(name): {
            "dtype": str(col.dtype),
            "n_missing": int(col.isna().sum()),
            "n_unique": int(col.nunique()),
            "examples": [str(v) for v in col.dropna().unique()[:max_examples]],
        }
        for name, col in df.items()
    }
    return {"n_rows": len(df), "n_duplicate_rows": int(df.duplicated().sum()), "columns": columns}
