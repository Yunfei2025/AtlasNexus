# -*- coding: utf-8 -*-
"""TREND tab for the AtlasNexus Daily Beta Book.

Provides:
  build_trend_layout()        – Dash layout component tree
  register_trend_callbacks()  – registers callbacks onto a given Dash app instance

Series data comes from the pre-computed ``trend-fig.obj`` pickle written by the
EOD pipeline (curves / factor engine).  The file is a ``dict[str, go.Figure]``
keyed by the same series identifiers used in the selector below.
"""

from __future__ import annotations

import os
from dash import dcc, html
from dash.dependencies import Input, Output

# ── Shared theme (aligned with the rest of Beta Book) ─────────────────────────
THEME = {
    "bg_main":       "#082255",
    "bg_card":       "#0c2b64",
    "bg_input":      "#112e66",
    "text_main":     "#ffffff",
    "text_sub":      "#aab0c0",
    "accent":        "#3498db",
    "accent_light":  "#5dade2",
    "table_header":  "#061E44",
    "chart_template": "plotly_dark",
}

# ── Dropdown options (disabled items act as visual group separators) ───────────
_OPTIONS = [
    {"label": "── Treasury Yields ──────────",   "value": "__t__",    "disabled": True},
    {"label": "1Y Treasury",                      "value": "中债国债到期收益率:1年"},
    {"label": "5Y Treasury",                      "value": "中债国债到期收益率:5年"},
    {"label": "10Y Treasury",                     "value": "中债国债到期收益率:10年"},
    {"label": "30Y Treasury",                     "value": "中债国债到期收益率:30年"},
    {"label": "── Treasury Slopes ─────────",    "value": "__ts__",   "disabled": True},
    {"label": "5Y − 1Y Treasury",                 "value": "中债国债到期收益率:5年-1年"},
    {"label": "10Y − 5Y Treasury",                "value": "中债国债到期收益率:10年-5年"},
    {"label": "30Y − 10Y Treasury",               "value": "中债国债到期收益率:30年-10年"},
    {"label": "── FR007 IRS ──────────────",     "value": "__irs__",  "disabled": True},
    {"label": "1Y FR007",                         "value": "FR007S1Y.IR"},
    {"label": "2Y FR007",                         "value": "FR007S2Y.IR"},
    {"label": "5Y FR007",                         "value": "FR007S5Y.IR"},
    {"label": "── IRS Slopes ───────────────",   "value": "__irss__", "disabled": True},
    {"label": "2Y − 1Y FR007",                    "value": "FR007:2Y-1Y"},
    {"label": "5Y − 2Y FR007",                    "value": "FR007:5Y-2Y"},
    {"label": "5Y − 1Y FR007",                    "value": "FR007:5Y-1Y"},
    {"label": "── Bond-Swap Spreads ────────",   "value": "__bsw__",  "disabled": True},
    {"label": "TBond − FR007  1Y",                "value": "TBond-FR007:1Y"},
    {"label": "TBond − FR007  2Y",                "value": "TBond-FR007:2Y"},
    {"label": "TBond − FR007  5Y",                "value": "TBond-FR007:5Y"},
]

# Label lookup used by the chart title
_LABEL_MAP: dict[str, str] = {
    o["value"]: o["label"]
    for o in _OPTIONS
    if not o.get("disabled")
}

# ── Quick-access buttons (value, display label) ────────────────────────────────
_QUICK = [
    ("中债国债到期收益率:1年",   "1Y Tsy"),
    ("中债国债到期收益率:5年",   "5Y Tsy"),
    ("中债国债到期收益率:10年",  "10Y Tsy"),
    ("中债国债到期收益率:30年",  "30Y Tsy"),
    ("中债国债到期收益率:5年-1年",  "5s1s"),
    ("中债国债到期收益率:10年-5年", "10s5s"),
    ("中债国债到期收益率:30年-10年","30s10s"),
    ("FR007S1Y.IR",  "IRS 1Y"),
    ("FR007S2Y.IR",  "IRS 2Y"),
    ("FR007S5Y.IR",  "IRS 5Y"),
    ("FR007:2Y-1Y",  "IRS 2s1s"),
    ("FR007:5Y-2Y",  "IRS 5s2s"),
    ("FR007:5Y-1Y",  "IRS 5s1s"),
    ("TBond-FR007:1Y", "BdSwap 1Y"),
    ("TBond-FR007:2Y", "BdSwap 2Y"),
    ("TBond-FR007:5Y", "BdSwap 5Y"),
]

