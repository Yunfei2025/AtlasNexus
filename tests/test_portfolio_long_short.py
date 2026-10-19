# -*- coding: utf-8 -*-
"""Portfolio-tab sizing rules (2026-10-17): floor 1/2/5Y, 20Y shorts held as 30Y shorts, long and short
reported separately and never netted."""

import numpy as np
import pandas as pd
import pytest

from multiasset.book.sizing import signed_sleeve_weights_snapshot
from multiasset.config import RiskModelConfig
from web.tabs.beta.callbacks.portfolio_run._run_analysis import long_short_totals
from web.tabs.beta.data import FACTOR_TO_ASSET_MAP

CGB = {
    '1Y': '中债国债到期收益率:1年', '2Y': '中债国债到期收益率:2年', '5Y': '中债国债到期收益率:5年',
    '10Y': '中债国债到期收益率:10年', '20Y': '中债国债到期收益率:20年', '30Y': '中债国债到期收益率:30年',
}


def _market(y=2.5):
    idx = pd.bdate_range('2024-01-01', periods=5)
    return {}, {'CGB': pd.DataFrame({c: y for c in CGB.values()}, index=idx)}, {}


def _snapshot(position, substitute):
    old = RiskModelConfig.CN_SHORT_SUBSTITUTE
    RiskModelConfig.CN_SHORT_SUBSTITUTE = substitute
    try:
        w, _ = signed_sleeve_weights_snapshot({'IRDL.CN': 1.0}, {'IRDL.CN': position}, FACTOR_TO_ASSET_MAP,
                                              _market(), long_only_assets=('CN1Y', 'CN2Y', 'CN5Y'))
    finally:
        RiskModelConfig.CN_SHORT_SUBSTITUTE = old
    return w


def test_bearish_snapshot_shorts_only_10y_and_30y_with_20y_moved_into_30y():
    plain = _snapshot(-0.8, {})
    moved = _snapshot(-0.8, {20.0: 30.0})
    for a in ('CN1Y', 'CN2Y', 'CN5Y'):
        assert moved[a] == 0.0                                          # floored: no short-end shorts
    assert plain['CN20Y'] < 0 and moved['CN20Y'] == 0.0                 # the illiquid 20Y short is gone
    from multiasset.book.hedge_instruments import mod_duration
    ratio = mod_duration(2.5, 20.0) / mod_duration(2.5, 30.0)
    assert moved['CN30Y'] == pytest.approx(plain['CN30Y'] + plain['CN20Y'] * ratio)
    # DV01 preserved by the move
    assert moved['CN30Y'] * mod_duration(2.5, 30.0) == pytest.approx(
        plain['CN30Y'] * mod_duration(2.5, 30.0) + plain['CN20Y'] * mod_duration(2.5, 20.0))
    assert moved['CN10Y'] == pytest.approx(plain['CN10Y'])


def test_bullish_snapshot_leaves_20y_long_untouched():
    plain, moved = _snapshot(0.8, {}), _snapshot(0.8, {20.0: 30.0})
    assert all(moved[a] == pytest.approx(plain[a]) for a in plain)


def test_long_short_totals_are_not_netted():
    cap = [1_000e6, -400e6, 300e6, -100e6]
    dur = [4.5, 8.5, 17.0, 0.0]
    long_c, short_c, dv_l, dv_s = long_short_totals(cap, dur)
    assert long_c == pytest.approx(1_300e6) and short_c == pytest.approx(500e6)        # 1300 + 500, NOT 800
    assert dv_l == pytest.approx((1_000e6 * 4.5 + 300e6 * 17.0) / 1e10)
    assert dv_s == pytest.approx(400e6 * 8.5 / 1e10)                                    # zero-duration short adds none


def test_lot_rounding_is_toward_zero_for_shorts():
    unit = 10_000_000.0
    raw = np.array([123_456_789.0, -123_456_789.0])
    assert (np.trunc(raw / unit) * unit).tolist() == [120_000_000.0, -120_000_000.0]    # np.floor would give -130m


def test_live_durations_use_the_annuity_basis_of_the_backtest_not_the_default_table():
    from multiasset.book.hedge_instruments import mod_duration
    from web.tabs.beta.callbacks.portfolio_run._run_analysis import live_mod_durations
    idx = pd.bdate_range('2024-01-01', periods=5)
    cgb = {'中债国债到期收益率:10年': 1.65, '中债国债到期收益率:30年': 2.06}
    md = ({}, {'CGB': pd.DataFrame({c: y for c, y in cgb.items()}, index=idx)}, {})
    out = live_mod_durations(['CN10Y', 'CN30Y', 'Gold'], ['Rates', 'Rates', 'Commodities'], [8.5, 17.0, 0.0], market_data=md)
    assert out[0] == pytest.approx(mod_duration(1.65, 10.0)) and out[1] == pytest.approx(mod_duration(2.06, 30.0))
    assert out[1] > 17.0 * 1.2                                           # the default table understated 30Y by >20%
    assert out[2] == 0.0                                                 # non-bond assets keep their default (0)
    # an asset with no usable yield keeps the default
    out2 = live_mod_durations(['CN5Y'], ['Rates'], [4.5], market_data=md)
    assert out2[0] == 4.5
