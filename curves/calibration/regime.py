# -*- coding: utf-8 -*-
"""Spread Regime Classification for Alpha Book.

Classifies spread series as 'trending' or 'mean_reverting' using rule-based
ensemble voting on four indicators: Efficiency Ratio, Hurst exponent,
Variance Ratio, and lag-1 autocorrelation of daily changes.

This is the lightweight real-time path; no HMM fitting required.

@author: CMBC
"""
import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple

# Reuse helper functions from the futures regime module
from futures.backtest.regime import (
    _estimate_hurst,
    _calculate_variance_ratio,
)


# ---------------------------------------------------------------------------
# Core feature computation (vectorised, no HMM dependency)
# ---------------------------------------------------------------------------

def compute_regime_features(
    spread_series: pd.Series,
    *,
    window: int = 20,
) -> Dict[str, float]:
    """Compute the latest regime feature snapshot for a single spread series.

    Operates on *levels* (not returns); internally computes first-differences.

    Returns dict with keys:
        efficiency_ratio, hurst, variance_ratio, autocorr, regime, regime_score
    All values are NaN-safe; returns NaN when data is insufficient.
    """
    s = pd.to_numeric(spread_series, errors="coerce").dropna()
    out: Dict[str, float] = {
        "efficiency_ratio": np.nan,
        "hurst": np.nan,
        "variance_ratio": np.nan,
        "autocorr": np.nan,
        "regime_score": np.nan,
    }
    if len(s) < window + 5:
        out["regime"] = "uncertain"
        return out

    changes = s.diff().dropna()
    if len(changes) < window:
        out["regime"] = "uncertain"
        return out

    tail = changes.iloc[-window:]

    # 1. Efficiency Ratio (Kaufman)
    net_displacement = abs(float(s.iloc[-1] - s.iloc[-window]))
    total_path = float(changes.abs().iloc[-window:].sum())
    er = net_displacement / total_path if total_path > 0 else 0.0
    out["efficiency_ratio"] = er

    # 2. Hurst exponent
    h = _estimate_hurst(tail.values)
    out["hurst"] = h

    # 3. Variance Ratio
    short_w = max(window // 4, 2)
    short_var = float(changes.iloc[-short_w:].var())
    long_var = float(changes.iloc[-window:].var())
    scale = window / short_w
    vr = (short_var * scale) / long_var if long_var > 0 else 1.0
    out["variance_ratio"] = vr

    # 4. Lag-1 autocorrelation
    ac = float(tail.autocorr(lag=1)) if len(tail) >= 5 else 0.0
    if np.isnan(ac):
        ac = 0.0
    out["autocorr"] = ac

    # Voting
    vote = 0
    n_votes = 4
    if er > 0.35:
        vote += 1
    elif er < 0.20:
        vote -= 1
    if h > 0.55:
        vote += 1
    elif h < 0.45:
        vote -= 1
    if vr > 1.05:
        vote += 1
    elif vr < 0.95:
        vote -= 1
    if ac > 0.05:
        vote += 1
    elif ac < -0.05:
        vote -= 1

    out["regime_score"] = vote / n_votes  # normalised to [-1, +1]

    if vote >= 2:
        out["regime"] = "trending"
    elif vote <= -2:
        out["regime"] = "mean_reverting"
    else:
        out["regime"] = "uncertain"

    return out


def compute_regime_features_series(
    spread_series: pd.Series,
    *,
    window: int = 20,
) -> pd.DataFrame:
    """Rolling regime features over the full history.

    Returns a DataFrame aligned to the spread index with columns:
        efficiency_ratio, hurst, variance_ratio, autocorr, regime_score, regime
    """
    s = pd.to_numeric(spread_series, errors="coerce").dropna()
    if len(s) < window + 5:
        return pd.DataFrame()

    changes = s.diff()

    # Efficiency Ratio
    net_disp = s.diff(window).abs()
    total_path = changes.abs().rolling(window).sum()
    er = (net_disp / total_path.replace(0, np.nan)).fillna(0.0)

    # Hurst (rolling)
    hurst = changes.rolling(window).apply(
        lambda x: _estimate_hurst(x.values), raw=False
    )

    # Variance Ratio
    short_w = max(window // 4, 2)
    short_var = changes.rolling(short_w).var()
    long_var = changes.rolling(window).var()
    scale = window / short_w
    vr = (short_var * scale) / long_var.replace(0, np.nan)

    # Autocorrelation
    ac = changes.rolling(window).apply(lambda x: x.autocorr(lag=1), raw=False).fillna(0.0)

    df = pd.DataFrame({
        "efficiency_ratio": er,
        "hurst": hurst,
        "variance_ratio": vr,
        "autocorr": ac,
    }, index=s.index)

    # Voting score
    vote = pd.Series(0, index=df.index, dtype=int)
    vote += np.where(df["efficiency_ratio"] > 0.35, 1, np.where(df["efficiency_ratio"] < 0.20, -1, 0))
    vote += np.where(df["hurst"] > 0.55, 1, np.where(df["hurst"] < 0.45, -1, 0))
    vote += np.where(df["variance_ratio"] > 1.05, 1, np.where(df["variance_ratio"] < 0.95, -1, 0))
    vote += np.where(df["autocorr"] > 0.05, 1, np.where(df["autocorr"] < -0.05, -1, 0))

    df["regime_score"] = vote / 4.0
    df["regime"] = "uncertain"
    df.loc[vote >= 2, "regime"] = "trending"
    df.loc[vote <= -2, "regime"] = "mean_reverting"

    return df.dropna(subset=["efficiency_ratio"])


# ---------------------------------------------------------------------------
# Convenience wrapper (used by alpha pipeline)
# ---------------------------------------------------------------------------

class SpreadRegimeClassifier:
    """Classify a spread series as trending or mean-reverting.

    Usage::

        clf = SpreadRegimeClassifier(window=20)
        result = clf.classify(spread_series)
        # result = {'regime': 'trending', 'regime_confidence': 0.75, ...}
    """

    def __init__(self, window: int = 20):
        self.window = window

    def classify(self, spread_series: pd.Series) -> Dict[str, float]:
        """Return latest regime snapshot."""
        feat = compute_regime_features(spread_series, window=self.window)
        # Confidence: abs(score) scaled to [0, 1]
        score = feat.get("regime_score", 0.0)
        if np.isnan(score):
            score = 0.0
        feat["regime_confidence"] = abs(score)
        return feat

    def classify_series(self, spread_series: pd.Series) -> pd.DataFrame:
        """Return full rolling regime history."""
        df = compute_regime_features_series(spread_series, window=self.window)
        if not df.empty:
            df["regime_confidence"] = df["regime_score"].abs()
        return df