_BTN_BASE = {
    "width": "100%",
    "marginBottom": "3px",
    "padding": "5px 8px",
    "backgroundColor": THEME["bg_input"],
    "color": THEME["text_main"],
    "border": f'1px solid {THEME["table_header"]}',
    "borderRadius": "3px",
    "cursor": "pointer",
    "fontSize": "11px",
    "textAlign": "left",
    "fontFamily": "inherit",
}

_BTN_ACTIVE = {
    **_BTN_BASE,
    "backgroundColor": THEME["accent"],
    "borderColor": THEME["accent_light"],
    "fontWeight": "bold",
}


def _section_label(text: str) -> html.Div:
    return html.Div(
        text,
        style={
            "color": THEME["accent"],
            "fontSize": "10px",
            "fontWeight": "bold",
            "letterSpacing": "0.8px",
            "textTransform": "uppercase",
            "marginTop": "12px",
            "marginBottom": "6px",
        },
    )


def build_trend_layout() -> html.Div:
    """Return the TREND tab content for the Beta Book."""

    # Quick-select button list (individual IDs for direct callback targeting)
    quick_buttons = [
        html.Button(
            label,
            id=f"an-trend-btn-{val.replace(':', '-').replace('中债国债到期收益率:', 'tsy').replace('.', '_')}",
            n_clicks=0,
            style=_BTN_BASE,
        )
        for val, label in _QUICK
    ]

    return html.Div(
        [
            html.Div(
                [
                    # ── Left sidebar ─────────────────────────────────────────────
                    html.Div(
                        [
                            _section_label("Series"),
                            dcc.Dropdown(
                                id="an-trend-type",
                                options=_OPTIONS,
                                value="中债国债到期收益率:10年",
                                clearable=False,
                                optionHeight=28,
                                style={
                                    "backgroundColor": THEME["bg_input"],
                                    "color": THEME["text_main"],
                                    "fontSize": "12px",
                                    "marginBottom": "14px",
                                },
                            ),
                            html.Hr(
                                style={
                                    "borderColor": THEME["table_header"],
                                    "margin": "6px 0 10px 0",
                                }
                            ),
                            _section_label("Quick select"),
                            html.Div(quick_buttons),
                        ],
                        style={
                            "width": "130px",
                            "minWidth": "130px",
                            "backgroundColor": THEME["bg_card"],
                            "padding": "14px 10px",
                            "borderRadius": "5px",
                            "border": f'1px solid {THEME["table_header"]}',
                            "overflowY": "auto",
                            "maxHeight": "620px",
                            "boxSizing": "border-box",
                        },
                    ),

                    # ── Chart panel ───────────────────────────────────────────────
                    html.Div(
                        [
                            # Info strip above the chart
                            html.Div(
                                id="an-trend-info",
                                style={
                                    "color": THEME["text_sub"],
                                    "fontSize": "11px",
                                    "marginBottom": "8px",
                                    "paddingLeft": "4px",
                                },
                            ),
                            dcc.Graph(
                                id="an-trend-graph",
                                style={"height": "820px"},
                                config={
                                    "displayModeBar": True,
                                    "scrollZoom": True,
                                    "modeBarButtonsToRemove": ["select2d", "lasso2d"],
                                    "toImageButtonOptions": {
                                        "format": "svg",
                                        "filename": "trend_chart",
                                    },
                                },
                                figure={
                                    "data": [],
                                    "layout": {
                                        "plot_bgcolor": THEME["bg_main"],
                                        "paper_bgcolor": THEME["bg_card"],
                                        "font": {"color": THEME["text_main"]},
                                        "xaxis": {"color": THEME["text_sub"]},
                                        "yaxis": {"color": THEME["text_sub"]},
                                        "annotations": [
                                            {
                                                "text": "Select a series — run EOD to generate data",
                                                "xref": "paper",
                                                "yref": "paper",
                                                "x": 0.5,
                                                "y": 0.5,
                                                "showarrow": False,
                                                "font": {
                                                    "size": 13,
                                                    "color": THEME["text_sub"],
                                                },
                                            }
                                        ],
                                    },
                                },
                            ),
                        ],
                        style={"flex": "1", "minWidth": "0"},
                    ),
                ],
                style={
                    "display": "flex",
                    "flexDirection": "row",
                    "gap": "14px",
                    "alignItems": "flex-start",
                },
            ),
        ],
        style={
            "backgroundColor": THEME["bg_main"],
            "padding": "16px",
            "borderRadius": "5px",
            "margin": "10px",
        },
    )


