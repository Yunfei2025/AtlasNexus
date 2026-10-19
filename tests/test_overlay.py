# -*- coding: utf-8 -*-
"""China-rates duration overlay (multiasset.book.overlay): CN shorts are traded
with futures / swaps whose P&L is their OWN series, not the short-bond formula."""

import numpy as np
import pandas as pd
import pytest

from multiasset.book import overlay as ov
from multiasset.book import hedge_instruments as hi
from multiasset.book.capital import weights_to_notional

CAP = 10e9
CGB_COLS = {
    '1Y': '中债国债到期收益率:1年', '2Y': '中债国债到期收益率:2年', '3Y': '中债国债到期收益率:3年',
    '5Y': '中债国债到期收益率:5年', '10Y': '中债国债到期收益率:10年',
    '20Y': '中债国债到期收益率:20年', '30Y': '中债国债到期收益率:30年',
}


def _idx(n=40, start='2024-01-02'):
    return pd.bdate_range(start, periods=n)


def _market(idx, y=2.5, swap=2.8, fr007=1.8):
    cgb = pd.DataFrame({c: y for c in CGB_COLS.values()}, index=idx)
    irs = pd.DataFrame({'FR007.IR': fr007, 'FR007S1Y.IR': swap, 'FR007S2Y.IR': swap, 'FR007S3Y.IR': swap}, index=idx)
    return {}, {'CGB': cgb, 'IRS': irs}, {}


@pytest.fixture
def flat_futures(monkeypatch):
    def make(idx, jump_day=None, jump=0.0):
        close = pd.Series(100.0, index=idx)
        if jump_day is not None:
            close.loc[idx[jump_day]:] += jump
        return {k: pd.DataFrame({'Close': close}) for k in ('TS.CFE', 'TF.CFE', 'T.CFE', 'TL.CFE')}
    return make


def _notional(idx, **cols):
    return pd.DataFrame({k: pd.Series(v, index=idx, dtype=float) for k, v in cols.items()})


FUT10 = {10.0: ['T', 'bond']}          # explicit futures routing for the futures-specific tests


def test_default_routing_swaps_for_1y_2y_and_short_bonds_for_5y_plus(monkeypatch, flat_futures):
    idx = _idx()
    monkeypatch.setattr(ov, '_load_futures', lambda: flat_futures(idx))
    n = _notional(idx, CN1Y=-1e9, CN2Y=-2e9, CN5Y=-3e9, CN10Y=-1e9, CN30Y=-5e8, US10Y=-5e8, CN20Y=2e9)
    res = ov.route_cn_shorts(n, _market(idx), total_capital=CAP, with_attribution=False)

    assert (res.cash_notional['CN1Y'] == 0).all() and (res.cash_notional['CN2Y'] == 0).all()
    assert list(res.deriv_notional.columns) == ['SWAP1Y', 'SWAP2Y']
    for a, v in {'CN5Y': -3e9, 'CN10Y': -1e9, 'CN30Y': -5e8, 'US10Y': -5e8, 'CN20Y': 2e9}.items():
        assert (res.cash_notional[a] == v).all(), a                       # shorts stay short bonds, longs untouched
    # DV01-matched with yesterday's duration: day 0 has no lagged yield -> no hedge yet
    assert res.deriv_notional['SWAP1Y'].iloc[1:].lt(0).all() and res.deriv_notional['SWAP1Y'].iloc[0] == 0.0


def test_swap_tenors_fall_back_to_the_short_bond_before_swap_data_starts(monkeypatch, flat_futures):
    idx = pd.bdate_range('2021-12-01', periods=120)              # swaps start 2022-02-28
    monkeypatch.setattr(ov, '_load_futures', lambda: flat_futures(idx))
    n = _notional(idx, CN2Y=-1e9)
    res = ov.route_cn_shorts(n, _market(idx), total_capital=CAP, with_attribution=False)
    before = idx < pd.Timestamp('2022-02-28')
    assert (res.cash_notional['CN2Y'][before] == -1e9).all()     # still a short bond
    assert (res.cash_notional['CN2Y'][~before] == 0).all()       # routed to the swap
    assert (res.deriv_notional['SWAP2Y'][before] == 0).all()
    assert res.deriv_notional['SWAP2Y'][~before].iloc[1:].lt(0).all()
    # without swaps allowed the 2Y short is always a bond
    res2 = ov.route_cn_shorts(n, _market(idx), total_capital=CAP, with_attribution=False, allow_swaps=False)
    assert (res2.cash_notional['CN2Y'] == -1e9).all() and res2.deriv_notional.empty


