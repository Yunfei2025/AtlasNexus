"""Dash app setup for Bond Futures intraday dashboard."""

from __future__ import annotations

import os
import datetime as dt

import dash
from dash import html
import pandas as pd

from settings.futures import FuturesConfig

# Preset info
date_list = pd.bdate_range(end=dt.datetime.today(), periods=7)
date_list_str = [d for d in date_list.strftime("%Y-%m-%d")]

t_int = 15000  # unit ms
GRAPH_INTERVAL = os.environ.get("GRAPH_INTERVAL", t_int)

# Dash app
app = dash.Dash(
    __name__,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
app.title = "FI Engine: Bond Futures"
app.head = [html.Link(rel="stylesheet", href="./assets/style.css")]
server = app.server


def run(debug: bool = True, port: int = 8051):
    """Run the Dash server."""
    app.run(port=port, debug=debug)
