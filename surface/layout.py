"""Layout components for yield surface dashboard."""

from __future__ import annotations

import datetime as dt

from dash import dcc, html
from dateutil.relativedelta import relativedelta

from .config import TERM_LIST

# Import app color from shared web styles
from web.core.styles import app_color


_VIEW_MODE_OPTIONS = [
    {"label": "3D", "value": 0},
    {"label": "Today", "value": 1},
    {"label": "Position", "value": 2},
    {"label": "Short", "value": 3},
    {"label": "Long", "value": 4},
    {"label": "Above", "value": 5},
]


def create_layout():
    return html.Div([
        dcc.Store(id="surface-click-output", data={"back": 0, "next": 0}),

        html.Div([
            html.Div([
                html.H6("Yield Surface Controls", className="graph__title"),
                html.Div([
                    html.H6("Country Selection", style={"color": "#FFFFFF", "margin-bottom": "10px"}),
                    dcc.RadioItems(
                        id="surface-country-selection",
                        options=[
                            {"label": " China", "value": "CN"},
                            {"label": " United States", "value": "US"},
                        ],
                        value="CN",
                        style={"color": "#FFFFFF"},
                        labelStyle={"display": "block", "margin-bottom": "8px"}
                    ),
                ], style={"marginBottom": "20px"}),
                html.Div([
                    html.H6("Select Date Range", style={"color": "#FFFFFF", "margin-bottom": "10px"}),
                    dcc.DatePickerRange(
                        id="surface-date-picker-range",
                        start_date=dt.datetime.today() - relativedelta(years=1),
                        end_date=dt.datetime.today(),
                        min_date_allowed=dt.date(2001, 1, 1),
                        max_date_allowed=dt.datetime.today(),
                        initial_visible_month=dt.datetime.today() - relativedelta(years=1),
                    ),
                ], style={"marginBottom": "20px"}),
                html.Div([
                    html.H6("View Mode", style={"color": "#FFFFFF", "margin-bottom": "10px"}),
                    dcc.RadioItems(
                        id="surface-slider",
                        options=_VIEW_MODE_OPTIONS,
                        value=0,
                        inline=True,
                        inputStyle={"display": "none"},
                        labelStyle={
                            "display":      "inline-block",
                            "padding":      "3px 10px",
                            "marginRight":  "4px",
                            "marginBottom": "4px",
                            "fontSize":     "11px",
                            "border":       "1px solid #1e3a5f",
                            "borderRadius": "3px",
                            "color":        "#6f83a3",
                            "background":   "#17345c",
                            "cursor":       "pointer",
                        },
                        className="surface-mode-chips",
                    ),
                ], style={"marginBottom": "20px"}),
                html.Div([
                    html.Button("< Back", id="surface-back", n_clicks=0,
                        style={"background": "#007ACE", "color": "white", "border": "none", "padding": "8px 16px", "border-radius": "4px", "cursor": "pointer", "margin-right": "10px"}),
                    html.Button("Next >", id="surface-next", n_clicks=0,
                        style={"background": "#007ACE", "color": "white", "border": "none", "padding": "8px 16px", "border-radius": "4px", "cursor": "pointer"}),
                ], style={"marginBottom": "20px"}),
                html.Div([
                    html.Button("↻ Refresh Data", id="surface-refresh-btn", n_clicks=0,
                        style={"background": "#17345c", "color": "#44C8F5", "border": "1px solid #007ACE", "padding": "8px 16px", "border-radius": "4px", "cursor": "pointer", "margin-right": "12px"}),
                    html.Span(
                        id="surface-refresh-status",
                        children="Loading latest surface data…",
                        style={"color": "#A9C7E8", "fontSize": "12px"},
                    ),
                ], style={"display": "flex", "alignItems": "center", "marginBottom": "20px", "flexWrap": "wrap", "rowGap": "8px"}),
                html.Div([
                    dcc.Markdown(id="surface-text", style={"color": "#FFFFFF", "fontSize": "13px", "lineHeight": "1.6", "borderTop": "1px solid #007ACE", "paddingTop": "15px", "marginTop": "10px"})
                ]),
            ], className="graph__title"),
        ], style={
            "width":       "280px",
            "minWidth":    "280px",
            "flexShrink":  "0",
            "boxSizing":   "border-box",
        }, className="histogram__container"),

        html.Div([
            html.Div([
                html.Span("3D Yield Surface", style={
                    "fontSize": "12px", "fontWeight": "600", "color": "#e9eef8",
                }),
                html.Span(" · ", style={"color": "#2e547f", "margin": "0 6px"}),
                html.Span(id="surface-chart-context",
                          style={"fontSize": "11px", "color": "#4a5d7c"}),
            ], style={"display": "flex", "alignItems": "center",
                      "padding": "9px 16px", "borderBottom": "1px solid rgba(255,255,255,0.06)"}),
            dcc.Graph(
                id="surface-graph",
                style={"height": "calc(80vh - 38px)"},
                figure=dict(layout=dict(plot_bgcolor=app_color["graph_bg"], paper_bgcolor=app_color["graph_bg"])),
                config={"displayModeBar": True, "displaylogo": False}
            ),
        ], style={"flex": "1", "display": "flex", "flexDirection": "column", "minWidth": "0"},
           className="futures__price__container"),
    ], style={"display": "flex", "alignItems": "flex-start", "gap": "16px"})
