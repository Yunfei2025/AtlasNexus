"""Lightweight style constants for AtlasNexus apps.

We avoid importing `web.core` here because `web.core.__init__` eagerly loads
large pickles and data.

The CSS classes referenced (e.g. app__header, app__container) are provided
by existing assets in `web/assets/`.
"""

from __future__ import annotations

from typing import Any, Dict

# Mirror the style objects used by web/core/styles.py and fi.py

# Top-level app tabs (Market/Beta Book/Alpha Book/...) are styled via CSS
# classes now — see .an-tabs / .an-tab / .an-tab--selected in
# web/assets/atlasnexus-design.css. Use className="an-tabs" / "an-tab" /
# "an-tab--selected" on dcc.Tabs/dcc.Tab instead of these dicts.

summary_subtabs_style: Dict[str, Any] = {
    "marginBottom": "16px",
}

summary_subtabs_colors: Dict[str, Any] = {
    "border": "#061E44",
    "primary": "#3498db",
    "background": "#112e66",
}

summary_subtab_style: Dict[str, Any] = {
    "backgroundColor": "#112e66",
    "color": "#aab0c0",
    "fontSize": "12px",
    "padding": "6px 20px",
    "border": "none",
}


def summary_subtab_selected_style(color: str = "#3498db") -> Dict[str, Any]:
    return {
        "backgroundColor": "#0c2b64",
        "color": color,
        "fontSize": "12px",
        "padding": "6px 20px",
        "borderTop": f"2px solid {color}",
        "borderBottom": "none",
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
