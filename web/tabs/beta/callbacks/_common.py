# -*- coding: utf-8 -*-
"""Shared imports, constants, and helpers used across the Beta callback modules."""

from __future__ import annotations

import pandas as pd

from multiasset.risk_loader import RiskFactorLoader
from settings.paths import DIR_INPUT


_SUMMARY_BETA_PARQUET    = str(DIR_INPUT / 'summary_beta_portfolio.parquet')
_SUMMARY_ALPHA_PARQUET   = str(DIR_INPUT / 'summary_alpha_portfolio.parquet')
_ALPHA_POSITIONS_PARQUET = str(DIR_INPUT / 'alpha_book_positions.parquet')

# Optional: carry+roll timeseries loader (from alpha data module)
try:
    from web.tabs.alpha.data import load_carry_roll_timeseries as _load_cr_ts
except ImportError:
    try:
        from ...alpha.data import load_carry_roll_timeseries as _load_cr_ts
    except ImportError:
        _load_cr_ts = None

# Map asset-name prefix → primary risk factor (used for close-price lookup)
_ASSET_PREFIX_TO_FACTOR: dict[str, str] = {
    'CN':  'IRDL.CN',  'US':  'IRDL.US',  'EU':  'IRDL.DE',
    'JP':  'IRDL.JP',  'UK':  'IRDL.UK',
    'IRS': 'SPDL.IRS', 'CDB': 'SPDL.CDB', 'ICP': 'SPDL.ICP',
}


def _upsert_snapshot(new_df: pd.DataFrame, parquet_path: str, id_cols: list[str]) -> pd.DataFrame:
    """Insert-or-update by id_cols: keep existing rows, replace matched ones, add new ones.

    Re-running Run Analysis / Run Optimization preserves prior trades that
    are not in the latest run, and refreshes values for trades that are.
    """
    import os
    existing = None
    if os.path.exists(parquet_path):
        try:
            existing = pd.read_parquet(parquet_path)
        except Exception:
            existing = None

    if existing is None or existing.empty:
        new_df.to_parquet(parquet_path, index=False)
        return new_df

    # Align columns: union of both schemas
    all_cols = list(dict.fromkeys(list(existing.columns) + list(new_df.columns)))
    existing = existing.reindex(columns=all_cols)
    new_df = new_df.reindex(columns=all_cols)

    # Drop existing rows whose id_cols match any row in new_df (so we replace)
    if all(c in existing.columns and c in new_df.columns for c in id_cols):
        merge_key = existing[id_cols].astype(str).agg('|'.join, axis=1)
        new_key = set(new_df[id_cols].astype(str).agg('|'.join, axis=1).tolist())
        kept = existing.loc[~merge_key.isin(new_key)].copy()
    else:
        kept = existing.copy()

    merged = pd.concat([kept, new_df], ignore_index=True)
    merged.to_parquet(parquet_path, index=False)
    return merged


def _get_beta_close_prices() -> dict[str, float]:
    """Return {asset_name_prefix: last_factor_level} for Beta-Book close prices.

    Uses the most-recent row of the risk-factor level time series as a proxy.
    IR / Spread factors are reported in %; FX / Commodity not yet supported.
    """
    try:
        loader = RiskFactorLoader(DIR_INPUT)
        factor_levels = loader.load_risk_factors(use_cache=True)
        if factor_levels is None or factor_levels.empty:
            return {}
        last_row = factor_levels.iloc[-1]
        return {
            prefix: round(float(last_row[factor]), 4)
            for prefix, factor in _ASSET_PREFIX_TO_FACTOR.items()
            if factor in last_row.index and pd.notna(last_row[factor])
        }
    except Exception:
        return {}
