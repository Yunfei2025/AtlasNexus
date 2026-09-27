# -*- coding: utf-8 -*-
"""Regression tests for multiasset.book.pnl (Step 5 of
docs/plans/beta_book_exposure_vs_capital.md — capital-gain vs carry split).

The load-bearing property: for bonds/IRS/credit, capital_gain + carry must
equal the legacy notional*total P&L exactly (calculate_daily_returns_series
already gives a clean decomposition; this module just multiplies it by
real notional). For FX/commodity, there IS no such decomposition
(calculate_daily_returns_series hardcodes their 'capital' column to 0.0),
so their entire P&L must land in BookPnL.other, not silently vanish.

Requires real market data (calculate_daily_returns_series reads live yield/
FX/commodity series) — skips gracefully if unavailable.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

try:
    from multiasset.data import load_raw_market_data, calculate_daily_returns_series
    from multiasset.book.pnl import compute_book_pnl, returns_split_is_exact, BookPnL
except Exception:  # pragma: no cover - import-time data/env issues
    load_raw_market_data = None


def _market_data_or_skip():
    if load_raw_market_data is None:
        pytest.skip("multiasset.data unavailable")
    try:
        return load_raw_market_data()
    except Exception as e:
        pytest.skip(f"market data unavailable: {e}")


def _date_range(years=2):
    end = date.today()
    start = end - timedelta(days=365 * years)
    return start.isoformat(), end.isoformat()


def _legacy_total_pnl(notional_daily: pd.DataFrame, market_data, start_date, end_date) -> pd.DataFrame:
    """The exact pre-Step-5 computation: notional * 'total' column only —
    kept HERE, in the test file, as the reconciliation baseline, rather
    than as production code (see docs/plans/beta_book_exposure_vs_capital.md
    Step 9, which asks for this same pattern at the book-reconciliation
    level; this is the Step 5-scoped, cheaper version of it)."""
    ret_series = {}
    for name in notional_daily.columns:
        df = calculate_daily_returns_series(name, market_data, start_date, end_date)
        if df.empty:
            continue
        s = df.set_index('Date')['total']
        if not isinstance(s.index, pd.DatetimeIndex):
            s.index = pd.to_datetime(s.index)
        ret_series[name] = s
    rets = pd.DataFrame(ret_series, index=notional_daily.index).reindex(columns=notional_daily.columns).fillna(0.0)
    return notional_daily * rets


def test_returns_split_is_exact_true_for_bonds_false_for_fx_and_commodity():
    market_data = _market_data_or_skip()
    assert returns_split_is_exact('CN10Y', market_data) is True
    assert returns_split_is_exact('USDCNY', market_data) is False
    assert returns_split_is_exact('Gold', market_data) is False


def test_bonds_only_book_capital_plus_carry_equals_legacy_total():
    """THE load-bearing reconciliation: for a bonds-only book,
    (capital_gain + carry).sum().sum() must equal the legacy
    notional*total computation to a tight tolerance — proving the split
    doesn't lose or double-count anything for the case where a clean
    decomposition exists."""
    market_data = _market_data_or_skip()
    start, end = _date_range()

    assets = ['CN1Y', 'CN2Y', 'CN5Y', 'CN10Y', 'CN20Y', 'CN30Y']
    idx = pd.bdate_range(start, end)
    notional_daily = pd.DataFrame(1_000_000.0, index=idx, columns=assets)  # flat 1mm CNY each, every day

    pnl = compute_book_pnl(notional_daily, market_data, start, end)
    new_total = (pnl.capital_gain + pnl.carry).sum().sum()

    legacy = _legacy_total_pnl(notional_daily, market_data, start, end)
    legacy_total = legacy.sum().sum()

    assert legacy_total != 0.0, "sanity check: legacy P&L should be nonzero over a multi-year window"
    rel_diff = abs(new_total - legacy_total) / abs(legacy_total)
    assert rel_diff < 1e-6, f"new split ({new_total}) must match legacy total ({legacy_total}) closely"


def test_book_with_fx_asset_total_still_matches_legacy():
    """Catches the 'capital=0.0 trap': a book with FX must still reconcile
    against the legacy total once BookPnL.other is included — using ONLY
    capital_gain+carry (ignoring `other`) would silently drop all FX P&L."""
    market_data = _market_data_or_skip()
    start, end = _date_range()

    assets = ['CN10Y', 'USDCNY']
    idx = pd.bdate_range(start, end)
    notional_daily = pd.DataFrame(1_000_000.0, index=idx, columns=assets)

    pnl = compute_book_pnl(notional_daily, market_data, start, end)

    # capital_gain+carry ALONE must NOT match legacy (proves FX P&L is
    # excluded from that pair, i.e. the trap is real) ...
    partial_total = (pnl.capital_gain + pnl.carry).sum().sum()
    legacy = _legacy_total_pnl(notional_daily, market_data, start, end)
    legacy_total = legacy.sum().sum()
    assert abs(partial_total - legacy_total) > 1.0, \
        "capital_gain+carry alone should NOT already equal legacy total once FX is in the book"

    # ... but BookPnL.total (which includes `other`) DOES match.
    full_total = pnl.total.sum().sum()
    rel_diff = abs(full_total - legacy_total) / abs(legacy_total)
    assert rel_diff < 1e-6, f"full total ({full_total}) must match legacy total ({legacy_total})"

    # And the FX asset's own P&L must be entirely in `other`, none in
    # capital_gain/carry.
    assert (pnl.capital_gain['USDCNY'] == 0.0).all()
    assert not (pnl.other['USDCNY'] == 0.0).all(), "USDCNY's P&L should show up in `other`"


def test_commodity_asset_pnl_lands_entirely_in_other():
    market_data = _market_data_or_skip()
    start, end = _date_range()
    idx = pd.bdate_range(start, end)
    notional_daily = pd.DataFrame(1_000_000.0, index=idx, columns=['Gold'])

    pnl = compute_book_pnl(notional_daily, market_data, start, end)
    assert (pnl.capital_gain['Gold'] == 0.0).all()
    assert (pnl.carry['Gold'] == 0.0).all()
    assert not (pnl.other['Gold'] == 0.0).all()


def test_book_pnl_cash_defaults_to_zero_series():
    market_data = _market_data_or_skip()
    start, end = _date_range(years=1)
    idx = pd.bdate_range(start, end)
    notional_daily = pd.DataFrame(0.0, index=idx, columns=['CN10Y'])
    pnl = compute_book_pnl(notional_daily, market_data, start, end)
    assert (pnl.cash == 0.0).all()
    assert list(pnl.cash.index) == list(idx)
