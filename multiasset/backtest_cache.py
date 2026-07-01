# -*- coding: utf-8 -*-
"""
Disk cache for the Beta Book historical portfolio backtest
(web/tabs/beta/callbacks/backtest_hist.py).

Two pieces are cached independently so that adding a new factor to the
factor-scaling pool does not force a recompute of the pure risk-parity (RP)
base or of factors that were already computed:

  - beta_rp_cache.pkl         one shared cache of RP weights per rebalance
                              date, keyed by a hash of RP-only params.
  - beta_factor_tilt_cache.pkl  per-factor tilted-weight contributions,
                              keyed by (factor_code, factor_hash, rp_hash) so
                              a tilt automatically misses cache if its RP base
                              changed.

Cache keys are content hashes (sha256 of sorted-key JSON), not in-memory
`hash()`, because the cache must remain valid across process restarts and
`hash()` of Python objects is not stable across interpreter runs
(PYTHONHASHSEED). Stale entries are never actively deleted on param change;
they simply stop being looked up once the hash differs, and are pruned by an
LRU-by-creation-time cap so the file does not grow unbounded.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Callable, Optional

import pandas as pd

# Max number of versions kept per logical cache family before the oldest
# (by `created` timestamp) are evicted.
_MAX_VERSIONS_PER_FAMILY = 5


@dataclass(frozen=True)
class RPCacheParams:
    """Params that fully determine the pure risk-parity weight series."""
    rebalance_dates: tuple = field(default_factory=tuple)   # sorted ISO date strings
    corr_lookback: str = '3M'
    top_pairs: int = 10
    factor_pool: tuple = field(default_factory=tuple)        # sorted selected factor codes
    factor_model_lookback_years: float = 1.0
    ewma_lambda: float = 0.94
    use_vol_sqrt_budgets: bool = True
    use_dv01_shape: bool = True
    risk_budgets_repr: Optional[str] = None
    hedge_asset_names: tuple = field(default_factory=tuple)
    neutral_asset_names: tuple = field(default_factory=tuple)
    bounds_version: str = "RiskModelConfig.v1"


@dataclass(frozen=True)
class FactorTiltCacheParams:
    """Params that fully determine one factor's tilted-weight contribution."""
    factor_code: str = ''
    scalar_to_coeff_version: str = "v1"
    factor_to_asset_map_version: str = "v1"
    signal_pkl_mtime: float = 0.0
    class_caps_version: str = "RiskModelConfig.v1"


def _stable_hash(obj) -> str:
    """Stable hash of a frozen dataclass instance: sorted-key JSON + sha256."""
    payload = json.dumps(asdict(obj), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]


def rp_hash(params: RPCacheParams) -> str:
    return _stable_hash(params)


def factor_hash(params: FactorTiltCacheParams) -> str:
    return _stable_hash(params)


def scalar_to_coeff(scalar: float, factor_name: str) -> float:
    """
    Convert a factor signal scalar into an asset allocation coefficient.

    Long-only factors (IRDL, CMDL, FXDL, EQDL, SPDL, SPSL):
      coeff = max(0, min(2.0, 1 + scalar))
    Directional factors (IRSL, IRCV):
      coeff = max(-1.5, min(1.5, scalar))

    Bump FactorTiltCacheParams.scalar_to_coeff_version whenever the clip
    bounds below change, so cached tilts computed under the old bounds are
    never reused.
    """
    factor_prefix = factor_name.split('.')[0] if '.' in factor_name else factor_name
    if factor_prefix in ('IRSL', 'IRCV'):
        return max(-1.5, min(1.5, scalar))
    return max(0.0, min(2.0, 1.0 + scalar))


def _pkl_path(input_dir, filename: str) -> str:
    return os.path.join(str(input_dir), filename)


def _load_pkl(path: str) -> dict:
    if os.path.exists(path):
        try:
            return pd.read_pickle(path)
        except Exception:
            return {}
    return {}


def _prune_lru(entries: dict, key_fn: Callable[[object], bool], max_versions: int) -> dict:
    """Keep only the `max_versions` most-recently-created entries matching key_fn."""
    matching = [(k, v) for k, v in entries.items() if key_fn(k)]
    if len(matching) <= max_versions:
        return entries
    matching.sort(key=lambda kv: kv[1].get('created', ''), reverse=True)
    to_drop = {k for k, _ in matching[max_versions:]}
    return {k: v for k, v in entries.items() if k not in to_drop}


# ─────────────────────────── RP cache ───────────────────────────

def load_rp(input_dir, params: RPCacheParams) -> Optional[dict]:
    h = rp_hash(params)
    cache = _load_pkl(_pkl_path(input_dir, 'beta_rp_cache.pkl'))
    return cache.get(h)


def save_rp(input_dir, params: RPCacheParams, weights_by_date: pd.DataFrame,
            asset_pools_by_date: dict, screened_factors_by_date: dict,
            last_corr_matrix=None) -> str:
    h = rp_hash(params)
    path = _pkl_path(input_dir, 'beta_rp_cache.pkl')
    cache = _load_pkl(path)
    cache[h] = {
        'params': asdict(params),
        'created': datetime.now().isoformat(),
        'weights_by_date': weights_by_date,
        'asset_pools_by_date': asset_pools_by_date,
        'screened_factors_by_date': screened_factors_by_date,
        'last_corr_matrix': last_corr_matrix,
    }
    cache = _prune_lru(cache, key_fn=lambda k: True, max_versions=_MAX_VERSIONS_PER_FAMILY)
    pd.to_pickle(cache, path)
    return h


# ─────────────────────────── Factor tilt cache ───────────────────────────

def load_factor_tilt(input_dir, rp_h: str, params: FactorTiltCacheParams) -> Optional[dict]:
    key = (params.factor_code, factor_hash(params), rp_h)
    cache = _load_pkl(_pkl_path(input_dir, 'beta_factor_tilt_cache.pkl'))
    return cache.get(key)


def save_factor_tilt(input_dir, rp_h: str, params: FactorTiltCacheParams,
                      tilt_weights_by_date: pd.DataFrame) -> tuple:
    key = (params.factor_code, factor_hash(params), rp_h)
    path = _pkl_path(input_dir, 'beta_factor_tilt_cache.pkl')
    cache = _load_pkl(path)
    cache[key] = {
        'created': datetime.now().isoformat(),
        'tilt_weights_by_date': tilt_weights_by_date,
    }
    cache = _prune_lru(
        cache,
        key_fn=lambda k: k[0] == params.factor_code,
        max_versions=_MAX_VERSIONS_PER_FAMILY,
    )
    pd.to_pickle(cache, path)
    return key
