"""Layout components for yield surface dashboard."""

from __future__ import annotations

import datetime as dt

from dash import dcc, html
from dateutil.relativedelta import relativedelta

from .config import TERM_LIST

# Import app color from shared web styles
from web.core.styles import app_color


_VIEW_MODE_OPTIONS = [
    {"label": "3D",       "value": 0},
    {"label": "Today",    "value": 1},
    {"label": "Position", "value": 2},
    {"label": "Short",    "value": 3},
    {"label": "Long",     "value": 4},
    {"label": "Above",    "value": 5},
]

_ACCENT      = "var(--accent-cyan)"
_ACCENT_SOFT = "rgba(69,182,230,0.08)"

_PANEL_BASE = {
    "padding":    "12px 14px",
    "background": "var(--surface-panel)",
    "border":     "1px solid var(--border-strong)",
    "borderTop":  "1px solid var(--border-default)",
}

_LBL = {
    "color":          "var(--text-muted)",
    "fontSize":       "10px",
    "textTransform":  "uppercase",
    "letterSpacing":  "0.06em",
    "fontWeight":     "600",
    "marginBottom":   "8px",
    "display":        "block",
}


def create_layout():
    sections = []

    # ── Panel 1: Title ──────────────────────────────────────────────────────
    sections.append(html.Div(
        html.Div("Yield Surface Controls", style={
            "fontSize":      "12px",
            "fontWeight":    "600",
            "letterSpacing": "0.06em",
            "textTransform": "uppercase",
            "color":         "var(--text-primary)",
        }),
        style={
            "padding":      "12px 14px 10px",
            "background":   "var(--surface-panel)",
            "border":       "1px solid var(--border-strong)",
            "borderRadius": "6px 6px 0 0",
            "borderBottom": "none",
        },
    ))

    # ── Panel 2: Country ────────────────────────────────────────────────────
    sections.append(html.Div(
        [
            html.Div("Country", style=_LBL),
            dcc.RadioItems(
                id="surface-country-selection",
                options=[
                    {"label": " China",         "value": "CN"},
                    {"label": " United States",  "value": "US"},
                ],
                value="CN",
                style={"color": "var(--text-secondary)"},
                labelStyle={
                    "display":       "block",
                    "marginBottom":  "6px",
                    "cursor":        "pointer",
                    "fontSize":      "11px",
                    "color":         "var(--text-secondary)",
                },
            ),
        ],
        style=_PANEL_BASE,
    ))

    # ── Panel 3: Date Range ─────────────────────────────────────────────────
    sections.append(html.Div(
        [
            html.Div("Date Range", style=_LBL),
            dcc.DatePickerRange(
                id="surface-date-picker-range",
                start_date=dt.datetime.today() - relativedelta(years=1),
                end_date=dt.datetime.today(),
                min_date_allowed=dt.date(2001, 1, 1),
                max_date_allowed=dt.datetime.today(),
                initial_visible_month=dt.datetime.today() - relativedelta(years=1),
                style={"width": "100%"},
            ),
        ],
        style=_PANEL_BASE,
    ))

    # ── Panel 4: View Mode ──────────────────────────────────────────────────
    sections.append(html.Div(
        [
            html.Div("View Mode", style=_LBL),
            dcc.RadioItems(
                id="surface-slider",
                options=_VIEW_MODE_OPTIONS,
                value=0,
                inline=True,
                inputStyle={"display": "none"},
                labelStyle={
                    "display":       "inline-block",
                    "padding":       "6px 8px",
                    "marginRight":   "4px",
                    "marginBottom":  "5px",
                    "fontSize":      "10px",
                    "fontWeight":    "600",
                    "border":        "1px solid var(--border-default)",
                    "borderRadius":  "4px",
                    "color":         "var(--text-muted)",
                    "background":    "transparent",
                    "cursor":        "pointer",
                    "transition":    "all 0.15s",
                },
                className="surface-mode-chips",
            ),
        ],
        style=_PANEL_BASE,
    ))

    # ── Panel 5: Navigate ───────────────────────────────────────────────────
    sections.append(html.Div(
        html.Div(
            [
                html.Button("← Back", id="surface-back", n_clicks=0, style={
                    "flex":         "1",
                    "padding":      "7px 10px",
                    "fontSize":     "10px",
                    "border":       "1px solid var(--border-default)",
                    "borderRadius": "4px",
                    "background":   "transparent",
                    "color":        "var(--text-muted)",
                    "cursor":       "pointer",
                }),
                html.Button("Next →", id="surface-next", n_clicks=0, style={
                    "flex":         "1",
                    "padding":      "7px 10px",
                    "fontSize":     "10px",
                    "border":       "1px solid var(--border-default)",
                    "borderRadius": "4px",
                    "background":   "transparent",
                    "color":        "var(--text-muted)",
                    "cursor":       "pointer",
                }),
            ],
            style={"display": "flex", "gap": "6px"},
        ),
        style=_PANEL_BASE,
    ))

    # ── Panel 6: Refresh + text ─────────────────────────────────────────────
    sections.append(html.Div(
        [
            html.Button("↻ Refresh Data", id="surface-refresh-btn", n_clicks=0, style={
                "width":        "100%",
                "padding":      "7px 10px",
                "fontSize":     "10px",
                "fontWeight":   "600",
                "border":       f"1px solid {_ACCENT}",
                "borderRadius": "4px",
                "cursor":       "pointer",
                "background":   _ACCENT_SOFT,
                "color":        _ACCENT,
                "marginBottom": "8px",
            }),
            html.Span(
                id="surface-refresh-status",
                children="Loading latest surface data…",
                style={"color": "var(--text-muted)", "fontSize": "9px", "lineHeight": "1.5"},
            ),
            dcc.Markdown(
                id="surface-text",
                style={
                    "color":       "var(--text-secondary)",
                    "fontSize":    "12px",
                    "lineHeight":  "1.6",
                    "borderTop":   "1px solid var(--border-default)",
                    "paddingTop":  "12px",
                    "marginTop":   "10px",
                },
            ),
        ],
        style={
            **_PANEL_BASE,
            "borderRadius": "0 0 6px 6px",
        },
    ))

    return html.Div([
        dcc.Store(id="surface-click-output", data={"back": 0, "next": 0}),

        # ── Header ──────────────────────────────────────────────────────────
        html.Div(
            [
                html.Span("3D Yield Surface", style={
                    "color":      "var(--text-primary)",
                    "fontSize":   "16px",
                    "fontWeight": "600",
                }),
                html.Span(id="surface-chart-context", style={
                    "color":    "var(--text-muted)",
                    "fontSize": "12px",
                }),
            ],
            style={
                "display":       "flex",
                "alignItems":    "baseline",
                "gap":           "10px",
                "marginBottom":  "10px",
            },
        ),

        # ── Grid: 220px control panel + chart ───────────────────────────────
        html.Div(
            [
                # Left control panel
                html.Div(
                    sections,
                    style={"display": "flex", "flexDirection": "column", "gap": "2px"},
                ),
                # Right chart
                dcc.Graph(
                    id="surface-graph",
                    style={"height": "calc(80vh - 38px)"},
                    figure=dict(layout=dict(
                        plot_bgcolor=app_color["graph_bg"],
                        paper_bgcolor=app_color["graph_bg"],
                    )),
                    config={"displayModeBar": True, "displaylogo": False},
                ),
            ],
            style={
                "display":              "grid",
                "gridTemplateColumns":  "220px 1fr",
                "gap":                  "16px",
                "alignItems":           "start",
            },
        ),
    ], style={"padding": "16px", "margin": "10px"})
