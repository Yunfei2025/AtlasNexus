# -*- coding: utf-8 -*-
"""AtlasNexus Daily Console (EOD).

A new Dash app that mirrors the styling of web/apps/fi.py,
without modifying existing apps.

Port: 8080
"""

from __future__ import annotations
import sys
import os
from dash import dcc, html
from dash.dependencies import Input, Output, State

from pathlib import Path
# Add project root to Python path
project_root = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(project_root))

# Import lightweight style constants (do not import web.core which triggers data loads).
from web.tabs.atlas_styles import tab_style, tabs_styles, tab_selected_style

# We intentionally create a new Dash instance to avoid interfering with existing apps.
from dash import Dash as _Dash
import pathlib

from web.services.artifacts import find_latest_run, format_run_meta
from web.services.jobs import (
    start_engine_job, tail_log, get_job_status,
    list_running_jobs, finalize_job_if_done, _cmd_type,
)

from web.tabs.atlas_fi_tabs import (
    build_curves_layout,
    build_pairs_layout,
    build_spreads_layout,
    build_surface_layout,
    register_callbacks as register_fi_callbacks,
)

from web.tabs.atlas_alpha_tabs import (
    build_candidates_layout,
    build_portfolio_layout,
    build_basket_layout,
    build_backtest_layout,
    register_alpha_callbacks,
)

from web.tabs.atlas_multiasset_tabs import (
    build_multiasset_factor_layout,
    build_multiasset_portfolio_layout,
    build_multiasset_bond_layout,
    build_multiasset_risk_layout,
    build_multiasset_backtest_layout,
    build_factor_backtest_layout,
    register_multiasset_callbacks,
)

from web.tabs.atlas_volatility_tabs import (
    build_volatility_layout,
    register_volatility_callbacks,
)

from web.tabs.atlas_factor_backtest_tabs import (
    build_factor_model_backtest_layout,
    register_factor_backtest_callbacks,
)

from web.tabs.atlas_trend_tabs import (
    build_trend_layout,
    register_trend_callbacks,
)


GRAPH_INTERVAL = int(os.environ.get("GRAPH_INTERVAL", 30 * 60_000))


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
    from flask import send_file, abort

    pairs_file = project_root / "pairs" / "regression_plots.html"
    if pairs_file.exists():
        return send_file(str(pairs_file))
    abort(404)

