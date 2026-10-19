# -*- coding: utf-8 -*-
"""Return and risk attribution for the Beta-book backtest.

Why this exists (docs/plans/factor_model_improvement.md §6, P0): the backtest's
reported ``annualized_return`` is the geometric CAGR of NAV = capital + cumulative
P&L, while positions are sized off *initial* capital. It therefore sits below the
simple annual P&L rate, and it mixes price, carry and cash income. Sizing decisions
(and "what is the book actually exposed to?") need the pieces separately.

Everything here is a pure function of already-computed backtest frames, so it adds
no behaviour change to the backtest itself.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

import numpy as np
import pandas as pd


def _pct(x: float) -> float:
    return float(x) * 100.0


def attribute_book_return(
    book_pnl,
    alloc_daily: pd.DataFrame,
    cash_daily_cny: pd.Series,
    tx_cost_cny: Optional[pd.Series],
    total_capital_cny: float,
    reported_ann_return: float,
    asset_class_of: Callable[[str], str],
) -> Dict:
    """Split the backtest into simple annual contributions and per-class risk.

    Parameters
    ----------
    book_pnl : BookPnL
        ``capital_gain`` / ``carry`` / ``other`` frames (date x asset, CNY).
    alloc_daily : DataFrame
        Daily signed notional per asset (CNY) — gross for the usage figures.
    cash_daily_cny : Series
        Daily return on undeployed capital (CNY), already part of reported P&L.
    tx_cost_cny : Series or None
        Daily transaction cost (CNY). NOT in the reported annualized return.
    total_capital_cny : float
        Initial capital; every ratio below is a fraction of it.
    reported_ann_return : float
        The backtest's own ``annualized_return`` (decimal, geometric CAGR).
    asset_class_of : callable
        asset name -> class label (e.g. ``multiasset.data.get_asset_type``).

    Returns
    -------
    dict with
      ``simple_annual_pct``: price / carry / cash / gross_total / tx_cost / net_total,
          each the mean annual P&L as % of initial capital (arithmetic, 252d);
      ``reported_cagr_pct`` and ``compounding_drag_pct`` (= reported - gross_total,
          the part of the gap that is pure geometric-vs-simple arithmetic);
      ``by_class``: per asset class price_ann_pct, carry_ann_pct, price_vol_pct,
          risk_share_pct (covariance share of price-P&L variance; sums to 100),
          avg_gross_pct;
      ``book``: price vol, max drawdown of cumulative price P&L, price Sharpe.
    """
    idx = alloc_daily.index
    n_years = max(len(idx) / 252.0, 1e-9)
    cap = float(total_capital_cny)

    price = book_pnl.capital_gain.add(book_pnl.other, fill_value=0.0).reindex(idx).fillna(0.0)
    carry = book_pnl.carry.reindex(idx).fillna(0.0)
    cash = cash_daily_cny.reindex(idx).fillna(0.0)
    tx = (tx_cost_cny.reindex(idx).fillna(0.0) if tx_cost_cny is not None
          else pd.Series(0.0, index=idx))

    price_tot, carry_tot = price.sum(axis=1), carry.sum(axis=1)
    ann = lambda s: _pct(s.sum() / cap / n_years)       # noqa: E731
    gross_total = ann(price_tot) + ann(carry_tot) + ann(cash)
    simple = {
        'price': ann(price_tot), 'carry': ann(carry_tot), 'cash': ann(cash),
        'gross_total': gross_total, 'tx_cost': -ann(tx),
        'net_total': gross_total - ann(tx),
    }

    # Per-class price P&L, carry and covariance risk share.
    classes = {a: asset_class_of(a) for a in price.columns}
    price_c = price.T.groupby(classes).sum().T / cap
    carry_c = carry.T.groupby(classes).sum().T / cap
    book_price = price_c.sum(axis=1)
    var = float(book_price.var())
    by_class = {}
    for c in price_c.columns:
        members = [a for a in alloc_daily.columns if classes.get(a) == c]
        by_class[c] = {
            'price_ann_pct': _pct(price_c[c].sum() / n_years),
            'carry_ann_pct': _pct(carry_c[c].sum() / n_years) if c in carry_c else 0.0,
            'price_vol_pct': _pct(price_c[c].std() * np.sqrt(252)),
            'risk_share_pct': (100.0 * float(price_c[c].cov(book_price)) / var) if var > 0 else 0.0,
            'avg_gross_pct': _pct(alloc_daily[members].abs().sum(axis=1).mean() / cap) if members else 0.0,
        }

    cum = book_price.cumsum()
    vol = float(book_price.std() * np.sqrt(252))
    return {
        'simple_annual_pct': simple,
        'reported_cagr_pct': _pct(reported_ann_return),
        'compounding_drag_pct': _pct(reported_ann_return) - gross_total,
        'by_class': by_class,
        'book': {
            'price_vol_pct': _pct(vol),
            'price_max_drawdown_pct': _pct((cum - cum.cummax()).min()),
            'price_sharpe': float(book_price.mean() * 252 / vol) if vol > 0 else float('nan'),
        },
    }
