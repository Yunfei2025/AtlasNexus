# -*- coding: utf-8 -*-
"""Risk / Summary tab callbacks: subtab show/hide, books table refresh.

This module used to contain all Summary/Risk callbacks in one ~2500-line
file. It is now a thin orchestrator that dispatches to sibling modules,
split by subtab for maintainability:

  - risk_helpers.py    shared (non-Dash) helper functions: parquet
                       loaders/persisters, tenor/leg resolution.
  - risk_books.py      Summary > Books subtab (Beta + Alpha allocation
                       tables, book toggle, column-visibility pills,
                       inline edit/delete/open-date callbacks).
  - risk_tickets.py    Summary > Tickets subtab.
  - risk_dashboard.py  Summary > Risk subtab (KPI strip, Net Position by
                       Instrument, DV01 Duration Ladder, Factor Risk
                       Attribution, Position Inventory).

`register_risk_callbacks(app)` is preserved as the single public entry
point so `web/tabs/beta/callbacks/__init__.py` needs no changes.
"""

from __future__ import annotations

from .risk_books import register_risk_books_callbacks
from .risk_tickets import register_risk_tickets_callbacks
from .risk_dashboard import register_risk_dashboard_callbacks


def register_risk_callbacks(app):
    """Register every Risk / Summary tab callback (Books + Tickets + Risk)."""
    register_risk_books_callbacks(app)
    register_risk_tickets_callbacks(app)
    register_risk_dashboard_callbacks(app)
