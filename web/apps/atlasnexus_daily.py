# -*- coding: utf-8 -*-
"""AtlasNexus Daily Console (EOD).

A new Dash app that mirrors the styling of web/apps/fi.py,
without modifying existing apps.

Port: 8080
"""

from __future__ import annotations
import sys
from dash import dcc, html
from dash.dependencies import Input, Output, State

from pathlib import Path
# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(project_root))

# Import lightweight style constants (do not import web.core which triggers data loads).
from web.atlas_styles import tab_style, tabs_styles, tab_selected_style

# We intentionally create a new Dash instance to avoid interfering with existing apps.
from dash import Dash as _Dash
import pathlib

from web.services.artifacts import find_latest_run, format_run_meta
from web.services.jobs import start_engine_job, tail_log, get_job_status

from web.atlas_fi_tabs import (
    build_curves_layout,
    build_pairs_layout,
    build_spreads_layout,
    build_surface_layout,
    register_callbacks as register_fi_callbacks,
)

from web.atlas_alpha_tabs import (
    build_candidates_layout,
    build_scoring_layout,
    build_basket_layout,
    build_backtest_layout,
    register_alpha_callbacks,
)

from web.atlas_multiasset_tabs import (
    build_multiasset_factor_layout,
    build_multiasset_portfolio_layout,
    build_multiasset_risk_layout,
    build_multiasset_backtest_layout,
    build_factor_backtest_layout,
    register_multiasset_callbacks,
)

from web.atlas_volatility_tabs import (
    build_volatility_layout,
    register_volatility_callbacks,
)


project_root = pathlib.Path(__file__).resolve().parents[2]
assets_folder = str(project_root / "web" / "assets")

app = _Dash(
    __name__,
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width"}],
    assets_folder=assets_folder,
)

app.title = "AtlasNexus Daily Console"

# Serve the pairs regression plots HTML as a static-like endpoint so iframes
# can access it from the Dash app (matches web/core/server.py behavior).
@app.server.route("/pairs/regression_plots.html")
def _serve_pairs_regression():
    try:
        from flask import send_file, abort
        pairs_file = project_root / "pairs" / "regression_plots.html"
        if pairs_file.exists():
            return send_file(str(pairs_file))
        else:
            abort(404)
    except Exception:
        pass  # abort(500) not available or simple pass to avoid crash

# Register callbacks for migrated legacy FI layouts (Pairs tab refresh callback).
register_fi_callbacks(app)
register_multiasset_callbacks(app)
register_alpha_callbacks(app)
register_volatility_callbacks(app)


