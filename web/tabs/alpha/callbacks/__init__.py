# -*- coding: utf-8 -*-
"""Dash callback registration for the Alpha Book tabs.

Single entry point preserved for back-compat: `register_alpha_callbacks(app)`.
Internally dispatches to per-section register_* functions in this package.
"""

from .candidates import register_candidate_callbacks
from .portfolio import register_portfolio_callbacks
from .backtest_tab import register_backtest_callbacks


def register_alpha_callbacks(app) -> None:
    """Register every callback used by the Alpha Book tabs."""
    register_candidate_callbacks(app)
    register_portfolio_callbacks(app)
    register_backtest_callbacks(app)


__all__ = [
    "register_alpha_callbacks",
    "register_candidate_callbacks",
    "register_portfolio_callbacks",
    "register_backtest_callbacks",
]
