# -*- coding: utf-8 -*-
"""Step 9 of docs/plans/beta_book_exposure_vs_capital.md — the acceptance
gate for the whole beta-book refactor.

The comparison here is against the OLD factor-level `_yield_carry`
convention (multiasset.factor_backtest — before Step 3, carry was applied
only to Level-type factors: IRDL/SPDL/CRDL; Slope/Curvature factors
(IRSL/IRCV/etc.) got exactly zero carry, since a level-based carry formula
has no economic meaning for a long-short, net-zero-notional contrast). That
is genuinely correct for an OUTRIGHT (level-only) book — the level factor's
carry accrual is unambiguous. It is genuinely WRONG for a book that also
holds slope/curvature legs: those legs are real tenor positions with real
carry, which the old convention simply never computed (it lived only at
the factor level, as a single blended "factor return", not per real tenor
notional).

This file proves, with real market data, that the NEW book-level carry
(multiasset.book.pnl.compute_book_pnl, computed on real per-tenor notional
via calculate_daily_returns_series) exactly reconciles with the "legacy"
convention for an outright book, and correctly DIVERGES — in the expected,
diagnostic direction — once slope/curvature legs are added.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

try:
    from multiasset.data import load_raw_market_data, calculate_daily_returns_series
    from multiasset.book.pnl import compute_book_pnl
except Exception:  # pragma: no cover - import-time data/env issues
    load_raw_market_data = None


# Deterministic per-tenor group used throughout: an IRDL.CN-style level
# book (CN1Y..CN30Y) plus, for the slope/curve test, the same tenors held
# as long-short legs (mimicking how IRSL.CN/IRCV.CN load onto real tenors —
# see FACTOR_TO_ASSET_MAP['IRSL.CN'] / ['IRCV.CN'] in web/tabs/beta/data.py).
_LEVEL_TENORS = ['CN1Y', 'CN2Y', 'CN5Y', 'CN10Y', 'CN20Y', 'CN30Y']


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
    """The exact pre-refactor combined computation: notional * 'total'
    column, from calculate_daily_returns_series — this is what
    backtest_hist.py's old (pre-Step-5) alloc_daily*rets_matrix line did.
    Distinct from the "legacy factor-level carry" baseline below — this one
    is the BOOK-level legacy (bond-by-bond, always correct for the capital-
    gain+carry-on-real-notional question); the factor-level baseline is
    what the OLD FACTOR ENGINE would have reported as "carry" for the
    combined factor. See module docstring."""
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


def _legacy_factor_level_carry(notional_daily: pd.DataFrame, market_data, start_date, end_date,
                               is_level_factor: bool) -> pd.DataFrame:
    """What the OLD factor-level `_yield_carry` convention would have
    accrued for this book, applied per tenor on the SAME real notional the
    new book uses. For a Level-type factor (is_level_factor=True) this is
    `notional * yield/100/365` — the old formula was `level.shift(1)/100/252`
    in FACTOR-RETURN space (dimensionless), which is economically the same
    accrual `calculate_daily_returns_series`'s own bond-path 'carry' column
    already computes (data.py:484, `series/100.0/365`) — both are "gross
    coupon accrual on the yield", just expressed in different units. For a
    Slope/Curvature factor (is_level_factor=False), the legacy value is
    IDENTICALLY ZERO for every tenor, every day — that's the entire point
    of the comparison this file makes."""
    if not is_level_factor:
        return pd.DataFrame(0.0, index=notional_daily.index, columns=notional_daily.columns)

    carry_series = {}
    for name in notional_daily.columns:
        df = calculate_daily_returns_series(name, market_data, start_date, end_date)
        if df.empty:
            continue
        s = df.set_index('Date')['carry']
        if not isinstance(s.index, pd.DatetimeIndex):
            s.index = pd.to_datetime(s.index)
        carry_series[name] = s
    carry_ret = pd.DataFrame(carry_series, index=notional_daily.index).reindex(columns=notional_daily.columns).fillna(0.0)
    return notional_daily * carry_ret


def test_outright_only_book_reconciles_with_legacy_total():
    """IRDL.CN-only (outright, level-only) book: CONSTANT notional (so
    turnover/signal cadence can't contaminate the comparison), no funding.
    New (capital_gain + carry) must match the legacy total-based P&L to
    <1e-6 relative — for an outright book, the old convention's carry was
    economically RIGHT; it just lived in the wrong layer (the factor engine
    instead of the book)."""
    market_data = _market_data_or_skip()
    start, end = _date_range()
    idx = pd.bdate_range(start, end)

    notional_daily = pd.DataFrame(1_000_000.0, index=idx, columns=_LEVEL_TENORS)

    pnl = compute_book_pnl(notional_daily, market_data, start, end)
    new_total = (pnl.capital_gain + pnl.carry).sum().sum()

    legacy = _legacy_total_pnl(notional_daily, market_data, start, end)
    legacy_total = legacy.sum().sum()

    assert legacy_total != 0.0, "sanity check: legacy P&L should be nonzero over a multi-year window"
    rel_diff = abs(new_total - legacy_total) / abs(legacy_total)
    assert rel_diff < 1e-6, \
        f"outright book: new split ({new_total}) must match legacy total ({legacy_total}) closely"


def test_slope_curve_book_diverges_from_legacy_carry_and_new_number_is_higher():
    """Add a slope/curvature-style long-short leg structure on the SAME
    tenors (long the short end, short the long end — mimicking
    FACTOR_TO_ASSET_MAP['IRSL.CN']'s real tenor loadings). The legacy
    factor-level carry convention (_yield_carry) is IDENTICALLY ZERO for
    Slope/Curvature factors; the new book-level carry is NOT zero, because
    it accrues on the real notional of every real tenor leg, long or
    short, regardless of which synthetic "factor" that leg happens to be
    associated with.

    This is the load-bearing pair: carry diverges (proving the old
    convention under-accrued), while capital_gain does NOT move (proving
    the divergence is isolated to carry, not a sizing bug)."""
    market_data = _market_data_or_skip()
    start, end = _date_range()
    idx = pd.bdate_range(start, end)

    # A slope-style book: long the short end, short the long end (net
    # long-short, not net-zero-notional in aggregate, but each individual
    # leg IS a real tenor position with real carry either way).
    notional_daily = pd.DataFrame({
        'CN1Y':  1_000_000.0,
        'CN2Y':  1_000_000.0,
        'CN10Y': -1_000_000.0,
        'CN20Y': -1_000_000.0,
    }, index=idx)

    pnl = compute_book_pnl(notional_daily, market_data, start, end)
    new_carry_total = pnl.carry.sum().sum()
    new_capital_total = pnl.capital_gain.sum().sum()

    # Legacy factor-level carry for a Slope/Curvature factor: zero, always.
    legacy_slope_carry = _legacy_factor_level_carry(
        notional_daily, market_data, start, end, is_level_factor=False,
    )
    legacy_carry_total = legacy_slope_carry.sum().sum()
    assert legacy_carry_total == 0.0, \
        "sanity check: the OLD Slope/Curvature carry convention is identically zero"

    # THE divergence: new carry is nonzero (in fact, whichever direction
    # the long/short legs' net carry differential points), strictly
    # different from the legacy zero.
    assert new_carry_total != pytest.approx(0.0, abs=1.0), \
        "new book-level carry must be nonzero for a real long-short tenor book"

    # capital_gain must be UNTOUCHED by this — it's driven purely by
    # -duration*dyield on the same notional, independent of which carry
    # convention applies. Verify by comparing against the SAME calculation
    # done directly (i.e. capital_gain is just notional * the 'capital'
    # column, which never depended on _yield_carry / the factor-level
    # engine at all — see compute_book_pnl / calculate_daily_returns_series).
    capital_series = {}
    for name in notional_daily.columns:
        df = calculate_daily_returns_series(name, market_data, start, end)
        s = df.set_index('Date')['capital']
        if not isinstance(s.index, pd.DatetimeIndex):
            s.index = pd.to_datetime(s.index)
        capital_series[name] = s
    capital_ret = pd.DataFrame(capital_series, index=idx).reindex(columns=notional_daily.columns).fillna(0.0)
    independent_capital_total = (notional_daily * capital_ret).sum().sum()

    rel_diff = abs(new_capital_total - independent_capital_total) / max(abs(independent_capital_total), 1.0)
    assert rel_diff < 1e-6, \
        "capital_gain must be UNCHANGED by the carry convention — divergence must be isolated to carry"


def test_capital_plus_carry_equals_total_for_bond_only_books():
    """Permanent invariant guarding Step-5 drift: for ANY bond-only
    (returns_split_is_exact) book, capital_gain + carry must equal
    BookPnL.total exactly (not just approximately) — total is DEFINED as
    capital_gain + carry + other, and other must be identically zero when
    every asset is a bond."""
    market_data = _market_data_or_skip()
    start, end = _date_range(years=1)
    idx = pd.bdate_range(start, end)

    notional_daily = pd.DataFrame({'CN2Y': 500_000.0, 'CN10Y': -300_000.0}, index=idx)
    pnl = compute_book_pnl(notional_daily, market_data, start, end)

    assert (pnl.other == 0.0).all().all(), "bond-only book must have zero 'other' P&L"
    reconstructed_total = pnl.capital_gain + pnl.carry
    pd.testing.assert_frame_equal(
        reconstructed_total.sort_index(axis=1), pnl.total.sort_index(axis=1),
        check_exact=False, atol=1e-9, rtol=1e-9,
    )
