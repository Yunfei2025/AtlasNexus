# -*- coding: utf-8 -*-
"""Regression tests for multiasset.book.funding (Step 6 of
docs/plans/beta_book_exposure_vs_capital.md — funding hurdle for Sharpe
only, cash return on undeployed capital).

The load-bearing property: 'DE Gov Bond' assets get country='EU' from
get_asset_yield_series (multiasset/data.py:231), but the funding-rate table
in factor_backtest.py keys 'DE' — without normalise_domicile, Bund funding
is silently zero. These tests confirm the fix, and confirm the funding
hurdle never touches daily_pnl itself (only Sharpe, via compute_metrics's
funding_hurdle param).
"""

from __future__ import annotations

import pandas as pd
import pytest

from multiasset import factor_backtest
from multiasset.book.funding import (
    normalise_domicile,
    book_funding_cost_daily,
    benchmark_hurdle_daily,
    cash_return_daily,
)
from multiasset.data import calendar_gap_days


def _idx(n=60):
    return pd.bdate_range('2024-01-01', periods=n)


@pytest.fixture(autouse=True)
def _clear_funding_cache():
    factor_backtest._funding_rate_cache.clear()
    yield
    factor_backtest._funding_rate_cache.clear()


def test_normalise_domicile_maps_eu_to_de():
    assert normalise_domicile('EU') == 'DE'
    assert normalise_domicile('CN') == 'CN'
    assert normalise_domicile('US') == 'US'
    assert normalise_domicile('UNKNOWN') == 'UNKNOWN'


def test_book_funding_cost_daily_charges_multiple_domiciles_differently(monkeypatch):
    """A CN + US + DE book must charge three DIFFERENT rates — proving
    per-domicile lookup actually happens, not one flat rate applied to
    everything."""
    idx = _idx()
    notional = pd.DataFrame({
        'CN10Y': 1_000_000.0,
        'US10Y': 1_000_000.0,
        'EU10Y': 1_000_000.0,  # domicile 'EU' -> normalises to 'DE'
    }, index=idx)

    rates = {'CN': 2.0, 'US': 5.0, 'DE': 3.0}

    def fake_load_funding_rate(country):
        r = rates.get(country)
        return pd.Series(r, index=idx) if r is not None else None

    monkeypatch.setattr(factor_backtest, '_load_funding_rate', fake_load_funding_rate)
    factor_backtest._funding_rate_cache.clear()

    domicile_of = {'CN10Y': 'CN', 'US10Y': 'US', 'EU10Y': 'EU'}
    cost = book_funding_cost_daily(notional, domicile_of)

    # Isolate each asset's contribution by zeroing the other two.
    for asset, rate_key, expected_rate in [('CN10Y', 'CN', 2.0), ('US10Y', 'US', 5.0), ('EU10Y', 'DE', 3.0)]:
        single = notional[[asset]]
        c = book_funding_cost_daily(single, {asset: domicile_of[asset]})
        expected_daily = 1_000_000.0 * expected_rate / 100.0 / 365.0
        assert c.dropna().iloc[-1] == pytest.approx(expected_daily, rel=1e-9), \
            f"{asset} should be charged the {rate_key} rate ({expected_rate}%), not some other domicile's"


def test_de_gov_bond_gets_nonzero_funding_cost_via_eu_alias(monkeypatch):
    """THE regression test for the EU/DE bug: an asset with domicile 'EU'
    (as get_asset_yield_series returns for German bonds) must get a
    NONZERO funding cost, because normalise_domicile maps it to 'DE' before
    the lookup — not silently zero, which is what happens if the alias is
    ever removed."""
    idx = _idx()
    notional = pd.DataFrame({'EU10Y': 1_000_000.0}, index=idx)

    def fake_load_funding_rate(country):
        if country == 'DE':
            return pd.Series(3.0, index=idx)  # ESTR-like rate, only under 'DE'
        return None  # 'EU' (unmapped) must never be looked up directly

    monkeypatch.setattr(factor_backtest, '_load_funding_rate', fake_load_funding_rate)
    factor_backtest._funding_rate_cache.clear()

    cost = book_funding_cost_daily(notional, {'EU10Y': 'EU'})
    assert (cost.dropna() != 0.0).any(), \
        "German bond funding cost must be nonzero via the EU->DE alias"


def test_book_funding_cost_daily_is_zero_for_unresolvable_domicile(monkeypatch):
    """An asset with no domicile mapping (e.g. FX/commodity) contributes
    zero funding cost, not an error."""
    idx = _idx()
    notional = pd.DataFrame({'Gold': 1_000_000.0}, index=idx)
    monkeypatch.setattr(factor_backtest, '_load_funding_rate', lambda c: None)
    factor_backtest._funding_rate_cache.clear()

    cost = book_funding_cost_daily(notional, {'Gold': ''})
    assert (cost.fillna(0) == 0.0).all()


