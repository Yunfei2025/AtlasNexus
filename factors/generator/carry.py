"""
Carry factor calculator.

Carry measures the expected return from holding a bond position, assuming the
yield curve stays unchanged.  Two main signals are computed:

1. Roll-down return  – the P&L from a bond "rolling down" the curve towards
   shorter maturities over a holding period (e.g., 1 month ≈ 22 trading days).
2. Carry spread     – the excess yield of each tenor over a short-rate proxy,
   providing a simple cross-sectional carry ranking.

Both signals are constructed from the same yield curve columns already
present in the OHLCV market data that the factor system loads (TB2Y, TB5Y,
TB10Y as WindInfo identifiers).
"""

import pandas as pd
import numpy as np
from typing import Dict
from .base import BaseFactorCalculator


# Ordered tenors in years and their expected Wind column names
_TENOR_YEARS = [2, 5, 10]
_TENOR_COLS = ['TB2Y.WI', 'TB5Y.WI', 'TB10Y.WI']


class CarryFactors(BaseFactorCalculator):
    """Calculator for carry / roll-down factors."""

    def _validate_data(self):
        """Override – yield column availability is checked per-method."""
        pass

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _available_tenor_pairs(self):
        """Return list of (short_col, long_col, short_yr, long_yr) for
        adjacent tenors that are present in self.data."""
        pairs = []
        cols = self.data.columns
        for i in range(len(_TENOR_COLS) - 1):
            if _TENOR_COLS[i] in cols and _TENOR_COLS[i + 1] in cols:
                pairs.append((_TENOR_COLS[i], _TENOR_COLS[i + 1],
                              _TENOR_YEARS[i], _TENOR_YEARS[i + 1]))
        return pairs

    # ------------------------------------------------------------------
    # factor calculations
    # ------------------------------------------------------------------
    def calculate_rolldown(self, holding_days: int = 22) -> Dict[str, pd.Series]:
        """
        Approximate roll-down return between adjacent tenors.

        Roll-down ≈ (yield_long - yield_short) × duration_mid / 12
        where duration_mid is the midpoint modified duration.

        Returns a dict of Series keyed by e.g. ``RollDown_2Y_5Y``.
        """
        results: Dict[str, pd.Series] = {}
        for short_col, long_col, short_yr, long_yr in self._available_tenor_pairs():
            spread = (self.data[long_col] - self.data[short_col]) / 100.0  # to decimal
            mid_dur = (short_yr + long_yr) / 2.0
            # Annualised fraction for the holding period
            annual_frac = holding_days / 252.0
            rolldown = spread * mid_dur * annual_frac * 100  # back to %
            results[f'RollDown_{short_yr}Y_{long_yr}Y'] = rolldown
        return results

    def calculate_carry_spread(self) -> Dict[str, pd.Series]:
        """
        Carry spread = tenor yield − shortest available yield (proxy for
        funding cost).  A higher carry spread means a bond is more
        attractive to hold.
        """
        results: Dict[str, pd.Series] = {}
        cols = self.data.columns
        available = [(yr, col) for yr, col in zip(_TENOR_YEARS, _TENOR_COLS) if col in cols]
        if len(available) < 2:
            return results
        short_col = available[0][1]
        for yr, col in available[1:]:
            results[f'CarrySpread_{yr}Y'] = self.data[col] - self.data[short_col]
        return results

    def calculate_carry_momentum(self, window: int = 20) -> Dict[str, pd.Series]:
        """
        Rolling change in carry spread – captures whether carry is expanding
        or contracting.
        """
        spreads = self.calculate_carry_spread()
        results: Dict[str, pd.Series] = {}
        for name, series in spreads.items():
            diff = series.diff(window)
            results[f'{name}_Mom{window}d'] = diff
        return results

    # ------------------------------------------------------------------
    # public interface
    # ------------------------------------------------------------------
    def calculate_all(self) -> Dict[str, pd.Series]:
        """Return all carry factors."""
        factors: Dict[str, pd.Series] = {}
        factors.update(self.calculate_rolldown())
        factors.update(self.calculate_carry_spread())
        factors.update(self.calculate_carry_momentum())
        return factors
