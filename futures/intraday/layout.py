"""Layout builder for the Bond Futures intraday dashboard."""

from __future__ import annotations

from dash import dcc, html
import dash_daq as daq

from .app import date_list_str, GRAPH_INTERVAL
from settings.futures import FuturesConfig
from .styles import app_color


def build_layout(app):
    """Return the app layout structure."""
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.H4("FI Engine: Bond Futures", className="app__header__title"),
                            html.P(
                                "This app continually queries Wind database every "
                                + str(int(GRAPH_INTERVAL) // 1000)
                                + "s and displays live charts of bond futures price and volume.",
                                className="app__header__title--grey",
                            ),
                        ],
                        className="app__header__desc",
                    ),
                    html.Div(
                        [
                            html.H6("Date for Ploting", className="graph__title"),
                            dcc.Dropdown(options=date_list_str, value=date_list_str[-1], id="select-date"),
                        ],
                        className="app__dropdown",
                    ),
                    html.Div(
                        [
                            html.H6("Futures ID", className="graph__title"),
                            dcc.Dropdown(
                                options=FuturesConfig.get_ticker_list(),
                                value=FuturesConfig.get_ticker_list()[0],
                                id="select-ticker",
                            ),
                        ],
                        className="app__dropdown",
                    ),
                    html.Div(
                        [
                            html.H6("CandleStick Interval", className="graph__title"),
                            dcc.Dropdown(
                                options=FuturesConfig.INTERVAL_LIST,
                                value=FuturesConfig.INTERVAL_LIST[1],
                                id="select-interval",
                            ),
                        ],
                        className="app__dropdown",
                    ),
                    html.Div(
                        [
                            html.H6("Imbalance Criterion", className="graph__title"),
                            dcc.Dropdown(
                                options=FuturesConfig.CRITERIA_LIST,
                                value=FuturesConfig.CRITERIA_LIST[1],
                                id="select-criterion",
                            ),
                        ],
                        className="app__dropdown",
                    ),
                    html.Div(
                        [
                            html.Div([html.H6("ORDER IMBALANCE", className="graph__title")]),
                            daq.Gauge(
                                id="order-imbalance",
                                className="gauge_logo",
                                color={"gradient": True, "ranges": {"green": [-1, -0.5], "yellow": [-0.5, 0.5], "red": [0.5, 1]}},
                                value=0,
                                max=1,
                                min=-1,
                                size=100,
                            ),
                        ],
                        className="app__header__logo",
                    ),
                ],
                className="app__header",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div([html.H6("Volume Histogram", className="graph__title")]),
                            dcc.Graph(
                                id="vol-histogram",
                                figure=dict(
                                    layout=dict(
                                        plot_bgcolor=app_color["graph_bg"],
                                        paper_bgcolor=app_color["graph_bg"],
                                    )
                                ),
                            ),
                        ],
                        className="one-fourth column histogram__container",
                    ),
                    html.Div(
                        [
                            html.Div([html.H6("Price Candlestick Chart", className="graph__title")]),
                            dcc.Graph(
                                id="futures-price",
                                figure=dict(
                                    layout=dict(
                                        plot_bgcolor=app_color["graph_bg"],
                                        paper_bgcolor=app_color["graph_bg"],
                                    )
                                ),
                            ),
                            dcc.Interval(id="futures-price-update", interval=int(GRAPH_INTERVAL), n_intervals=0),
                        ],
                        className="three-fourths column futures__price__container",
                    ),
                ],
                className="app__content",
            ),
        ],
        className="app__container",
    )
