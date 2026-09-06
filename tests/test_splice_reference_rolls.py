"""Tests for curves/calibration/stat.py::splice_reference_rolls."""
import numpy as np
import pandas as pd

from curves.calibration.stat import splice_reference_rolls


def _idx(n=10):
    return pd.date_range('2026-01-01', periods=n, freq='D')


def test_no_roll_dates_returns_unchanged():
    idx = _idx(6)
    df = pd.DataFrame({'A': [1.0, 1.1, 1.2, 1.3, 1.4, 1.5]}, index=idx)
    out = splice_reference_rolls(df, [])
    pd.testing.assert_frame_equal(out, df)


def test_roll_date_outside_window_returns_unchanged():
    idx = _idx(6)
    df = pd.DataFrame({'A': [1.0, 1.1, 1.2, 1.3, 1.4, 1.5]}, index=idx)
    out = splice_reference_rolls(df, [pd.Timestamp('2020-01-01')])
    pd.testing.assert_frame_equal(out, df)


def test_removes_the_roll_day_step():
    """A discontinuous step on the roll date must be spliced out, leaving a
    level-continuous series that still reflects genuine day-to-day moves."""
    idx = _idx(6)
    # A 5.0 step at index 3 (the roll), otherwise a smooth +0.1/day trend.
    df = pd.DataFrame({'A': [1.0, 1.1, 1.2, 6.3, 6.4, 6.5]}, index=idx)
    out = splice_reference_rolls(df, [idx[3]])
    # The roll date's own diff is zeroed (the identity-change step is
    # dropped, not replaced with the day's real move), so every OTHER
    # day-over-day diff should still show the smooth +0.1/day trend.
    diffs = out['A'].diff().dropna()
    non_roll_diffs = diffs.drop(idx[3])
    assert np.allclose(non_roll_diffs.to_numpy(), 0.1, atol=1e-9)
    assert out['A'].loc[idx[3]] == out['A'].loc[idx[2]]


def test_missing_final_observation_does_not_wipe_the_whole_column():
    """Regression: anchoring the re-cumulated series on spread.iloc[-1] (the
    panel's last ROW) instead of each column's own last VALID value meant a
    single bond missing only its most recent quote (e.g. the run date is a
    non-trading day with no fresh close yet) had that NaN broadcast across
    its entire history via `spliced - spliced.iloc[-1] + spread.iloc[-1]`.
    On real TBond data this collapsed OU_calibrate's coverage from 100+
    reference bonds to 25, which cascaded into the Daily Spread Statistics
    chart showing only a handful of tickers.
    """
    idx = _idx(6)
    df = pd.DataFrame({
        'complete': [1.0, 1.1, 1.2, 1.3, 1.4, 1.5],
        'missing_last': [2.0, 2.1, 2.2, 2.3, 2.4, np.nan],
    }, index=idx)
    out = splice_reference_rolls(df, [idx[2]])

    assert out['complete'].notna().sum() == 6
    # Only the genuinely-missing final point should be NaN -- not the whole column.
    assert out['missing_last'].notna().sum() == 5
    assert pd.isna(out['missing_last'].iloc[-1])


def test_original_nan_positions_stay_nan():
    """A gap in the middle of the panel is carried through the cumsum as
    'no change' so later values stay level-continuous, but that gap was
    never an observation and must not be reported as one."""
    idx = _idx(6)
    df = pd.DataFrame({'A': [1.0, 1.1, np.nan, 1.3, 1.4, 1.5]}, index=idx)
    out = splice_reference_rolls(df, [idx[1]])
    assert pd.isna(out['A'].iloc[2])
    assert out['A'].notna().sum() == 5


def test_bond_with_no_observations_at_all_stays_all_nan():
    idx = _idx(6)
    df = pd.DataFrame({'A': [np.nan] * 6}, index=idx)
    out = splice_reference_rolls(df, [idx[2]])
    assert out['A'].isna().all()