# Register callbacks for migrated legacy FI layouts (Pairs tab refresh callback).
register_fi_callbacks(app)
register_multiasset_callbacks(app)
register_alpha_callbacks(app)
register_volatility_callbacks(app)
register_factor_backtest_callbacks(app)
register_trend_callbacks(app)


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
    # Pre-build all main tab contents to preserve state
    _btn_style = {
        'background': '#1a3a6e', 'color': '#ffffff', 'border': '1px solid #2a5298',
        'borderRadius': '4px', 'padding': '6px 14px', 'cursor': 'pointer', 'fontSize': '13px',
    }
    _lbl_style = {'color': '#aab0c0', 'fontSize': '11px', 'marginBottom': '4px', 'display': 'block'}
    _input_style = {
        'background': '#112e66', 'color': '#ffffff', 'border': '1px solid #2a5298',
        'borderRadius': '4px', 'padding': '5px 8px', 'width': '100%', 'fontSize': '13px',
    }
    _dd_style = {'fontSize': '13px'}
    _dd_theme = {
        'backgroundColor': '#112e66',
        'optionHeight': 30,
    }

    run_center_content = html.Div(
        [
            # ── Engine jobs row ──────────────────────────────────────────────
            html.Div([
                html.A(html.Button("Update Data",       id="an-btn-update",     n_clicks=0, style={**_btn_style, 'marginRight': '10px'})),
                html.A(html.Button("Run EOD",           id="an-btn-eod",        n_clicks=0, style={**_btn_style, 'marginRight': '10px'})),
                html.A(html.Button("Run EOD (+update)", id="an-btn-eod-update", n_clicks=0, style=_btn_style)),
            ], style={'padding': '15px 15px 8px 15px'}),

            # ── Curve Backtest panel ─────────────────────────────────────────
            html.Hr(style={'borderColor': '#1a3a6e', 'margin': '0 12px 0 12px'}),
            html.Div([
                html.Div("CURVE BACKTEST", style={
                    'color': '#aab0c0', 'fontSize': '11px', 'fontWeight': '600',
                    'letterSpacing': '0.08em', 'marginBottom': '12px',
                }),
                html.Div([
                    # Instrument type
                    html.Div([
                        html.Label("Instrument Type", style=_lbl_style),
                        dcc.Dropdown(
                            id="an-bt-btype",
                            options=[
                                {'label': 'IRS',   'value': 'IRS'},
                                {'label': 'TBond', 'value': 'TBond'},
                                {'label': 'CBond', 'value': 'CBond'},
                            ],
                            value='IRS',
                            clearable=False,
                            style=_dd_style,
                        ),
                    ], style={'minWidth': '120px', 'flex': '0 0 120px'}),
                    # Update steps
                    html.Div([
                        html.Label("Update Steps", style=_lbl_style),
                        dcc.Dropdown(
                            id="an-bt-update-list",
                            options=[
                                {'label': 'pool',  'value': 'pool'},
                                {'label': 'bonds', 'value': 'bonds'},
                                {'label': 'cbts',  'value': 'cbts'},
                            ],
                            value=['pool'],
                            multi=True,
                            clearable=False,
                            style=_dd_style,
                        ),
                    ], style={'minWidth': '200px', 'flex': '1 1 200px'}),
                    # Start date
                    html.Div([
                        html.Label("Start Date", style=_lbl_style),
                        dcc.Input(
                            id="an-bt-start",
                            type="text",
                            value="2026-01-01",
                            placeholder="YYYY-MM-DD",
                            debounce=True,
                            style=_input_style,
                        ),
                    ], style={'minWidth': '120px', 'flex': '0 0 120px'}),
                    # End date
                    html.Div([
                        html.Label("End Date", style=_lbl_style),
                        dcc.Input(
                            id="an-bt-end",
                            type="text",
                            value="2026-03-01",
                            placeholder="YYYY-MM-DD",
                            debounce=True,
                            style=_input_style,
                        ),
                    ], style={'minWidth': '120px', 'flex': '0 0 120px'}),
                    # Workers
                    html.Div([
                        html.Label("Workers", style=_lbl_style),
                        dcc.Input(
                            id="an-bt-processes",
                            type="number",
                            value=4,
                            min=1,
                            max=32,
                            step=1,
                            style=_input_style,
                        ),
                    ], style={'minWidth': '80px', 'flex': '0 0 80px'}),
                    # Run button (aligned to bottom of row)
                    html.Div([
                        html.Button(
                            "▶  Run Backtest",
                            id="an-btn-backtest",
                            n_clicks=0,
                            style={**_btn_style, 'background': '#1a5276', 'borderColor': '#2e86c1',
                                   'fontWeight': '600', 'marginTop': '18px'},
                        ),
                    ]),
                ], style={
                    'display': 'flex', 'flexDirection': 'row', 'gap': '12px',
                    'alignItems': 'flex-end', 'flexWrap': 'wrap',
                }),
            ], style={
                'padding': '14px 15px', 'background': '#0c2b64',
                'margin': '10px 12px', 'borderRadius': '6px',
            }),

            # ── Status + log ─────────────────────────────────────────────────
            html.Div(id="an-job-status", children="No job running.",
                     style={'padding': '4px 15px', 'fontStyle': 'italic', 'color': '#aab0c0', 'fontSize': '12px'}),
            html.Div(id="an-run-center-content"),
            dcc.Interval(id="an-run-center-interval", interval=5_000, n_intervals=0),
        ]
    )
    
    beta_content = html.Div(
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
                            dcc.Tab(label="BOND", value="bond", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="BACKTEST", value="factor-model-bt", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="FUTURES", value="backtest-factor", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="REBALANCE", value="backtest-portfolio", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="SURFACE", value="surface", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="TREND",   value="trend",   style=tab_style, selected_style=tab_selected_style),
                        ],
                        style={"height": "520px"},
                    ),
                    html.Div([
                        html.Div(id="beta-factor-div",            children=build_multiasset_factor_layout(),    style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "block"}),
                        html.Div(id="beta-portfolio-div",         children=build_multiasset_portfolio_layout(), style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "none"}),
                        html.Div(id="beta-bond-div",              children=build_multiasset_bond_layout(),      style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "none"}),
                        html.Div(id="beta-factor-model-bt-div",   children=build_factor_model_backtest_layout(), style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "none"}),
                        html.Div(id="beta-backtest-factor-div",   children=build_factor_backtest_layout(),      style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "none"}),
                        html.Div(id="beta-backtest-portfolio-div",children=build_multiasset_backtest_layout(),  style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "none"}),
                        html.Div(id="beta-surface-div",           children=build_surface_layout(),              style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "none"}),
                        html.Div(id="beta-trend-div",             children=build_trend_layout(),                style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "none"}),
                    ], style={"position": "relative", "width": "100%", "minHeight": "500px"}),
                ],
                style={"display": "flex", "flexDirection": "row", "gap": "12px"},
            ),
        ]
    )
    
    alpha_content = html.Div(
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
                            dcc.Tab(label="PORTFOLIO", value="portfolio", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="BACKTEST", value="backtest", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="BASKET", value="basket", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="SPREAD", value="spreads", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="PAIRS", value="pairs", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="CURVES", value="curves", style=tab_style, selected_style=tab_selected_style),
                            dcc.Tab(label="VOLATILITY", value="volatility", style=tab_style, selected_style=tab_selected_style),
                        ],
                        style={"height": "520px"},
                    ),
                    html.Div([
                        html.Div(id="alpha-candidates-div", children=build_candidates_layout(), style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "block"}),
                        html.Div(id="alpha-portfolio-div", children=build_portfolio_layout(), style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "none"}),
                        html.Div(id="alpha-backtest-div", children=build_backtest_layout(), style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "none"}),
                        html.Div(id="alpha-basket-div", children=build_basket_layout(), style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "none"}),
                        html.Div(id="alpha-spreads-div", children=build_spreads_layout(), style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "none"}),
                        html.Div(id="alpha-pairs-div", children=build_pairs_layout(), style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "none"}),
                        html.Div(id="alpha-curves-div", children=build_curves_layout(), style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "none"}),
                        html.Div(id="alpha-volatility-div", children=build_volatility_layout(), style={"position": "absolute", "top": "0", "left": "16px", "right": "0", "display": "none"}),
                    ], style={"position": "relative", "width": "100%", "minHeight": "500px"}),
                ],
                style={"display": "flex", "flexDirection": "row", "gap": "12px"},
            ),
        ]
    )
    
    risk_content = build_multiasset_risk_layout()
    
    return html.Div(
        [
            # Shared stores for persisting content across tab switches
            dcc.Store(id='alpha-selected-candidates', data=[]),
            dcc.Store(id='alpha-candidates-content', storage_type='session'),
            dcc.Store(id='alpha-portfolio-content', storage_type='session'),
            dcc.Store(id='alpha-backtest-content', storage_type='session'),
            dcc.Store(id='alpha-basket-content', storage_type='session'),
            dcc.Store(id='alpha-spreads-content', storage_type='session'),
            dcc.Store(id='alpha-pairs-content', storage_type='session'),
            dcc.Store(id='alpha-curves-content', storage_type='session'),
            dcc.Store(id='alpha-volatility-content', storage_type='session'),
            dcc.Store(id='beta-factor-content', storage_type='session'),
            dcc.Store(id='beta-portfolio-content', storage_type='session'),
            dcc.Store(id='beta-factor-model-bt-content', storage_type='session'),
            dcc.Store(id='beta-backtest-factor-content', storage_type='session'),
            dcc.Store(id='beta-backtest-portfolio-content', storage_type='session'),
            dcc.Store(id='beta-surface-content', storage_type='session'),
            dcc.Store(id='beta-trend-content', storage_type='session'),
            dcc.Store(id='an-autoruns1-status', storage_type='memory'),
            dcc.Store(id='an-autoruns2-status', storage_type='memory'),
            
            # Shared intervals
            dcc.Interval(id="data-refresh", interval=GRAPH_INTERVAL, n_intervals=0),
            
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
                        ],
                        style=tabs_styles,
                    ),
                    # Pre-render all main tabs with absolute positioning to preserve state
                    html.Div([
                        html.Div(id="run-center-div", children=run_center_content, style={"position": "relative", "display": "block"}),
                        html.Div(id="beta-div", children=beta_content, style={"position": "relative", "display": "none"}),
                        html.Div(id="alpha-div", children=alpha_content, style={"position": "relative", "display": "none"}),
                        html.Div(id="risk-div", children=risk_content, style={"position": "relative", "display": "none"}),
                    ], style={"width": "100%"}),
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
    Output("an-autoruns1-status", "data"),
    Input("data-refresh", "n_intervals"),
)
def _run_core_autoruns1(n_intervals):
    try:
        from web.core.scripts import autoruns1 as core_autoruns1

        return core_autoruns1(n_intervals, "AtlasNexus Daily active")
    except Exception as exc:
        return f"autoruns1 failed: {exc}"