def test_overlay_routed_assets_lists_only_derivative_tenors():
    idx = _idx()
    cols = ['CN1Y', 'CN2Y', 'CN5Y', 'CN10Y', 'US10Y', 'USDCNY']
    assert ov.overlay_routed_assets(cols, _market(idx)) == ['CN1Y', 'CN2Y']
    assert ov.overlay_routed_assets(cols, _market(idx), routing={5.0: ['TF', 'bond']}) == ['CN5Y']


def test_futures_routing_when_asked(monkeypatch, flat_futures):
    idx = _idx()
    monkeypatch.setattr(ov, '_load_futures', lambda: flat_futures(idx))
    n = _notional(idx, CN10Y=-1e9, CN5Y=2e9)
    res = ov.route_cn_shorts(n, _market(idx), total_capital=CAP, with_attribution=False, routing=FUT10)
    assert (res.cash_notional['CN10Y'] == 0).all() and (res.cash_notional['CN5Y'] == 2e9).all()
    assert list(res.deriv_notional.columns) == ['T']
    assert res.deriv_notional['T'].iloc[1:].to_numpy() == pytest.approx(-1e9)    # same yield & duration -> same notional


def test_futures_pnl_is_the_contract_move_with_no_bond_carry(monkeypatch, flat_futures):
    idx = _idx()
    md = _market(idx)
    monkeypatch.setattr(ov, '_load_futures', lambda: flat_futures(idx, jump_day=10, jump=1.0))   # +1 point on day 10
    n = _notional(idx, CN10Y=-1e9)
    res = ov.route_cn_shorts(n, md, total_capital=CAP, with_attribution=True, routing=FUT10)

    pnl = res.deriv_pnl['T']
    assert pnl.iloc[10] == pytest.approx(-1e9 * 1.0 / 100.0)             # short loses notional x dF/100
    assert pnl.drop(idx[10]).abs().iloc[1:].sum() == 0.0                 # flat price -> NO carry, unlike a bond
    assert res.short_bond_pnl.sum() < 0                                   # a short cash bond PAYS the bond yield
    assert res.short_bond_repo.sum() > 0                                  # and earns repo through the hurdle


def test_swap_pays_fixed_and_earns_fr007(monkeypatch, flat_futures):
    idx = _idx(start='2024-01-02')
    md = _market(idx, swap=2.8, fr007=1.8)
    monkeypatch.setattr(ov, '_load_futures', lambda: flat_futures(idx))
    n = _notional(idx, CN1Y=-1e9)
    res = ov.route_cn_shorts(n, md, total_capital=CAP, with_attribution=False)
    assert list(res.deriv_notional.columns) == ['SWAP1Y']
    day = res.deriv_pnl['SWAP1Y'].iloc[5]
    assert day == pytest.approx(-res.deriv_notional['SWAP1Y'].abs().iloc[5] * (2.8 - 1.8) / 100 / 365)


def test_margin_is_a_fraction_of_overlay_notional_and_counts_in_the_cap(monkeypatch, flat_futures):
    idx = _idx()
    monkeypatch.setattr(ov, '_load_futures', lambda: flat_futures(idx))
    n = _notional(idx, CN10Y=-2e9, CN5Y=9.4e9)                           # 9.4bn cash + 0.06bn margin = 9.46bn
    res = ov.route_cn_shorts(n, _market(idx), total_capital=CAP, with_attribution=False, routing=FUT10)
    assert res.margin.iloc[5] == pytest.approx(0.03 * 2e9)
    used = (res.cash_notional.abs().sum(axis=1) + res.margin) / CAP
    assert used.iloc[5] == pytest.approx(0.9460)
    # push over the cap: everything scales down so usage == 95%
    big = _notional(idx, CN10Y=-2e9, CN5Y=9.8e9)
    res2 = ov.route_cn_shorts(big, _market(idx), total_capital=CAP, with_attribution=False, routing=FUT10)
    used2 = (res2.cash_notional.abs().sum(axis=1) + res2.margin) / CAP
    assert used2.iloc[5] == pytest.approx(0.95)


