"""Tests for the OFR{k}-vs-OFR1 residual-pair RV construction and the
stale-bond gate that feeds it.

Covers three defects found on production TBond data (2026-09-06):
  1. `_adf_result` reported a frozen (constant) series as stationary, so dead
     instruments passed StatInfo's stationarity filter with a ~0 vol divisor.
  2. `statAnalysis_BC` kept bonds that had left the instrument universe or
     whose residual had stopped updating.
  3. `_episode_rows_to_pair_frames` built its fallback series against
     whichever bond was OFR1 on each date rather than the pair's own OFR1,
     collapsing every pair sharing a leg-A onto one identical spread.
"""
import numpy as np
import pandas as pd

from curves.calibration.stat import (
    _adf_result,
    _drop_stale_residual_bonds,
    _trailing_frozen_count,
)
from curves.refreshers.otr_ofr_rv import (
    _episode_rows_to_pair_frames,
    _residual_pair_series,
)


# ---------------------------------------------------------------- stale gate

def test_constant_series_is_not_reported_stationary():
    """A frozen residual is a dead instrument, not a mean-reverting process."""
    _, stationary, _, _ = _adf_result(pd.Series([1.5] * 100))
    assert stationary == 'NO'


def test_trailing_frozen_count():
    assert _trailing_frozen_count(pd.Series([1.0, 2.0, 3.0, 3.0, 3.0])) == 3
    assert _trailing_frozen_count(pd.Series([1.0, 2.0, 3.0])) == 1
    assert _trailing_frozen_count(pd.Series([np.nan, 2.0, 2.0])) == 2
    assert _trailing_frozen_count(pd.Series([], dtype=float)) == 0


def _env(ttm_by_bond):
    return {'Def': pd.DataFrame({'剩余期限': pd.Series(ttm_by_bond)})}


def test_drops_frozen_and_delisted_bonds_keeps_live_ones():
    idx = pd.date_range('2026-01-01', periods=30, freq='D')
    rng = np.random.default_rng(0)
    spread = pd.DataFrame({
        'live.IB': rng.standard_normal(30) * 0.01,
        'frozen.IB': np.r_[rng.standard_normal(20) * 0.01, np.full(10, -0.68)],
        'delisted.IB': rng.standard_normal(30) * 0.01,
    }, index=idx)
    # 'delisted.IB' has no remaining maturity -> gone from the live universe.
    env = _env({'live.IB': 5.0, 'frozen.IB': 7.0, 'delisted.IB': np.nan})

    kept, dropped = _drop_stale_residual_bonds(spread, env)

    assert set(dropped) == {'frozen.IB', 'delisted.IB'}
    assert list(kept.columns) == ['live.IB']


def test_stale_gate_is_a_noop_when_everything_is_live():
    idx = pd.date_range('2026-01-01', periods=30, freq='D')
    rng = np.random.default_rng(1)
    spread = pd.DataFrame({'a.IB': rng.standard_normal(30) * 0.01,
                           'b.IB': rng.standard_normal(30) * 0.01}, index=idx)
    kept, dropped = _drop_stale_residual_bonds(spread, _env({'a.IB': 5.0, 'b.IB': 9.0}))
    assert dropped == []
    assert list(kept.columns) == ['a.IB', 'b.IB']


# ------------------------------------------------------------- residual pair

def test_residual_pair_differences_the_two_named_legs():
    idx = pd.date_range('2026-01-01', periods=5, freq='D')
    residuals = pd.DataFrame({'A.IB': [0.10] * 5, 'B.IB': [0.04] * 5}, index=idx)
    out = _residual_pair_series(residuals, 'A.IB', 'B.IB')
    assert np.allclose(out.to_numpy(), 0.06)
    # ...and is antisymmetric in its legs.
    rev = _residual_pair_series(residuals, 'B.IB', 'A.IB')
    assert np.allclose(rev.to_numpy(), -0.06)


def test_residual_pair_empty_when_a_leg_is_missing():
    residuals = pd.DataFrame({'A.IB': [0.1, 0.2]})
    assert _residual_pair_series(residuals, 'A.IB', 'missing.IB').empty
    assert _residual_pair_series(pd.DataFrame(), 'A.IB', 'B.IB').empty


def _universe_frame(n=40):
    """Two rungs whose OFR1 reference CHANGES midway, so a series built
    against the moving reference differs from one built against a fixed leg.
    """
    idx = pd.date_range('2026-01-01', periods=n, freq='D')
    half = n // 2
    return pd.DataFrame({
        'ofr1_id': ['REF1.IB'] * half + ['REF2.IB'] * (n - half),
        'ofr2_id': ['K.IB'] * n,
        'ytm_ofr1': np.r_[np.full(half, 2.50), np.full(n - half, 2.60)],
        'ytm_ofr2': np.full(n, 2.55),
    }, index=idx)


def test_pair_spread_depends_on_its_own_ofr1_leg():
    """Two pairs sharing leg A must not collapse onto one identical spread."""
    idx = pd.date_range('2026-01-01', periods=40, freq='D')
    rng = np.random.default_rng(2)
    residuals = pd.DataFrame({
        'K.IB': 0.05 + rng.standard_normal(40) * 0.001,
        'REF1.IB': 0.01 + rng.standard_normal(40) * 0.001,
        'REF2.IB': -0.03 + rng.standard_normal(40) * 0.001,
    }, index=idx)

    out = _episode_rows_to_pair_frames(_universe_frame(), residuals)

    # One episode per (ofr1_id, ofrk_id) identity: K vs REF1 and K vs REF2.
    assert set(out) == {'K.IB|REF1.IB', 'K.IB|REF2.IB'}
    s1 = out['K.IB|REF1.IB']['Spread']
    s2 = out['K.IB|REF2.IB']['Spread']
    # Each must equal its OWN legs' residual difference...
    assert np.allclose(s1.to_numpy(), (residuals['K.IB'] - residuals['REF1.IB']).to_numpy())
    assert np.allclose(s2.to_numpy(), (residuals['K.IB'] - residuals['REF2.IB']).to_numpy())
    # ...and therefore differ from one another (the collapse bug).
    assert not np.allclose(s1.to_numpy(), s2.to_numpy())


def test_pair_falls_back_to_raw_spread_without_a_residual_panel():
    """Missing residuals must not fabricate a one-legged spread."""
    out = _episode_rows_to_pair_frames(_universe_frame(), pd.DataFrame())
    assert set(out) == {'K.IB|REF1.IB', 'K.IB|REF2.IB'}
    # Raw-yield fallback: ytm_ofr2 - ytm_ofr1 over that episode.
    assert np.allclose(out['K.IB|REF1.IB']['Spread'].to_numpy(), 2.55 - 2.50)
    assert np.allclose(out['K.IB|REF2.IB']['Spread'].to_numpy(), 2.55 - 2.60)


def test_self_pair_is_never_emitted():
    """A pair needs two distinct instruments to have any economic content."""
    idx = pd.date_range('2026-01-01', periods=25, freq='D')
    df = pd.DataFrame({
        'ofr1_id': ['SAME.IB'] * 25,
        'ofr2_id': ['SAME.IB'] * 25,
        'ytm_ofr1': np.full(25, 2.5),
        'ytm_ofr2': np.full(25, 2.5),
    }, index=idx)
    assert _episode_rows_to_pair_frames(df, pd.DataFrame()) == {}
