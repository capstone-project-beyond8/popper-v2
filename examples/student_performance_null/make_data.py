"""Shuffle numeric outcomes across unique students, retaining original data issues."""

from pathlib import Path

import numpy as np
import pandas as pd
from examples.student_performance.make_data import build as signal_data


def build() -> pd.DataFrame:
    data = signal_data()
    unique = data.drop_duplicates("student_id").set_index("student_id")
    numeric = pd.to_numeric(unique.exam_score, errors="coerce").notna()
    unique.loc[numeric, "exam_score"] = np.random.default_rng(17).permutation(
        unique.loc[numeric, "exam_score"].to_numpy()
    )
    data["exam_score"] = data.student_id.map(unique.exam_score)
    return data


if __name__ == "__main__":
    build().to_csv(Path(__file__).with_name("data.csv"), index=False)
