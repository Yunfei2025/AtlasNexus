"""
Value factor calculator.

Value factors measure how "cheap" or "expensive" an asset is relative to a
reference or fair-value model.  For fixed-income futures the simplest approach
is to compare the current yield (or spread) against its own rolling history.

Signals produced:
1. **Yield deviation** – z-score of current yield vs rolling mean.
2. **Term-premium value** – z-score of the term spread (10Y−2Y) vs its own
   rolling distribution – captures cheapness of duration risk.
3. **Real yield proxy** – yield minus trailing inflation expectations (if
   available in the macro data, otherwise uses yield momentum as proxy).
4. **Mean-reversion score** – normalised distance from rolling percentile
   midpoint, indicating reversion potential.
"""

import pandas as pd
import numpy as np
from typing import Dict
from .base import BaseFactorCalculator


_TENOR_COLS = ['TB2Y.WI', 'TB5Y.WI', 'TB10Y.WI']


class ValueFactors(BaseFactorCalculator):
    """Calculator for yield-based value factors."""

    def _validate_data(self):
        """Override – yield columns are checked per-method."""
        pass

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _rolling_zscore(series: pd.Series, window: int) -> pd.Series:
        """Z-score of *series* over a rolling window."""
        mu = series.rolling(window=window, min_periods=max(window // 2, 20)).mean()
        sigma = series.rolling(window=window, min_periods=max(window // 2, 20)).std()
        z = (series - mu) / sigma.replace(0, np.nan)
        return z.replace([np.inf, -np.inf], np.nan)

    @staticmethod
    def _rolling_percentile_score(series: pd.Series, window: int) -> pd.Series:
        """Where the latest value sits relative to the rolling [min, max] range.
        Returns a value in [-1, 1]: -1 = at rolling low, +1 = at rolling high."""
        rmin = series.rolling(window=window, min_periods=max(window // 2, 20)).min()
        rmax = series.rolling(window=window, min_periods=max(window // 2, 20)).max()
        rng = rmax - rmin
        mid = (rmax + rmin) / 2.0
        score = (series - mid) / rng.replace(0, np.nan) * 2.0
        return score.clip(-1, 1)

    # ------------------------------------------------------------------
    # factor calculations
    # ------------------------------------------------------------------
    def calculate_yield_deviation(self, window: int = 252) -> Dict[str, pd.Series]:
        """Z-score of each tenor yield vs its rolling 1Y mean."""
        results: Dict[str, pd.Series] = {}
        for col in _TENOR_COLS:
            if col in self.data.columns:
                tenor = col.split('.')[0].replace('TB', '')
                results[f'YieldDev_{tenor}'] = self._rolling_zscore(self.data[col], window)
        return results

    def calculate_term_premium_value(self, window: int = 252) -> pd.Series:
        """Z-score of the 10Y−2Y term spread vs rolling history."""
        if 'TB10Y.WI' not in self.data.columns or 'TB2Y.WI' not in self.data.columns:
            return pd.Series(dtype=float, index=self.data.index)
        spread = self.data['TB10Y.WI'] - self.data['TB2Y.WI']
        return self._rolling_zscore(spread, window)

    def calculate_mean_reversion_score(self, window: int = 252) -> Dict[str, pd.Series]:
        """Rolling percentile score for each tenor – measures reversion potential."""
        results: Dict[str, pd.Series] = {}
        for col in _TENOR_COLS:
            if col in self.data.columns:
                tenor = col.split('.')[0].replace('TB', '')
                results[f'MRScore_{tenor}'] = self._rolling_percentile_score(self.data[col], window)
        return results

    def calculate_yield_momentum_value(self, fast: int = 20, slow: int = 252) -> Dict[str, pd.Series]:
        """Difference between short-term and long-term yield z-scores.
        A large positive value means yields have risen fast (bonds cheap
        relative to recent history) – a contrarian value signal."""
        results: Dict[str, pd.Series] = {}
        for col in _TENOR_COLS:
            if col in self.data.columns:
                tenor = col.split('.')[0].replace('TB', '')
                z_fast = self._rolling_zscore(self.data[col], fast)
                z_slow = self._rolling_zscore(self.data[col], slow)
                results[f'ValueMom_{tenor}'] = z_fast - z_slow
        return results

    # ------------------------------------------------------------------
    # public interface
    # ------------------------------------------------------------------
    def calculate_all(self) -> Dict[str, pd.Series]:
        """Return all value factors."""
        factors: Dict[str, pd.Series] = {}
        factors.update(self.calculate_yield_deviation())
        tp = self.calculate_term_premium_value()
        if not tp.empty:
            factors['TermPremiumValue'] = tp
        factors.update(self.calculate_mean_reversion_score())
        factors.update(self.calculate_yield_momentum_value())
        return factors
