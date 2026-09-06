"""Tests for item 3.2 (docs/dev/affine-curve-improvement-plan.md F6):
RefBondSelector.select_reference_bonds must record an explicit
reference-change event whenever a bucket's selected bond actually rolls,
so downstream residual z-scores can reset/adjust at the switch date instead
of silently absorbing the resulting curve-level jump.

Exercises select_reference_bonds directly, mocking out
_process_single_date and the upstream data-loading calls (px.pkl date list,
_prepare_bond_data) so the test targets the roll-detection/event-recording
logic itself rather than re-deriving a full production bond universe.
"""
import os

import pandas as pd
import pytest

from curves.calibration.selector import RefBondSelector
from curves.utils.file import loadPKL
from settings.fixed_income import BondConfig


def _run_selector(monkeypatch, tmp_path, dates, day_results_by_date, existing_ref_bond=None):
    """Drive select_reference_bonds with a scripted sequence of
    _process_single_date outputs, one per date in `dates`."""
    monkeypatch.setattr(BondConfig, 'TERM_BUCKETS', {5: [4.0, 6.0]})
    monkeypatch.setattr('curves.calibration.selector.DIR_INPUT', str(tmp_path))
    monkeypatch.setattr('curves.calibration.selector.DIR_DATA', str(tmp_path))

    px_path = os.path.join(str(tmp_path), 'TBond-px.pkl')
    close = pd.DataFrame(1.0, index=dates, columns=['dummy'])
    from curves.utils.file import updatePKL
    updatePKL({'Close': close}, px_path, rewrite=True)

    if existing_ref_bond is not None:
        ref_path = os.path.join(str(tmp_path), 'TBond-cvref.pkl')
        updatePKL({'RefBond': existing_ref_bond}, ref_path, rewrite=True)

    call_index = {'i': 0}

    def fake_process_single_date(self, bonds, current_date, bond_type, term_buckets, existing_results):
        result = day_results_by_date[call_index['i']]
        call_index['i'] += 1
        return result

    monkeypatch.setattr(RefBondSelector, '_process_single_date', fake_process_single_date)
    monkeypatch.setattr(RefBondSelector, '_prepare_bond_data', lambda self, env: {})

    selector = RefBondSelector()
    result_df = selector.select_reference_bonds(
        {}, [dates[0], dates[-1]], 'TBond', daily=False, update=True
    )
    ref_path = os.path.join(str(tmp_path), 'TBond-cvref.pkl')
    data = loadPKL(ref_path)
    return result_df, data


def test_reference_change_event_recorded_on_roll(monkeypatch, tmp_path):
    dates = pd.date_range('2026-01-01', periods=4, freq='D')
    col = 'Term near 5Y'
    scripted = [
        {col: 'BONDA.IB'},
        {col: 'BONDA.IB'},
        {col: 'BONDB.IB'},  # roll here
        {col: 'BONDB.IB'},
    ]
    result_df, data = _run_selector(monkeypatch, tmp_path, dates, scripted)

    assert 'RefBondChange' in data
    events = data['RefBondChange']
    assert len(events) == 1
    row = events.iloc[0]
    assert row['old_bond'] == 'BONDA.IB'
    assert row['new_bond'] == 'BONDB.IB'
    assert events.index.get_level_values('bucket')[0] == col
    assert events.index.get_level_values('date')[0] == dates[2]


def test_no_change_event_when_selection_is_stable(monkeypatch, tmp_path):
    dates = pd.date_range('2026-01-01', periods=4, freq='D')
    col = 'Term near 5Y'
    scripted = [{col: 'BONDA.IB'}] * 4
    result_df, data = _run_selector(monkeypatch, tmp_path, dates, scripted)
    assert 'RefBondChange' not in data or data['RefBondChange'].empty


def test_multiple_buckets_roll_same_day_both_recorded(monkeypatch, tmp_path):
    dates = pd.date_range('2026-01-01', periods=3, freq='D')
    col5, col10 = 'Term near 5Y', 'Term near 10Y'
    scripted = [
        {col5: 'A5.IB', col10: 'A10.IB'},
        {col5: 'B5.IB', col10: 'B10.IB'},  # both roll on the same day
        {col5: 'B5.IB', col10: 'B10.IB'},
    ]
    result_df, data = _run_selector(monkeypatch, tmp_path, dates, scripted)
    events = data['RefBondChange']
    assert len(events) == 2
    buckets = set(events.index.get_level_values('bucket'))
    assert buckets == {col5, col10}


def test_roll_detected_against_seeded_history_not_first_run_gap(monkeypatch, tmp_path):
    """A roll on the very first processed date must still be detected if
    prior history already has a value for that bucket (seeded from
    existing_result_df), not treated as a fresh bucket with no prior."""
    dates = pd.date_range('2026-01-05', periods=2, freq='D')
    col = 'Term near 5Y'
    existing = pd.DataFrame({col: ['BONDA.IB']}, index=[pd.Timestamp('2026-01-01')])
    scripted = [
        {col: 'BONDB.IB'},  # roll relative to seeded history, on day 1 of this run
        {col: 'BONDB.IB'},
    ]
    result_df, data = _run_selector(monkeypatch, tmp_path, dates, scripted, existing_ref_bond=existing)
    events = data['RefBondChange']
    assert len(events) == 1
    assert events.iloc[0]['old_bond'] == 'BONDA.IB'
    assert events.iloc[0]['new_bond'] == 'BONDB.IB'


