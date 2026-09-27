# -*- coding: utf-8 -*-
"""Portfolio (Allocation) tab — analysis & risk callbacks.

Package split from the original single-file portfolio_run.py, whose
`register_portfolio_run_callbacks` was one ~940-line function holding 8
callbacks (including the ~285-line risk-budget row builder and the
~390-line Run Analysis optimisation callback). Public API unchanged:
callers still do
`from .portfolio_run import register_portfolio_run_callbacks`
(or `from web.tabs.beta.callbacks.portfolio_run import ...`).

Contains:
  3.6 Risk Factor Budget Input Generator
  3.7 Factor Model Signals refresh & render
  3.8 Mode status hint
  4.  Run Analysis (Portfolio Tab → Results) — the main optimisation callback
  IRDL Hedge Overlay
"""

from __future__ import annotations

from .register import register_portfolio_run_callbacks

__all__ = ["register_portfolio_run_callbacks"]
