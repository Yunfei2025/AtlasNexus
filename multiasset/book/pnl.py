# -*- coding: utf-8 -*-
"""Capital-gain vs carry P&L split, computed on real per-tenor notional.

See docs/plans/beta_book_exposure_vs_capital.md Step 5. Reuses
calculate_daily_returns_series (multiasset/data.py) exactly as it already
exists — that function's bond path already returns a clean
carry + capital == total decomposition (data.py:479-511); this module does
not re-derive the duration/carry formulas, it multiplies the per-unit-
notional decomposition already computed there by the actual daily notional
held (see multiasset/book/sizing.py for how that notional is produced).

capital_gain[d, a] = notional[d, a] * capital[d, a]   # == DV01 x dy already
carry[d, a]        = notional[d, a] * carry[d, a]     # == y/365 already, current-day yield

FX / FX-cross / commodities do NOT have this clean split (calculate_daily_
returns_series hardcodes their 'capital' column to 0.0 while the whole
price return lives in 'total' — see returns_split_is_exact) — those assets'
P&L goes entirely into BookPnL.other, never into capital_gain/carry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import pandas as pd

from multiasset.data import calculate_daily_returns_series, get_asset_yield_series


def returns_split_is_exact(asset_name: str, market_data) -> bool:
    """True when calculate_daily_returns_series's carry+capital columns sum
    exactly to 'total' for this asset (the bond/IRS-spread/credit path —
    data.py:479-511) — False for FX, FX-cross and commodities, where
    'capital' is hardcoded 0.0 and the whole price return lives in 'total'
    (data.py:513-552, 362-433 for the FX-cross helper).

    Uses get_asset_yield_series's own `is_bond` flag (its 4th return value)
    rather than re-deriving the same classification from get_asset_type —
    that flag is what calculate_daily_returns_series itself branches on
    (data.py:479 `if is_bond:`), including Spread/IRS and Credit assets,
    which get_asset_type alone would not tell you carry the same 'is_bond'
    treatment (they're their own get_asset_type categories, 'Spread' and
    'Credit', but go through the identical carry+capital bond math).

    The one caveat: a bond whose country implies FX-hedging (a foreign bond
    — data.py:497 `if country and country != 'CN':`) still has its exact
    carry+capital==total property; the FX HEDGE leg is recorded separately
    in 'fx' and deliberately excluded from 'total' (data.py:493-497), so
    this function still returns True for foreign bonds — 'fx' isn't part
    of the split this module cares about (capital_gain vs carry), it's a
    third, always-hedged-out component.
    """
    try:
        _series, _duration, _country, is_bond = get_asset_yield_series(asset_name, market_data)
    except Exception:
        return False
    return bool(is_bond)


@dataclass
class BookPnL:
    """Per-asset, per-day P&L, split into components with a well-defined
    economic meaning. All three DataFrames share the same (date x asset)
    shape; an asset with no valid return data for a given day is 0.0 in
    every column for that day, not NaN (matches calculate_daily_returns_series's
    own convention downstream once combined with notional).

    capital_gain: DV01 x dyield, in CNY (bonds/IRS/credit only; 0 for FX/commodity)
    carry:        notional x yield/365, in CNY (bonds/IRS/credit only; 0 for FX/commodity)
    other:        notional x 'total', in CNY, for assets where
                  returns_split_is_exact() is False (FX/FX-cross/commodity) —
                  their entire P&L, unsplit, since calculate_daily_returns_series
                  doesn't give a capital/carry decomposition for them.
    cash:         daily CNY return on UNDEPLOYED capital (Step 6,
                  multiasset.book.funding.cash_return_daily) — a Series,
                  not per-asset, since cash isn't held in any one asset.
                  Defaults to an all-zero Series; callers that don't yet
                  compute a capital-utilisation buffer (before Step 7) leave
                  this at its default.
    """
    capital_gain: pd.DataFrame
    carry: pd.DataFrame
    other: pd.DataFrame
    cash: pd.Series

    @property
    def total(self) -> pd.DataFrame:
        """capital_gain + carry + other, per asset per day (NOT including
        cash — cash is a book-level scalar per day, not a per-asset column;
        add BookPnL.cash separately when computing the book's total daily
        P&L, e.g. `pnl.total.sum(axis=1) + pnl.cash`)."""
        return self.capital_gain.add(self.carry, fill_value=0.0).add(self.other, fill_value=0.0)


def compute_book_pnl(
    notional_daily: pd.DataFrame,
    market_data,
    start_date,
    end_date,
) -> BookPnL:
    """Per-asset, per-day capital-gain/carry/other split, in the same CNY
    units as notional_daily (typically actual CNY, not millions — divide
    by 1e6 downstream for display, matching the existing convention in
    web/tabs/beta/callbacks/backtest_hist/_pnl.py).

    Reads each asset's calculate_daily_returns_series ONCE (today's callers
    — backtest_hist.py's old alloc_daily*rets_matrix, dashboard.py,
    report_export.py — all read only ['total']; this reads ['carry'],
    ['capital'] and ['total'] together) and keeps whichever columns each
    asset's classification (returns_split_is_exact) says are meaningful.
    """
    assets = list(notional_daily.columns)
    daily_idx = notional_daily.index

    capital_series: Dict[str, pd.Series] = {}
    carry_series: Dict[str, pd.Series] = {}
    other_series: Dict[str, pd.Series] = {}

    for name in assets:
        ret_df = calculate_daily_returns_series(name, market_data, start_date, end_date)
        if ret_df.empty:
            continue
        ret_df = ret_df.set_index('Date')
        if not isinstance(ret_df.index, pd.DatetimeIndex):
            ret_df.index = pd.to_datetime(ret_df.index)

        if returns_split_is_exact(name, market_data):
            capital_series[name] = ret_df['capital'].reindex(daily_idx)
            carry_series[name] = ret_df['carry'].reindex(daily_idx)
        else:
            other_series[name] = ret_df['total'].reindex(daily_idx)

    capital_ret = pd.DataFrame(capital_series, index=daily_idx).reindex(columns=assets).fillna(0.0)
    carry_ret = pd.DataFrame(carry_series, index=daily_idx).reindex(columns=assets).fillna(0.0)
    other_ret = pd.DataFrame(other_series, index=daily_idx).reindex(columns=assets).fillna(0.0)

    notional_aligned = notional_daily.reindex(columns=assets).fillna(0.0)

    return BookPnL(
        capital_gain=notional_aligned * capital_ret,
        carry=notional_aligned * carry_ret,
        other=notional_aligned * other_ret,
        cash=pd.Series(0.0, index=daily_idx),
    )


def aggregate_for_display(pnl: BookPnL, domicile_of: Dict[str, str],
                          type_of: Dict[str, str]) -> pd.DataFrame:
    """Aggregate BookPnL's per-asset daily total P&L to (domicile, type) —
    e.g. ('CN', 'Rates'), ('CDB', 'Credit') — for DISPLAY only. All sizing,
    carry, funding and metrics computation elsewhere in the book stays on
    the per-tenor frames; this is purely a reporting convenience so a UI
    table can show "how much did the CN book earn" without forcing the
    underlying carry math to ever be computed at anything coarser than the
    per-tenor level (see docs/plans/beta_book_exposure_vs_capital.md
    section 3 on why the tenor MIX must stay granular even though it's
    fine to freeze the mix for a month at the sizing step — display
    aggregation is a different, purely cosmetic axis of coarsening).

    domicile_of / type_of: asset_name -> label (e.g. from FACTOR_TO_ASSET_MAP
    or get_universe/get_asset_type); assets missing from either mapping are
    grouped under ('Unknown', 'Unknown').
    """
    total = pnl.total
    group_key = pd.Series(
        {name: (domicile_of.get(name, 'Unknown'), type_of.get(name, 'Unknown'))
         for name in total.columns},
    )
    grouped = total.T.groupby(group_key).sum().T
    grouped.columns = pd.MultiIndex.from_tuples(grouped.columns, names=['domicile', 'type'])
    return grouped
