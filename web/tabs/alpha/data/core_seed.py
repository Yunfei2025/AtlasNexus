# -*- coding: utf-8 -*-
"""Cached seed list of the Alpha core (default TenorSpread) book's membership,
for diversifying satellite candidates against the actual core -- not just
against each other.

See docs/plans/portfolio_construction_beta_alpha.md §5.2.

Two different things were being conflated before this module existed:
  - The core book's *membership* (which instruments) is structurally stable
    -- it only changes when an instrument crosses
    ``build_default_category_portfolio``'s ``min_history_days`` threshold or
    drops out of the universe; day to day it's the same ~14 instruments even
    though each one's BUY/SELL direction flips with its current z-score sign.
    Rebuilding this on every "Check Correlation" click is unnecessary churn.
  - The correlation matrix computed *against* that membership should stay
    live, using current price history on whatever lookback the user picked --
    unchanged from today.

This module only caches the former: a list of ``{spread_type, ID}`` pairs,
refreshed on a time-based expiry (default 90 days / quarterly), not on every
page load and not requiring a manual trigger.

Schema (single pickle, ``DIR_INPUT / 'alpha_core_seed.pkl'``):
    {
        'built_at': pd.Timestamp,     # when this snapshot was built
        'spread_type': str,           # 'TenorSpread' -- the core category
        'instruments': list[dict],    # [{'spread_type': ..., 'ID': ...}, ...]
    }
"""

from __future__ import annotations

import pickle
from typing import Optional

import pandas as pd

from .io import _get_input_dir, _load_pickle_cached

_SEED_FILENAME = 'alpha_core_seed.pkl'
_CORE_SPREAD_TYPE = 'TenorSpread'

# Quarterly refresh -- core book membership moves slowly (§5.2 rationale
# above); a shorter cadence would just mean the same rebuild for no benefit,
# a much longer one risks the seed drifting from a universe that has actually
# changed (new long-history instrument, one dropped out).
CORE_SEED_MAX_AGE_DAYS = 90


def _seed_path():
    return _get_input_dir() / _SEED_FILENAME


def _build_core_seed(spread_type: str = _CORE_SPREAD_TYPE) -> list[dict]:
    """Build a fresh seed list from the live default category portfolio.

    Only ``spread_type``/``ID`` are kept -- direction, weight, and Zscore are
    per-day outputs of the core book and not part of what the correlation
    check needs from a "membership" seed.
    """
    from ..scoring import build_default_category_portfolio

    try:
        records = build_default_category_portfolio(spread_type)
    except Exception:
        return []
    return [
        {'spread_type': str(r.get('spread_type', spread_type)), 'ID': str(r.get('ID', ''))}
        for r in records
        if r.get('ID')
    ]


def load_core_seed(
    spread_type: str = _CORE_SPREAD_TYPE,
    max_age_days: int = CORE_SEED_MAX_AGE_DAYS,
) -> list[dict]:
    """Return the cached core book seed list, rebuilding it if missing/expired.

    Rebuild triggers: no cache file yet, the cached category doesn't match
    ``spread_type``, or the cache is older than ``max_age_days``. Otherwise
    the persisted list is returned as-is -- no per-call recomputation of the
    (expensive) default category portfolio.
    """
    cached = _load_pickle_cached(_seed_path())
    if isinstance(cached, dict) and cached.get('spread_type') == spread_type:
        built_at = cached.get('built_at')
        if isinstance(built_at, pd.Timestamp):
            age_days = (pd.Timestamp.now() - built_at).days
            if age_days < max_age_days:
                return list(cached.get('instruments') or [])

    instruments = _build_core_seed(spread_type)
    payload = {
        'built_at': pd.Timestamp.now(),
        'spread_type': spread_type,
        'instruments': instruments,
    }
    try:
        with open(_seed_path(), 'wb') as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass
    return instruments


def core_seed_age_days(spread_type: str = _CORE_SPREAD_TYPE) -> Optional[int]:
    """Age in days of the current cached seed, or None if there is none yet."""
    cached = _load_pickle_cached(_seed_path())
    if not isinstance(cached, dict) or cached.get('spread_type') != spread_type:
        return None
    built_at = cached.get('built_at')
    if not isinstance(built_at, pd.Timestamp):
        return None
    return (pd.Timestamp.now() - built_at).days