def test_shorts_consume_no_capital_and_are_never_netted():
    """The 95% cap limits LONG size only (RiskModelConfig.SHORT_CAPITAL_RATE = 0)."""
    cls = {'CN10Y': 'bond', 'CN5Y': 'bond', 'CN2Y': 'bond'}
    kw = dict(asset_class_of=cls, signed_classes=('bond',))
    # 90% long + 90% short: nothing scales (the old |notional| rule would have scaled by 0.95/1.8)
    w = pd.Series({'CN5Y': 0.90, 'CN10Y': -0.90})
    out = weights_to_notional(w, 1000.0, **kw)
    assert out['CN5Y'] == pytest.approx(900.0) and out['CN10Y'] == pytest.approx(-900.0)
    # long size over the cap scales the WHOLE book (shape kept), whatever the short size
    big = pd.Series({'CN5Y': 1.20, 'CN10Y': -0.30})
    out2 = weights_to_notional(big, 1000.0, **kw)
    assert out2['CN5Y'] == pytest.approx(1200.0 * 0.95 / 1.20) and out2['CN10Y'] == pytest.approx(-300.0 * 0.95 / 1.20)
    # a short does NOT free capital for longs either: net exposure is irrelevant
    assert weights_to_notional(pd.Series({'CN5Y': 1.20, 'CN10Y': -1.20}), 1000.0, **kw)['CN5Y'] == pytest.approx(950.0)


def test_legacy_rate_counts_shorts_in_full_and_routed_shorts_cost_margin():
    cls = {'CN10Y': 'bond', 'CN5Y': 'bond'}
    kw = dict(asset_class_of=cls, signed_classes=('bond',))
    big = pd.Series({'CN10Y': -0.40, 'CN5Y': 0.98})
    legacy = weights_to_notional(big, 1000.0, short_capital_rate=1.0, **kw)
    assert legacy['CN5Y'] == pytest.approx(980.0 * 0.95 / 1.38)                       # 0.98 + 0.40 gross
    routed = weights_to_notional(big, 1000.0, short_capital_rate=1.0, overlay_assets=['CN10Y'],
                                 overlay_margin_rate=0.03, **kw)
    assert routed['CN5Y'] == pytest.approx(980.0 * 0.95 / (0.98 + 0.03 * 0.40))        # overlay short = margin only
    assert routed['CN5Y'] > legacy['CN5Y']
    # with shorts free (default) the overlay margin still counts: derivatives tie up margin
    free = weights_to_notional(big, 1000.0, overlay_assets=['CN10Y'], overlay_margin_rate=0.03, **kw)
    assert free['CN5Y'] == pytest.approx(980.0 * 0.95 / (0.98 + 0.012))
    plain_free = weights_to_notional(big, 1000.0, **kw)
    assert plain_free['CN5Y'] == pytest.approx(980.0 * 0.95 / 0.98)


def test_dv01_scaling_counts_long_size_only_and_dv01_stays_gross():
    from multiasset.book.sizing import scale_sleeve_to_dv01_target
    idx = _idx(5)
    w = pd.DataFrame({'CN10Y': -0.20, 'CN5Y': 0.40}, index=idx)
    dur = pd.DataFrame({'CN10Y': 8.0, 'CN5Y': 4.5}, index=idx)
    # huge DV01 target so the capital cap binds: shorts are free -> long book scales to 95%
    free = scale_sleeve_to_dv01_target(w, dur, 10e9, 1e6, 0.95)
    assert free['CN5Y'].iloc[0] == pytest.approx(0.95)
    assert (free['CN10Y'] / free['CN5Y']).iloc[0] == pytest.approx(-0.5)               # shape preserved
    legacy = scale_sleeve_to_dv01_target(w, dur, 10e9, 1e6, 0.95, short_capital_rate=1.0)
    assert legacy['CN5Y'].iloc[0] == pytest.approx(0.40 * 0.95 / 0.60)
    routed = scale_sleeve_to_dv01_target(w, dur, 10e9, 1e6, 0.95, overlay_assets=['CN10Y'],
                                         overlay_margin_rate=0.03)
    assert routed['CN5Y'].iloc[0] == pytest.approx(0.40 * 0.95 / (0.40 + 0.03 * 0.20))
    # the DV01 cap is GROSS (long + short): 0.4*4.5 + 0.2*8.0 = 3.4 years of capital -> 3.4/1e4*1e10... target binds
    target = scale_sleeve_to_dv01_target(w, dur, 10e9, 2.0, 0.95)                      # 2.0 MM/bp on 10bn
    dv01_mm = (target * dur).abs().sum(axis=1).iloc[0] * 10e9 / 1e10
    assert dv01_mm == pytest.approx(2.0)


