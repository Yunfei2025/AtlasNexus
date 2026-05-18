# -*- coding: utf-8 -*-
"""Backtest engines and results display for the Alpha Book tabs.

Public API (preserved for back-compat with `from .backtest import …`):
    - run_spread_backtest      — mean-reversion engine
    - run_trend_backtest_dc    — trend / DC engine
    - build_backtest_results_display — Dash UI renderer
"""

from .engine_mr import run_spread_backtest
from .engine_trend import run_trend_backtest_dc, _dc_trend_state
from .display import build_backtest_results_display

__all__ = [
    "run_spread_backtest",
    "run_trend_backtest_dc",
    "build_backtest_results_display",
]
