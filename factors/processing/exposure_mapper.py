"""
Exposure Bucket Mapper — converts continuous factor model signals into
discrete risk-budget scalars via quantile-based bucketing.

This is the bridge between the factor prediction engine and the Beta Book's
risk budgeting system.  The ``FactorRiskParityOptimizer`` in
``multiasset/factor_optimizer.py`` already supports signed (directional)
risk budgets — this module feeds it signal-driven scalars.

Design choices
--------------
* **7 symmetric buckets** (±3 + neutral) by default; configurable.
* **Rolling quantile thresholds** computed on a lookback window to avoid
  look-ahead bias.
* **Hysteresis** to prevent excessive bucket flipping.
* **Confidence weighting** to shrink toward neutral when signals disagree.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


# ── Bucket definition ────────────────────────────────────────────────

@dataclass
class BucketConfig:
    """Configuration for signal-to-bucket mapping."""

    # Quantile boundaries (ascending).  Length = n_buckets + 1.
    # Example for 7 buckets: [0, 0.05, 0.20, 0.40, 0.60, 0.80, 0.95, 1.0]
    quantile_boundaries: List[float] = field(default_factory=lambda: [
        0.0, 0.05, 0.20, 0.40, 0.60, 0.80, 0.95, 1.0
    ])

    # Risk-budget scalar for each bucket (same length as n_buckets)
    bucket_scalars: List[float] = field(default_factory=lambda: [
        -1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5
    ])

    # Human-readable labels
    bucket_labels: List[str] = field(default_factory=lambda: [
        'Strong Short', 'Short', 'Mild Short', 'Neutral',
        'Mild Long', 'Long', 'Strong Long'
    ])

    # Rolling lookback for quantile estimation (trading days)
    quantile_lookback: int = 252

    # Hysteresis: a bucket change only triggers if the signal has been in
    # the new bucket for at least this many consecutive days
    persistence_days: int = 3

    # Base risk budget (in capital units, e.g. millions CNY) applied per factor
    base_risk_budget: float = 1.0

    def __post_init__(self):
        n = len(self.bucket_scalars)
        assert len(self.quantile_boundaries) == n + 1, \
            "quantile_boundaries must have len(bucket_scalars) + 1 entries"
        assert len(self.bucket_labels) == n, \
            "bucket_labels must match bucket_scalars length"


# ── Core mapper ──────────────────────────────────────────────────────

def classify_signal(
    signal_value: float,
    quantile_thresholds: np.ndarray,
    config: BucketConfig,
) -> Tuple[int, str, float]:
    """
    Classify a single signal value into a bucket.

    Parameters
    ----------
    signal_value : float
        The current composite signal.
    quantile_thresholds : np.ndarray
        Absolute signal values at each quantile boundary
        (length = len(config.quantile_boundaries)).
    config : BucketConfig

    Returns
    -------
    (bucket_index, label, scalar)
    """
    for i in range(len(config.bucket_scalars)):
        lower = quantile_thresholds[i]
        upper = quantile_thresholds[i + 1]
        if signal_value <= upper or i == len(config.bucket_scalars) - 1:
            return i, config.bucket_labels[i], config.bucket_scalars[i]
    # Fallback (should not happen)
    idx = len(config.bucket_scalars) - 1
    return idx, config.bucket_labels[idx], config.bucket_scalars[idx]


def map_signals_to_buckets(
    signals: pd.Series,
    config: Optional[BucketConfig] = None,
) -> pd.DataFrame:
    """
    Map a time series of signals to bucket labels and risk-budget scalars
    using **rolling quantiles** (no look-ahead).

    Parameters
    ----------
    signals : pd.Series
        Continuous signal values indexed by date.
    config : BucketConfig, optional
        Bucket configuration.  Uses defaults if not supplied.

    Returns
    -------
    pd.DataFrame with columns:
        signal, bucket_index, bucket_label, scalar, risk_budget
    """
    if config is None:
        config = BucketConfig()

    lookback = config.quantile_lookback
    quantiles = config.quantile_boundaries

    records = []
    raw_bucket_indices = []

    for i in range(len(signals)):
        # Rolling window ending at current row (inclusive)
        start = max(0, i - lookback + 1)
        window = signals.iloc[start:i + 1]

        if len(window) < max(lookback // 4, 30):
            # Not enough history — default to neutral
            neutral_idx = len(config.bucket_scalars) // 2
            raw_bucket_indices.append(neutral_idx)
            records.append({
                'signal': signals.iloc[i],
                'bucket_index': neutral_idx,
                'bucket_label': config.bucket_labels[neutral_idx],
                'scalar': config.bucket_scalars[neutral_idx],
            })
            continue

        thresholds = np.quantile(np.asarray(window.dropna().values, dtype=float), quantiles)
        idx, label, scalar = classify_signal(signals.iloc[i], thresholds, config)
        raw_bucket_indices.append(idx)
        records.append({
            'signal': signals.iloc[i],
            'bucket_index': idx,
            'bucket_label': label,
            'scalar': scalar,
        })

    df = pd.DataFrame(records, index=signals.index)

    # Apply hysteresis — only change bucket if the new bucket persists
    if config.persistence_days > 1:
        df['bucket_index'] = _apply_hysteresis(
            raw_indices=raw_bucket_indices,
            persistence=config.persistence_days,
        )
        # Update label and scalar from the smoothed index
        df['bucket_label'] = df['bucket_index'].map(
            dict(enumerate(config.bucket_labels))
        )
        df['scalar'] = df['bucket_index'].map(
            dict(enumerate(config.bucket_scalars))
        )

    df['risk_budget'] = df['scalar'] * config.base_risk_budget
    return df


def _apply_hysteresis(raw_indices: list, persistence: int) -> list:
    """Apply persistence-based hysteresis to bucket transitions."""
    smoothed = [raw_indices[0]]
    streak = 1

    for i in range(1, len(raw_indices)):
        if raw_indices[i] == raw_indices[i - 1]:
            streak += 1
        else:
            streak = 1

        if raw_indices[i] != smoothed[-1]:
            if streak >= persistence:
                smoothed.append(raw_indices[i])
            else:
                smoothed.append(smoothed[-1])
        else:
            smoothed.append(raw_indices[i])

    return smoothed


# ── Multi-signal aggregation per risk factor ─────────────────────────

def aggregate_signals(
    signal_dict: Dict[str, pd.Series],
    ic_weights: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """
    Aggregate multiple signal series (trend, carry, value …) into a single
    composite signal via IC-weighted averaging.

    Parameters
    ----------
    signal_dict : dict
        Mapping of signal_name → signal Series (all same index).
    ic_weights : dict, optional
        Mapping of signal_name → IC weight.  If None, equal weights are used.

    Returns
    -------
    pd.Series — the combined signal.
    """
    if not signal_dict:
        return pd.Series(dtype=float)

    df = pd.DataFrame(signal_dict)
    if ic_weights is None:
        weights = pd.Series(1.0 / len(df.columns), index=df.columns)
    else:
        weights = pd.Series(ic_weights).reindex(df.columns).fillna(0)
        w_sum = weights.abs().sum()
        if w_sum > 0:
            weights = weights / w_sum

    composite = (df * weights).sum(axis=1)
    return composite


# ── Snapshot: latest bucket state per risk factor ────────────────────

def compute_signal_snapshot(
    risk_factor_signals: Dict[str, pd.Series],
    config: Optional[BucketConfig] = None,
) -> pd.DataFrame:
    """
    Produce a summary table of the **latest** signal bucket for each risk
    factor.  This is what the Beta Book Factor Signals panel displays.

    Parameters
    ----------
    risk_factor_signals : dict
        Mapping of risk_factor_name → composite signal Series.
    config : BucketConfig, optional

    Returns
    -------
    pd.DataFrame with one row per risk factor and columns:
        risk_factor, signal, bucket_label, scalar, risk_budget, confidence
    """
    if config is None:
        config = BucketConfig()

    rows = []
    for rf_name, signal_series in risk_factor_signals.items():
        if signal_series.empty:
            continue
        buckets = map_signals_to_buckets(signal_series, config)
        latest = buckets.iloc[-1]
        # Confidence = how far from neutral the signal is (normalised 0-1)
        neutral_idx = len(config.bucket_scalars) // 2
        max_dist = max(neutral_idx, len(config.bucket_scalars) - 1 - neutral_idx)
        confidence = abs(latest['bucket_index'] - neutral_idx) / max_dist if max_dist > 0 else 0.0
        rows.append({
            'risk_factor': rf_name,
            'signal': latest['signal'],
            'bucket_label': latest['bucket_label'],
            'scalar': latest['scalar'],
            'risk_budget': latest['risk_budget'],
            'confidence': round(confidence, 2),
        })

    return pd.DataFrame(rows)