def build_header():
    return html.Div(
        [
            html.Div(
                [
                    html.H4("AtlasNexus · Daily", className="app__header__title"),
                    html.P(id="an-refresh-time", className="app__header__title--grey"),
                    html.P(id="an-latest-run", className="app__header__title--grey"),
                ],
                className="app__header__desc",
            ),
            html.Div(
                [
                    dcc.Store(id="an-job-id", storage_type="memory"),
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
                        id="an-tabs",
                        value="run-center",
                        children=[
                            dcc.Tab(label="Run Center", value="run-center", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="Beta Book", value="beta", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="Alpha Book", value="alpha", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="Summary", value="risk", style=tab_style, selected_style=tab_selected_style),
                            # Spreads tab moved into the Alpha Book content (bottom-up signals / pair screens)
                        ],
                        style=tabs_styles,
                    ),
                    html.Div(id="an-tabs-content"),
                    dcc.Interval(id="an-interval", interval=5_000, n_intervals=0),
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
            html.Div([build_tabs_panel()], className="app__content"),
        ],
        className="app__container",
    )


app.layout = create_layout()


@app.callback(
    Output("an-refresh-time", "children"),
    Output("an-latest-run", "children"),
    Input("an-interval", "n_intervals"),
)
def _tick(n):
    meta = find_latest_run(mode="eod")
    return (
        f"Refresh tick: {n}",
        f"Latest EOD run: {format_run_meta(meta)}",
    )


@app.callback(
    Output("an-job-id", "data"),
    Output("an-job-status", "children"),
    Input("an-btn-update", "n_clicks"),
    Input("an-btn-eod", "n_clicks"),
    Input("an-btn-eod-update", "n_clicks"),
    prevent_initial_call=True,
)
def _start_jobs(n_update, n_eod, n_eod_update):
    ctx = __import__("dash").callback_context
    if not ctx.triggered:
        raise __import__("dash").exceptions.PreventUpdate

    trig = ctx.triggered[0]["prop_id"].split(".")[0]

    if trig == "an-btn-update":
        job = start_engine_job(argv=["update-data"])
        return job.job_id, f"Started job {job.job_id}: update-data"

    if trig == "an-btn-eod":
        job = start_engine_job(argv=["eod"])
        return job.job_id, f"Started job {job.job_id}: eod"

    if trig == "an-btn-eod-update":
        job = start_engine_job(argv=["eod", "--update-data"])
        return job.job_id, f"Started job {job.job_id}: eod --update-data"

    raise __import__("dash").exceptions.PreventUpdate


@app.callback(
    Output("an-tabs-content", "children"),
    Input("an-tabs", "value"),
)
def _render_tab(tab):
    if tab == "run-center":
        # Return a container with a dynamic updating section
        return html.Div(
            [
                html.Div([
                    html.A(html.Button("Update Data", id="an-btn-update", n_clicks=0, style={'marginRight': '10px'})),
                    html.A(html.Button("Run EOD", id="an-btn-eod", n_clicks=0, style={'marginRight': '10px'})),
                    html.A(html.Button("Run EOD (+update)", id="an-btn-eod-update", n_clicks=0)),
                ], style={'padding': '15px'}),
                html.Div(id="an-job-status", children="No job running.", style={'padding': '0 15px', 'fontStyle': 'italic'}),
                html.Div(id="an-run-center-content"),
                dcc.Interval(id="an-run-center-interval", interval=5_000, n_intervals=0),
            ]
        )

    if tab == "beta":
        return html.Div(
            [
                html.H5("Beta Book (Top-down)"),
                html.P("Planned: factor/regime → portfolio construction → risk-managed execution."),
                html.Div(
                    [
                        dcc.Tabs(
                            id="an-beta-subtabs",
                            value="factor",
                            vertical=True,
                            children=[
                                dcc.Tab(label="FACTOR", value="factor", style=tab_style, selected_style=tab_selected_style),
                                dcc.Tab(label="PORTFOLIO", value="portfolio", style=tab_style, selected_style=tab_selected_style),
                                dcc.Tab(label="FUTURES", value="backtest-factor", style=tab_style, selected_style=tab_selected_style),
                                dcc.Tab(label="REBALANCE", value="backtest-portfolio", style=tab_style, selected_style=tab_selected_style),
                                dcc.Tab(label="SURFACE", value="surface", style=tab_style, selected_style=tab_selected_style),
                            ],
                            style={"height": "520px"},
                        ),
                        html.Div(id="an-beta-subtabs-content", style={"paddingLeft": "16px", "width": "100%"}),
                    ],
                    style={"display": "flex", "flexDirection": "row", "gap": "12px"},
                ),
            ]
        )

    if tab == "alpha":
        return html.Div(
            [
                html.H5("Alpha Book (Bottom-up)"),
                html.P("Relative value alpha: candidates → correlation check → scoring → risk parity sizing → basket."),
                html.Div(
                    [
                        dcc.Tabs(
                            id="an-alpha-subtabs",
                            value="candidates",
                            vertical=True,
                            children=[
                                dcc.Tab(label="CANDIDATES", value="candidates", style=tab_style, selected_style=tab_selected_style),
                                dcc.Tab(label="VOLATILITY", value="volatility", style=tab_style, selected_style=tab_selected_style),
                                dcc.Tab(label="SCORING", value="scoring", style=tab_style, selected_style=tab_selected_style),
                                dcc.Tab(label="BACKTEST", value="backtest", style=tab_style, selected_style=tab_selected_style),
                                dcc.Tab(label="BASKET", value="basket", style=tab_style, selected_style=tab_selected_style),
                                dcc.Tab(label="SPREAD INFO", value="spreads", style=tab_style, selected_style=tab_selected_style),
                                dcc.Tab(label="PAIRS", value="pairs", style=tab_style, selected_style=tab_selected_style),
                                dcc.Tab(label="CURVES", value="curves", style=tab_style, selected_style=tab_selected_style),
                            ],
                            style={"height": "520px"},
                        ),
                        html.Div(id="an-alpha-subtabs-content", style={"paddingLeft": "16px", "width": "100%"}),
                    ],
                    style={"display": "flex", "flexDirection": "row", "gap": "12px"},
                ),
            ]
        )

    if tab == "risk":
        return build_multiasset_risk_layout()

    return html.Div([html.P(f"Unknown tab: {tab}")])


@app.callback(
    Output("an-run-center-content", "children"),
    Input("an-run-center-interval", "n_intervals"),
    State("an-job-id", "data"),
)
def _update_run_center(n, job_id):
    """Update Run Center content on interval - only when Run Center tab is active."""
    meta = find_latest_run(mode="eod")
    # Job info
    status = get_job_status(job_id) if job_id else None
    if status:
        state = status.get("state", "UNKNOWN")
        pid = status.get("pid")
        started = status.get("started_at")
        ended = status.get("ended_at")
        cmd = status.get("cmd")
        return html.Div(
            [
                html.H5("Run Center"),
                html.P("Use the buttons above to run engine jobs."),
                html.P(f"Latest EOD run: {format_run_meta(meta)}"),
                html.Hr(),
                html.Div(
                    [
                        html.H6("Job status"),
                        html.Div(
                            [
                                html.Strong("Job ID: "),
                                html.Span(job_id),
                                html.Br(),
                                html.Strong("State: "),
                                html.Span(state),
                                html.Br(),
                                html.Strong("PID: "),
                                html.Span(str(pid)),
                                html.Br(),
                                html.Strong("Started: "),
                                html.Span(str(started)),
                                html.Br(),
                                html.Strong("Ended: "),
                                html.Span(str(ended)),
                                html.Br(),
                                html.Strong("Cmd: "),
                                html.Code(str(cmd)),
                            ],
                            style={"lineHeight": "1.6em"},
                        ),
                    ],
                    style={"marginBottom": "12px"},
                ),
                html.H6("Job log (tail)"),
                html.Pre(
                    tail_log(job_id, max_lines=200),
                    style={"whiteSpace": "pre-wrap", "maxHeight": "360px", "overflowY": "auto"},
                ),
            ]
        )
    else:
        # No active job selected: show latest run meta and a helpful hint
        return html.Div(
            [
                html.H5("Run Center"),
                html.P("Use the buttons above to run engine jobs."),
                html.P(f"Latest EOD run: {format_run_meta(meta)}"),
                html.Hr(),
                html.P("No active job selected. Start a job using the header buttons to see live logs and status."),
            ]
        )


@app.callback(
    Output("an-beta-subtabs-content", "children"),
    Input("an-beta-subtabs", "value"),
)
def _render_beta_subtabs(subtab: str):
    if subtab == "factor":
        return build_multiasset_factor_layout()

    if subtab == "portfolio":
        return build_multiasset_portfolio_layout()

    if subtab == "backtest-factor":
        return build_factor_backtest_layout()

    if subtab == "backtest-portfolio":
        return build_multiasset_backtest_layout()

    if subtab == "surface":
        return build_surface_layout()

    return html.Div([html.P(f"Unknown Beta subtab: {subtab}")])


@app.callback(
    Output("an-alpha-subtabs-content", "children"),
    Input("an-alpha-subtabs", "value"),
)
def _render_alpha_subtabs(subtab: str):
    if subtab == "candidates":
        return build_candidates_layout()
    if subtab == "volatility":
        return build_volatility_layout()
    if subtab == "scoring":
        return build_scoring_layout()
    if subtab == "backtest":
        return build_backtest_layout()
    if subtab == "basket":
        return build_basket_layout()
    if subtab == "spreads":
        return build_spreads_layout()
    if subtab == "pairs":
        return build_pairs_layout()
    if subtab == "curves":
        return build_curves_layout()

    return html.Div([html.P(f"Unknown Alpha subtab: {subtab}")])



if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=False, use_reloader=False)
