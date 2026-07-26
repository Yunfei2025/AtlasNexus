# -*- coding: utf-8 -*-
"""Risk / Summary tab callbacks: subtab show/hide, books table refresh.

This module used to contain all Summary/Risk callbacks in one ~2500-line
file. It is now a thin orchestrator that dispatches to sibling modules,
split by subtab for maintainability:

  - helpers.py          shared non-Dash functions: parquet loaders/persisters,
                         tenor/leg resolution.
  - books/              Summary > Books subtab callbacks.
  - tickets.py          Summary > Tickets subtab.
  - dashboard.py        Summary > Risk subtab (KPI strip, Net Position by
                       Instrument, DV01 Duration Ladder, Factor Risk
                       Attribution, Position Inventory).

`register_risk_callbacks(app)` is the package-level registration entry point.
"""

from __future__ import annotations

from .books import register_risk_books_callbacks
from .dashboard import register_risk_dashboard_callbacks
from .tickets import register_risk_tickets_callbacks


def register_risk_callbacks(app):
    """Register every Risk / Summary tab callback (Books + Tickets + Risk)."""
    register_risk_books_callbacks(app)
    register_risk_tickets_callbacks(app)
    register_risk_dashboard_callbacks(app)
