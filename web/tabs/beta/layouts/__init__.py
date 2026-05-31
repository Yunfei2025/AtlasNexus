# -*- coding: utf-8 -*-
"""Layout builders for the Multi-Asset (beta) Dashboard tabs.

Public API preserved:
    build_multiasset_factor_layout, build_multiasset_portfolio_layout,
    build_multiasset_bond_layout, build_multiasset_risk_layout,
    build_multiasset_backtest_layout, build_risk_factor_backtest_layout,
    build_factor_backtest_layout

Also re-exports _build_bond_signal_cards for the bond callback's use.
"""

from .factor import build_multiasset_factor_layout
from .portfolio import build_multiasset_portfolio_layout
from .bond import build_multiasset_bond_layout
from .risk import build_multiasset_risk_layout
from .backtest import (
    build_multiasset_backtest_layout,
    build_risk_factor_backtest_layout,
    build_factor_backtest_layout,
    build_beta_backtest_combined_layout,
    build_factor_history_layout,
)
from ._bond_signals import _build_bond_signal_cards

__all__ = [
    "build_multiasset_factor_layout",
    "build_multiasset_portfolio_layout",
    "build_multiasset_bond_layout",
    "build_multiasset_risk_layout",
    "build_multiasset_backtest_layout",
    "build_risk_factor_backtest_layout",
    "build_factor_backtest_layout",
    "build_beta_backtest_combined_layout",
    "build_factor_history_layout",
    "_build_bond_signal_cards",
]
