# -*- coding: utf-8 -*-
"""Spread Regime Classification for Alpha Book.

Classifies spread series as 'trending' or 'mean_reverting' using rule-based
ensemble voting on four indicators: Efficiency Ratio, Hurst exponent,
Variance Ratio, and lag-1 autocorrelation of daily changes.

This is the lightweight real-time path; no HMM fitting required.

Each indicator is calibrated so that its expected vote on an i.i.d. (random
walk) null is neutral, regardless of the trailing window length ``w``. Without
this, a naive R/S Hurst estimate, an overlapping-sum variance ratio, and a
window-invariant efficiency-ratio threshold are all biased toward the
mean-reverting vote at short/medium windows (verified: a simulated random
walk was mislabeled 'mean_reverting' ~60% of the time by the unscaled
version of this classifier). See docs/report/04_pairs_spread.tex,
"Regime Selection and Scope" for the derivation.

@author: CMBC
"""
import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple


DEFAULT_REGIME_WINDOW = 60

# Reuse the Hurst helper from the futures regime module; the classic R/S
# formula it returns is bias-corrected below via _hurst_null_mean().
from futures.backtest.regime import _estimate_hurst


_HURST_NULL_CACHE: Dict[int, float] = {}


def _hurst_null_mean(n: int, *, n_sims: int = 4000, seed: int = 20260816) -> float:
    """Expected value of ``_estimate_hurst`` on i.i.d. noise of length ``n``.

    The plain ``log(R/S) / log(n)`` estimator used by ``_estimate_hurst`` is
    not centred on 0.5 in finite samples -- it drifts up with ``n`` (e.g.
    ~0.51 at n=30, ~0.53 at n=500 empirically). A closed-form correction
    (Anis-Lloyd) does not match this estimator's exact ``ddof=1``/max-min
    convention closely enough to be reliable, so the null is instead
    calibrated directly by simulating i.i.d. Gaussian noise through the same
    ``_estimate_hurst`` call and caching the result per window length. This
    keeps the +-0.05 trending/mean-reverting gate centred on "no memory"
    regardless of window length, and stays correct even if
    ``_estimate_hurst`` itself is later revised.
    """
    n = int(n)
    if n < 10:
        return 0.5
    cached = _HURST_NULL_CACHE.get(n)
    if cached is not None:
        return cached
    rng = np.random.default_rng(seed)
    samples = rng.standard_normal((n_sims, n))
    values = np.apply_along_axis(_estimate_hurst, 1, samples)
    finite = values[np.isfinite(values)]
    mean_h = float(finite.mean()) if len(finite) else 0.5
    _HURST_NULL_CACHE[n] = mean_h
    return mean_h


def _efficiency_ratio_null_mean(w: int) -> float:
    """Expected efficiency ratio for an i.i.d. random walk over ``w`` steps.

    ``E[ER] ~ sqrt(2 / (pi * w))`` for a mean-zero i.i.d. increment series
    (expected |sum of w steps| over the expected sum of |steps|). This shrinks
    as the window grows, so a fixed 0.20/0.35 gate is systematically too easy
    to trip on the mean-reverting side at longer windows and too hard at
    shorter ones. Voting bands are set relative to this null instead.
    """
    if w < 1:
        return 0.5
    return float(np.sqrt(2.0 / (np.pi * w)))


def _variance_ratio(changes: pd.Series, k: int) -> float:
    """Bias-corrected overlapping variance ratio (Lo & MacKinlay, 1988).

    Returns the ratio of the per-period k-step variance to the 1-step
    variance for a return series, using the unbiased overlapping-sample
    estimator (Lo & MacKinlay 1988, eq. 8-9). The naive
    ``rolling(k).sum().var() / (k * var())`` version is severely
    downward-biased for k not << len(values) (e.g. mean ~0.72 instead of 1.0
    on white noise at k=window/4), which tips the vote toward mean-reverting
    even on pure noise.

    ``sigma_b^2(k) = (1/m) * sum_{t=k}^{n}(sum_{i=0}^{k-1} r_{t-i} - k*mu)^2``
    with ``m = k*(n-k+1)*(1 - k/n)`` is already the *per-period* k-step
    variance (the ``m`` normalizer absorbs the factor of ``k``), so it is
    compared directly to the 1-step variance -- dividing by an extra ``k``
    here would reintroduce a ``1/k`` bias toward mean-reversion.
    """
    values = pd.to_numeric(changes, errors='coerce').dropna()
    n = len(values)
    if n < k + 2 or k < 1:
        return 1.0
    values = values.to_numpy(dtype=float)
    mu = values.mean()
    one_period_var = float(((values - mu) ** 2).sum()) / (n - 1)
    if not np.isfinite(one_period_var) or one_period_var <= 0:
        return 1.0
    k_sums = np.convolve(values, np.ones(k), mode='valid') - k * mu
    m = k * (n - k + 1) * (1.0 - k / n)
    if not np.isfinite(m) or m <= 0:
        return 1.0
    k_period_var = float((k_sums ** 2).sum()) / m
    if not np.isfinite(k_period_var):
        return 1.0
    return k_period_var / one_period_var