@app.callback(
    Output("an-autoruns2-status", "data"),
    Input("data-refresh", "n_intervals"),
)
def _run_core_autoruns2(n_intervals):
    try:
        from web.core.scripts import autoruns2 as core_autoruns2

        return core_autoruns2(n_intervals, "AtlasNexus Daily active")
    except Exception as exc:
        return f"autoruns2 failed: {exc}"


@app.callback(
    Output("an-job-id", "data"),
    Output("an-job-status", "children"),
    Input("an-btn-update", "n_clicks"),
    Input("an-btn-eod", "n_clicks"),
    Input("an-btn-eod-update", "n_clicks"),
    Input("an-btn-backtest", "n_clicks"),
    State("an-bt-btype", "value"),
    State("an-bt-update-list", "value"),
    State("an-bt-start", "value"),
    State("an-bt-end", "value"),
    State("an-bt-processes", "value"),
    prevent_initial_call=True,
)
def _start_jobs(n_update, n_eod, n_eod_update, n_bt,
                bt_btype, bt_update_list, bt_start, bt_end, bt_processes):
    ctx = __import__("dash").callback_context
    if not ctx.triggered:
        raise __import__("dash").exceptions.PreventUpdate

    trig = ctx.triggered[0]["prop_id"].split(".")[0]

    if trig == "an-btn-update":
        job = start_engine_job(argv=["update-data", "--force"])
        return job.job_id, f"Started job {job.job_id}: update-data --force"

    if trig == "an-btn-eod":
        job = start_engine_job(argv=["eod"])
        return job.job_id, f"Started job {job.job_id}: eod"

    if trig == "an-btn-eod-update":
        job = start_engine_job(argv=["eod", "--update-data"])
        return job.job_id, f"Started job {job.job_id}: eod --update-data"

    if trig == "an-btn-backtest":
        btype = bt_btype or "IRS"
        ul = bt_update_list or ["pool"]
        start = (bt_start or "").strip()
        end = (bt_end or "").strip()
        procs = str(int(bt_processes)) if bt_processes else "4"
        argv = ["curve-backtest", "--btype", btype,
                "--update-list", *ul,
                "--start", start, "--end", end,
                "--processes", procs]
        job = start_engine_job(argv=argv)
        return job.job_id, f"Started job {job.job_id}: curve-backtest ({btype}, {start}→{end})"

    raise __import__("dash").exceptions.PreventUpdate


