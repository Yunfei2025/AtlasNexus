# -*- coding: utf-8 -*-
"""Compatibility entry point for Alpha Candidates callbacks.

The implementation is organized by responsibility in sibling modules:
``helpers`` for shared data logic, ``scan_callbacks`` for scanning, and
``correlation_callbacks`` / ``portfolio_callbacks`` for their respective UI
workflows.  This module retains the original public registration function.
"""

from .helpers import (
    _apply_seasonal_quality_gate,
    _get_upstream_regime,
    _load_alpha_book_positions,
    _load_seasonal_screener,
    _merge_curated_entries,
    _normalize_curated_entry,
    _style_to_regime,
)
from .correlation_callbacks import register_correlation_callbacks
from .portfolio_callbacks import register_portfolio_callbacks
from .scan_callbacks import register_scan_callbacks


def register_candidate_callbacks(app) -> None:
    """Register all callbacks used by the Alpha Candidates workflow."""
    register_scan_callbacks(app)
    register_correlation_callbacks(app)
    register_portfolio_callbacks(app)


__all__ = [
    'register_candidate_callbacks',
    '_apply_seasonal_quality_gate',
    '_get_upstream_regime',
    '_load_alpha_book_positions',
    '_load_seasonal_screener',
    '_merge_curated_entries',
    '_normalize_curated_entry',
    '_style_to_regime',
]
