import pandas as pd
from examples.student_performance.make_data import build as signal_data
from examples.student_performance_null.make_data import build as null_data


def test_null_shuffle_preserves_entities_absent_mask_and_data_issues() -> None:
    signal, null = signal_data(), null_data()
    pd.testing.assert_frame_equal(null, null_data())
    pd.testing.assert_frame_equal(
        signal.drop(columns="exam_score"), null.drop(columns="exam_score")
    )
    assert signal.exam_score.eq("absent").equals(null.exam_score.eq("absent"))
    original = pd.to_numeric(
        signal.drop_duplicates("student_id").exam_score, errors="coerce"
    ).dropna()
    shuffled = pd.to_numeric(
        null.drop_duplicates("student_id").exam_score, errors="coerce"
    ).dropna()
    assert sorted(original) == sorted(shuffled)
    assert not signal.exam_score.equals(null.exam_score)
    assert null.groupby("student_id").exam_score.nunique().eq(1).all()