@app.callback(
    [Output("run-center-div", "style"),
     Output("beta-div", "style"),
     Output("alpha-div", "style"),
     Output("risk-div", "style")],
    Input("an-tabs", "value"),
)
def _render_tab(tab):
    """Show/hide main tabs to preserve state."""
    styles = {
        "run-center": {"display": "block"} if tab == "run-center" else {"display": "none"},
        "beta": {"display": "block"} if tab == "beta" else {"display": "none"},
        "alpha": {"display": "block"} if tab == "alpha" else {"display": "none"},
        "risk": {"display": "block"} if tab == "risk" else {"display": "none"},
    }
    
    return styles["run-center"], styles["beta"], styles["alpha"], styles["risk"]


@app.callback(
    Output("an-run-center-content", "children"),
    Input("an-run-center-interval", "n_intervals"),
    State("an-job-id", "data"),
)
def _update_run_center(n, job_id):
    """Update Run Center content on interval.

    Each tick:
    - Auto-finalizes any RUNNING jobs whose PID has exited.
    - Shows a live "running jobs" badge strip.
    - Shows full log/status for the last-launched job (job_id from store).
    """
    meta = find_latest_run(mode="eod")

    # Auto-finalize all stale RUNNING jobs and collect what is truly running.
    running_jobs = list_running_jobs()  # already finalizes stale entries internally

    _state_colors = {
        "RUNNING":  ("#1a5276", "#2e86c1"),
        "FINISHED": ("#1a4731", "#27ae60"),
        "FAILED":   ("#6e1a1a", "#c0392b"),
    }

    def _badge(s):
        bg, fg = _state_colors.get(s, ("#2c2c3e", "#aab0c0"))
        return html.Span(
            s,
            style={
                "background": bg, "color": fg, "border": f"1px solid {fg}",
                "borderRadius": "3px", "padding": "1px 6px",
                "fontSize": "11px", "fontWeight": "600",
            },
        )

    def _job_row(s):
        jid   = s.get("job_id", "?")
        state = s.get("state", "UNKNOWN")
        jtype = _cmd_type(s.get("cmd", [])) or "?"
        pid   = s.get("pid")
        start = s.get("started_at", "")[:19]
        return html.Div(
            [
                _badge(state),
                html.Span(f" {jtype}",  style={"color": "#ffffff", "fontWeight": "600", "marginLeft": "6px"}),
                html.Span(f" {jid[:8]}\u2026", style={"color": "#aab0c0", "fontSize": "11px"}),
                html.Span(f" pid={pid}",       style={"color": "#aab0c0", "fontSize": "11px", "marginLeft": "8px"}),
                html.Span(f" started {start}", style={"color": "#aab0c0", "fontSize": "11px", "marginLeft": "8px"}),
            ],
            style={"padding": "4px 0"},
        )

    # Running jobs banner
    if running_jobs:
        banner = html.Div(
            [html.Div("RUNNING JOBS", style={"color": "#aab0c0", "fontSize": "11px",
                                              "fontWeight": "600", "letterSpacing": "0.08em",
                                              "marginBottom": "6px"})] +
            [_job_row(j) for j in running_jobs],
            style={"background": "#0c2b64", "border": "1px solid #2a5298",
                   "borderRadius": "5px", "padding": "10px 14px", "marginBottom": "10px"},
        )
    else:
        banner = html.Div(
            "No jobs currently running.",
            style={"color": "#aab0c0", "fontSize": "12px", "fontStyle": "italic",
                   "marginBottom": "8px"},
        )

    # Finalize & refresh status for the tracked job_id
    status = None
    if job_id:
        status = finalize_job_if_done(job_id)

    header = html.Div(
        [
            html.P(f"Latest EOD run: {format_run_meta(meta)}",
                   style={"margin": "0 0 8px 0", "color": "#aab0c0", "fontSize": "12px"}),
            banner,
        ]
    )

    if status:
        state   = status.get("state", "UNKNOWN")
        pid     = status.get("pid")
        started = status.get("started_at", "")[:19]
        ended   = status.get("ended_at", "") or "—"
        cmd     = status.get("cmd", [])
        jtype   = _cmd_type(cmd) or "?"
        return html.Div(
            [
                header,
                html.Hr(style={"borderColor": "#1a3a6e", "margin": "0 0 10px 0"}),
                html.Div(
                    [
                        html.Div(
                            "LAST JOB",
                            style={"color": "#aab0c0", "fontSize": "11px", "fontWeight": "600",
                                   "letterSpacing": "0.08em", "marginBottom": "6px"},
                        ),
                        html.Div(
                            [
                                _badge(state),
                                html.Span(f"  {jtype}",
                                          style={"color": "#ffffff", "fontWeight": "600"}),
                            ],
                            style={"marginBottom": "6px"},
                        ),
                        html.Div(
                            [
                                html.Strong("Job ID: "),   html.Span(job_id), html.Br(),
                                html.Strong("PID: "),      html.Span(str(pid)), html.Br(),
                                html.Strong("Started: "),  html.Span(started), html.Br(),
                                html.Strong("Ended: "),    html.Span(str(ended)[:19]), html.Br(),
                                html.Strong("Cmd: "),      html.Code(" ".join(str(a) for a in cmd)),
                            ],
                            style={"lineHeight": "1.8em", "fontSize": "12px"},
                        ),
                    ],
                    style={"background": "#082255", "borderRadius": "5px",
                           "padding": "10px 14px", "marginBottom": "10px"},
                ),
                html.Div(
                    "LOG OUTPUT (TAIL)",
                    style={"color": "#aab0c0", "fontSize": "11px", "fontWeight": "600",
                           "letterSpacing": "0.08em", "marginBottom": "4px"},
                ),
                html.Pre(
                    tail_log(job_id, max_lines=200),
                    style={"whiteSpace": "pre-wrap", "maxHeight": "360px", "overflowY": "auto",
                           "background": "#040f24", "color": "#c8d8f0",
                           "padding": "10px", "borderRadius": "4px", "fontSize": "12px"},
                ),
            ]
        )
    else:
        return html.Div(
            [
                header,
                html.Hr(style={"borderColor": "#1a3a6e", "margin": "0 0 10px 0"}),
                html.P(
                    "No active job selected. Start a job using the buttons above to see live logs.",
                    style={"color": "#aab0c0", "fontStyle": "italic", "fontSize": "12px"},
                ),
            ]
        )


