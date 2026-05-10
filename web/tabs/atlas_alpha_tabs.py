# -*- coding: utf-8 -*-
"""Backwards-compatible re-export shim.

The implementation has been split into web/tabs/alpha/ submodules:
  data.py      – constants, loaders, _tenor_to_duration
  scoring.py   – correlation, risk-parity, candidate scoring
  backtest.py  – carry/trend backtests, results display
  layouts.py   – Dash layout builders
  callbacks.py – register_alpha_callbacks(app)
"""
from web.tabs.alpha.data import *  # noqa: F401, F403
from web.tabs.alpha.scoring import *  # noqa: F401, F403
from web.tabs.alpha.layouts import (  # noqa: F401
    build_candidates_layout,
    build_portfolio_layout,
    build_basket_layout,
    build_backtest_layout,
    build_individual_backtest_panel,
    build_portfolio_backtest_panel,
    build_diversified_trades_display,
)
from web.tabs.alpha.backtest import (  # noqa: F401
    run_spread_backtest,
    run_trend_backtest_dc,
    build_backtest_results_display,
)
from web.tabs.alpha.callbacks import register_alpha_callbacks  # noqa: F401
