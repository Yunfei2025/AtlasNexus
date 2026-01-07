"""Dash callbacks for Bond Futures intraday dashboard."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import plotly.graph_objs as go
from dash import dcc, html
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
from scipy.stats import norm

from .app import app
from .styles import app_color, color_mode
from .funcs import candlestick_trace, queryPriceVolumeData


@app.callback(
    Output("futures-price", "figure"),
    Input("futures-price-update", "n_intervals"),
    Input("select-date", "value"),
    Input("select-ticker", "value"),
    Input("select-interval", "value"),
    Input("select-criterion", "value"),
)
def gen_price_trend(interval, date, futures, csinterval, imc):
    d = dt.datetime.strptime(date, "%Y-%m-%d")
    start = pd.Timestamp(d.year, d.month, d.day, 9, 32, 0)
    end = pd.Timestamp(d.year, d.month, d.day, 15, 15, 0)
    dp = d - pd.offsets.BDay()
    dps = dp.strftime("%Y-%m-%d")
    if dt.datetime.now() < start:
        data_dict = queryPriceVolumeData(dps, futures, csinterval)
        time_range = [
            pd.Timestamp(dp.year, dp.month, dp.day, 9, 30, 0),
            pd.Timestamp(dp.year, dp.month, dp.day, 15, 15, 0),
        ]
    else:
        data_dict = queryPriceVolumeData(date, futures, csinterval)
        if data_dict["price"].shape[0] <= 20:
            xs = data_dict["price"].index[0]
            xe = data_dict["price"].index[-1]
        else:
            xs = data_dict["price"].index[-20]
            xe = data_dict["price"].index[-1]
        time_range = [xs, xe]

    df = data_dict["price"]
    vol = data_dict["vol"]
    vwap = data_dict["vwap"]
    price_vol = data_dict["vol_prof"]

    mean = sum((price_vol.index * price_vol.values)) / price_vol.sum()
    std = np.sqrt(sum(price_vol.values * (price_vol.index - mean) ** 2) / sum(price_vol.values))

    trace = candlestick_trace(df, vol, imc)
    trace_vwap = go.Scatter(x=vwap.index, y=vwap.values, mode="lines", line=dict(color="orange", width=2), name="VWAP")

    layout = dict(
        hoverlabel=dict(bgcolor="white"),
        plot_bgcolor=app_color["graph_bg"],
        paper_bgcolor=app_color["graph_bg"],
        font={"color": "white"},
        height=600,
        legend=dict(yanchor="top", y=1.2, xanchor="right", x=1.0),
        xaxis={
            "title": "Time",
            "range": time_range,
            "showline": True,
            "zeroline": False,
            "gridcolor": "#0f3174",
            "fixedrange": True,
            "rangeslider": {"visible": True},
            "rangebreaks": [
                dict(bounds=[6, 1], pattern="day of week"),
                dict(bounds=[0, 9.5], pattern="hour"),
                dict(bounds=[11.5, 13], pattern="hour"),
                dict(bounds=[15.25, 24], pattern="hour"),
            ],
        },
        yaxis={
            "title": "Futures Price (¥)",
            "range": [min(df["Low"]) - 0.01, max(df["High"]) + 0.01],
            "showgrid": True,
            "showline": True,
            "fixedrange": True,
            "zeroline": False,
            "gridcolor": "#0f3174",
            "nticks": max(6, round(df["Close"].iloc[-1] / 10)),
        },
        shapes=[
            {"xref": "x", "yref": "y", "x1": end, "x0": start, "y0": mean, "y1": mean, "type": "line", "line": {"dash": "dash", "color": "#BD9391", "width": 3}},
            {"xref": "x", "yref": "y", "x1": end, "x0": start, "y0": mean - std, "y1": mean - std, "type": "line", "line": {"dash": "dot", "color": "#BD9391", "width": 3}},
            {"xref": "x", "yref": "y", "x1": end, "x0": start, "y0": mean + std, "y1": mean + std, "type": "line", "line": {"dash": "dot", "color": "#BD9391", "width": 3}},
        ],
    )
    return dict(data=[trace, trace_vwap], layout=layout)


@app.callback(
    Output("order-imbalance", "value"),
    Input("futures-price-update", "n_intervals"),
    Input("select-date", "value"),
    Input("select-ticker", "value"),
    Input("select-interval", "value"),
)
def gen_order_imbalance(interval, date, futures, csinterval):
    d = dt.datetime.strptime(date, "%Y-%m-%d")
    start = pd.Timestamp(d.year, d.month, d.day, 9, 30, 0)
    dp = d - pd.offsets.BDay()
    dps = dp.strftime("%Y-%m-%d")
    if dt.datetime.now() < start:
        data_dict = queryPriceVolumeData(dps, futures, csinterval)
    else:
        data_dict = queryPriceVolumeData(date, futures, csinterval)

    value = data_dict["price"]["Imbanlace"].iloc[-1]
    if np.isnan(value):
        return 0
    return value


@app.callback(
    Output("vol-histogram", "figure"),
    Input("futures-price-update", "n_intervals"),
    Input("select-date", "value"),
    Input("select-ticker", "value"),
    Input("select-interval", "value"),
)
def gen_vol_histogram(interval, date, futures, csinterval):
    try:
        d = dt.datetime.strptime(date, "%Y-%m-%d")
        start = pd.Timestamp(d.year, d.month, d.day, 9, 30, 0)
        dp = d - pd.offsets.BDay()
        dps = dp.strftime("%Y-%m-%d")
        if dt.datetime.now() < start:
            data_dict = queryPriceVolumeData(dps, futures, csinterval)
        else:
            data_dict = queryPriceVolumeData(date, futures, csinterval)

        price_vol = data_dict["vol_prof"]
        bin_val = (np.array(price_vol.values), np.array(price_vol.index))

        price_vol_bf_last_min = data_dict["bf_lst_vol"]
        bin_bf_last_min_val = (np.array(price_vol_bf_last_min.values), np.array(price_vol_bf_last_min.index))

        price_vol_last_min = data_dict["vol_last_min"]
        bin_last_min_val = (np.array(price_vol_last_min.values), np.array(price_vol_last_min.index))

        value = data_dict["price"]["Imbanlace"].iloc[-1]
    except Exception as error:
        raise PreventUpdate from error

    mean = sum((price_vol.index * price_vol.values)) / price_vol.sum()
    price_vol_cs = price_vol.cumsum()
    median_val = price_vol_cs.index[price_vol_cs.searchsorted(price_vol.sum() / 2)]
    std = np.sqrt(sum(price_vol.values * (price_vol.index - mean) ** 2) / sum(price_vol.values))

    pdf_fitted = norm.pdf(bin_val[1], loc=mean, scale=std)

    y_val = pdf_fitted * sum(bin_val[0] * 0.005)
    y_val_max = max(y_val)
    bin_val_max = max(bin_val[0])

    trace = dict(type="bar", x=bin_bf_last_min_val[0], y=bin_bf_last_min_val[1], marker={"color": app_color["graph_line"]}, showlegend=False, hoverinfo="x+y", orientation="h")

    trace_last_min = dict(type="bar", x=bin_last_min_val[0], y=bin_last_min_val[1], marker={"color": color_mode[np.sign(value)]}, showlegend=False, hoverinfo="x+y", orientation="h")

    traces_scatter = [
        {"line_dash": "dash", "line_color": "#BD9391", "name": "Average"},
        {"line_dash": "dot", "line_color": "#BD9391", "name": "±Std"},
        {"line_dash": "dot", "line_color": "#2E5266", "name": "Median"},
    ]

    scatter_data = [
        dict(
            type="scatter",
            y=[bin_val[int(len(bin_val) / 2)]],
            x=[0],
            mode="lines",
            line={"dash": traces["line_dash"], "color": traces["line_color"]},
            marker={"opacity": 0},
            visible=True,
            name=traces["name"],
        )
        for traces in traces_scatter
    ]

    trace3 = dict(type="scatter", mode="lines", line={"color": "#42C4F7"}, x=y_val, y=bin_val[1][: len(bin_val[1])], name="Norm Fit")
    layout = dict(
        height=500,
        barmode="stack",
        plot_bgcolor=app_color["graph_bg"],
        paper_bgcolor=app_color["graph_bg"],
        font={"color": "#fff"},
        xaxis={"showgrid": True, "showline": True, "gridcolor": "#0f3174", "zeroline": False, "title": "Number of Contracts", "fixedrange": True},
        yaxis={"title": "Futures Price (¥)", "showgrid": True, "showline": True, "gridcolor": "#0f3174", "fixedrange": True},
        autosize=True,
        bargap=0.01,
        bargroupgap=0,
        hovermode="closest",
        legend={"orientation": "h", "yanchor": "bottom", "xanchor": "center", "y": 1, "x": 0.5},
        shapes=[
            {"xref": "x", "yref": "y", "x1": int(max(bin_val_max, y_val_max)) + 0.5, "x0": 0, "y0": mean, "y1": mean, "type": "line", "line": {"dash": "dash", "color": "#BD9391", "width": 5}},
            {"xref": "x", "yref": "y", "x1": int(max(bin_val_max, y_val_max)) + 0.5, "x0": 0, "y0": mean - std, "y1": mean - std, "type": "line", "line": {"dash": "dot", "color": "#BD9391", "width": 3}},
            {"xref": "x", "yref": "y", "x1": int(max(bin_val_max, y_val_max)) + 0.5, "x0": 0, "y0": mean + std, "y1": mean + std, "type": "line", "line": {"dash": "dot", "color": "#BD9391", "width": 3}},
            {"xref": "x", "yref": "y", "x1": int(max(bin_val_max, y_val_max)) + 0.5, "x0": 0, "y0": median_val, "y1": median_val, "type": "line", "line": {"dash": "dot", "color": "#2E5266", "width": 5}},
        ],
    )
    return dict(data=[trace, trace_last_min, *scatter_data, trace3], layout=layout)