@app.callback(
    [Output("beta-factor-div", "style"),
     Output("beta-portfolio-div", "style"),
    Output("beta-bond-div", "style"),
     Output("beta-factor-model-bt-div", "style"),
     Output("beta-backtest-factor-div", "style"),
     Output("beta-backtest-portfolio-div", "style"),
     Output("beta-surface-div", "style"),
     Output("beta-trend-div", "style")],
    Input("an-beta-subtabs", "value"),
)
def _render_beta_subtabs(subtab: str):
    """Show/hide Beta Book subtabs to preserve state."""
    base_style = {"position": "absolute", "top": "0", "left": "16px", "right": "0"}
    keys = ["factor", "portfolio", "bond", "factor-model-bt", "backtest-factor", "backtest-portfolio", "surface", "trend"]
    return tuple(
        {**base_style, "display": "block"} if subtab == k else {**base_style, "display": "none"}
        for k in keys
    )


@app.callback(
    [Output("alpha-candidates-div", "style"),
     Output("alpha-portfolio-div", "style"),
     Output("alpha-backtest-div", "style"),
     Output("alpha-basket-div", "style"),
     Output("alpha-spreads-div", "style"),
     Output("alpha-pairs-div", "style"),
     Output("alpha-curves-div", "style"),
     Output("alpha-volatility-div", "style")],
    Input("an-alpha-subtabs", "value"),
)
def _render_alpha_subtabs(subtab: str):
    """Show/hide Alpha Book subtabs to preserve state."""
    base_style = {"position": "absolute", "top": "0", "left": "16px", "right": "0"}
    styles = {
        "candidates": {**base_style, "display": "block"} if subtab == "candidates" else {**base_style, "display": "none"},
        "portfolio": {**base_style, "display": "block"} if subtab == "portfolio" else {**base_style, "display": "none"},
        "backtest": {**base_style, "display": "block"} if subtab == "backtest" else {**base_style, "display": "none"},
        "basket": {**base_style, "display": "block"} if subtab == "basket" else {**base_style, "display": "none"},
        "spreads": {**base_style, "display": "block"} if subtab == "spreads" else {**base_style, "display": "none"},
        "pairs": {**base_style, "display": "block"} if subtab == "pairs" else {**base_style, "display": "none"},
        "curves": {**base_style, "display": "block"} if subtab == "curves" else {**base_style, "display": "none"},
        "volatility": {**base_style, "display": "block"} if subtab == "volatility" else {**base_style, "display": "none"},
    }
    
    return (
        styles["candidates"],
        styles["portfolio"],
        styles["backtest"],
        styles["basket"],
        styles["spreads"],
        styles["pairs"],
        styles["curves"],
        styles["volatility"]
    )



if __name__ == "__main__":
    # Delegate to the canonical entry point so there is one startup path.
    import subprocess, sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    raise SystemExit(
        subprocess.call([sys.executable, str(root / "main.py"), "daily-web"])
    )
