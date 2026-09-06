"""Regression tests for the 2026-09-05 "spot curve stuck near 0.25%" bug.

Market Monitor -> Curves showed a near-flat TBond/CBond spot curve averaging
~0.25% that missed every reference spot by 40-90bp. Three independent
defects compounded:

1. `extract_yield` returned NaN for EVERY bond when `env['BondRT']` was
   absent (no live Wind session), because its CNBD fallback sat *inside* the
   `bond_rt_data is not None` branch. The reference set came back empty.
2. `YieldCurveBuilder.build_curve` never wrote `bond_id`/`ttm` into its
   `results` frame (dropped when the loop was split into two passes for the
   coupon-beta fit), so the spot lookup keyed off an all-NaN `ttm` column
   and returned NaN even when the bootstrap itself succeeded.
3. `Curve.extractFactorsRobust` accepted a near-empty reference set and let
   `np.linalg.lstsq` return a garbage near-zero factor vector; the resulting
   degenerate factors were then persisted and EWMA-blended into the NEXT
   refresh, so one bad run poisoned subsequent good ones.
"""
import numpy as np
import pandas as pd
import pytest

from curves.affine.curve import Curve, quote_quality_weights
from curves.calibration.selector import extract_yield


def _env_with_cnbd(bond_id='250022.IB', cnbd=1.664, bond_rt=None):
    df_def = pd.DataFrame({'估价收益率:%(中债)': [cnbd]}, index=[bond_id])
    env = {'Def': df_def}
    if bond_rt is not None:
        env['BondRT'] = bond_rt
    return env


def test_extract_yield_falls_back_to_cnbd_when_bondrt_missing():
    """Defect 1: outside live Wind hours BondRT is None. Every realtime
    lookup must still return the CNBD valuation, not NaN."""
    env = _env_with_cnbd()
    for price_type in ('Bid', 'Ofr'):
        ytm = extract_yield(env, '250022.IB', pd.Timestamp('2026-09-04'), price_type)
        assert pd.notna(ytm), f'{price_type} returned NaN with BondRT absent'
        assert ytm == pytest.approx(1.664)


def test_extract_yield_falls_back_when_bond_absent_from_bondrt():
    """Same fallback must apply when BondRT exists but lacks this bond."""
    bond_rt = pd.DataFrame({'买价收益率': [1.5], '卖价收益率': [1.5]}, index=['OTHER.IB'])
    env = _env_with_cnbd(bond_rt=bond_rt)
    ytm = extract_yield(env, '250022.IB', pd.Timestamp('2026-09-04'), 'Bid')
    assert ytm == pytest.approx(1.664)


def test_extract_yield_prefers_live_quote_over_cnbd():
    """The fallback must not shadow a genuine live quote when one exists."""
    bond_rt = pd.DataFrame({'买价收益率': [1.719], '卖价收益率': [1.635]}, index=['250022.IB'])
    env = _env_with_cnbd(bond_rt=bond_rt)
    assert extract_yield(env, '250022.IB', pd.Timestamp('2026-09-04'), 'Bid') == pytest.approx(1.719)
    assert extract_yield(env, '250022.IB', pd.Timestamp('2026-09-04'), 'Ofr') == pytest.approx(1.635)


def test_extract_factors_robust_rejects_empty_reference_set():
    """Defect 3: an empty/near-empty reference set must raise rather than
    silently yield garbage factors and a degenerate ~flat curve."""
    curve = Curve(pd.Timestamp('2026-09-04'), 'TBond')
    curve.S2 = np.eye(3) * 1e-4
    for n in (0, 1, 2):
        df_bs = pd.Series([1.2] * n, index=[0.5, 1.0, 2.0][:n], dtype=float)
        with pytest.raises(ValueError, match='need >=3 usable reference points'):
            curve.extractFactorsRobust(df_bs, pd.Series(dtype=object))


def test_extract_factors_robust_accepts_three_points():
    """Three real anchors is the documented minimum and must still work."""
    curve = Curve(pd.Timestamp('2026-09-04'), 'TBond')
    curve.S2 = np.eye(3) * 1e-4
    df_bs = pd.Series([1.10, 1.25, 1.70], index=[0.5, 2.0, 9.0], dtype=float)
    curve.extractFactorsRobust(df_bs, pd.Series(dtype=object))
    factors = np.asarray(curve.factors, dtype=float).ravel()
    assert factors.shape == (3,)
    assert np.isfinite(factors).all()


