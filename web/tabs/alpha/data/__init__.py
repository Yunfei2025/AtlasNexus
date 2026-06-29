# -*- coding: utf-8 -*-
"""Constants, data loaders, and duration helpers for the Alpha Book tabs.

Split into submodules for size; re-exported here so existing
``from web.tabs.alpha.data import ...`` call sites keep working unchanged:
  - constants: THEME, SPREAD_CATEGORIES, SPREAD_TYPE_OPTIONS, thresholds
  - io: pickle cache, repo-label normalization, input dir resolution
  - loaders: load_spread_data, load_spread_timeseries, load_realtime_spreads, ...
  - duration: duration multiplier, borrow cost, tenor yields, TTM display
  - legs: resolve_legs and supporting leg-parsing helpers
"""

from __future__ import annotations

from .constants import (
    THEME,
    SPREAD_CATEGORIES,
    SPREAD_TYPE_OPTIONS,
    YIELD_BASED_SPREAD_TYPES,
    ZSCORE_ENTRY_THRESHOLD,
    ZSCORE_EXIT_THRESHOLD,
    MAX_CORRELATION_THRESHOLD,
    MACRO_PREFIX,
    DIVERSIFIED_TRADE_RECOMMENDATIONS,
    _SWAP_SPREAD_BUTTERFLY_PATTERN,
    _exclude_swapspread_butterflies,
    _build_tenor_spread_timeseries,
)
from .io import (
    _get_input_dir,
    _normalize_repo_label,
    _normalize_repo_obj,
    _normalize_repo_frame,
    _load_pickle_cached,
    _load_pickle_safe,
    _PICKLE_CACHE,
)
from .loaders import (
    load_spread_data,
    load_carry_roll_timeseries,
    display_key,
    load_spread_timeseries,
    load_macro_series,
    load_realtime_spreads,
    get_spread_style,
)
from .duration import (
    _tenor_to_duration,
    _get_duration_mult,
    _get_borrow_cost_annual_bp,
    _get_tenor_yields_for_spread,
    _get_current_fr007_bp,
    _get_ttm_display,
)
from .legs import (
    _parse_repo_spread_legs,
    _tenor_str_to_years,
    _load_leg_data,
    resolve_legs,
)

__all__ = [
    'THEME',
    'SPREAD_CATEGORIES',
    'SPREAD_TYPE_OPTIONS',
    'YIELD_BASED_SPREAD_TYPES',
    'ZSCORE_ENTRY_THRESHOLD',
    'ZSCORE_EXIT_THRESHOLD',
    'MAX_CORRELATION_THRESHOLD',
    'MACRO_PREFIX',
    'DIVERSIFIED_TRADE_RECOMMENDATIONS',
    'load_spread_data',
    'load_carry_roll_timeseries',
    'display_key',
    'load_spread_timeseries',
    'load_macro_series',
    'load_realtime_spreads',
    'get_spread_style',
    'resolve_legs',
]
