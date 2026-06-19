"""Lightweight style constants for AtlasNexus apps.

We avoid importing `web.core` here because `web.core.__init__` eagerly loads
large pickles and data.

The CSS classes referenced (e.g. app__header, app__container) are provided
by existing assets in `web/assets/`.
"""

from __future__ import annotations

from typing import Any, Dict

# Mirror the style objects used by web/core/styles.py and fi.py

# Single source of truth for the navy ramp + signal colors. Mirrors the
# :root tokens in web/assets/z_atlasnexus-design.css (--an-*).
TOKENS: Dict[str, str] = {
    "navy_900": "#040f30", "navy_800": "#082255", "navy_700": "#0c2b64",
    "navy_600": "#112e66", "navy_500": "#1a3a6e", "navy_400": "#2a5298",
    "navy_300": "#425476",
    "blue":     "#2e86c1", "cyan":     "#45b6e6",
    "green":    "#27ae60", "amber":    "#f39c12",
    "red":      "#c0392b", "purple":   "#8e44ad",
    "text":     "#ffffff", "muted":    "#aab0c0", "faint": "#5a6478",
}

# Per-book accent colors — keep in sync with .an-subtab--* classes and the
# --book-accent CSS variable injected by _set_book_accent in atlasnexus_daily.py.
BOOK_ACCENT: Dict[str, str] = {
    "market":     TOKENS["blue"],
    "beta":       TOKENS["blue"],
    "alpha":      TOKENS["amber"],
    "risk":       TOKENS["green"],
    "run-center": TOKENS["purple"],
}

# Top-level app tabs (Market/Beta Book/Alpha Book/...) and sub-tabs are
# styled via CSS classes — see .an-tabs / .an-tab / .an-tab--selected and
# .an-subtab / .an-subtab--selected in web/assets/z_atlasnexus-design.css.
# Use className="an-tabs" / "an-tab" / "an-tab--selected" on dcc.Tabs/dcc.Tab,
# and className="an-subtab" / selected_className="an-subtab--selected" on
# sub-tabs, instead of inline style dicts.

summary_subtabs_style: Dict[str, Any] = {
    "marginBottom": "16px",
}

summary_subtabs_colors: Dict[str, Any] = {
    "border": "#061E44",
    "primary": "#3498db",
    "background": "#112e66",
}

# ---------------------------------------------------------------------------
# Plotly figure layout defaults
#
# Apply to any figure with:
#   fig.update_layout(**PLOTLY_LAYOUT_DEFAULTS)
#
# Or register once globally in the app entry-point:
#   import plotly.io as pio
#   from web.tabs.atlas_styles import ATLAS_PLOTLY_TEMPLATE
#   pio.templates["atlas"] = ATLAS_PLOTLY_TEMPLATE
#   pio.templates.default = "plotly_dark+atlas"
# ---------------------------------------------------------------------------
import plotly.graph_objects as go  # noqa: E402

PLOTLY_LAYOUT_DEFAULTS: Dict[str, Any] = {
    "paper_bgcolor": "#082255",
    "plot_bgcolor":  "#082255",
    "font":          {"family": "Open Sans, sans-serif", "size": 12, "color": "#ffffff"},
    "xaxis": {
        "gridcolor":     "rgba(170,176,192,0.10)",
        "zerolinecolor": "rgba(170,176,192,0.22)",
        "linecolor":     "rgba(170,176,192,0.22)",
        "tickfont":      {"size": 11, "color": "#aab0c0"},
        "title_font":    {"size": 12, "color": "#aab0c0"},
    },
    "yaxis": {
        "gridcolor":     "rgba(170,176,192,0.10)",
        "zerolinecolor": "rgba(170,176,192,0.22)",
        "linecolor":     "rgba(170,176,192,0.22)",
        "tickfont":      {"size": 11, "color": "#aab0c0"},
        "title_font":    {"size": 12, "color": "#aab0c0"},
    },
    "legend": {
        "bgcolor":     "rgba(8,34,85,0.7)",
        "bordercolor": "rgba(42,82,152,0.5)",
        "borderwidth": 1,
        "font":        {"size": 11, "color": "#aab0c0"},
    },
    "margin": {"t": 40, "b": 40, "l": 50, "r": 20},
    "hoverlabel": {
        "bgcolor":    "#0c2b64",
        "bordercolor":"#2a5298",
        "font_size":  12,
        "font_color": "#ffffff",
    },
    "colorway": [
        "#2e86c1", "#27ae60", "#f39c12", "#8e44ad",
        "#16a085", "#c0392b", "#2980b9", "#d35400",
        "#1abc9c", "#7f8c8d",
    ],
}

# Plotly template object — use with pio.templates
ATLAS_PLOTLY_TEMPLATE = go.layout.Template(
    layout=go.Layout(**PLOTLY_LAYOUT_DEFAULTS)
)