def test_illiquid_20y_short_is_held_as_a_dv01_equivalent_30y_short():
    idx = _idx()
    md = _market(idx)
    n = _notional(idx, CN20Y=-1e9, CN30Y=5e8, CN10Y=-3e8, CN5Y=1e9)
    out = ov.substitute_shorts(n, md, mapping={20.0: 30.0})

    d20, d30 = hi.mod_duration(2.5, 20.0), hi.mod_duration(2.5, 30.0)
    assert (out['CN20Y'].iloc[1:] == 0).all()                                   # no 20Y short remains
    assert out['CN30Y'].iloc[3] == pytest.approx(5e8 - 1e9 * d20 / d30)         # nets against the 30Y long
    assert out['CN30Y'].iloc[3] * d30 + out['CN20Y'].iloc[3] * d20 == pytest.approx(5e8 * d30 - 1e9 * d20)  # DV01 preserved
    assert (out['CN10Y'] == -3e8).all() and (out['CN5Y'] == 1e9).all()          # other tenors untouched
    # day 0 has no lagged duration: the short stays where it is
    assert out['CN20Y'].iloc[0] == -1e9 and out['CN30Y'].iloc[0] == 5e8


def test_20y_long_is_not_moved_and_missing_target_leaves_the_short():
    idx = _idx()
    md = _market(idx)
    longs = _notional(idx, CN20Y=1e9, CN30Y=0.0)
    assert (ov.substitute_shorts(longs, md, mapping={20.0: 30.0}) == longs).all().all()
    no_target = _notional(idx, CN20Y=-1e9)
    assert (ov.substitute_shorts(no_target, md, mapping={20.0: 30.0})['CN20Y'] == -1e9).all()
    assert ov.substitute_shorts(no_target, md, mapping={}) is no_target


def test_all_short_day_is_still_scaled_to_the_dv01_target_not_treated_as_flat():
    """With shorts free, capital usage on a short-only day is ~0, but the book is real: it must be
    sized to the (gross) DV01 target, with no division blow-up."""
    from multiasset.book.sizing import scale_sleeve_to_dv01_target
    idx = _idx(6)
    w = pd.DataFrame({'CN10Y': [-0.10, -0.10, -0.10, -0.10, -0.10, -0.10], 'CN5Y': [0.30, 0.30, 0.30, 0.30, 0.30, 0.0]}, index=idx)
    dur = pd.DataFrame({'CN10Y': 8.0, 'CN5Y': 4.5}, index=idx)
    out = scale_sleeve_to_dv01_target(w, dur, 10e9, 2.0, 0.95)               # target 2.0 MM/bp gross
    short_only = out.iloc[5]                                                  # day with NO long at all
    assert short_only['CN5Y'] == 0.0 and short_only['CN10Y'] < -0.10          # scaled UP to the DV01 target
    assert (short_only * dur.iloc[5]).abs().sum() * 10e9 / 1e10 == pytest.approx(2.0)      # gross DV01 = target
    assert np.isfinite(out.to_numpy()).all()


def test_dv01_scaling_respects_the_short_size_ceiling():
    from multiasset.book.sizing import scale_sleeve_to_dv01_target
    idx = _idx(5)
    w = pd.DataFrame({'CN10Y': -0.60, 'CN5Y': 0.20}, index=idx)                   # short-heavy book
    dur = pd.DataFrame({'CN10Y': 1.0, 'CN5Y': 1.0}, index=idx)
    out = scale_sleeve_to_dv01_target(w, dur, 10e9, 1e6, 0.95)                    # huge DV01 target: caps decide
    assert out['CN10Y'].iloc[0] == pytest.approx(-0.95)                           # short ceiling binds, not the 0.20 long
    assert out['CN5Y'].iloc[0] == pytest.approx(0.95 / 3.0)
    long_heavy = pd.DataFrame({'CN10Y': -0.20, 'CN5Y': 0.60}, index=idx)
    out2 = scale_sleeve_to_dv01_target(long_heavy, dur, 10e9, 1e6, 0.95)
    assert out2['CN5Y'].iloc[0] == pytest.approx(0.95)                            # long ceiling binds


def test_router_enforces_the_short_ceiling_across_cash_and_derivative_shorts(monkeypatch, flat_futures):
    idx = _idx()
    monkeypatch.setattr(ov, '_load_futures', lambda: flat_futures(idx))
    n = _notional(idx, CN10Y=-8e9, CN30Y=-3e9, CN5Y=2e9)                          # 11bn short on 10bn capital
    res = ov.route_cn_shorts(n, _market(idx), total_capital=CAP, with_attribution=False, routing={})
    short = res.cash_notional.clip(upper=0).abs().sum(axis=1) + res.deriv_notional.clip(upper=0).abs().sum(axis=1)
    assert (short.iloc[3:] / CAP).max() == pytest.approx(0.95)
