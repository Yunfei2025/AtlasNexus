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
from multiasset.data import get_asset_yield_series, calendar_gap_days

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
    gap = calendar_gap_days(daily_idx).to_numpy()      # calendar days since the previous row

    rate_cache: Dict[str, Optional[pd.Series]] = {}
    for asset_name in notional_daily.columns:
        domicile = normalise_domicile(domicile_of.get(asset_name, ''))
        if domicile not in rate_cache:
            rate_cache[domicile] = load_funding_rate(domicile)
        rate = rate_cache[domicile]
        if rate is None:
            continue

        rate_aligned = rate.reindex(daily_idx).ffill()
        daily_rate = rate_aligned.shift(1) / 100.0 / 365.0 * gap
        notional_shifted = notional_daily[asset_name].shift(1).fillna(0.0)
        cost = cost.add((notional_shifted * daily_rate).fillna(0.0), fill_value=0.0)

    return cost


_BOND_CLASSES = ('Rates', 'Credit', 'Spread')


def cash_return_daily(
    notional_daily: pd.DataFrame,
    total_capital: float,
    margin: Optional[pd.Series] = None,
    asset_type_of=None,
    max_utilisation: Optional[float] = None,
) -> pd.Series:
    """Daily CNY interest on the cash the book actually holds, at the CN base rate (FR007).

        cash[d] = (C - L - S_other - margin + S_bond)[d-1] * FR007[d-1] / 100 / 365 * gap[d]

    with C total capital, L the long notional, S_bond the short notional of bond-class
    assets (government, credit, swap-spread) and S_other the short notional of every other
    asset (FX, commodity, equity). Accrual is per CALENDAR day (``gap`` = days since the
    previous row).

    * The 5% utilisation buffer is cash like any other: it earns FR007. The cap
      (``RiskModelConfig.CAPITAL_UTILISATION_MAX``) limits what may be DEPLOYED, not what
      cash earns. ``max_utilisation`` is accepted for backwards compatibility and ignored.
    * A short bond is a reverse repo plus a sale: the sale proceeds fund the repo
      lending, so net cash is unchanged and the book earns the repo rate on the short
      notional (user decision 2026-10-17: "earn FR007 in P&L, shorts counted at full
      notional" - the CAP still counts them in full, see multiasset.book.capital).
    * Other shorts (FX, commodity) have no proceeds interest; they use cash only at
      ``RiskModelConfig.SHORT_CAPITAL_RATE`` (0 by default: a short consumes no capital).
    * ``margin`` (derivative initial margin, CNY) is cash tied up at the broker and earns
      nothing.

    Returns an all-zero Series if the funding rate is unavailable (never raises).
    """
    if notional_daily.empty:
        return pd.Series(dtype=float)

    rate = load_funding_rate(_BASE_CURRENCY_DOMICILE)
    if rate is None:
        return pd.Series(0.0, index=notional_daily.index)

    if asset_type_of is None:
        from multiasset.data import get_asset_type as asset_type_of
    bond_cols = [c for c in notional_daily.columns if asset_type_of(c) in _BOND_CLASSES]
    other_cols = [c for c in notional_daily.columns if c not in bond_cols]

    daily_idx = notional_daily.index
    longs = notional_daily.clip(lower=0.0).sum(axis=1)
    short_bond = notional_daily[bond_cols].clip(upper=0.0).abs().sum(axis=1) if bond_cols else 0.0
    short_other = notional_daily[other_cols].clip(upper=0.0).abs().sum(axis=1) if other_cols else 0.0
    mrg = margin.reindex(daily_idx).fillna(0.0) if margin is not None else 0.0

    from multiasset.config import RiskModelConfig
    cash_balance = (total_capital - longs - RiskModelConfig.SHORT_CAPITAL_RATE * short_other
                    - mrg + short_bond).shift(1)
    rate_aligned = rate.reindex(daily_idx).ffill()
    daily_rate = rate_aligned.shift(1) / 100.0 / 365.0 * calendar_gap_days(daily_idx).to_numpy()
    return (cash_balance * daily_rate).fillna(0.0)