def test_book_funding_cost_daily_never_appears_in_pnl_only_in_hurdle(monkeypatch):
    """The funding cost series must be usable as compute_metrics's
    funding_hurdle WITHOUT ever being subtracted from a P&L/return series
    directly — this test just confirms book_funding_cost_daily returns a
    plain additive-cost series (CNY), the same shape compute_metrics
    expects for its funding_hurdle param (a decimal RATE series, not a CNY
    amount) only once divided by notional — i.e. callers convert this CNY
    cost into a rate by dividing by total_capital before passing it to
    compute_metrics, they don't pass the CNY series directly."""
    idx = _idx()
    notional = pd.DataFrame({'CN10Y': 1_000_000.0}, index=idx)

    def fake_load_funding_rate(country):
        return pd.Series(2.0, index=idx) if country == 'CN' else None

    monkeypatch.setattr(factor_backtest, '_load_funding_rate', fake_load_funding_rate)
    factor_backtest._funding_rate_cache.clear()

    cost_cny = book_funding_cost_daily(notional, {'CN10Y': 'CN'})
    total_capital = 10_000_000.0
    hurdle_rate = cost_cny / total_capital  # what a caller would pass into compute_metrics

    from multiasset.factor_backtest import compute_metrics
    rets = pd.Series(0.0005, index=idx) + pd.Series(range(len(idx)), index=idx) * 1e-7  # tiny variance
    df = pd.DataFrame({'strategy_returns': rets})
    m_no_hurdle = compute_metrics(df, geometric_annualisation=True)
    m_with_hurdle = compute_metrics(df, geometric_annualisation=True, funding_hurdle=hurdle_rate)

    assert m_with_hurdle['Ann. Vol'] == m_no_hurdle['Ann. Vol']
    assert m_with_hurdle['Ann. Return'] == m_no_hurdle['Ann. Return']
    assert m_with_hurdle['Ann. Funding Cost'] > 0.0


def _patch_cn_rate(monkeypatch, idx, rate_pct):
    from multiasset.book import funding as F
    factor_backtest._funding_rate_cache.clear()
    monkeypatch.setattr(F, 'load_funding_rate',
                        lambda country: pd.Series(rate_pct, index=idx) if country == 'CN' else None)


def test_cash_return_daily_earns_fr007_on_everything_not_deployed(monkeypatch):
    """Idle cash, INCLUDING the utilisation buffer, earns FR007; deploying a long CNY
    removes exactly one CNY of cash."""
    idx = _idx()
    C = 10_000_000.0
    _patch_cn_rate(monkeypatch, idx, 3.65)                               # 0.01% per calendar day
    flat = pd.DataFrame({'CN10Y': 0.0}, index=idx)
    deployed = pd.DataFrame({'CN10Y': 0.95 * C}, index=idx)
    gap = calendar_gap_days(idx).to_numpy()

    cash_flat = cash_return_daily(flat, C)
    cash_dep = cash_return_daily(deployed, C)
    assert (cash_flat.iloc[2:] / gap[2:]).round(6).eq(C * 0.0001).all()   # 100% of capital earns, not 95%
    assert (cash_dep.iloc[2:] / gap[2:]).round(6).eq(0.05 * C * 0.0001).all()   # the 5% buffer still earns


def test_cash_accounting_for_shorts_and_margin(monkeypatch):
    idx = _idx()
    C = 10_000_000.0
    _patch_cn_rate(monkeypatch, idx, 3.65)
    per_day = lambda s: float((s.iloc[3] / calendar_gap_days(idx).to_numpy()[3]))   # noqa: E731

    flat = per_day(cash_return_daily(pd.DataFrame({'CN2Y': 0.0, 'CN10Y': 0.0}, index=idx), C))
    # a short BOND is a reverse repo + sale: proceeds earn FR007, so long+short of equal size = all cash
    ls = pd.DataFrame({'CN2Y': 0.45 * C, 'CN10Y': -0.45 * C}, index=idx)
    assert per_day(cash_return_daily(ls, C)) == pytest.approx(flat)
    # a short COMMODITY has no proceeds interest and (SHORT_CAPITAL_RATE = 0) consumes no capital
    ls_c = pd.DataFrame({'CN2Y': 0.45 * C, 'Gold': -0.45 * C}, index=idx)
    assert per_day(cash_return_daily(ls_c, C)) == pytest.approx(0.55 * C * 0.0001)      # only the long uses cash
    # with the legacy rate 1.0 the short is funded notional and uses cash too
    from multiasset.config import RiskModelConfig
    monkeypatch.setattr(RiskModelConfig, 'SHORT_CAPITAL_RATE', 1.0)
    assert per_day(cash_return_daily(ls_c, C)) == pytest.approx(0.10 * C * 0.0001)
    # derivative margin is cash tied up at the broker and earns nothing
    margin = pd.Series(0.03 * C, index=idx)
    assert per_day(cash_return_daily(pd.DataFrame({'CN2Y': 0.0}, index=idx), C, margin=margin)) == pytest.approx(0.97 * C * 0.0001)


