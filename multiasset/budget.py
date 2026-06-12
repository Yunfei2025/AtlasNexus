# -*- coding: utf-8 -*-
"""Shared budget-derivation utilities.

Single source of truth for the vol^0.5 risk-budget computation used by the
Portfolio tab, the risk-budget display, and the historical backtest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, List, Optional

from multiasset.config import RiskModelConfig


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
