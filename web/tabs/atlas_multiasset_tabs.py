# -*- coding: utf-8 -*-
"""Backwards-compatible re-export shim.

The implementation has been split into web/tabs/beta/ submodules:
  data.py      – constants, global state, loaders
  backtest.py  – placeholder, re-exports from data
  layouts.py   – Dash layout builders
  callbacks.py – register_multiasset_callbacks(app)
"""
from web.tabs.beta.data import *  # noqa: F401, F403
from web.tabs.beta.layouts import (  # noqa: F401
    build_multiasset_factor_layout,
    build_multiasset_portfolio_layout,
    build_multiasset_bond_layout,
    build_multiasset_risk_layout,
    build_multiasset_backtest_layout,
    build_risk_factor_backtest_layout,
    build_factor_backtest_layout,
)
from web.tabs.beta.callbacks import register_multiasset_callbacks  # noqa: F401