def benchmark_hurdle_daily(
    notional_daily: pd.DataFrame,
    domicile_of: Dict[str, str],
    total_capital: float,
) -> pd.Series:
    """Daily CNY cash benchmark a book must beat, for the post-funding Sharpe numerator.

        hurdle[d] = [ C * FR007 + sum_foreign N[d-1, a] * (r_dom(a) - FR007) ][d-1] / 100 / 365 * gap[d]

    The first term is what the same capital earns in cash. The second is the FX-hedge
    carry of a foreign bond: hedged to CNY it earns (foreign yield - foreign overnight
    rate), not the full yield, so foreign notional is charged (foreign rate - FR007) on top
    of the CNY cash rate (long positive, short negative; zero for CN and for assets
    without a foreign domicile). With this hurdle a book that earns exactly the cash rate
    on everything - whatever its deployment, long or short - scores zero excess return;
    the old hurdle charged FR007 only on deployed notional while P&L also contained the
    FR007 earned on idle cash, so an idle book looked profitable and every deployed CNY
    paid FR007 twice (docs/plans/factor_model_improvement.md 3.14).
    """
    daily_idx = notional_daily.index
    if notional_daily.empty:
        return pd.Series(dtype=float)
    base = load_funding_rate(_BASE_CURRENCY_DOMICILE)
    if base is None:
        return pd.Series(0.0, index=daily_idx)
    base_a = base.reindex(daily_idx).ffill()
    gap = calendar_gap_days(daily_idx).to_numpy()
    hurdle = total_capital * base_a.shift(1) / 100.0 / 365.0 * gap

    for asset_name in notional_daily.columns:
        dom = normalise_domicile(domicile_of.get(asset_name, ''))
        if not dom or dom == _BASE_CURRENCY_DOMICILE:
            continue
        r = load_funding_rate(dom)
        if r is None:
            continue
        spread = (r.reindex(daily_idx).ffill() - base_a).shift(1) / 100.0 / 365.0 * gap
        hurdle = hurdle.add((notional_daily[asset_name].shift(1) * spread).fillna(0.0), fill_value=0.0)
    return hurdle.fillna(0.0)


def short_bond_borrow_cost_daily(
    notional_daily: pd.DataFrame,
    market_data,
    fee_bp: Optional[Dict[str, Dict[float, float]]] = None,
):
    """Daily borrow fee (CNY) on SHORT cash-bond notional, per asset and in total.

        cost[d, a] = |min(notional[d-1, a], 0)| * bp(country_a, tenor_a) / 1e4 / 365 * gap[d]

    ``fee_bp`` is ``{market: {tenor_years: bp}}`` (default
    ``RiskModelConfig.SHORT_BOND_BORROW_COST_BP``); a bond whose market/tenor is not
    listed pays nothing. Only government-bond ('Rates') assets are charged. Unlike the
    funding HURDLE this is a real cash cost: the backtest nets it into P&L.

    Returns ``(total: Series, by_asset: DataFrame, bp_by_asset: dict)``.
    """
    from multiasset.config import RiskModelConfig
    from multiasset.data import get_asset_type, get_asset_yield_series
    fee_bp = RiskModelConfig.SHORT_BOND_BORROW_COST_BP if fee_bp is None else fee_bp
    cols, bps = {}, {}
    gap = calendar_gap_days(notional_daily.index).to_numpy()
    for a in notional_daily.columns:
        if get_asset_type(a) != 'Rates':
            continue
        try:
            _s, n, country, _b = get_asset_yield_series(a, market_data)
        except Exception:
            continue
        bp = float(fee_bp.get(normalise_domicile(country or ''), {}).get(float(n), 0.0)) if n else 0.0
        if bp <= 0:
            continue
        bps[a] = bp
        short = notional_daily[a].clip(upper=0.0).abs().shift(1).fillna(0.0)
        cols[a] = short * bp / 1e4 / 365.0 * gap
    by_asset = pd.DataFrame(cols, index=notional_daily.index)
    total = by_asset.sum(axis=1) if cols else pd.Series(0.0, index=notional_daily.index)
    return total, by_asset, bps


def hurdle_rate_on_nav(hurdle_cny: pd.Series, nav_cny: pd.Series) -> pd.Series:
    """The cash-benchmark hurdle as a RATE on the same base the strategy return uses.

    ``compute_portfolio_metrics`` measures returns as ``nav.pct_change()``, i.e. day-t P&L over
    day t-1 NAV, and NAV compounds (about +12% over a 10-year, 3%-a-year book). A hurdle
    divided by INITIAL capital is therefore too large relative to those returns, by about
    ``hurdle x NAV growth`` (~0.3 pt/yr at a 2.3% cash rate). Dividing by the previous NAV
    makes ``return - hurdle`` an exact daily excess return. ``hurdle_cny`` and ``nav_cny``
    must share an index.
    """
    return (hurdle_cny / nav_cny.shift(1)).replace([float('inf'), float('-inf')], float('nan'))
