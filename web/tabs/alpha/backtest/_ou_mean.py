# -*- coding: utf-8 -*-
"""OU-mean anchor helper shared by both MR backtest engines.

``curves.calibration.stat.OU_calibrate`` fits its ADF test and OU long-run
mean on a trailing ``GeneralConfig.STAT_WINDOW``-month window, refit fresh
every EOD run — it is a *current-regime* estimate, not a claim about what the
spread's fair value was years ago. Applying that single static mean as the
backtest's fair-value anchor across a spread's entire multi-year history
implicitly assumes today's regime also held years ago, which can silently
turn a mild mean-reversion signal into a very different, far more active one
for any spread that has trended over its full sample (see docs/report
04_pairs_spread.tex, section on OU-mean consistency, for the CGB-5s10s
example that exposed this).

``blended_mr_mean`` avoids that by using the OU mean only for the trailing
window it was actually calibrated over, and falling back to the plain
rolling(120) mean — the same anchor already used for non-stationary spreads —
for everything older.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from settings.general import GeneralConfig

MR_LOOKBACK = 120


def blended_mr_mean(
    spread_ts: pd.Series,
    ou_mean: Optional[float],
    lookback: int = MR_LOOKBACK,
    ou_window_months: int = GeneralConfig.STAT_WINDOW,
) -> pd.Series:
    """Rolling(lookback) mean, overridden by ``ou_mean`` for the trailing
    ``ou_window_months`` months only. Returns the plain rolling mean unchanged
    when ``ou_mean`` is None/NaN (non-stationary or unavailable)."""
    rolling_mean = spread_ts.rolling(lookback).mean()
    if ou_mean is None or not np.isfinite(ou_mean):
        return rolling_mean

    index = pd.to_datetime(spread_ts.index)
    cutoff = index[-1] - pd.DateOffset(months=int(ou_window_months))
    blended = rolling_mean.copy()
    blended.loc[index >= cutoff] = float(ou_mean)
    return blended