# ---------------------------------------------------------------------------
# Core feature computation (vectorised, no HMM dependency)
# ---------------------------------------------------------------------------

def _vr_short_window(window: int) -> int:
    """Short-horizon ``k`` for the variance ratio.

    ``window // 4`` (the original choice) makes ``k`` a large fraction of
    ``window``, which starves the Lo-MacKinlay estimator of independent
    overlapping blocks and reintroduces bias even after the correction above.
    ``window // 12`` keeps at least ~10 non-overlapping blocks for the
    default 60-day window while remaining well-defined (min 2) for shorter
    custom windows.
    """
    return max(window // 12, 2)


def _vote_thresholds(window: int) -> Dict[str, Tuple[float, float]]:
    """Window-scaled (trending_gate, mean_reverting_gate) per indicator.

    Efficiency ratio and Hurst have a random-walk null that shifts with the
    window length (see ``_efficiency_ratio_null_mean`` / ``_hurst_null_mean``);
    thresholds are set as offsets from that null so the same +-1 vote logic
    stays approximately neutral on noise at any window. Variance ratio and
    autocorrelation nulls are window-invariant (1.0 and 0.0 respectively), so
    their bands stay fixed.
    """
    er_null = _efficiency_ratio_null_mean(window)
    h_null = _hurst_null_mean(window)
    return {
        "efficiency_ratio": (er_null * 1.6, er_null * 0.7),
        "hurst": (h_null + 0.05, h_null - 0.05),
        "variance_ratio": (1.05, 0.95),
        "autocorr": (0.05, -0.05),
    }


def compute_regime_features(
    spread_series: pd.Series,
    *,
    window: int = DEFAULT_REGIME_WINDOW,
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

    # 3. Variance Ratio (bias-corrected, short block << window)
    k = _vr_short_window(window)
    vr = _variance_ratio(tail, k)
    out["variance_ratio"] = vr

    # 4. Lag-1 autocorrelation
    ac = float(tail.autocorr(lag=1)) if len(tail) >= 5 else 0.0
    if np.isnan(ac):
        ac = 0.0
    out["autocorr"] = ac

    # Voting, thresholds scaled to `window` so the classifier's random-walk
    # null stays centred regardless of window length (see _vote_thresholds).
    thresholds = _vote_thresholds(window)
    vote = 0
    n_votes = 4
    er_hi, er_lo = thresholds["efficiency_ratio"]
    if er > er_hi:
        vote += 1
    elif er < er_lo:
        vote -= 1
    h_hi, h_lo = thresholds["hurst"]
    if h > h_hi:
        vote += 1
    elif h < h_lo:
        vote -= 1
    vr_hi, vr_lo = thresholds["variance_ratio"]
    if vr > vr_hi:
        vote += 1
    elif vr < vr_lo:
        vote -= 1
    ac_hi, ac_lo = thresholds["autocorr"]
    if ac > ac_hi:
        vote += 1
    elif ac < ac_lo:
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
    window: int = DEFAULT_REGIME_WINDOW,
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

    # Variance Ratio (bias-corrected, short block << window)
    k = _vr_short_window(window)
    vr = changes.rolling(window).apply(
        lambda values: _variance_ratio(pd.Series(values), k), raw=False,
    )

    # Autocorrelation
    ac = changes.rolling(window).apply(lambda x: x.autocorr(lag=1), raw=False).fillna(0.0)

    df = pd.DataFrame({
        "efficiency_ratio": er,
        "hurst": hurst,
        "variance_ratio": vr,
        "autocorr": ac,
    }, index=s.index)

    # Voting score, thresholds scaled to `window` (see _vote_thresholds).
    thresholds = _vote_thresholds(window)
    er_hi, er_lo = thresholds["efficiency_ratio"]
    h_hi, h_lo = thresholds["hurst"]
    vr_hi, vr_lo = thresholds["variance_ratio"]
    ac_hi, ac_lo = thresholds["autocorr"]

    vote = pd.Series(0, index=df.index, dtype=int)
    vote += np.where(df["efficiency_ratio"] > er_hi, 1, np.where(df["efficiency_ratio"] < er_lo, -1, 0))
    vote += np.where(df["hurst"] > h_hi, 1, np.where(df["hurst"] < h_lo, -1, 0))
    vote += np.where(df["variance_ratio"] > vr_hi, 1, np.where(df["variance_ratio"] < vr_lo, -1, 0))
    vote += np.where(df["autocorr"] > ac_hi, 1, np.where(df["autocorr"] < ac_lo, -1, 0))

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

        clf = SpreadRegimeClassifier(window=DEFAULT_REGIME_WINDOW)
        result = clf.classify(spread_series)
        # result = {'regime': 'trending', 'regime_confidence': 0.75, ...}
    """

    def __init__(self, window: int = DEFAULT_REGIME_WINDOW):
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
