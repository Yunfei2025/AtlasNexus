# -*- coding: utf-8 -*-
"""Disk cache for the Individual Factors ("RFBT") Run Backtest callback.

Mirrors multiasset/backtest_cache.py's pattern (frozen dataclass params ->
sha256 of sorted-key JSON -> pkl keyed by hash), but for the walk-forward
FactorModel backtest run from web/tabs/beta/callbacks/backtest_rfbt: keys on
every input that determines run_factor_backtest's output (factor, date
range, FactorModelConfig kwargs) so that re-clicking Run Backtest with
unchanged params loads the cached (results, models_by_month) instead of
re-running the multi-minute walk-forward retrain.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Callable, Optional

import pandas as pd

_MAX_VERSIONS_PER_FAMILY = 20
_CACHE_FILENAME = 'rfbt_run_cache.pkl'


@dataclass(frozen=True)
class RfbtCacheParams:
    """Params that fully determine run_rfbt_backtest's output for one factor."""
    factor: str = ''
    start_date: str = ''
    end_date: str = ''
    kwargs_repr: str = ''  # sorted-key JSON of build_factor_model_kwargs(...)


def _stable_hash(obj) -> str:
    payload = json.dumps(asdict(obj), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]


def rfbt_hash(params: RfbtCacheParams) -> str:
    return _stable_hash(params)


def make_cache_params(factor_val, start_date, end_date, kwargs) -> RfbtCacheParams:
    kwargs_repr = json.dumps(kwargs, sort_keys=True, default=str)
    return RfbtCacheParams(
        factor=factor_val, start_date=start_date, end_date=end_date,
        kwargs_repr=kwargs_repr,
    )


def _pkl_path(input_dir) -> str:
    return os.path.join(str(input_dir), _CACHE_FILENAME)


def _load_pkl(path: str) -> dict:
    if os.path.exists(path):
        try:
            return pd.read_pickle(path)
        except Exception:
            return {}
    return {}


def _prune_lru(entries: dict, max_versions: int) -> dict:
    if len(entries) <= max_versions:
        return entries
    ordered = sorted(entries.items(), key=lambda kv: kv[1].get('created', ''), reverse=True)
    keep = {k for k, _ in ordered[:max_versions]}
    return {k: v for k, v in entries.items() if k in keep}


def load_rfbt_run(input_dir, params: RfbtCacheParams) -> Optional[dict]:
    """Returns None (cache miss) if no entry matches the current params hash."""
    h = rfbt_hash(params)
    cache = _load_pkl(_pkl_path(input_dir))
    return cache.get(h)


def save_rfbt_run(input_dir, params: RfbtCacheParams, results, models_by_month) -> str:
    h = rfbt_hash(params)
    path = _pkl_path(input_dir)
    cache = _load_pkl(path)
    cache[h] = {
        'params': asdict(params),
        'created': datetime.now().isoformat(),
        'results': results,
        'models_by_month': models_by_month,
    }
    cache = _prune_lru(cache, _MAX_VERSIONS_PER_FAMILY)
    pd.to_pickle(cache, path)
    return h
