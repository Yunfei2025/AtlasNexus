# -*- coding: utf-8 -*-
"""Shared budget-derivation utilities.

Single source of truth for the vol^0.5 risk-budget computation used by the
Portfolio tab, the risk-budget display, and the historical backtest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple

from multiasset.config import RiskModelConfig

_IR_PREFIXES = ('IRDL', 'IRSL', 'IRCV')


def derive_vol_sqrt_budgets(
    factor_names: List[str],
    vol_map: Dict[str, float],
    total_capital_m: Optional[float] = None,
    fallback_vol: float = RiskModelConfig.ESTIMATED_FALLBACK_VOL,
) -> tuple[Dict[str, float], List[str]]:
    """Convert a factor-vol map to vol^0.5 risk budgets.

    Vol^0.5 weighting gives higher budget to higher-vol factors (Level > Slope
    > Curvature) while staying closer to equal risk than a raw vol-proportional
    scheme.

    Args:
        factor_names: Ordered list of factor names.
        vol_map: Dict of factor → annualised vol (percent or decimal).
        total_capital_m: If provided, budgets are scaled to sum to this value
            (in million CNY).  If None, budgets are fractions summing to 1.
        fallback_vol: Vol to use when a factor has no data in vol_map.

    Returns:
        (budgets, missing_factors) where budgets is a dict {factor: budget}
        and missing_factors lists the factors that used the fallback vol.
    """
    raw: Dict[str, float] = {}
    missing: List[str] = []

    for f in factor_names:
        v = vol_map.get(f)
        if v is not None and pd.notna(v) and float(v) > 0:
            raw[f] = float(np.sqrt(v))
        else:
            missing.append(f)
            raw[f] = float(np.sqrt(fallback_vol))

    total = sum(raw.values())
    if total <= 0:
        equal = (total_capital_m / len(factor_names)) if (total_capital_m and factor_names) else 1.0
        return {f: equal for f in factor_names}, missing

    if total_capital_m is not None:
        budgets = {f: round(total_capital_m * raw[f] / total, 2) for f in factor_names}
    else:
        budgets = {f: raw[f] / total for f in factor_names}

    return budgets, missing


def derive_ir_ratio_constraints(
    factor_names: List[str],
    vol_map: Dict[str, float],
    asset_names: List[str],
    exposure_matrix,           # np.ndarray (n_assets, n_factors), columns aligned to factor_names
    fallback_vol: float = RiskModelConfig.ESTIMATED_FALLBACK_VOL,
) -> Tuple[List[dict], List[str]]:
    """Build SLSQP equality constraints enforcing capital ∝ √vol for IR factors.

    For each consecutive pair of IR factors (i, j) in factor_names the constraint is:
        (Bᵢ · w) · √vol_j  =  (Bⱼ · w) · √vol_i
    where Bᵢ is the column of the exposure matrix for factor i.  This pins the
    net IR factor exposure ratios to √vol, which translates to capital allocated
    to each IR factor being proportional to √vol when the portfolio has a single
    dominant asset per factor.

    Only factors whose prefix is in ('IRDL', 'IRSL', 'IRCV') are constrained.
    Commodity, FX, and spread factors are left free for the min-vol optimizer.

    Returns:
        (constraints, missing_vols) where constraints is a list of dicts
        accepted by scipy.optimize.minimize, and missing_vols lists IR factors
        that fell back to the fallback vol.
    """
    ir_factors = [f for f in factor_names if f.split('.')[0] in _IR_PREFIXES]
    if len(ir_factors) < 2:
        return [], []

    sqrt_vols: Dict[str, float] = {}
    missing: List[str] = []
    for f in ir_factors:
        v = vol_map.get(f)
        if v is not None and pd.notna(v) and float(v) > 0:
            sqrt_vols[f] = float(np.sqrt(float(v)))
        else:
            missing.append(f)
            sqrt_vols[f] = float(np.sqrt(fallback_vol))

    # Index of each IR factor in the full factor_names list
    f_idx = {f: factor_names.index(f) for f in ir_factors}

    constraints: List[dict] = []
    # Anchor all IR factors relative to the first one: exposure(f0)/√vol(f0) = exposure(fi)/√vol(fi)
    f0 = ir_factors[0]
    sv0 = sqrt_vols[f0]
    col0 = exposure_matrix[:, f_idx[f0]]  # (n_assets,) — net exposure of f0 per unit weight

    for fi in ir_factors[1:]:
        svi = sqrt_vols[fi]
        coli = exposure_matrix[:, f_idx[fi]]
        # Closure must capture col0, coli, sv0, svi by value
        def _make_con(c0, ci, s0, si):
            def fun(w):
                return float(c0 @ w) * si - float(ci @ w) * s0
            return fun
        constraints.append({'type': 'eq', 'fun': _make_con(col0, coli, sv0, svi)})

    return constraints, missing
