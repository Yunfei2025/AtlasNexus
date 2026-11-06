# -*- coding: utf-8 -*-
"""Futures Desk: daily intraday-futures workflow (Today / Research / Monitor)."""

from .layout import build_futures_desk_layout
from .pool_corr import register_pool_corr_callbacks
from .research import register_research_callbacks
from .today import register_today_callbacks
from .live_ui import register_live_callbacks
from .monitor_ui import register_monitor_callbacks


def register_futures_desk_callbacks(app):
    """Register every callback used by the Futures Desk tab (idempotent)."""
    if getattr(app, "_atlasnexus_futures_desk_callbacks_registered", False):
        return
    app._atlasnexus_futures_desk_callbacks_registered = True
    from web.tabs.beta.callbacks.backtest_futures import register_backtest_futures_callbacks
    register_backtest_futures_callbacks(app)
    register_pool_corr_callbacks(app)
    register_research_callbacks(app)
    register_today_callbacks(app)
    register_monitor_callbacks(app)
    register_live_callbacks(app)


__all__ = ["build_futures_desk_layout", "register_futures_desk_callbacks"]