def test_gap_day_with_no_selection_does_not_create_spurious_event(monkeypatch, tmp_path):
    """A day where the bucket has no selection (NaN) must not be treated as
    a roll, nor should the NaN itself become 'old_bond' for the next real
    change."""
    dates = pd.date_range('2026-01-01', periods=3, freq='D')
    col = 'Term near 5Y'
    scripted = [
        {col: 'BONDA.IB'},
        {col: float('nan')},   # gap day, no candidate found
        {col: 'BONDB.IB'},     # this is still a real roll from BONDA
    ]
    result_df, data = _run_selector(monkeypatch, tmp_path, dates, scripted)
    events = data['RefBondChange']
    assert len(events) == 1
    assert events.iloc[0]['old_bond'] == 'BONDA.IB'
    assert events.iloc[0]['new_bond'] == 'BONDB.IB'


def test_roll_reset_handles_date_indexed_history():
    """The cvref pickles index by `datetime.date` while the RefBondChange log
    is built from Timestamps. pandas raises TypeError on a datetime64-vs-date
    comparison rather than coercing, which broke the roll-reset guard on real
    production data. Both sides must be normalised before comparing."""
    import datetime as _dt
    import numpy as np
    from curves.calibration.residual_stats import compute_residual_stats

    dates = [_dt.date(2026, 1, 1) + _dt.timedelta(days=i) for i in range(80)]
    values = [1.0] * 40 + [1.5] * 40          # clean step change at the roll
    residual = pd.Series(values, index=dates, dtype=float)

    roll = pd.Timestamp('2026-02-10')          # Timestamp, not date
    events = pd.DataFrame(
        [{'old_bond': 'A', 'new_bond': 'B'}],
        index=pd.MultiIndex.from_tuples([(roll, 'Term near 5Y')], names=['date', 'bucket']),
    )

    out = compute_residual_stats(residual, change_events=events, bucket='Term near 5Y')
    assert out['fit_start'] is not None
    # Must fit only post-roll data, so the mean is the post-roll level.
    assert out['n_obs'] < len(residual)
    assert out['ou_mean'] == pytest.approx(1.5, abs=0.05)


def test_roll_reset_excludes_pre_roll_step_from_vol():
    """Without roll awareness the step-change inflates the vol estimate;
    with it, vol reflects genuine post-roll variation only."""
    import datetime as _dt
    import numpy as np
    from curves.calibration.residual_stats import compute_residual_stats

    rng = np.random.default_rng(0)
    dates = [_dt.date(2026, 1, 1) + _dt.timedelta(days=i) for i in range(80)]
    pre = 1.0 + rng.normal(0, 0.002, 40)
    post = 1.5 + rng.normal(0, 0.002, 40)
    residual = pd.Series(np.concatenate([pre, post]), index=dates, dtype=float)

    roll = pd.Timestamp(dates[40])
    events = pd.DataFrame(
        [{'old_bond': 'A', 'new_bond': 'B'}],
        index=pd.MultiIndex.from_tuples([(roll, 'B5')], names=['date', 'bucket']),
    )

    naive = compute_residual_stats(residual)
    fixed = compute_residual_stats(residual, change_events=events, bucket='B5')
    assert naive['ewm_vol'] > 5 * fixed['ewm_vol']


def test_splice_reference_rolls_is_noop_without_rolls():
    """No roll dates (or none matching the index) must return the input
    unchanged, so every existing caller is byte-identical."""
    import numpy as np
    from curves.calibration.stat import splice_reference_rolls

    dates = pd.date_range('2026-01-01', periods=30, freq='D')
    df = pd.DataFrame({'B': np.linspace(1.0, 1.3, 30)}, index=dates)

    assert splice_reference_rolls(df, []).equals(df)
    assert splice_reference_rolls(df, None) is df
    # A roll date outside the index changes nothing.
    assert splice_reference_rolls(df, [pd.Timestamp('2030-01-01')]).equals(df)


def test_splice_removes_roll_step_from_vol_but_keeps_history():
    """The whole point: kill the identity-change step so the vol estimate
    reflects genuine variation, WITHOUT discarding pre-roll observations
    (a hard reset would starve the estimator -- rolls are frequent)."""
    import numpy as np
    from curves.calibration.stat import splice_reference_rolls, OU_calibrate

    rng = np.random.default_rng(0)
    dates = pd.date_range('2026-01-01', periods=120, freq='D')
    series = 1.0 + rng.normal(0, 0.01, 120)
    series[60:] += 0.5                      # reference roll step
    df = pd.DataFrame({'B': series}, index=dates)

    spliced = splice_reference_rolls(df, [dates[60]])

    raw_vol = OU_calibrate(df)['ewm_vol'].iloc[0]
    spl_vol = OU_calibrate(spliced)['ewm_vol'].iloc[0]

    assert raw_vol > 5 * spl_vol             # contamination removed
    assert spl_vol == pytest.approx(0.01, rel=0.5)   # recovers true noise scale
    assert len(spliced) == len(df)           # full history retained


def test_splice_preserves_end_level():
    """Downstream 'close'/'mean' comparisons are on the raw scale, so the
    spliced series must end at the same level as the input."""
    import numpy as np
    from curves.calibration.stat import splice_reference_rolls

    dates = pd.date_range('2026-01-01', periods=40, freq='D')
    series = np.full(40, 1.0)
    series[20:] += 0.3
    df = pd.DataFrame({'B': series}, index=dates)

    spliced = splice_reference_rolls(df, [dates[20]])
    assert spliced['B'].iloc[-1] == pytest.approx(df['B'].iloc[-1])
