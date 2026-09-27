# -*- coding: utf-8 -*-
"""Per-domicile funding hurdle (for Sharpe only, never subtracted from
book P&L) and cash return on undeployed capital.

See docs/plans/beta_book_exposure_vs_capital.md Step 6. Two pieces:

1. book_funding_cost_daily: the cost of financing the notional actually
   held, per domicile's own funding/repo rate. This is NEVER netted into
   daily_pnl — it is passed as `funding_hurdle` into
   multiasset.factor_backtest.compute_metrics/compute_portfolio_metrics,
   which subtracts it only from the Sharpe numerator, leaving Ann. Vol and
   Ann. Return untouched (see that function's own docstring for why: an
   earlier attempt at netting funding directly into a low-vol return series
   could swing Sharpe by many points off a tiny vol denominator).

2. cash_return_daily: what UNDEPLOYED capital earns (decision #7 of the
   plan) — makes de-risking (Step 7's capital constraint allowing gross
   exposure below 95%) a fair comparison, since going to cash doesn't
   forfeit the risk-free return.
"""

from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from multiasset.factor_backtest import load_funding_rate
from multiasset.data import get_asset_yield_series

# get_asset_yield_series (multiasset/data.py) returns country='EU' for
# German ('DE Gov Bond') assets — data.py:231,608 — but
# _IRDL_FUNDING_RATE_MACRO_COL (multiasset/factor_backtest.py) keys 'DE'.
# Without this alias, Bund funding is silently zero: _load_funding_rate('EU')
# finds no entry in _IRDL_FUNDING_RATE_MACRO_COL and returns None. This is
# the ONE place that reconciles the two naming conventions — book_funding_
# cost_daily always routes through normalise_domicile before calling
# load_funding_rate.
_DOMICILE_ALIASES: Dict[str, str] = {'EU': 'DE'}

# The base-currency (CN) short-term rate, for cash_return_daily. Reuses the
# same _IRDL_FUNDING_RATE_MACRO_COL mapping that IRDL.CN's own funding cost
# uses, since undeployed CNY capital earns the same repo rate a CN book
# would be financed at.
_BASE_CURRENCY_DOMICILE = 'CN'


def build_domicile_of(asset_names, market_data) -> Dict[str, str]:
    """asset_name -> domicile code (already normalised, e.g. 'DE' not 'EU'),
    for every asset get_asset_yield_series can resolve a country for.
    FX/commodity/equity assets (country=None) and anything
    get_asset_yield_series can't resolve get '' — book_funding_cost_daily
    treats that as "no funding cost", which is correct for those classes.
    """
    domicile_of: Dict[str, str] = {}
    for name in asset_names:
        try:
            _series, _duration, country, _is_bond = get_asset_yield_series(name, market_data)
        except Exception:
            country = None
        domicile_of[name] = normalise_domicile(country) if country else ''
    return domicile_of


def normalise_domicile(code: str) -> str:
    """'EU' -> 'DE' (data.py's country code for German bonds vs
    factor_backtest.py's funding-rate-table key). Identity for every other
    code. Single reconciliation point — see module docstring."""
    return _DOMICILE_ALIASES.get(code, code)


def book_funding_cost_daily(
    notional_daily: pd.DataFrame,
    domicile_of: Dict[str, str],
) -> pd.Series:
    """Daily funding/repo cost of the book's notional, in the SAME CNY units
    as notional_daily (not yet divided by anything — divide by 1e6 for the
    same "millions" convention used elsewhere if needed).

        cost[d] = sum_a notional[d-1, a] * rate[normalise(domicile_a)][d-1] / 100 / 365

    /365 (not /252) to match the book's own carry convention
    (multiasset/data.py:484's `series / 100.0 / 365` for bond carry) — book
    P&L accrues on calendar days. This is DELIBERATELY different from
    multiasset.factor_backtest.funding_cost_series's /252, which matches
    the factor-level return convention (business days only). Both are
    correct for their own layer; don't "fix" one to match the other.

    Only assets whose domicile (after normalise_domicile) has an entry in
    _IRDL_FUNDING_RATE_MACRO_COL contribute a nonzero cost — anything else
    (FX, commodity, credit/spread assets with no sovereign-country
    domicile) contributes 0.0 for that asset, matching
    funding_cost_series's IRDL-only scoping at the factor level (see that
    function's docstring for why CRDL/etc. funding isn't assumed here
    either).

    Returns an all-zero Series (not raising) if notional_daily is empty or
    no asset has a resolvable domicile.
    """
    if notional_daily.empty:
        return pd.Series(dtype=float)

    daily_idx = notional_daily.index
    cost = pd.Series(0.0, index=daily_idx)

    rate_cache: Dict[str, Optional[pd.Series]] = {}
    for asset_name in notional_daily.columns:
        domicile = normalise_domicile(domicile_of.get(asset_name, ''))
        if domicile not in rate_cache:
            rate_cache[domicile] = load_funding_rate(domicile)
        rate = rate_cache[domicile]
        if rate is None:
            continue

        rate_aligned = rate.reindex(daily_idx).ffill()
        daily_rate = rate_aligned.shift(1) / 100.0 / 365.0
        notional_shifted = notional_daily[asset_name].shift(1).fillna(0.0)
        cost = cost.add((notional_shifted * daily_rate).fillna(0.0), fill_value=0.0)

    return cost


def cash_return_daily(
    notional_daily: pd.DataFrame,
    total_capital: float,
    max_utilisation: float = 0.95,
) -> pd.Series:
    """Daily CNY return earned on capital NOT deployed into any position —
    decision #7 of the plan: de-risking (holding less than max_utilisation
    of capital) should not forfeit the risk-free return, so undeployed
    capital earns the CN base-currency funding rate (FR007) rather than
    zero.

        cash[d] = (max_utilisation * total_capital - notional[d].abs().sum())
                  * FR007[d] / 100 / 365

    Floored at the max_utilisation*total_capital deployment ceiling, not at
    notional_daily's actual gross on a given day being possibly ABOVE that
    ceiling on a rare day before Step 7's capital constraint is applied —
    callers that haven't yet applied weights_to_notional's cap should treat
    a negative "cash" value here (gross exceeds the ceiling) as a signal
    that the capital constraint upstream needs revisiting, not as a real
    negative cash position.

    Uses .abs().sum() (gross exposure), not .sum() (net) — a long-short
    slope position that nets to ~0 CNY of directional exposure still ties
    up capital on both legs' notional, none of which is "cash". Returns an
    all-zero Series if the funding rate is unavailable (never raises).
    """
    if notional_daily.empty:
        return pd.Series(dtype=float)

    rate = load_funding_rate(_BASE_CURRENCY_DOMICILE)
    if rate is None:
        return pd.Series(0.0, index=notional_daily.index)

    daily_idx = notional_daily.index
    rate_aligned = rate.reindex(daily_idx).ffill()
    daily_rate = rate_aligned.shift(1) / 100.0 / 365.0

    gross_deployed = notional_daily.abs().sum(axis=1).shift(1).fillna(0.0)
    cash_balance = max_utilisation * total_capital - gross_deployed

    return (cash_balance * daily_rate).fillna(0.0)