def test_quote_quality_weights_floor_is_min_weight_not_its_square():
    """Compounding live/spread/volume penalties must not push a point far
    below `min_weight` -- graded weighting means "counts less", not
    "effectively dropped" (this compounding measurably degraded the fit)."""
    idx = ['a', 'b', 'c', 'd']
    # Worst case on every factor simultaneously.
    is_live = pd.Series([False] * 4, index=idx)
    spread_bp = pd.Series([50.0] * 4, index=idx)      # far beyond max_spread_bp
    volume = pd.Series([1.0, 2.0, 3.0, 4.0], index=idx)

    w = quote_quality_weights(is_live, spread_bp, volume, max_spread_bp=15.0, min_weight=0.1)
    assert (w >= 0.1 - 1e-12).all(), f'weights fell below min_weight: {w.to_dict()}'
    assert (w <= 1.0 + 1e-12).all()


def test_quote_quality_weights_still_rank_by_quality():
    """The floor must not flatten genuine quality differences."""
    idx = ['good', 'bad']
    w = quote_quality_weights(
        pd.Series([True, False], index=idx),
        pd.Series([0.5, 14.0], index=idx),
        pd.Series([1000.0, 10.0], index=idx),
        max_spread_bp=15.0,
        min_weight=0.1,
    )
    assert w['good'] > w['bad']


def test_coupon_adjustment_is_per_asset_class():
    """The coupon-vintage adjustment (settings.fixed_income.BondConfig.
    APPLY_COUPON_ADJUSTMENT) must resolve independently per asset class,
    since the underlying effect is CGB-specific -- CDB shows no comparable
    coupon sensitivity despite similar coupon dispersion, so enabling it
    there would only inject noise. This does not assert which asset classes
    are currently on: TBond's beta was found unstable across 2023-2024
    (mean +0.09 to +0.12, sd up to 0.24, wrong sign) despite being small and
    stable in the 2024-2026 window it was originally validated on, so it is
    off for both classes as of 2026-09-06 pending re-validation. See
    docs/dev/affine-curve-improvement-plan.md F13 / item 1.7 and
    settings/fixed_income.py's APPLY_COUPON_ADJUSTMENT comment."""
    from curves.calibration.selector import coupon_adjustment_enabled
    from settings.fixed_income import BondConfig

    assert isinstance(BondConfig.APPLY_COUPON_ADJUSTMENT, dict)
    assert coupon_adjustment_enabled('TBond') == BondConfig.APPLY_COUPON_ADJUSTMENT['TBond']
    assert coupon_adjustment_enabled('CBond') == BondConfig.APPLY_COUPON_ADJUSTMENT['CBond']


def test_coupon_adjustment_setting_accepts_plain_bool(monkeypatch):
    """Back-compatibility: a plain bool must still be honoured."""
    from settings.fixed_income import BondConfig
    from curves.calibration.selector import coupon_adjustment_enabled

    monkeypatch.setattr(BondConfig, 'APPLY_COUPON_ADJUSTMENT', True, raising=False)
    assert coupon_adjustment_enabled('AnyBond') is True
    monkeypatch.setattr(BondConfig, 'APPLY_COUPON_ADJUSTMENT', False, raising=False)
    assert coupon_adjustment_enabled('TBond') is False


def test_coupon_adjustment_unknown_asset_class_defaults_off():
    """An asset class absent from the mapping must default to OFF rather than
    silently inheriting another class's setting."""
    from curves.calibration.selector import coupon_adjustment_enabled

    assert coupon_adjustment_enabled('LBond') is False


def test_mid_ref_series_keeps_stale_reference_points():
    """The realtime fit must span the SAME reference bonds as the EOD fit.

    curves/calibration/selector.py's extract_yield deliberately substitutes a
    bond's CNBD valuation when it has no genuine live quote, precisely so the
    reference set is never starved. _build_mid_ref_series used to then run
    _drop_stale_refs, which removed exactly those CNBD-backfilled points --
    the two layers worked against each other. Measured 2026-09-04: EOD fit 8
    reference points while realtime fit only 4 (the bare min_points=4 floor
    for a 3-factor model, entire sub-0.6y short end gone), giving curvature
    -1.01 vs EOD's -1.98 and moving a 6.2y bond's Z-score from -2.3 to -7.7
    against the same mean/vol.
    """
    import inspect
    from curves.refreshers.rates import BondCurveRefresher

    src = inspect.getsource(BondCurveRefresher._build_mid_ref_series)
    # The stale filter's RESULT must never be assigned back over the series
    # that gets fitted -- keeping the call for logging/diagnostics is fine.
    assert 'bid_series = self._drop_stale_refs' not in src
    assert 'ofr_series = self._drop_stale_refs' not in src
