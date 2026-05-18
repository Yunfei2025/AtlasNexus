# -*- coding: utf-8 -*-
"""Dash callback registration for the Multi-Asset (Beta) Dashboard.

Single entry point preserved for back-compat: `register_multiasset_callbacks(app)`.
Internally dispatches to per-section register_* functions in this package.
"""

from .factor import register_factor_callbacks
from .portfolio_pool import register_portfolio_pool_callbacks
from .portfolio_run import register_portfolio_run_callbacks
from .bond import register_bond_callbacks
from .backtest_hist import register_backtest_hist_callbacks
from .backtest_futures import register_backtest_futures_callbacks
from .backtest_rfbt import register_backtest_rfbt_callbacks
from .risk import register_risk_callbacks


def register_portfolio_callbacks(app):
    """Combined registration of both portfolio sub-modules (back-compat alias)."""
    register_portfolio_pool_callbacks(app)
    register_portfolio_run_callbacks(app)


def register_multiasset_callbacks(app):
    """Register every callback used by the Multi-Asset (Beta) Dashboard."""
    register_factor_callbacks(app)
    register_portfolio_pool_callbacks(app)
    register_portfolio_run_callbacks(app)
    register_bond_callbacks(app)
    register_backtest_hist_callbacks(app)
    register_backtest_futures_callbacks(app)
    register_backtest_rfbt_callbacks(app)
    register_risk_callbacks(app)


__all__ = [
    "register_multiasset_callbacks",
    "register_factor_callbacks",
    "register_portfolio_callbacks",
    "register_portfolio_pool_callbacks",
    "register_portfolio_run_callbacks",
    "register_bond_callbacks",
    "register_backtest_hist_callbacks",
    "register_backtest_futures_callbacks",
    "register_backtest_rfbt_callbacks",
    "register_risk_callbacks",
]