def test_carry_is_accrued_per_calendar_day_not_per_row():
    idx = pd.bdate_range('2023-01-02', '2023-12-29')
    gap = calendar_gap_days(idx)
    assert gap.iloc[0] == 1 and gap.loc['2023-01-09'] == 3                  # Monday row = Fri->Mon, 3 days
    year_carry = (2.5 / 100 / 365 * gap).sum()
    assert year_carry == pytest.approx(0.025 * (idx[-1] - idx[0]).days / 365 + 0.025 / 365, rel=1e-9)
    assert year_carry > 0.99 * 0.025 * 363 / 365                            # ~a full year, not 0.69 of it


@pytest.mark.parametrize('deployed', [0.0, 0.5, 0.95])
@pytest.mark.parametrize('side', [1.0, -1.0])
def test_a_book_earning_exactly_the_cash_rate_scores_zero_excess(monkeypatch, deployed, side):
    """THE regression for docs/plans/factor_model_improvement.md 3.14: bond yield == FR007
    and zero price risk -> excess return is 0 at any deployment, long or short. The old
    numerator gave 1.3% idle and double-charged FR007 on every deployed CNY."""
    idx = pd.bdate_range('2020-01-01', periods=504)
    C, y = 10e9, 2.0
    _patch_cn_rate(monkeypatch, idx, y)
    gap = calendar_gap_days(idx).to_numpy()
    alloc = pd.DataFrame({'CN10Y': side * deployed * C}, index=idx)
    carry = alloc['CN10Y'] * (y / 100 / 365) * gap                           # long earns y, short pays y
    cash = cash_return_daily(alloc, C)
    hurdle = benchmark_hurdle_daily(alloc, {'CN10Y': 'CN'}, C)
    rets = pd.DataFrame({'strategy_returns': (carry + cash) / C}, index=idx)
    m = factor_backtest.compute_metrics(rets, geometric_annualisation=True, funding_hurdle=hurdle / C)
    # geometric compounding of a 2% rate adds ~0.02%; the OLD numerator gave 1.318% at 0% deployed
    assert m['Ann. Return'] - m['Ann. Funding Cost'] == pytest.approx(0.0, abs=5e-4)


def test_foreign_hedged_bond_excess_is_yield_minus_foreign_short_rate(monkeypatch):
    from multiasset.book import funding as F
    idx = pd.bdate_range('2020-01-01', periods=504)
    C, y_f, r_f, fr = 10e9, 4.0, 3.0, 2.0                                    # US bond: yield 4%, SOFR 3%, FR007 2%
    factor_backtest._funding_rate_cache.clear()
    monkeypatch.setattr(F, 'load_funding_rate',
                        lambda c: pd.Series({'CN': fr, 'US': r_f}.get(c), index=idx) if c in ('CN', 'US') else None)
    gap = calendar_gap_days(idx).to_numpy()
    alloc = pd.DataFrame({'US10Y': 0.5 * C}, index=idx)
    carry = alloc['US10Y'] * (y_f / 100 / 365) * gap                         # FX-hedged: the full foreign yield
    cash = cash_return_daily(alloc, C)
    hurdle = benchmark_hurdle_daily(alloc, {'US10Y': 'US'}, C)
    rets = pd.DataFrame({'strategy_returns': (carry + cash) / C}, index=idx)
    m = factor_backtest.compute_metrics(rets, geometric_annualisation=True, funding_hurdle=hurdle / C)
    assert m['Ann. Return'] - m['Ann. Funding Cost'] == pytest.approx(0.5 * (y_f - r_f) / 100, abs=5e-4)


def test_foreign_funding_rate_backfilled_from_1y_govt_yield(monkeypatch):
    """Before a foreign overnight series starts, the funding rate comes from
    the 1Y government yield minus the mean (1Y - overnight) spread over the
    first year of overlap — not NaN, which book_funding_cost_daily would
    turn into a zero charge on foreign notional."""
    from multiasset import data as ma_data

    pre = pd.bdate_range('2017-01-02', '2018-03-30')
    post = pd.bdate_range('2018-04-02', '2019-12-31')
    overnight = pd.Series(2.0, index=post)
    y1 = pd.concat([pd.Series(1.5, index=pre), pd.Series(2.25, index=post)])
    monkeypatch.setattr(ma_data, '_load_fx_curve_artifact',
                        lambda: {'US': pd.DataFrame({'US1Y': y1})})

    out = factor_backtest._backfill_with_1y_govt_proxy(overnight, 'US')

    assert out.index.min() == pre[0]
    assert out[pre].tolist() == pytest.approx([1.25] * len(pre))   # 1.5 - 0.25 spread
    assert out[post].tolist() == pytest.approx([2.0] * len(post))  # real series untouched


