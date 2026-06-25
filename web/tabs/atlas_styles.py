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
# :root tokens in web/assets/design.css (--an-*).
TOKENS: Dict[str, str] = {
    "navy_950": "#060d1c", "navy_900": "#0a1428", "navy_850": "#0c1830",
    "navy_800": "#0e1d3a", "navy_750": "#102544", "navy_700": "#122a4c",
    "navy_600": "#17345c", "navy_500": "#21426e", "navy_400": "#2e547f",
    "navy_300": "#3a4d6e",
    "blue":   "#3d8bd4", "cyan":   "#45b6e6",
    "green":  "#2f9d6b", "amber":  "#e0a23c",
    "red":    "#d56b6b", "purple": "#7c70d6", "teal": "#36a6b8",
    "text":   "#e9eef8", "muted":  "#a4b6d2", "faint": "#4a5d7c",
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
# .an-subtab / .an-subtab--selected in web/assets/design.css.
# Use className="an-tabs" / "an-tab" / "an-tab--selected" on dcc.Tabs/dcc.Tab,
# and className="an-subtab" / selected_className="an-subtab--selected" on
# sub-tabs, instead of inline style dicts.

summary_subtabs_style: Dict[str, Any] = {
    "marginBottom": "16px",
}

summary_subtabs_colors: Dict[str, Any] = {
    "border": TOKENS["navy_800"],
    "primary": TOKENS["blue"],
    "background": TOKENS["navy_600"],
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
    "paper_bgcolor": TOKENS["navy_900"],
    "plot_bgcolor":  TOKENS["navy_900"],
    "font":          {"family": "Open Sans, sans-serif", "size": 12, "color": TOKENS["text"]},
    "xaxis": {
        "gridcolor":     "rgba(164,182,210,0.10)",
        "zerolinecolor": "rgba(164,182,210,0.22)",
        "linecolor":     "rgba(164,182,210,0.22)",
        "tickfont":      {"size": 11, "color": TOKENS["muted"]},
        "title_font":    {"size": 12, "color": TOKENS["muted"]},
    },
    "yaxis": {
        "gridcolor":     "rgba(164,182,210,0.10)",
        "zerolinecolor": "rgba(164,182,210,0.22)",
        "linecolor":     "rgba(164,182,210,0.22)",
        "tickfont":      {"size": 11, "color": TOKENS["muted"]},
        "title_font":    {"size": 12, "color": TOKENS["muted"]},
    },
    "legend": {
        "bgcolor":     "rgba(10,20,40,0.7)",
        "bordercolor": "rgba(46,84,127,0.5)",
        "borderwidth": 1,
        "font":        {"size": 11, "color": TOKENS["muted"]},
    },
    "margin": {"t": 40, "b": 40, "l": 50, "r": 20},
    "hoverlabel": {
        "bgcolor":    TOKENS["navy_700"],
        "bordercolor":TOKENS["navy_400"],
        "font_size":  12,
        "font_color": TOKENS["text"],
    },
    "colorway": [
        TOKENS["blue"], TOKENS["green"], TOKENS["amber"], TOKENS["purple"],
        TOKENS["teal"], TOKENS["red"], TOKENS["cyan"], "#d35400",
        "#1abc9c", "#7f8c8d",
    ],
}

# Plotly template object — use with pio.templates
ATLAS_PLOTLY_TEMPLATE = go.layout.Template(
    layout=go.Layout(**PLOTLY_LAYOUT_DEFAULTS)
)
