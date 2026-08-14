# -*- coding: utf-8 -*-
"""Backtest engines and results display for the Alpha Book tabs.

Public API (preserved for back-compat with `from .backtest import …`):
    - run_spread_backtest      — mean-reversion engine
    - run_trend_backtest       — trend / z-momentum hysteresis engine
    - run_trend_backtest_dc    — backward-compatible alias
    - run_new_issue_backtest   — BondNewIssue walk-forward cohort event engine
    - build_backtest_results_display — Dash UI renderer
"""

from .engine_mr import run_spread_backtest
from .engine_trend import run_trend_backtest, run_trend_backtest_dc, _dc_trend_state
from .engine_event import run_new_issue_backtest
from .engine_monthly import (
    build_monthly_style_schedule, canonical_style, run_monthly_style_backtest,
)
from .display import build_backtest_results_display

__all__ = [
    "run_spread_backtest",
    "run_trend_backtest",
    "run_trend_backtest_dc",
    "_dc_trend_state",
    "run_new_issue_backtest",
    "run_monthly_style_backtest",
    "build_monthly_style_schedule",
    "canonical_style",
    "build_backtest_results_display",
]