def test_foreign_funding_backfill_noop_without_curve(monkeypatch):
    from multiasset import data as ma_data

    def _missing():
        raise FileNotFoundError

    monkeypatch.setattr(ma_data, '_load_fx_curve_artifact', _missing)
    rate = pd.Series(2.0, index=_idx())
    assert factor_backtest._backfill_with_1y_govt_proxy(rate, 'US').equals(rate)


def test_foreign_bond_carries_rates_and_fx_factors():
    """A CNY-based investor in a US bond holds rates AND USDCNY: the risk
    model must expose both (the hedge is a book-level overlay, multiasset.book.fx)."""
    from multiasset.assets import MultiFactorBondAsset

    us = MultiFactorBondAsset('US10Y', country='US', tenor='10Y')
    assert any(f.startswith('IRDL.US') for f in us.factors)
    assert us.factors['FXDL.USDCNY'] == 1.0


def test_short_bond_borrow_cost_is_per_tenor_and_only_on_shorts():
    from multiasset.book.funding import short_bond_borrow_cost_daily

    idx = _idx(5)
    cgb = {c: pd.Series(2.5, index=idx) for c in (
        '中债国债到期收益率:5年', '中债国债到期收益率:10年', '中债国债到期收益率:30年')}
    md = ({}, {'CGB': pd.DataFrame(cgb)}, {})
    n = pd.DataFrame({'CN10Y': -1e9, 'CN30Y': -2e8, 'CN5Y': -3e8}, index=idx)
    fees = {'CN': {10.0: 40.0, 30.0: 100.0}}

    total, by_asset, bps = short_bond_borrow_cost_daily(n, md, fees)
    assert bps == {'CN10Y': 40.0, 'CN30Y': 100.0}                       # 5Y not listed -> free
    assert by_asset['CN10Y'].iloc[2] == pytest.approx(1e9 * 40 / 1e4 / 365)
    assert by_asset['CN30Y'].iloc[2] == pytest.approx(2e8 * 100 / 1e4 / 365)
    assert total.iloc[0] == 0.0                                          # lagged: nothing on day 0

    long_only = pd.DataFrame({'CN10Y': 1e9}, index=idx)                  # longs never pay a fee
    assert short_bond_borrow_cost_daily(long_only, md, fees)[0].sum() == 0.0
    assert short_bond_borrow_cost_daily(n, md, {})[0].sum() == 0.0       # empty table -> not modelled


def test_cash_benchmark_zero_excess_holds_on_a_compounding_nav(monkeypatch):
    """The same invariance, evaluated the way the app does it: returns are NAV.pct_change(),
    so the hurdle must be a rate on previous-day NAV. A hurdle over INITIAL capital leaves a
    ~0.3 pt/yr hole once NAV has grown (the bug fixed 2026-10-17)."""
    from multiasset.book.funding import hurdle_rate_on_nav

    idx = pd.bdate_range('2014-01-01', periods=2520)                 # 10 years
    C, y = 10e9, 2.5
    _patch_cn_rate(monkeypatch, idx, y)
    gap = calendar_gap_days(idx).to_numpy()
    alloc = pd.DataFrame({'CN10Y': 0.5 * C}, index=idx)
    # a book that earns the cash rate PLUS a steady 3%/yr of outperformance, so NAV compounds
    alpha = pd.Series(0.03 / 365 * gap, index=idx) * C
    pnl = alloc['CN10Y'] * (y / 100 / 365) * gap + cash_return_daily(alloc, C) + alpha
    nav = C + pnl.cumsum()
    hurdle = benchmark_hurdle_daily(alloc, {'CN10Y': 'CN'}, C)

    def excess(h_rate):
        rets = pd.DataFrame({'strategy_returns': nav.pct_change()}).dropna()
        m = factor_backtest.compute_metrics(rets, geometric_annualisation=True, funding_hurdle=h_rate)
        return m['Ann. Return'] - m['Ann. Funding Cost']

    on_nav = excess(hurdle_rate_on_nav(hurdle, nav))
    on_initial = excess(hurdle / C)
    # the NAV-based hurdle recovers the true excess (the 3%/yr alpha measured on a growing base);
    # dividing by initial capital understates it by roughly hurdle x NAV growth
    assert on_nav > on_initial + 0.002
    assert on_nav == pytest.approx(0.03 * C / nav.mean(), abs=3e-3)
