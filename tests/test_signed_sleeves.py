# -*- coding: utf-8 -*-
"""Signed factor sleeves (factor_scaling mode): the portfolio must hold each
factor's own mimicking portfolio x its FactorModel position, so the book
earns the same thing the Individual Factors tab scores."""

import numpy as np
import pandas as pd
import pytest

from multiasset.book.sizing import (
    factor_mimicking_weights, pool_sleeve_budgets, signed_sleeve_weights_daily,
    signed_sleeve_weights_snapshot, scale_sleeve_to_dv01_target,
)
from web.tabs.beta.data import FACTOR_TO_ASSET_MAP


def test_ir_mimicking_weights_match_deterministic_factor_definition():
    from multiasset.pca_analyzer import get_deterministic_ir_weights
    w_lvl, is_yield = factor_mimicking_weights('IRDL.CN', FACTOR_TO_ASSET_MAP)
    assert is_yield
    assert w_lvl == {f'CN{t}': pytest.approx(1 / 6) for t in ('1Y', '2Y', '5Y', '10Y', '20Y', '30Y')}
    w_slp, _ = factor_mimicking_weights('IRSL.CN', FACTOR_TO_ASSET_MAP)
    expected = dict(zip(['CN1Y', 'CN2Y', 'CN5Y', 'CN10Y', 'CN20Y', 'CN30Y'],
                        get_deterministic_ir_weights('CN')['Slope']))
    assert w_slp == pytest.approx(expected)
    assert w_slp['CN1Y'] < 0 < w_slp['CN30Y']          # steepener legs are signed
    w_crv, _ = factor_mimicking_weights('IRCV.CN', FACTOR_TO_ASSET_MAP)
    assert 'CN2Y' not in w_crv and 'CN20Y' not in w_crv  # zero-weight tenors dropped


def test_price_factor_and_unreplicable_factor():
    assert factor_mimicking_weights('FXDL.USDCNY', FACTOR_TO_ASSET_MAP) == ({'USDCNY': 1.0}, False)
    # CRCV.NCD: NCD is in CREDIT_NO_CURVATURE (too few tenors for a butterfly
    # read) — genuinely unreplicable, unlike CRDL/CRSL/CRCV.CDB below.
    assert factor_mimicking_weights('CRCV.NCD', FACTOR_TO_ASSET_MAP) is None
    assert factor_mimicking_weights('CRDL.XYZ', FACTOR_TO_ASSET_MAP) is None  # unknown universe


def test_credit_mimicking_weights_match_get_credit_weights():
    from multiasset.config import CREDIT_CONFIG, get_credit_weights

    w_lvl, is_yield = factor_mimicking_weights('CRDL.CDB', FACTOR_TO_ASSET_MAP)
    assert is_yield
    tenor_years = [t for _, _, t in CREDIT_CONFIG['CDB'][2]]
    expected_lvl = dict(zip(['CDB1Y', 'CDB2Y', 'CDB5Y', 'CDB10Y', 'CDB30Y'],
                            get_credit_weights(tenor_years)['Level']))
    assert w_lvl == pytest.approx(expected_lvl)
    assert sum(w_lvl.values()) == pytest.approx(1.0)

    w_slp, _ = factor_mimicking_weights('CRSL.CDB', FACTOR_TO_ASSET_MAP)
    assert w_slp['CDB1Y'] < 0 < w_slp['CDB30Y']          # steepener legs are signed
    assert sum(w_slp.values()) == pytest.approx(0.0)

    w_crv, _ = factor_mimicking_weights('CRCV.CDB', FACTOR_TO_ASSET_MAP)
    assert sum(w_crv.values()) == pytest.approx(0.0)

    # NCD has no curvature (CREDIT_NO_CURVATURE) but does have Level/Slope.
    w_ncd_lvl, _ = factor_mimicking_weights('CRDL.NCD', FACTOR_TO_ASSET_MAP)
    assert set(w_ncd_lvl) == {'NCD3M', 'NCD6M', 'NCD9M', 'NCD1Y'}


def test_pool_sleeve_budgets_vol_sqrt_for_ir_equal_for_rest():
    vols = {'IRDL.CN': 0.09, 'IRSL.CN': 0.04, 'IRCV.CN': 0.01, 'FXDL.USDCNY': 5.0}
    b = pool_sleeve_budgets(list(vols), vols)
    assert sum(b.values()) == pytest.approx(1.0)
    assert b['IRDL.CN'] > b['IRSL.CN'] > b['IRCV.CN']
    assert b['IRDL.CN'] / b['IRCV.CN'] == pytest.approx(np.sqrt(9.0))
    assert b['FXDL.USDCNY'] == pytest.approx(0.25)     # FX vol does not dominate IR


