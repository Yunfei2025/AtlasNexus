# -*- coding: utf-8 -*-
"""Backtest engines and results display for the Alpha Book tabs.

Public API (preserved for back-compat with `from .backtest import …`):
    - run_spread_backtest      — mean-reversion engine
    - run_trend_backtest_dc    — trend / DC engine
    - run_regime_hybrid_backtest — point-in-time MR/trend switching engine
    - build_backtest_results_display — Dash UI renderer
"""

from .engine_mr import run_spread_backtest
from .engine_trend import run_trend_backtest_dc, _dc_trend_state
from .engine_hybrid import run_regime_hybrid_backtest
from .display import build_backtest_results_display

__all__ = [
    "run_spread_backtest",
    "run_trend_backtest_dc",
    "run_regime_hybrid_backtest",
    "build_backtest_results_display",
]
