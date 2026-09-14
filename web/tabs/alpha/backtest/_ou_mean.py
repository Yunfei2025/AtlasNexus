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

The switch between the two anchors is linearly tapered over
``MR_TRANSITION_DAYS`` trading days rather than applied on a single day: a
hard cutover creates a one-day jump in the mean whenever the rolling(120)
mean has drifted from the current OU estimate (routine for any spread that
trended over the past year), and since the EWMA vol in the z-score
denominator does not move on that same day, the jump alone can produce a
z-score spike of 10+ with no change in the underlying spread (see
CGB-10s20s30s / CGB-5s10s20s, Sep 2025). Tapering spreads that jump across
``MR_TRANSITION_DAYS`` so it shows up as a slope in the fair-value line
instead of a single-day discontinuity in the z-score.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from settings.general import GeneralConfig

MR_LOOKBACK = 120
MR_TRANSITION_DAYS = 20


def blended_mr_mean(
    spread_ts: pd.Series,
    ou_mean: Optional[float],
    lookback: int = MR_LOOKBACK,
    ou_window_months: int = GeneralConfig.STAT_WINDOW,
    transition_days: int = MR_TRANSITION_DAYS,
) -> pd.Series:
    """Rolling(lookback) mean, blended into ``ou_mean`` over the
    ``transition_days`` trading days before the trailing ``ou_window_months``
    cutoff, then held at ``ou_mean`` for the rest of the trailing window.
    Returns the plain rolling mean unchanged when ``ou_mean`` is None/NaN
    (non-stationary or unavailable)."""
    rolling_mean = spread_ts.rolling(lookback).mean()
    if ou_mean is None or not np.isfinite(ou_mean):
        return rolling_mean

    index = pd.to_datetime(spread_ts.index)
    cutoff = index[-1] - pd.DateOffset(months=int(ou_window_months))
    cutoff_pos = int(index.searchsorted(cutoff))
    ramp_start_pos = max(0, cutoff_pos - int(transition_days))

    blended = rolling_mean.copy()
    ou_mean = float(ou_mean)
    blended.iloc[cutoff_pos:] = ou_mean
    if ramp_start_pos < cutoff_pos:
        ramp_len = cutoff_pos - ramp_start_pos
        weight = np.linspace(0.0, 1.0, ramp_len, endpoint=False)
        ramp_rolling = rolling_mean.iloc[ramp_start_pos:cutoff_pos].to_numpy()
        blended.iloc[ramp_start_pos:cutoff_pos] = (
            (1.0 - weight) * ramp_rolling + weight * ou_mean
        )
    return blended
