"""Generate a deterministic student-performance dataset with planted signal and data-quality issues."""

from pathlib import Path

import numpy as np
import pandas as pd

N = 600


def build() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    school = rng.choice(["A", "B", "C"], N)
    gender = rng.choice(["F", "M"], N)
    income_idx = rng.choice([0, 1, 2], N, p=[0.3, 0.45, 0.25])
    income = np.array(["low", "mid", "high"])[income_idx]
    study = np.clip(rng.normal(12 + 2.5 * income_idx, 5, N), 0, 30)
    sleep = np.clip(rng.normal(7.2, 1.1, N), 4, 10)
    attendance = np.clip(rng.beta(8, 1.5, N), 0, 1)
    job = (rng.random(N) < 0.25).astype(int)

    score = (
        30
        + 12 * np.log1p(study)
        + 15 * attendance
        + 2.5 * np.minimum(sleep, 8.0)
        - 3 * job
        + 4 * (school == "C")
        + rng.normal(0, 8, N)
    )
    score = np.clip(score, 0, 100).round(1)

    df = pd.DataFrame(
        {
            "student_id": [f"S{i + 1:04d}" for i in range(N)],
            "school": school,
            "gender": gender,
            "family_income": income,
            "study_hours_week": study.round(1),
            "sleep_hours": sleep.round(1),
            "attendance_rate": attendance.round(3),
            "part_time_job": job,
            "exam_score": score,
        }
    )

    # Data-quality issues.
    df.loc[rng.choice(N, int(0.03 * N), replace=False), "sleep_hours"] = np.nan
    df.loc[rng.choice(N, int(0.02 * N), replace=False), "attendance_rate"] = np.nan
    bad = rng.choice(N, 5, replace=False)
    df.loc[bad[:2], "study_hours_week"] = -1.0
    df.loc[bad[2:4], "study_hours_week"] = 99.0
    df.loc[bad[4], "attendance_rate"] = 1.4

    mid = df.index[df["family_income"] == "mid"].to_numpy()
    variants = rng.choice(["Mid", "medium"], 40)
    df.loc[rng.choice(mid, 40, replace=False), "family_income"] = variants

    absent = np.zeros(N, dtype=bool)
    absent[rng.choice(N, 6, replace=False)] = True
    df["exam_score"] = df["exam_score"].astype(str).mask(absent, "absent")

    dupes = df.iloc[rng.choice(N, 8, replace=False)]
    return pd.concat([df, dupes], ignore_index=True)


if __name__ == "__main__":
    build().to_csv(Path(__file__).with_name("data.csv"), index=False)
