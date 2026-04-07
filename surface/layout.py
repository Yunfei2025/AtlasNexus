"""Layout components for yield surface dashboard."""

from __future__ import annotations

import datetime as dt

from dash import dcc, html
from dateutil.relativedelta import relativedelta

from .config import TERM_LIST

# Import app color from shared web styles
from web.core.styles import app_color


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
                    dcc.Slider(
                        min=0, max=5, value=0,
                        marks={
                            0: {"label": "3D", "style": {"color": "#FFFFFF"}},
                            1: {"label": "Today", "style": {"color": "#FFFFFF"}},
                            2: {"label": "Position", "style": {"color": "#FFFFFF"}},
                            3: {"label": "Short", "style": {"color": "#FFFFFF"}},
                            4: {"label": "Long", "style": {"color": "#FFFFFF"}},
                            5: {"label": "Above", "style": {"color": "#FFFFFF"}},
                        },
                        id="surface-slider",
                    ),
                ], style={"marginBottom": "20px"}),
                html.Div([
                    html.Button("< Back", id="surface-back", n_clicks=0,
                        style={"background": "#007ACE", "color": "white", "border": "none", "padding": "8px 16px", "border-radius": "4px", "cursor": "pointer", "margin-right": "10px"}),
                    html.Button("Next >", id="surface-next", n_clicks=0,
                        style={"background": "#007ACE", "color": "white", "border": "none", "padding": "8px 16px", "border-radius": "4px", "cursor": "pointer"}),
                ], style={"marginBottom": "20px"}),
                html.Div([
                    dcc.Markdown(id="surface-text", style={"color": "#FFFFFF", "fontSize": "13px", "lineHeight": "1.6", "borderTop": "1px solid #007ACE", "paddingTop": "15px", "marginTop": "10px"})
                ]),
            ], className="graph__title"),
        ], className="one-fourth column histogram__container"),
        
        html.Div([
            html.Div([html.H6("3D Yield Surface Visualization", className="graph__title")]),
            dcc.Graph(
                id="surface-graph",
                style={"height": "80vh"},
                figure=dict(layout=dict(plot_bgcolor=app_color["graph_bg"], paper_bgcolor=app_color["graph_bg"])),
                config={"displayModeBar": True, "displaylogo": False}
            ),
        ], className="three-fourths column futures__price__container"),
    ])