def test_sleeve_uses_previous_day_position_and_keeps_sign():
    """weight[d] must use position[d-1] (the Factor tab's position.shift(1)),
    and a negative position must produce a SHORT, not be clipped to flat."""
    idx = pd.bdate_range('2024-01-01', periods=5)
    pos = pd.Series([0.0, 1.5, -1.0, -1.0, 2.0], index=idx)
    weights, mod_dur, skipped = signed_sleeve_weights_daily(
        {idx[0]: {'FXDL.USDCNY': 0.4}}, {'FXDL.USDCNY': pos}, idx, FACTOR_TO_ASSET_MAP, market_data=None,
    )
    assert skipped == []
    np.testing.assert_allclose(weights['USDCNY'].values, [0.0, 0.0, 0.6, -0.4, -0.4])
    assert (mod_dur['USDCNY'] == 0).all()              # FX carries no duration


def test_long_only_assets_floor_net_short_but_leave_other_tenors_signed():
    """A steepener (IRSL.CN: short end negative, long end positive) with a
    negative position flips into a NET SHORT on the short-end tenors — the
    floor must clip those to 0 while leaving the long-end legs (still net
    short, since a negative position on a positive weight is negative) and
    unlisted tenors untouched. Uses real market_data (needed for bond
    duration lookup inside signed_sleeve_weights_daily)."""
    from multiasset.data import load_raw_market_data
    md = load_raw_market_data()
    if md is None:
        pytest.skip("market data unavailable in this environment")

    idx = pd.bdate_range('2024-01-01', periods=3)
    # IRSL.CN's mimicking weights are negative on the short end, positive on
    # the long end (factor_mimicking_weights('IRSL.CN', ...): CN1Y=-0.278,
    # CN30Y=+0.278) — a POSITIVE position therefore shorts the short end and
    # goes long the long end (a steepening view: short-end weight x positive
    # position = negative/short; long-end weight x positive position =
    # positive/long).
    pos = pd.Series(1.0, index=idx)

    weights, mod_dur, skipped = signed_sleeve_weights_daily(
        {idx[0]: {'IRSL.CN': 1.0}}, {'IRSL.CN': pos}, idx, FACTOR_TO_ASSET_MAP, md,
        long_only_assets=('CN1Y', 'CN2Y'),
    )
    assert skipped == []
    last_day = weights.loc[idx[-1]]
    # Un-floored, this position genuinely shorts CN1Y/CN2Y (see comment
    # above). Floored tenors must be clipped to exactly 0, not merely reduced.
    assert last_day['CN1Y'] == 0.0
    assert last_day['CN2Y'] == 0.0
    # Long-end legs (CN10Y/CN20Y/CN30Y: positive weight x positive position =
    # long) are NOT in long_only_assets and must be left signed/untouched.
    assert last_day['CN30Y'] > 0.0


def test_long_only_assets_with_no_matching_column_is_a_noop():
    idx = pd.bdate_range('2024-01-01', periods=3)
    weights, mod_dur, skipped = signed_sleeve_weights_daily(
        {idx[0]: {'FXDL.USDCNY': 1.0}}, {'FXDL.USDCNY': pd.Series(-1.0, index=idx)},
        idx, FACTOR_TO_ASSET_MAP, market_data=None, long_only_assets=('CN1Y', 'CN2Y'),
    )
    assert (weights['USDCNY'] < 0).any()  # FX unaffected by a bond-tenor floor list


def test_factor_without_signal_holds_no_sleeve():
    idx = pd.bdate_range('2024-01-01', periods=3)
    weights, mod_dur, skipped = signed_sleeve_weights_daily(
        {idx[0]: {'FXDL.USDCNY': 0.5, 'CMDL.AU': 0.5}},
        {'FXDL.USDCNY': pd.Series(1.0, index=idx)}, idx, FACTOR_TO_ASSET_MAP, market_data=None,
    )
    assert 'CMDL.AU' in skipped
    assert list(weights.columns) == ['USDCNY']        # no gold sleeve at all
    assert list(mod_dur.columns) == ['USDCNY']


def test_scale_sleeve_to_dv01_target_hits_target_when_gross_allows():
    """10BN capital, max_dv01_per_capital=10 -> target DV01 = 10 MM/bp.
    A day with plenty of gross headroom must scale exactly to that DV01,
    preserving the long/short SHAPE (CN2Y:CN30Y ratio unchanged)."""
    idx = pd.bdate_range('2024-01-01', periods=1)
    weights = pd.DataFrame({'CN2Y': [-0.02], 'CN30Y': [0.03]}, index=idx)
    mod_dur = pd.DataFrame({'CN2Y': [1.9], 'CN30Y': [17.0]}, index=idx)
    total_capital_cny = 10e9  # 10 BN

    out = scale_sleeve_to_dv01_target(weights, mod_dur, total_capital_cny,
                                      max_dv01_per_capital=10.0, max_utilisation=0.95)

    dv01_mm = (out * mod_dur).abs().sum(axis=1) * (total_capital_cny / 1e10)
    assert dv01_mm.iloc[0] == pytest.approx(10.0, rel=1e-6)
    assert out['CN2Y'].iloc[0] / out['CN30Y'].iloc[0] == pytest.approx(
        weights['CN2Y'].iloc[0] / weights['CN30Y'].iloc[0])  # shape preserved


