"""Lightweight style constants for AtlasNexus apps.

We avoid importing `web.core` here because `web.core.__init__` eagerly loads
large pickles and data.

The CSS classes referenced (e.g. app__header, app__container) are provided
by existing assets in `web/assets/`.
"""

from __future__ import annotations

from typing import Any, Dict

# Mirror the style objects used by web/core/styles.py and fi.py

tabs_styles: Dict[str, Any] = {
    "zIndex": 99,
    "background": "#082255",
    "border": "grey",
    "border-radius": "4px",
}

tab_selected_style: Dict[str, Any] = {
    "background": "#082255",
    "text-transform": "uppercase",
    "color": "white",
    "border": "grey",
    "font-size": "14px",
    "font-weight": 600,
    "align-items": "center",
    "justify-content": "center",
    "border-radius": "4px",
    "padding": "6px",
}

tab_style: Dict[str, Any] = {
    "background": "#425476",
    "text-transform": "uppercase",
    "color": "white",
    "font-size": "14px",
    "font-weight": 600,
    "align-items": "center",
    "justify-content": "center",
    "border-radius": "4px",
    "padding": "6px",
    "border-style": "solid",
    "border-color": "#061E44",
}
