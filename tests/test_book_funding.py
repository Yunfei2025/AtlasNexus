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
    cash_return_daily,
)


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


def test_cash_return_daily_scales_with_undeployed_capital(monkeypatch):
    """More undeployed capital -> more cash return. A fully-deployed book
    (gross == max_utilisation*capital) earns ~zero cash return; a
    lightly-deployed book earns close to the full cash rate."""
    idx = _idx()
    total_capital = 10_000_000.0

    def fake_load_funding_rate(country):
        return pd.Series(3.65, index=idx) if country == 'CN' else None  # 3.65%/yr -> 0.01%/day

    monkeypatch.setattr(factor_backtest, '_load_funding_rate', fake_load_funding_rate)
    factor_backtest._funding_rate_cache.clear()

    fully_deployed = pd.DataFrame({'CN10Y': 0.95 * total_capital}, index=idx)
    lightly_deployed = pd.DataFrame({'CN10Y': 0.10 * total_capital}, index=idx)

    cash_full = cash_return_daily(fully_deployed, total_capital, max_utilisation=0.95)
    cash_light = cash_return_daily(lightly_deployed, total_capital, max_utilisation=0.95)

    assert cash_light.dropna().iloc[-1] > cash_full.dropna().iloc[-1], \
        "less deployed capital must earn more cash return"
    assert cash_full.dropna().iloc[-1] == pytest.approx(0.0, abs=1e-6)


def test_cash_return_daily_uses_gross_not_net_exposure(monkeypatch):
    """A long-short book that nets to ~0 CNY of directional exposure must
    still show LOW cash return (both legs' notional ties up capital) — not
    high cash return, which would happen if net (not gross) exposure were
    used."""
    idx = _idx()
    total_capital = 10_000_000.0

    def fake_load_funding_rate(country):
        return pd.Series(3.65, index=idx) if country == 'CN' else None

    monkeypatch.setattr(factor_backtest, '_load_funding_rate', fake_load_funding_rate)
    factor_backtest._funding_rate_cache.clear()

    # Long CN2Y, short CN10Y, both large, net notional ~0.
    long_short = pd.DataFrame({
        'CN2Y': 0.45 * total_capital,
        'CN10Y': -0.45 * total_capital,
    }, index=idx)
    cash = cash_return_daily(long_short, total_capital, max_utilisation=0.95)

    flat = pd.DataFrame({'CN2Y': 0.0, 'CN10Y': 0.0}, index=idx)
    cash_all_in_cash = cash_return_daily(flat, total_capital, max_utilisation=0.95)

    assert cash.dropna().iloc[-1] < cash_all_in_cash.dropna().iloc[-1], \
        "a large gross (even if net-flat) position must earn less cash return than being fully in cash"
