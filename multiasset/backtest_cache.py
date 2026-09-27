# -*- coding: utf-8 -*-
"""
Disk cache for the Beta Book historical portfolio backtest
(web/tabs/beta/callbacks/backtest_hist/orchestrator.py).

Only ONE piece is cached — the expensive part:

  - beta_rp_cache.pkl   one shared cache of RP weights (Stage 1's SLSQP ERC
                        solve) AND each rebalance date's Stage2Context (see
                        multiasset.factor_optimizer), per rebalance date,
                        keyed by a hash of RP-only params.

Per-factor tilted-weight caching (formerly beta_factor_tilt_cache.pkl,
FactorTiltCacheParams / factor_hash / load_factor_tilt / save_factor_tilt)
was REMOVED in docs/plans/beta_book_exposure_vs_capital.md Step 4: daily
factor-scaling resizing (multiasset.book.sizing) recomputes the cheap
Stage-2 tenor tilt (a closed-form solve, ~24us/group) directly from the
cached Stage2Context on every call — measured at ~0.03s for a full
multi-year daily backtest, which is faster than loading/pruning/rewriting a
multi-MB pickle cache would have been, and the cache would otherwise have
needed to store an (n_factors x n_days x n_assets) cube per version. A
`beta_factor_tilt_cache.pkl` file from before this change may still exist
on disk; it is simply never read any more (nothing auto-deletes it).

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
    tilt_lambda: Optional[float] = None
    risk_budgets_repr: Optional[str] = None
    hedge_asset_names: tuple = field(default_factory=tuple)
    neutral_asset_names: tuple = field(default_factory=tuple)
    bounds_version: str = "RiskModelConfig.v3"
    # Bumped whenever the factor-level return convention that
    # compute_ewma_factor_vols/compute_ewma_factor_covariance feed into
    # Stage 1's ERC solve changes — e.g. Step 3 of
    # docs/plans/beta_book_exposure_vs_capital.md, which made factor-level
    # returns price-only (previously IRDL/SPDL/CRDL included carry). Without
    # this, a cached RP base computed under the old convention would be
    # silently reused and the carry-removal change would be invisible.
    returns_convention: str = "price_only_v1"
    # Bumped whenever Stage 1's budgeting scheme changes. "volsqrt_v1":
    # use_vol_sqrt_budgets now actually pins slope/curve budgets to level by
    # sqrt(vol) inside the SLSQP solve (it was previously a no-op flag), so
    # entries cached under the same use_vol_sqrt_budgets=True key before that
    # change hold plain-ERC weights and must not be reused.
    stage1_scheme: str = "volsqrt_v1"


def _stable_hash(obj) -> str:
    """Stable hash of a frozen dataclass instance: sorted-key JSON + sha256."""
    payload = json.dumps(asdict(obj), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]


def rp_hash(params: RPCacheParams) -> str:
    return _stable_hash(params)


def scalar_to_coeff(scalar: float, factor_name: str) -> float:
    """
    Convert a factor signal scalar into an asset allocation coefficient.

    Long-only factors (IRDL, CMDL, EQDL, SPDL, SPSL):
      coeff = max(0, min(2.0, 1 + scalar))
    Directional factors (IRSL, IRCV, FXDL):
      coeff = max(-1.5, min(1.5, scalar))

    FXDL is directional (not long-only) because a currency view is inherently
    two-sided: a bearish FactorModel signal on USDCNY should be expressible as
    a short, not just a shrink-to-zero long. Direction and size both come from
    the signal — a Pure Risk Parity base has no signal, so it stays long-only/
    flat via the trend-veto in backtest_hist/_signals.py instead of this function.

    The clip bounds below are no longer cache-keyed (the old per-factor
    tilt cache was removed — see module docstring), since the daily
    resizing path recomputes this on every call anyway; changing them
    simply takes effect on the next run.
    """
    factor_prefix = factor_name.split('.')[0] if '.' in factor_name else factor_name
    if factor_prefix in ('IRSL', 'IRCV', 'FXDL'):
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
    """Returns None (cache miss) if the cached entry predates
    ``stage2_ctx_by_date`` being saved (see save_rp) — an older cache entry
    can't half-hydrate a caller that needs the context for daily resizing
    (docs/plans/beta_book_exposure_vs_capital.md Step 4); it's simpler and
    safer to force a full recompute than to reconstruct it after the fact.
    """
    h = rp_hash(params)
    cache = _load_pkl(_pkl_path(input_dir, 'beta_rp_cache.pkl'))
    entry = cache.get(h)
    if entry is not None and 'stage2_ctx_by_date' not in entry:
        return None
    # Contexts pickled before Stage2Context gained asset_class_of can't be
    # consumed by the staticmethod rebuild_asset_weights — treat as a miss.
    if entry is not None and any(
        ctx is not None and not hasattr(ctx, 'asset_class_of')
        for ctx in entry['stage2_ctx_by_date'].values()
    ):
        return None
    return entry


def save_rp(input_dir, params: RPCacheParams, weights_by_date: pd.DataFrame,
            asset_pools_by_date: dict, screened_factors_by_date: dict,
            last_corr_matrix=None, stage2_ctx_by_date: Optional[dict] = None) -> str:
    """``stage2_ctx_by_date``: {rebalance_date -> Stage2Context | None},
    one entry per successful rebalance date in weights_by_date — None on
    dates where fit_and_calculate took the _optimize_weights branch instead
    of the two-stage path (Stage2Context wasn't populated there). Consumed
    by the daily-resizing loop (Step 4) to rebuild per-tenor weights with a
    rescaled factor budget without re-running Stage 1's SLSQP solve.
    Stage2Context is a plain frozen dataclass of numpy arrays / dicts /
    tuples, so it pickles the same way weights_by_date already does.
    """
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
        'stage2_ctx_by_date': stage2_ctx_by_date or {},
    }
    cache = _prune_lru(cache, key_fn=lambda k: True, max_versions=_MAX_VERSIONS_PER_FAMILY)
    pd.to_pickle(cache, path)
    return h
