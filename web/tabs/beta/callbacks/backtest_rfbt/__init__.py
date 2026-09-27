# -*- coding: utf-8 -*-
"""Risk-factor backtest (RFBT) callbacks: parameter panels, generate
factor-rates.pkl, and run the factor-model backtest.

Package split from the original single-file backtest_rfbt.py (which was one
~1050-line `register_backtest_rfbt_callbacks` function holding 8 nested
callbacks). Public API unchanged: callers still do
`from .backtest_rfbt import register_backtest_rfbt_callbacks` (or
`from web.tabs.beta.callbacks.backtest_rfbt import ...`).
"""

from .register import register_backtest_rfbt_callbacks

__all__ = ["register_backtest_rfbt_callbacks"]