def test_scale_sleeve_to_dv01_target_backstopped_by_gross_cap():
    """A low-duration day (tiny DV01 per unit of gross) must not be scaled
    past max_utilisation gross chasing an unreachable-without-huge-notional
    DV01 target."""
    idx = pd.bdate_range('2024-01-01', periods=1)
    weights = pd.DataFrame({'CN1Y': [0.05]}, index=idx)
    mod_dur = pd.DataFrame({'CN1Y': [0.95]}, index=idx)
    total_capital_cny = 10e9

    out = scale_sleeve_to_dv01_target(weights, mod_dur, total_capital_cny,
                                      max_dv01_per_capital=10.0, max_utilisation=0.95)

    assert out.abs().sum(axis=1).iloc[0] <= 0.95 + 1e-9
    dv01_mm = (out * mod_dur).abs().sum(axis=1) * (total_capital_cny / 1e10)
    assert dv01_mm.iloc[0] < 10.0  # target not reached — gross cap binds first


def test_scale_sleeve_to_dv01_target_leaves_flat_day_unscaled():
    idx = pd.bdate_range('2024-01-01', periods=1)
    weights = pd.DataFrame({'CN2Y': [0.0]}, index=idx)
    mod_dur = pd.DataFrame({'CN2Y': [1.9]}, index=idx)
    out = scale_sleeve_to_dv01_target(weights, mod_dur, 10e9,
                                      max_dv01_per_capital=10.0, max_utilisation=0.95)
    assert (out == 0.0).all().all()


def test_snapshot_matches_daily_shape_at_a_single_date():
    """signed_sleeve_weights_snapshot (live Portfolio tab) must agree with
    signed_sleeve_weights_daily (backtest) for the SAME budget/position
    inputs — same sign, same relative tenor split, same order of magnitude.
    Not bit-exact: the daily path uses YESTERDAY's duration (its own
    day-over-day lag convention), the one-shot snapshot uses TODAY's (there
    is no "yesterday" in a live one-shot view) — a small, expected
    difference from one day's yield move, not a construction bug."""
    from multiasset.data import load_raw_market_data
    md = load_raw_market_data()
    if md is None:
        pytest.skip("market data unavailable in this environment")

    idx = pd.bdate_range('2024-01-01', periods=2)  # position lagged 1 day -> use day 2
    budget = {'IRDL.CN': 0.5, 'IRSL.CN': 0.5}
    position_by_factor = {'IRDL.CN': 0.8, 'IRSL.CN': 1.0}
    short_end = ('CN1Y', 'CN2Y', 'CN5Y')

    daily_weights, _mod_dur, _skipped = signed_sleeve_weights_daily(
        {idx[0]: budget},
        {f: pd.Series(p, index=idx) for f, p in position_by_factor.items()},
        idx, FACTOR_TO_ASSET_MAP, md,
        long_only_assets=short_end,
    )
    snapshot_weights, skipped = signed_sleeve_weights_snapshot(
        budget, position_by_factor, FACTOR_TO_ASSET_MAP, md,
        long_only_assets=short_end,
    )
    assert skipped == []
    for asset, w in snapshot_weights.items():
        daily_w = daily_weights.loc[idx[-1], asset]
        assert (w > 0) == (daily_w > 0) or (w == 0 == daily_w)  # same sign
        assert w == pytest.approx(daily_w, rel=0.3)              # within duration drift, not a magic-number match


def test_snapshot_floors_short_end_same_as_daily():
    from multiasset.data import load_raw_market_data
    md = load_raw_market_data()
    if md is None:
        pytest.skip("market data unavailable in this environment")

    weights, skipped = signed_sleeve_weights_snapshot(
        {'IRSL.CN': 1.0}, {'IRSL.CN': 1.0}, FACTOR_TO_ASSET_MAP, md,
        long_only_assets=('CN1Y', 'CN2Y'),
    )
    assert skipped == []
    assert weights['CN1Y'] == 0.0
    assert weights['CN2Y'] == 0.0
    assert weights['CN30Y'] > 0.0  # long-end leg untouched (see IRSL sign convention)


def test_snapshot_skips_unreplicable_factor_and_missing_position():
    weights, skipped = signed_sleeve_weights_snapshot(
        {'CRDL.CDB': 1.0, 'FXDL.USDCNY': 1.0}, {'FXDL.USDCNY': 1.0},
        FACTOR_TO_ASSET_MAP, market_data=None,
    )
    assert 'CRDL.CDB' in skipped   # not replicable at all
    assert 'FXDL.USDCNY' not in skipped
    assert weights == {'USDCNY': 1.0}