# ── Callbacks ──────────────────────────────────────────────────────────────────

def register_trend_callbacks(app) -> None:
    """Register all TREND tab callbacks onto *app*."""

    # Pickle cache keyed by path → (mtime, object)
    _cache: dict[str, tuple[float, object]] = {}

    def _load_pickle_cached(path: str) -> object:
        try:
            mtime = os.path.getmtime(path)
        except FileNotFoundError:
            raise
        hit = _cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
        import pickle
        with open(path, "rb") as fh:
            obj = pickle.load(fh)
        _cache[path] = (mtime, obj)
        return obj

    def _empty_figure(msg: str) -> dict:
        return {
            "data": [],
            "layout": {
                "plot_bgcolor": THEME["bg_main"],
                "paper_bgcolor": THEME["bg_card"],
                "font": {"color": THEME["text_sub"]},
                "xaxis": {"visible": False},
                "yaxis": {"visible": False},
                "annotations": [
                    {
                        "text": msg,
                        "xref": "paper",
                        "yref": "paper",
                        "x": 0.5,
                        "y": 0.5,
                        "showarrow": False,
                        "font": {"size": 13, "color": THEME["text_sub"]},
                    }
                ],
            },
        }

    # ── Quick-select buttons: each writes to the dropdown ──────────────────────
    # Build the list of output/input mappings at registration time so Dash sees
    # them as individual Input objects (pattern-matching not needed).
    _quick_btn_ids = [
        f"an-trend-btn-{val.replace(':', '-').replace('中债国债到期收益率:', 'tsy').replace('.', '_')}"
        for val, _label in _QUICK
    ]
    _quick_btn_values = [val for val, _label in _QUICK]

    @app.callback(
        Output("an-trend-type", "value"),
        [Input(btn_id, "n_clicks") for btn_id in _quick_btn_ids],
        prevent_initial_call=True,
    )
    def _quick_select(*n_clicks_list):
        import dash
        ctx = dash.callback_context
        if not ctx.triggered:
            raise dash.exceptions.PreventUpdate
        triggered_id = ctx.triggered[0]["prop_id"].split(".")[0]
        try:
            idx = _quick_btn_ids.index(triggered_id)
            return _quick_btn_values[idx]
        except ValueError:
            raise dash.exceptions.PreventUpdate

    # ── Main chart callback ────────────────────────────────────────────────────
    @app.callback(
        Output("an-trend-graph", "figure"),
        Output("an-trend-info", "children"),
        Input("data-refresh", "n_intervals"),
        Input("an-trend-type", "value"),
    )
    def _update_trend(n_intervals, ctype):
        import datetime
        import plotly.graph_objs as go

        label = _LABEL_MAP.get(ctype, ctype)
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")

        try:
            from settings.paths import DIR_INPUT
            path = os.path.join(str(DIR_INPUT), "trend-fig.obj")
            figures = _load_pickle_cached(path)

            fig = figures.get(ctype)
            if fig is None:
                return (
                    _empty_figure(f"No data for: {label}"),
                    f"Series not found in trend-fig.obj: {ctype}",
                )

            fig = go.Figure(fig)
            legacy_td_prefixes = ("TD ", "TDST ")
            fig.data = tuple(
                trace for trace in fig.data
                if not (getattr(trace, "name", "") or "").startswith(legacy_td_prefixes)
            )

            # Convert to dict for safe mutation
            if hasattr(fig, "to_dict"):
                fig = fig.to_dict()
            else:
                import copy
                fig = copy.deepcopy(fig)

            # Apply Beta Book theme
            layout = fig.setdefault("layout", {})
            layout["plot_bgcolor"] = THEME["bg_main"]
            layout["paper_bgcolor"] = THEME["bg_card"]
            layout.setdefault("font", {})["color"] = THEME["text_main"]
            layout.setdefault("xaxis", {})["gridcolor"] = THEME["table_header"]
            layout.setdefault("yaxis", {})["gridcolor"] = THEME["table_header"]
            layout["title"] = {
                "text": label,
                "font": {"color": THEME["text_main"], "size": 14},
            }
            layout["margin"] = {"l": 60, "r": 20, "t": 40, "b": 40}
            info = f"Updated {timestamp}  ·  {label}"
            return fig, info

        except FileNotFoundError:
            return (
                _empty_figure("trend-fig.obj not found — run EOD pipeline to generate it"),
                "Data file missing",
            )
        except Exception as exc:
            return _empty_figure(f"Error: {exc}"), f"Error: {exc}"
