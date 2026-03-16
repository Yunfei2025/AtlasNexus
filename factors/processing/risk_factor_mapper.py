"""
Risk Factor Mapper — bridge between futures-level factor signals and
macro risk factor exposures used by the Beta Book.

A futures contract (e.g. T.CFE — the Chinese 10-year treasury bond future)
has exposure to multiple PCA-based risk factors:
  - IRDL (level / PC1)
  - IRSL (slope / PC2)
  - IRCV (curvature / PC3)

This module decomposes a scalar composite signal produced by the factor
model into signed contributions per risk factor, using the same tenor
sensitivity table that the multiasset module uses.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Dict, Optional


# ── Default sensitivity profiles for common futures contracts ─────────
# Sensitivity = approximate value change (%) per 1-unit PC score change.
# Signs follow bond convention: negative duration means rising yields hurt.
# These are consistent with multiasset/utils.get_default_sensitivities.

CONTRACT_RISK_PROFILES: Dict[str, Dict[str, float]] = {
    # Chinese Treasury Bond Futures
    'T.CFE': {                # 10Y bond future
        'IRDL.CN': -8.50,    # high level sensitivity (duration ≈ 8.5)
        'IRSL.CN': -1.00,    # slope exposure via KRD mismatch
        'IRCV.CN':  0.50,    # mild curvature (belly underweight)
    },
    'TF.CFE': {               # 5Y bond future
        'IRDL.CN': -4.50,
        'IRSL.CN': -0.50,
        'IRCV.CN': -1.00,    # high curvature exposure (belly)
    },
    'TS.CFE': {               # 2Y bond future
        'IRDL.CN': -1.90,
        'IRSL.CN':  0.15,    # small inverse slope
        'IRCV.CN':  0.50,
    },
    'TL.CFE': {               # 30Y bond future
        'IRDL.CN': -17.0,
        'IRSL.CN': -2.00,
        'IRCV.CN':  0.00,
    },
}


def decompose_signal(
    signal: float,
    contract: str,
    profile: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    """
    Decompose a scalar composite signal into per-risk-factor contributions.

    The idea is simple: each risk factor's contribution is proportional to
    the contract's *normalised* absolute sensitivity to that factor, with the
    sign preserved from both the signal and the sensitivity.

    Example
    -------
    >>> decompose_signal(0.8, 'T.CFE')
    {'IRDL.CN': -0.68, 'IRSL.CN': -0.08, 'IRCV.CN': 0.04}

    Parameters
    ----------
    signal : float
        Composite signal value (e.g. from IC-weighted predictor output).
    contract : str
        Futures contract code.
    profile : dict, optional
        Custom risk profile.  Falls back to CONTRACT_RISK_PROFILES.

    Returns
    -------
    dict mapping risk factor name → signed contribution.
    """
    if profile is None:
        profile = CONTRACT_RISK_PROFILES.get(contract)
    if profile is None:
        raise ValueError(f"No risk profile for contract '{contract}'. "
                         f"Known contracts: {list(CONTRACT_RISK_PROFILES)}")

    total_abs = sum(abs(v) for v in profile.values())
    if total_abs == 0:
        return {k: 0.0 for k in profile}

    contributions = {}
    for factor, sensitivity in profile.items():
        weight = sensitivity / total_abs          # normalised signed weight
        contributions[factor] = signal * weight

    return contributions


def decompose_signal_series(
    signals: pd.Series,
    contract: str,
    profile: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """
    Vectorised version of :func:`decompose_signal` for a full time series.

    Returns a DataFrame with the same index as *signals* and one column per
    risk factor.
    """
    if profile is None:
        profile = CONTRACT_RISK_PROFILES.get(contract)
    if profile is None:
        raise ValueError(f"No risk profile for contract '{contract}'.")

    total_abs = sum(abs(v) for v in profile.values())
    if total_abs == 0:
        return pd.DataFrame(0.0, index=signals.index,
                            columns=list(profile.keys()))

    weights = {k: v / total_abs for k, v in profile.items()}
    result = pd.DataFrame(index=signals.index)
    for factor, w in weights.items():
        result[factor] = signals * w
    return result


def aggregate_risk_factor_signals(
    contract_signals: Dict[str, pd.Series],
    profiles: Optional[Dict[str, Dict[str, float]]] = None,
) -> pd.DataFrame:
    """
    Aggregate signals from multiple contracts into a single risk-factor
    signal table.

    When multiple contracts contribute to the same risk factor (e.g. T.CFE
    and TL.CFE both have IRDL.CN exposure), contributions are summed.

    Parameters
    ----------
    contract_signals : dict
        Mapping of contract code → signal Series.
    profiles : dict, optional
        Mapping of contract code → risk profile dict.

    Returns
    -------
    DataFrame indexed by date, one column per unique risk factor, values
    are aggregated signed signal contributions.
    """
    frames = []
    for contract, signal_series in contract_signals.items():
        prof = (profiles or {}).get(contract)
        df = decompose_signal_series(signal_series, contract, prof)
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, axis=0)
    # Sum contributions for the same (date, factor) across contracts
    aggregated = combined.groupby(combined.index).sum()
    return aggregated
