# -*- coding: utf-8 -*-
"""Latest-data Close Price / Z-Score for IRS (SwapSpread) rows of the Books Alpha table.

TenorSpread rows read their spread and Z-Score from the alpha spread snapshot,
which is rebuilt from database-px.pkl whenever that file changes. SwapSpread
rows used to take Close Price from IRS-pxspds.pkl (EOD pipeline, can lag the
data feed by days) using only the first two legs -- wrong for a 3-leg fly --
and Z-Score from the real-time quote file IRS-spdsrt.pkl (refreshed only by a
live market-data pull). These helpers price the spread from the freshest daily
closes across all legs and re-derive the Z-Score from that same close.
"""

from __future__ import annotations

from typing import Optional, Sequence

import numpy as np
import pandas as pd


def freshest_daily_closes(*frames: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Combine daily close-yield frames (%), earlier arguments taking priority.

    Union of dates and columns: a later frame only fills dates/columns the
    earlier ones lack, so passing the data feed first and the EOD pipeline
    second yields the newest closes without losing older history.
    """
    out: Optional[pd.DataFrame] = None
    for f in frames:
        if not isinstance(f, pd.DataFrame) or f.empty:
            continue
        g = f.apply(pd.to_numeric, errors='coerce')
        g.index = pd.to_datetime(g.index, errors='coerce')
        g = g[g.index.notna()]
        g = g[~g.index.duplicated(keep='last')].sort_index()
        out = g if out is None else out.combine_first(g)
    return out if out is not None else pd.DataFrame()


def swap_spread_close_bp(
    closes: pd.DataFrame, legs: Sequence[str],
) -> Optional[tuple[float, pd.Timestamp]]:
    """(spread in bp, date) from the latest day on which every leg has a close.

    Two legs: leg1 - leg2. Three legs (butterfly, leg1 = belly): 2*leg1 -
    leg2 - leg3 -- the same convention as the stored Repo7d fly spreads. None
    when a leg is missing or has no common date.
    """
    legs = [str(x) for x in legs if x]
    if len(legs) not in (2, 3) or closes.empty or any(x not in closes.columns for x in legs):
        return None
    panel = closes[legs].dropna()
    if panel.empty:
        return None
    y = panel.iloc[-1]
    pct = (y[legs[0]] - y[legs[1]]) if len(legs) == 2 else (2.0 * y[legs[0]] - y[legs[1]] - y[legs[2]])
    return round(float(pct) * 100.0, 4), pd.Timestamp(panel.index[-1])


def zscore_from_close(close_bp: float, mean: Optional[float], vol: Optional[float]) -> Optional[float]:
    """(spread - mean) / vol with spread in bp and mean/vol in % (snapshot units)."""
    try:
        close_pct, mean_f, vol_f = float(close_bp) / 100.0, float(mean), float(vol)
    except (TypeError, ValueError):
        return None
    if not np.isfinite([close_pct, mean_f, vol_f]).all() or vol_f <= 0:
        return None
    return (close_pct - mean_f) / vol_f
