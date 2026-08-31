# -*- coding: utf-8 -*-
"""Shared performance metrics for the Alpha backtest engines.

The engines historically reported a *per-trade* Sharpe scaled by
``sqrt(min(n_trades, 20))``.  That number is not comparable to a conventional
Sharpe ratio and, because of the ``min(..., 20)`` cap, saturates once a
backtest has 20 trades -- beyond that point additional good trades cannot
improve it, so it is actively misleading as a tuning objective (a change that
raises the trade count is credited with nothing).

``annualized_sharpe`` computes the standard quantity instead: the mean of the
daily P&L series over its standard deviation, scaled by ``sqrt(252)``.  It is
driven by the daily equity curve rather than by trade records, so flat days
between trades correctly count as zero-return days.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252


def annualized_sharpe(equity_ts: Optional[pd.Series]) -> float:
    """Annualized Sharpe of a daily cumulative-P&L (equity) series, in bp.

    ``equity_ts`` is cumulative, so it is differenced to daily P&L first.
    Returns 0.0 when the series is too short or has no variance.
    """
    if equity_ts is None or not isinstance(equity_ts, pd.Series) or equity_ts.empty:
        return 0.0
    daily = pd.to_numeric(equity_ts, errors='coerce').diff().dropna()
    if len(daily) < 2:
        return 0.0
    sd = float(daily.std())
    if not np.isfinite(sd) or sd <= 0:
        return 0.0
    return float(daily.mean() / sd * np.sqrt(TRADING_DAYS_PER_YEAR))


def per_trade_sharpe(pnls: np.ndarray, n_trades: int) -> float:
    """Legacy per-trade Sharpe, capped at ``sqrt(20)``.

    Retained so existing artifacts/consumers keep a stable value under the
    ``sharpe_per_trade`` key; prefer :func:`annualized_sharpe` for any new use.
    """
    pnls = np.asarray(pnls, dtype=float)
    if pnls.size == 0:
        return 0.0
    sd = float(np.nanstd(pnls))
    if not np.isfinite(sd) or sd <= 0:
        return 0.0
    return float(np.nanmean(pnls) / sd * np.sqrt(min(int(n_trades), 20)))
