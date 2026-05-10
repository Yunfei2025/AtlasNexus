# -*- coding: utf-8 -*-
"""
Computation helper functions used by callbacks in the Multi-Asset Dashboard.
Functions here are shared across multiple callbacks or too long to keep inline.
"""
from __future__ import annotations

# All helpers used by callbacks are defined inline within register_multiasset_callbacks
# in callbacks.py.  This module is kept as a placeholder that satisfies the
# data ← backtest ← layouts ← callbacks dependency chain.

from .data import (
    THEME,
    ALLOCATION_RESULTS,
    DIVERSIFICATION_RECOMMENDATIONS,
    SELECTED_FACTOR_POOL,
    RISK_BUDGET_VOL_LOOKBACK_YEARS,
    RISK_BUDGET_EWMA_LAMBDA,
    FACTOR_TO_ASSET_MAP,
    BOND_SIGNAL_FILE_MAP,
    BOND_SIGNAL_LABELS,
    BOND_SIGNAL_BUCKETS,
    compute_factor_vol_map,
    get_assets_from_factors,
)
