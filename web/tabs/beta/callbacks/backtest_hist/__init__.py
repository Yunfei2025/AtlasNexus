# -*- coding: utf-8 -*-
"""Historical allocation backtest callbacks (Backtest tab: factor pool display,
date info, and historical correlation-based analysis chart).

Package split from the original single-file backtest_hist.py — see
docs/plans/beta_book_exposure_vs_capital.md Step 1. Public API unchanged:
callers still do `from .backtest_hist import register_backtest_hist_callbacks`
(or `from web.tabs.beta.callbacks.backtest_hist import ...`).
"""

from .register import register_backtest_hist_callbacks

__all__ = ["register_backtest_hist_callbacks"]
