"""Regression test for the stale reference-bucket-column bug found 2026-09-05
(F7, docs/dev/affine-curve-improvement-plan.md): updatePKL's merge
(new_df.combine_first(target_df)) unions columns and forward-fills, so a
bucket removed from TERM_BUCKETS (e.g. 7Y) would otherwise linger forever
in RefSpot/RefTerm, displayed in the Market Monitor as if it were live.
"""
import datetime as dt
import os
import pickle
import tempfile

import pandas as pd

from curves.utils.file import updatePKL, loadPKL


def test_updatepkl_merge_reintroduces_stale_column_confirming_the_bug():
    """Confirms the root cause: without an explicit trim, combine_first
    brings back a column no longer produced by the current bucket set."""
    tmpdir = tempfile.mkdtemp()
    file_path = os.path.join(tmpdir, 'test-cvref.pkl')

    existing = {
        'RefSpot': pd.DataFrame(
            {'Term near 0.3Y': [1.0], 'Term near 10Y': [2.0], 'Term near 7Y': [7.76]},
            index=[pd.Timestamp('2026-09-01')],
        ),
    }
    with open(file_path, 'wb') as f:
        pickle.dump(existing, f)

    new_data = {
        'RefSpot': pd.DataFrame(
            {'Term near 0.3Y': [1.1], 'Term near 10Y': [2.1]},
            index=[pd.Timestamp('2026-09-02')],
        ),
    }
    merged = updatePKL(new_data, file_path)
    assert 'Term near 7Y' in merged['RefSpot'].columns
    # Forward-filled with the stale value, not NaN.
    assert merged['RefSpot'].loc[pd.Timestamp('2026-09-02'), 'Term near 7Y'] == 7.76


def test_trim_stale_columns_preserves_other_pickle_keys():
    """The fix (compute_spot_term_panels) must trim RefSpot/RefTerm back to
    the current bucket set, while writing the full on-disk dict back (not
    just RefSpot/RefTerm) so RefBond/Factors/ImpliedVol survive the rewrite."""
    tmpdir = tempfile.mkdtemp()
    file_path = os.path.join(tmpdir, 'test-cvref.pkl')

    existing = {
        'RefBond': pd.DataFrame(
            {'Term near 0.3Y': ['b1'], 'Term near 10Y': ['b2']},
            index=[pd.Timestamp('2026-09-01')],
        ),
        'RefSpot': pd.DataFrame(
            {'Term near 0.3Y': [1.0], 'Term near 10Y': [2.0], 'Term near 7Y': [7.76]},
            index=[pd.Timestamp('2026-09-01')],
        ),
        'RefTerm': pd.DataFrame(
            {'Term near 0.3Y': [0.3], 'Term near 10Y': [10.0], 'Term near 7Y': [7.0]},
            index=[pd.Timestamp('2026-09-01')],
        ),
        'Factors': pd.DataFrame({'a': [1], 'b': [2], 'c': [3]}),
        'ImpliedVol': pd.DataFrame({'x': [1]}),
    }
    with open(file_path, 'wb') as f:
        pickle.dump(existing, f)

    final_data = {
        'RefSpot': pd.DataFrame(
            {'Term near 0.3Y': [1.1], 'Term near 10Y': [2.1]},
            index=[pd.Timestamp('2026-09-02')],
        ),
        'RefTerm': pd.DataFrame(
            {'Term near 0.3Y': [0.3], 'Term near 10Y': [10.0]},
            index=[pd.Timestamp('2026-09-02')],
        ),
    }
    final_data = updatePKL(final_data, file_path)

    # Replicate the trim logic added to compute_spot_term_panels.
    columns = ['Term near 0.3Y', 'Term near 10Y']
    trimmed = False
    for key in ('RefSpot', 'RefTerm'):
        df = final_data.get(key)
        stale_cols = [c for c in df.columns if c not in columns]
        if stale_cols:
            final_data[key] = df.drop(columns=stale_cols)
            trimmed = True
    assert trimmed

    full_on_disk = loadPKL(file_path)
    full_on_disk.update(final_data)
    updatePKL(full_on_disk, file_path, rewrite=True)

    reloaded = loadPKL(file_path)
    assert 'Term near 7Y' not in reloaded['RefSpot'].columns
    assert 'Term near 7Y' not in reloaded['RefTerm'].columns
    assert 'RefBond' in reloaded
    assert 'Factors' in reloaded
    assert 'ImpliedVol' in reloaded
    assert list(reloaded['RefBond'].columns) == ['Term near 0.3Y', 'Term near 10Y']


def test_updatepkl_handles_duplicate_date_labels_after_alignment():
    """A single calendar day may appear as both datetime.date and Timestamp after
    the index normalization step. The merge must collapse duplicates and keep the
    newest value instead of tripping pandas' duplicate-label reindex path."""
    tmpdir = tempfile.mkdtemp()
    file_path = os.path.join(tmpdir, 'series-date-dup.pkl')

    existing = {
        'Spread': pd.Series(
            [1.0],
            index=pd.Index([pd.Timestamp('2026-01-01')], dtype=object),
        )
    }
    with open(file_path, 'wb') as f:
        pickle.dump(existing, f)

    incoming = {
        'Spread': pd.Series(
            [2.0, 3.0],
            index=pd.Index([
                pd.Timestamp('2026-01-01'),
                dt.date(2026, 1, 1),
            ], dtype=object),
        )
    }

    merged = updatePKL(incoming, file_path)
    assert merged['Spread'].index.is_unique
    assert merged['Spread'].loc[pd.Timestamp('2026-01-01')] == 3.0


def test_manual_factor_refresh_marker_suppresses_stale_warning(monkeypatch, tmp_path):
    """A successful manual factor-series rebuild should clear stale warnings until
    the next refresh window expires, even if the underlying series still ends on
    an older historical date."""
    from web.tabs.beta.callbacks.backtest_rfbt import _train_predict

    monkeypatch.setattr(_train_predict, 'DIR_INPUT', str(tmp_path))
    stale_df = pd.DataFrame({'f1': [1.0]}, index=pd.DatetimeIndex([pd.Timestamp('2026-10-01')]))
    with open(tmp_path / 'factor-rates.pkl', 'wb') as fh:
        pickle.dump(stale_df, fh)

    _train_predict.touch_factor_series_refresh_marker()

    assert _train_predict.build_stale_data_warning() is None
