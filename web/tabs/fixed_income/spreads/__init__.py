# -*- coding: utf-8 -*-
"""Spread Analysis tab (Alpha Book > Spread subtab).

Package split from the original single-file spreads.py, whose
`register_spreads_callbacks` was one ~1160-line function holding every
callback plus several inline figure-building closures. Public API
unchanged: callers still do
`from .spreads import build_spreads_layout, register_spreads_callbacks`
(or `from web.tabs.fixed_income.spreads import ...`).
"""

from __future__ import annotations

from ._layout import build_spreads_layout
from .register import register_spreads_callbacks

__all__ = ["build_spreads_layout", "register_spreads_callbacks"]
