# -*- coding: utf-8 -*-
"""
Created on Fri Dec  8 11:13:16 2023

@author: 马云飞
"""

from dash import dcc, html
from web.core.server import app
from web.core import content  # Import registers callbacks
from web.core.styles import tab_style, tabs_styles, tab_selected_style


def build_header():
    return html.Div(
        [
            html.Div(
                [
                    html.H4("FI Engine: Curves and Spreads", className="app__header__title"),
                    html.P(
                        id="refresh-time",
                        className="app__header__title--grey",
                    ),
                ],
                className="app__header__desc",
            ),
            html.Div(
                [
                    html.Div(id="hidden-div", style={"display": "none"}),
                    html.A(
                        html.Button("Initialise Data and Curves", id="generate-button", n_clicks=0),
                    ),
                    html.Div(id="container-button-1", children="Click to initialise daily."),
                ],
                className="app__dropdown",
            ),
        ],
        className="app__header",
    )


def build_tabs_panel():
    return html.Div(
        [
            html.Div(
                [
                    dcc.Tabs(
                        id="tabs-graph",
                        value="tabs-graph",
                        children=[
                            dcc.Tab(label="Trends", value="tab-5-graph", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="Spread Info", value="tab-1-graph", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="CURVES", value="tab-2-graph", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="Pairs", value="tab-3-graph", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="SURFACES", value="tab-4-graph", style=tab_style, selected_style=tab_selected_style),
                        ],
                        style=tabs_styles,
                    ),
                    html.Div(id="tabs-content-graph"),
                    dcc.Store(id="realtime-data"),
                ],
                className="tab__title",
            ),
        ],
        className="twelve columns futures__price__container",
    )


def create_layout():
    return html.Div(
        [
            build_header(),
            html.Div(
                [
                    build_tabs_panel(),
                ],
                className="app__content",
            ),
        ],
        className="app__container",
    )


app.title = "FI Engine: Data Viewer"
app.layout = create_layout()

if __name__ == "__main__":
    # Disable reloader to avoid double imports during debugging
    app.run(host="127.0.0.1", port=8052, debug=False, use_reloader=False)
