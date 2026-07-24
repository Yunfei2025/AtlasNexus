"""Lightweight access to the legacy FI dashboard tab content.

Goal:
- Reuse the proven tab UIs from `web.core.content` (Spread Info / Curves / Pairs)
  inside the new AtlasNexus Daily console.
- Avoid importing `web.core` at module import time because `web.core.__init__`
  triggers heavy data loads.

Design:
- Provide small wrapper functions returning layout components.
- Provide a `register_callbacks(app)` function so callbacks used by these layouts
  are registered onto the *AtlasNexus app instance*.

Notes:
- `web.core.content` defines callbacks at import time using `web.core.server.app`.
  That app is a different Dash instance than AtlasNexus.
- We cannot safely import that module and expect callbacks to bind to our app.
  Instead, we re-implement only the required callbacks here, by copying minimal
  logic and switching decorators to use `app.callback`.

This module is a thin facade over the per-tab modules below, kept for backward
compatibility with existing imports (`from web.tabs.atlas_fi_tabs import ...`):

- `atlas_fi_common.py`  -- shared small UI helpers (e.g. `_fi_card_header`)
- `atlas_fi_spreads.py` -- Spread Analysis tab layout + callbacks
- `atlas_fi_curves.py`  -- Curves tab layout + callbacks
- `atlas_fi_pairs.py`   -- Pairs tab layout + callbacks
- `atlas_fi_surface.py` -- Surface (yield surface) tab layout + callbacks
"""

from __future__ import annotations

from web.tabs.atlas_fi_curves import build_curves_layout, register_curves_callbacks
from web.tabs.atlas_fi_pairs import build_pairs_layout, register_pairs_callbacks
from web.tabs.atlas_fi_spreads import build_spreads_layout, register_spreads_callbacks
from web.tabs.atlas_fi_surface import build_surface_layout, register_surface_callbacks

__all__ = [
    "build_spreads_layout",
    "build_curves_layout",
    "build_pairs_layout",
    "build_surface_layout",
    "register_callbacks",
]


def register_callbacks(app) -> None:
    """Register the callbacks required by the migrated layouts onto `app`."""
    register_surface_callbacks(app)
    register_spreads_callbacks(app)
    register_curves_callbacks(app)
    register_pairs_callbacks(app)
