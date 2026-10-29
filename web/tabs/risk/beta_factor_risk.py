# -*- coding: utf-8 -*-
"""Factor risk attribution of the *stored* Beta book for Summary > Risk.

The Run Analysis output (allocation-results store / ALLOCATION_RESULTS) is the
optimizer's pre-tilt risk-parity attribution of whatever was last run in the
session -- not the book that was saved, and not the factor-scaling weights.
This recomputes the attribution from summary_beta_portfolio.parquet with the
optimizer's own exposure matrix and full-covariance RC formula, using the
same EWMA vol/cov window and month-end anchor as the optimizer.
"""

from __future__ import annotations

import os

import pandas as pd

from settings.paths import DIR_INPUT
from web.tabs.beta.callbacks._common import _SUMMARY_BETA_PARQUET

_CACHE: dict = {}


def _stored_weights() -> pd.Series:
    """Asset Name -> signed weight (fraction of the run's total capital)."""
    snap = pd.read_parquet(_SUMMARY_BETA_PARQUET)
    if 'Asset Type' in snap.columns:
        snap = snap[snap['Asset Type'].astype(str) != 'TOTAL']
    if snap.empty or 'Asset Name' not in snap.columns:
        return pd.Series(dtype=float)
    if 'Weight (%)' in snap.columns and pd.to_numeric(snap['Weight (%)'], errors='coerce').notna().all():
        w = pd.to_numeric(snap['Weight (%)'], errors='coerce') / 100.0
    else:
        cap = pd.to_numeric(snap['Capital (CNY)'], errors='coerce')
        total = pd.to_numeric(snap.get('_capital_cny'), errors='coerce')
        total = float(total.iloc[0]) if total is not None and total.notna().any() else float(cap.abs().sum())
        w = cap / total
    w.index = snap['Asset Name'].astype(str)
    return w.groupby(level=0).sum()


def stored_beta_factor_risk() -> pd.DataFrame | None:
    """Factor RC table (Risk Factor / Volatility / Net Exposure / Risk Contribution (%))
    for the stored Beta book, or None when there is no stored book."""
    if not os.path.exists(_SUMMARY_BETA_PARQUET):
        return None
    key = os.path.getmtime(_SUMMARY_BETA_PARQUET)
    if key in _CACHE:
        return _CACHE[key]

    from multiasset.main import create_custom_portfolio
    from multiasset.factor_optimizer import FactorRiskParityOptimizer
    from web.tabs.beta.data import compute_factor_vol_map, compute_factor_cov

    weights = _stored_weights()
    if weights.empty:
        return None
    portfolio = create_custom_portfolio(list(weights.index), use_cache=True, use_deterministic=True)
    factors = sorted({f for a in portfolio.assets.values() for f in a.factors})
    vols = pd.Series(compute_factor_vol_map(factors), dtype=float)
    if vols.dropna().empty:
        return None
    cov = compute_factor_cov(list(vols.dropna().index))
    opt = FactorRiskParityOptimizer(portfolio=portfolio, input_dir=str(DIR_INPUT))
    exposure, _assets, factor_names = opt._build_exposure_matrix(vols)
    fr = opt._compute_factor_risk_contributions(weights, exposure, factor_names, cov, vols)
    _CACHE.clear()
    _CACHE[key] = fr
    return fr
