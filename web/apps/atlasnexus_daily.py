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
from web.tabs.atlas_styles import (
    summary_subtabs_style, summary_subtabs_colors,
    BOOK_ACCENT,
    ATLAS_PLOTLY_TEMPLATE,
)

# Register AtlasNexus Plotly theme globally so all figures pick it up.
import plotly.io as _pio
_pio.templates["atlas"] = ATLAS_PLOTLY_TEMPLATE
_pio.templates.default = "plotly_dark+atlas"

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
    build_backtest_layout,
    register_alpha_callbacks,
)

from web.tabs.atlas_multiasset_tabs import (
    build_multiasset_factor_layout,
    build_multiasset_portfolio_layout,
    build_multiasset_bond_layout,
    build_multiasset_risk_layout,
    build_multiasset_backtest_layout,
    build_risk_factor_backtest_layout,
    build_factor_backtest_layout,
    build_beta_backtest_combined_layout,
    build_factor_history_layout,
    register_multiasset_callbacks,
)

from web.tabs.atlas_volatility_tabs import (
    build_volatility_layout,
    register_volatility_callbacks,
)

from web.tabs.atlas_factor_backtest_tabs import (
    build_factor_model_backtest_layout,
    # register_factor_backtest_callbacks,  # replaced by rfbt- callbacks in multiasset
)

from web.tabs.atlas_trend_tabs import (
    build_trend_layout,
    register_trend_callbacks,
)

from web.tabs.atlas_market_data_tab import (
    build_market_data_layout,
    register_market_data_callbacks,
)

from web.tabs.atlas_pricer_tab import (
    build_pricer_layout,
    register_pricer_callbacks,
)


# Refresh interval constants (milliseconds) — tune these in one place
GRAPH_INTERVAL        = int(os.environ.get("GRAPH_INTERVAL", 30 * 60_000))  # data graphs: 30 min
_INTERVAL_HEADER_MS   = 5_000   # header clock + job pill strip
_INTERVAL_RUN_CTR_MS  = 5_000   # run center log tail / job status

# ---------------------------------------------------------------------------
# Module-level style constants (shared across all layout builders)
# ---------------------------------------------------------------------------
_BTN_STYLE: dict = {
    'background': '#1a3a6e', 'color': '#ffffff', 'border': '1px solid #2a5298',
    'borderRadius': '4px', 'padding': '6px 14px', 'cursor': 'pointer', 'fontSize': '13px',
}
_LBL_STYLE: dict = {
    'color': '#aab0c0', 'fontSize': '11px', 'marginBottom': '4px', 'display': 'block',
}
_INPUT_STYLE: dict = {
    'background': '#112e66', 'color': '#ffffff', 'border': '1px solid #2a5298',
    'borderRadius': '4px', 'padding': '5px 8px', 'width': '100%', 'fontSize': '13px',
}
_DD_STYLE: dict = {'fontSize': '13px'}
_DD_THEME: dict = {'backgroundColor': '#112e66', 'optionHeight': 30}

assets_folder = str(project_root / "web" / "assets")

app = _Dash(
    __name__,
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
    assets_folder=assets_folder,
    url_base_pathname="/dashboard/",
)

app.title = "AtlasNexus Daily Console"

# Serve the cover page (AtlasNexus landing page)
@app.server.route("/")
def _serve_cover():
    from flask import send_file, abort

    cover_file = project_root / "web" / "assets" / "cover.html"
    if cover_file.exists():
        return send_file(str(cover_file))
    abort(404)


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
# register_factor_backtest_callbacks(app)  # replaced by rfbt- callbacks in multiasset
register_trend_callbacks(app)
register_market_data_callbacks(app)
register_pricer_callbacks(app)


def build_header():
    return html.Div(
        [
            # ---- Left: title + timestamps ----
            html.Div(
                [
                    html.H4([
                        "AtlasNexus ",
                        html.Span("·", className="sep"),
                        " Daily",
                    ], className="app__header__title"),
                    html.P(id="an-latest-run",
                           style={"fontSize": "12px", "margin": "0", "color": "#ffffff", "fontWeight": "500"}),
                    html.P(id="an-refresh-time", className="app__header__title--grey",
                           style={"fontSize": "10px", "margin": "0", "opacity": "0.6"}),
                ],
                className="app__header__desc",
            ),
            # ---- Right: live status strip ----
            html.Div(
                [
                    dcc.Store(id="an-job-id", storage_type="memory"),
                    html.Div(id="an-header-status", className="an-header-status"),
                ],
                style={"display": "flex", "flexDirection": "column",
                       "alignItems": "flex-end", "justifyContent": "center", "gap": "6px"},
            ),
        ],
        className="app__header",
    )


def build_tabs_panel():
    # Pre-build all main tab contents to preserve state
    _btn_style   = _BTN_STYLE
    _lbl_style   = _LBL_STYLE
    _input_style = _INPUT_STYLE
    _dd_style    = _DD_STYLE
    _dd_theme    = _DD_THEME


    # Default start/end for Run Center: end = previous CN workday, start = end - 3 months
    try:
        from settings.general import DateConfig
        from dateutil.relativedelta import relativedelta
        dp = DateConfig.get_date_mappings()['dp'].date()
        end_default = dp.strftime('%Y-%m-%d')
        start_default = (dp - relativedelta(months=3)).strftime('%Y-%m-%d')
    except Exception:
        # Fallback to a sensible static default if date utilities are unavailable
        end_default = '2026-05-15'
        start_default = '2026-02-15'

    # As-of date default for EOD button:
    #   before 6pm → previous CN working day (same as end_default)
    #   from 6pm onward → today
    try:
        import datetime as _dt
        import chinese_calendar as _cc
        _now = _dt.datetime.now()
        if _now.hour >= 18:
            # today — walk back to nearest working day if today is a holiday/weekend
            _asof = _now.date()
            while not _cc.is_workday(_asof):
                _asof -= _dt.timedelta(days=1)
        else:
            # previous working day
            _asof = _now.date() - _dt.timedelta(days=1)
            while not _cc.is_workday(_asof):
                _asof -= _dt.timedelta(days=1)
        asof_default = _asof.strftime('%Y-%m-%d')
    except Exception:
        asof_default = end_default

    run_center_content = html.Div(
        [
            html.Div([
            # ── Daily Pipeline card ──────────────────────────────────────────
            html.Div([
                html.Div("DAILY PIPELINE", className="an-card-hdr"),
                html.Div([
                    html.Button("Update Data",         id="an-btn-update",     n_clicks=0, style={**_btn_style, 'marginRight': '10px'}),
                    html.Button("Run EOD",             id="an-btn-eod",        n_clicks=0, style={**_btn_style, 'marginRight': '10px'}),
                    html.Button("Run EOD (+update)",   id="an-btn-eod-update", n_clicks=0, style={**_btn_style, 'marginRight': '16px'}),
                    html.Button("Refresh Instruments", id="an-btn-refresh-instruments", n_clicks=0, style={**_btn_style, 'marginRight': '10px'}),
                    # As-of date shared by all buttons — on the same row
                    html.Div([
                        html.Label("As Of Date", style={**_lbl_style, 'marginBottom': '4px', 'display': 'block'}),
                        dcc.DatePickerSingle(
                            id="an-eod-asof",
                            date=asof_default,
                            display_format='YYYY-MM-DD',
                            first_day_of_week=1,
                            style={'fontSize': '13px', 'minWidth': '140px'},
                        ),
                    ], style={'display': 'flex', 'flexDirection': 'column', 'justifyContent': 'center', 'position': 'relative', 'zIndex': '1001'}),
                ], style={'display': 'flex', 'flexDirection': 'row', 'alignItems': 'flex-end', 'flexWrap': 'wrap', 'gap': '14px', 'padding': '22px'}),
            ], className="an-card"),

            # ── Data Backfill card ──────────────────────────────────────────
            html.Div([
                html.Div("DATA BACKFILL", className="an-card-hdr"),
                html.Div([
                    html.Div([
                        # Instrument type
                        html.Div([
                            html.Label("Instrument Type", style=_lbl_style),
                            dcc.Dropdown(
                                id="an-bt-btype",
                                options=[
                                    {'label': 'IRS',             'value': 'IRS'},
                                    {'label': 'TBond',           'value': 'TBond'},
                                    {'label': 'CBond',           'value': 'CBond'},
                                    {'label': 'Futures Analytics', 'value': 'Futures'},
                                ],
                                value='IRS',
                                clearable=False,
                                style=_dd_style,
                            ),
                        ], style={'minWidth': '150px', 'flex': '0 0 150px'}),
                        # Update steps
                        # pool/bonds/cbts: curve-backtest steps
                        # rewrite: futures-analytics full rebuild flag
                        html.Div([
                            html.Label("Update Steps", style=_lbl_style),
                            dcc.Dropdown(
                                id="an-bt-update-list",
                                options=[
                                    {'label': 'pool',    'value': 'pool'},
                                    {'label': 'bonds',   'value': 'bonds'},
                                    {'label': 'cbts',    'value': 'cbts'},
                                    {'label': 'rewrite', 'value': 'rewrite'},
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
                            dcc.DatePickerSingle(
                                id="an-bt-start",
                                date=start_default,
                                display_format='YYYY-MM-DD',
                                style={'fontSize': '13px', 'minWidth': '140px'},
                            ),
                        ], style={'minWidth': '160px', 'flex': '0 0 160px', 'position': 'relative', 'zIndex': '1001'}),
                        # End date
                        html.Div([
                            html.Label("End Date", style=_lbl_style),
                            dcc.DatePickerSingle(
                                id="an-bt-end",
                                date=end_default,
                                display_format='YYYY-MM-DD',
                                style={'fontSize': '13px', 'minWidth': '140px'},
                            ),
                        ], style={'minWidth': '160px', 'flex': '0 0 160px', 'position': 'relative', 'zIndex': '1001'}),
                        # Workers (curve-backtest only)
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
                        # Run button
                        html.Div([
                            html.Button(
                                "▶  Run Backfill",
                                id="an-btn-backtest",
                                n_clicks=0,
                                style={**_btn_style, 'background': '#1a5276', 'borderColor': '#2e86c1', 'fontWeight': '600'},
                            ),
                        ], style={'alignSelf': 'flex-end'}),
                    ], style={
                        'display': 'flex', 'flexDirection': 'row', 'gap': '14px',
                        'alignItems': 'flex-end', 'flexWrap': 'wrap',
                    }),

                    # ── Factor Series row ────────────────────────────────────────
                    html.Div([
                        html.Button(
                            "Generate Factor Series",
                            id="an-btn-gen-factor-series",
                            n_clicks=0,
                            title="Full rebuild of factor-rates.pkl from raw market data. "
                                  "Use on-demand when source data changes.",
                            style={**_btn_style, 'background': '#0e3a3f', 'borderColor': '#36a6b8'},
                        ),
                        html.Span(
                            id="an-gen-factor-series-status",
                            style={'color': '#aab0c0', 'fontSize': '12px', 'marginLeft': '12px'},
                        ),
                    ], style={'marginTop': '14px', 'display': 'flex', 'alignItems': 'center'}),
                ], style={'padding': '22px'}),
            ], className="an-card"),

            # ── Status & Logs card ───────────────────────────────────────────
            html.Div([
                html.Div("STATUS & LOGS", className="an-card-hdr"),
                html.Div([
                    html.Div(id="an-job-status", children="No job running.",
                             style={'fontStyle': 'italic', 'color': '#aab0c0', 'fontSize': '12px', 'marginBottom': '8px'}),
                    html.Div(id="an-run-center-content"),
                ], style={'padding': '22px'}),
            ], className="an-card"),
            ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '20px'}),

            dcc.Interval(id="an-run-center-interval", interval=_INTERVAL_RUN_CTR_MS, n_intervals=0),
        ]
    )
    
    beta_content = html.Div(
        [
            dcc.Tabs(
                id="an-beta-subtabs",
                value="candidates",
                children=[
                    dcc.Tab(label="Candidates", value="candidates", className="an-subtab", selected_className="an-subtab--selected an-subtab--blue"),
                    dcc.Tab(label="Portfolio",  value="portfolio",  className="an-subtab", selected_className="an-subtab--selected an-subtab--blue"),
                    dcc.Tab(label="Backtest",   value="backtest",   className="an-subtab", selected_className="an-subtab--selected an-subtab--blue"),
                    dcc.Tab(label="Factor",     value="factor",     className="an-subtab", selected_className="an-subtab--selected an-subtab--blue"),
                    dcc.Tab(label="Bond",       value="bond",       className="an-subtab", selected_className="an-subtab--selected an-subtab--blue"),
                    dcc.Tab(label="Futures",    value="futures",    className="an-subtab", selected_className="an-subtab--selected an-subtab--blue"),
                ],
                style={**summary_subtabs_style, "marginTop": "8px"},
                colors=summary_subtabs_colors,
            ),
            html.Div([
                html.Div(id="beta-candidates-div", children=build_multiasset_factor_layout(),       style={"display": "block"}),
                html.Div(id="beta-portfolio-div",  children=build_multiasset_portfolio_layout(),    style={"display": "none"}),
                html.Div(id="beta-backtest-div",   children=build_beta_backtest_combined_layout(),  style={"display": "none"}),
                html.Div(id="beta-factor-div",     children=build_factor_history_layout(),          style={"display": "none"}),
                html.Div(id="beta-bond-div",       children=build_multiasset_bond_layout(),         style={"display": "none"}),
                html.Div(id="beta-futures-div",    children=build_factor_backtest_layout(),         style={"display": "none"}),
            ], style={"position": "relative"}),
        ],
        className="an-tab-pane",
    )
    
    alpha_content = html.Div(
        [
            dcc.Tabs(
                id="an-alpha-subtabs",
                value="candidates",
                children=[
                    dcc.Tab(label="Candidates", value="candidates", className="an-subtab", selected_className="an-subtab--selected an-subtab--amber"),
                    dcc.Tab(label="Portfolio",  value="portfolio",  className="an-subtab", selected_className="an-subtab--selected an-subtab--amber"),
                    dcc.Tab(label="Backtest",   value="backtest",   className="an-subtab", selected_className="an-subtab--selected an-subtab--amber"),
                    dcc.Tab(label="Spread",     value="spreads",    className="an-subtab", selected_className="an-subtab--selected an-subtab--amber"),
                    dcc.Tab(label="Pairs",      value="pairs",      className="an-subtab", selected_className="an-subtab--selected an-subtab--amber"),
                    dcc.Tab(label="Volatility", value="volatility", className="an-subtab", selected_className="an-subtab--selected an-subtab--amber"),
                ],
                style={**summary_subtabs_style, "marginTop": "8px"},
                colors={**summary_subtabs_colors, "primary": "#f39c12"},
            ),
            html.Div([
                html.Div(id="alpha-candidates-div", children=build_candidates_layout(), style={"display": "block"}),
                html.Div(id="alpha-portfolio-div",  children=build_portfolio_layout(),  style={"display": "none"}),
                html.Div(id="alpha-backtest-div",   children=build_backtest_layout(),   style={"display": "none"}),
                html.Div(id="alpha-spreads-div",    children=build_spreads_layout(),    style={"display": "none"}),
                html.Div(id="alpha-pairs-div",      children=build_pairs_layout(),      style={"display": "none"}),
                html.Div(id="alpha-volatility-div", children=build_volatility_layout(), style={"display": "none"}),
            ], style={"position": "relative"}),
        ],
        className="an-tab-pane",
    )

    _risk_inner = build_multiasset_risk_layout()
    risk_content = html.Div(
        [
            dcc.Tabs(
                id="an-summary-subtabs",
                value="books",
                children=[
                    dcc.Tab(label="Books",   value="books",   className="an-subtab", selected_className="an-subtab--selected an-subtab--blue"),
                    dcc.Tab(label="Risk",    value="risk",    className="an-subtab", selected_className="an-subtab--selected an-subtab--amber"),
                    dcc.Tab(label="Tickets", value="tickets", className="an-subtab", selected_className="an-subtab--selected an-subtab--green"),
                ],
                style={**summary_subtabs_style, "marginTop": "8px"},
                colors=summary_subtabs_colors,
            ),
            html.Div([
                html.Div(id="summary-books-div",   children=_risk_inner.children[0], style={"display": "block"}),
                html.Div(id="summary-risk-div",    children=_risk_inner.children[1], style={"display": "none"}),
                html.Div(id="summary-tickets-div", children=_risk_inner.children[2], style={"display": "none"}),
            ], style={"position": "relative"}),
        ],
        className="an-tab-pane",
    )

    market_content = html.Div(
        [
            dcc.Tabs(
                id="an-market-subtabs",
                value="data",
                children=[
                    dcc.Tab(label="Data",    value="data",    className="an-subtab", selected_className="an-subtab--selected an-subtab--blue"),
                    dcc.Tab(label="Trend",   value="trend",   className="an-subtab", selected_className="an-subtab--selected an-subtab--blue"),
                    dcc.Tab(label="Pricer",  value="pricer",  className="an-subtab", selected_className="an-subtab--selected an-subtab--blue"),
                    dcc.Tab(label="Surface", value="surface", className="an-subtab", selected_className="an-subtab--selected an-subtab--blue"),
                    dcc.Tab(label="Curves",  value="curves",  className="an-subtab", selected_className="an-subtab--selected an-subtab--blue"),
                ],
                style={**summary_subtabs_style, "marginTop": "8px"},
                colors=summary_subtabs_colors,
            ),
            html.Div([
                html.Div(id="market-data-div",    children=build_market_data_layout(), style={"display": "block"}),
                html.Div(id="market-trend-div",   children=build_trend_layout(),       style={"display": "none"}),
                html.Div(id="market-pricer-div",  children=build_pricer_layout(),      style={"display": "none"}),
                html.Div(id="market-surface-div", children=build_surface_layout(),     style={"display": "none"}),
                html.Div(id="market-curves-div",  children=build_curves_layout(),      style={"display": "none"}),
            ], style={"position": "relative"}),
        ],
        className="an-tab-pane",
    )

    return html.Div(
        [
            # Shared stores for persisting content across tab switches
            dcc.Store(id='alpha-selected-candidates', data=[]),
            # NOTE: per-tab content stores removed — state is preserved via
            # the keep-alive show/hide DOM pattern; session stores were unused.
            dcc.Store(id='an-autoruns1-status', storage_type='memory'),
            dcc.Store(id='an-autoruns2-status', storage_type='memory'),
            
            # Shared intervals
            dcc.Interval(id="data-refresh", interval=GRAPH_INTERVAL, n_intervals=0),
            
            html.Div(
                [
                    dcc.Tabs(
                        id="an-tabs",
                        value="market",
                        className="an-tabs",
                        children=[
                            dcc.Tab(label="Market",     value="market",     className="an-tab", selected_className="an-tab--selected"),
                            dcc.Tab(label="Beta Book",  value="beta",       className="an-tab", selected_className="an-tab--selected"),
                            dcc.Tab(label="Alpha Book", value="alpha",      className="an-tab", selected_className="an-tab--selected"),
                            dcc.Tab(label="Summary",    value="risk",       className="an-tab", selected_className="an-tab--selected"),
                            dcc.Tab(label="Run Center", value="run-center", className="an-tab", selected_className="an-tab--selected"),
                        ],
                    ),
                    # Pre-render all main tabs with absolute positioning to preserve state
                    html.Div([
                        html.Div(id="market-div",     children=market_content,     style={"position": "relative", "display": "block"}),
                        html.Div(id="beta-div",       children=beta_content,       style={"position": "relative", "display": "none"}),
                        html.Div(id="alpha-div",      children=alpha_content,      style={"position": "relative", "display": "none"}),
                        html.Div(id="risk-div",       children=risk_content,       style={"position": "relative", "display": "none"}),
                        html.Div(id="run-center-div", children=run_center_content, style={"position": "relative", "display": "none"}),
                    ], style={"width": "100%"}),
                    dcc.Interval(id="an-interval", interval=_INTERVAL_HEADER_MS, n_intervals=0),
                ],
                id="an-main-content",
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


# ---------------------------------------------------------------------------
# Generic show/hide tab-switcher factory
# ---------------------------------------------------------------------------
def _make_tab_switcher(input_id: str, div_ids: list[str], keys: list[str]):
    """Register a show/hide callback that maps *input_id* tab value to div visibility."""
    base = {"boxSizing": "border-box"}   # removed paddingLeft — .an-tab-pane handles all padding

    @app.callback(
        [Output(did, "style") for did in div_ids],
        Input(input_id, "value"),
    )
    def _switcher(active):
        return tuple(
            {**base, "display": "block"} if active == k else {**base, "display": "none"}
            for k in keys
        )

    return _switcher





@app.callback(
    Output("an-main-content", "style"),
    Input("an-tabs", "value"),
)
def _set_book_accent(tab):
    """Propagate the active book's accent color to cards, KPIs, and sub-tabs
    via the --book-accent CSS variable (see z_atlasnexus-design.css)."""
    accent = BOOK_ACCENT.get(tab, BOOK_ACCENT["market"])
    return {"--book-accent": accent}


@app.callback(
    Output("an-refresh-time", "children"),
    Output("an-latest-run", "children"),
    Input("an-interval", "n_intervals"),
)
def _tick(n):
    import datetime
    now = datetime.datetime.now().strftime("%H:%M:%S")
    meta = find_latest_run(mode="eod")
    return (
        f"Updated {now}",
        f"Latest EOD: {format_run_meta(meta)}",
    )


@app.callback(
    Output("an-header-status", "children"),
    Input("an-interval", "n_intervals"),
    State("an-job-id", "data"),
)
def _header_status(n, job_id):
    """Render the right-side status pill strip in the header."""
    import datetime

    pills = []

    # ---- Wind connectivity ----
    try:
        from data.providers.retrieve import _WIND_AVAILABLE
        if _WIND_AVAILABLE is True:
            wind_cls, wind_dot, wind_txt = "ok",    "dot", "Wind \u2713"
        elif _WIND_AVAILABLE is False:
            wind_cls, wind_dot, wind_txt = "warn",  "dot", "Wind offline"
        else:
            wind_cls, wind_dot, wind_txt = "idle",  "dot", "Wind \u2014"
    except Exception:
        wind_cls, wind_dot, wind_txt = "idle", "dot", "Wind ?"

    pills.append(html.Span(
        [html.Span(className=f"dot"), wind_txt],
        className=f"an-status-pill {wind_cls}",
    ))

    # ---- Active job ----
    running = list_running_jobs()
    if running:
        jtype = _cmd_type(running[0].get("cmd", [])) or "job"
        pills.append(html.Span(
            [html.Span(className="dot"), f"\u25b6 {jtype}"],
            className="an-status-pill warn",
        ))
    elif job_id:
        status = finalize_job_if_done(job_id)
        state = (status or {}).get("state", "")
        if state == "FINISHED":
            pills.append(html.Span(
                [html.Span(className="dot"), "Done"],
                className="an-status-pill ok",
            ))
        elif state == "FAILED":
            pills.append(html.Span(
                [html.Span(className="dot"), "Failed"],
                className="an-status-pill error",
            ))

    return pills


@app.callback(
    Output("an-autoruns1-status", "data"),
    Output("an-autoruns2-status", "data"),
    Input("data-refresh", "n_intervals"),
)
def _run_core_autoruns(n_intervals):
    """Fire both autorun pipelines in one callback to avoid duplicate interval triggers."""
    try:
        from web.core.scripts import autoruns1 as _ar1
        r1 = _ar1(n_intervals, "AtlasNexus Daily active")
    except Exception as exc:
        r1 = f"autoruns1 failed: {exc}"
    try:
        from web.core.scripts import autoruns2 as _ar2
        r2 = _ar2(n_intervals, "AtlasNexus Daily active")
    except Exception as exc:
        r2 = f"autoruns2 failed: {exc}"
    return r1, r2


@app.callback(
    Output("an-job-id", "data"),
    Output("an-job-status", "children"),
    Input("an-btn-update", "n_clicks"),
    Input("an-btn-eod", "n_clicks"),
    Input("an-btn-eod-update", "n_clicks"),
    Input("an-btn-backtest", "n_clicks"),
    Input("an-btn-refresh-instruments", "n_clicks"),
    State("an-eod-asof", "date"),
    State("an-bt-btype", "value"),
    State("an-bt-update-list", "value"),
    State("an-bt-start", "date"),
    State("an-bt-end", "date"),
    State("an-bt-processes", "value"),
    prevent_initial_call=True,
)
def _start_jobs(n_update, n_eod, n_eod_update, n_bt, n_refresh_instruments,
                eod_asof,
                bt_btype, bt_update_list, bt_start, bt_end, bt_processes):
    ctx = __import__("dash").callback_context
    if not ctx.triggered:
        raise __import__("dash").exceptions.PreventUpdate

    trig = ctx.triggered[0]["prop_id"].split(".")[0]

    if trig == "an-btn-update":
        job = start_engine_job(argv=["update-data", "--force"])
        return job.job_id, f"Started job {job.job_id}: update-data --force"

    if trig == "an-btn-refresh-instruments":
        asof = (eod_asof or "").strip()
        # Convert YYYY-MM-DD to YYYY-MM-DD (CLI accepts this format via _parse_date)
        argv = ["refresh-instruments", "--asof", asof] if asof else ["refresh-instruments"]
        job = start_engine_job(argv=argv)
        label = f"refresh-instruments --asof {asof}" if asof else "refresh-instruments"
        return job.job_id, f"Started job {job.job_id}: {label}"

    if trig == "an-btn-eod":
        asof = (eod_asof or "").strip()
        argv = ["eod", "--asof", asof] if asof else ["eod"]
        # FI_FORCE_RERUN=1: bypass the "already run today" completion guard in
        # curves/initialise.py so the user can re-run EOD for any date at any time.
        job = start_engine_job(argv=argv, extra_env={"FI_FORCE_RERUN": "1"})
        label = f"eod --asof {asof}" if asof else "eod"
        return job.job_id, f"Started job {job.job_id}: {label}"

    if trig == "an-btn-eod-update":
        asof = (eod_asof or "").strip()
        argv = ["eod", "--asof", asof, "--update-data"] if asof else ["eod", "--update-data"]
        job = start_engine_job(argv=argv, extra_env={"FI_FORCE_RERUN": "1"})
        label = f"eod --update-data --asof {asof}" if asof else "eod --update-data"
        return job.job_id, f"Started job {job.job_id}: {label}"

    if trig == "an-btn-backtest":
        btype = bt_btype or "IRS"
        ul = bt_update_list or ["pool"]
        start = (bt_start or "").strip()
        end = (bt_end or "").strip()

        if btype == "Futures":
            argv = ["futures-analytics-backfill"]
            if start:
                argv.extend(["--start", start])
            if end:
                argv.extend(["--end", end])
            if "rewrite" in ul:
                argv.append("--rewrite")
            job = start_engine_job(argv=argv)
            mode = "rewrite" if "rewrite" in ul else "incremental"
            range_label = f"{start}→{end or 'today'}" if start else (end or "today")
            return job.job_id, f"Started job {job.job_id}: futures-analytics-backfill ({mode}, {range_label})"

        procs = str(int(bt_processes)) if bt_processes else "4"
        curve_ul = [s for s in ul if s in ("pool", "bonds", "cbts")]
        argv = ["curve-backtest", "--btype", btype,
                "--update-list", *(curve_ul or ["pool"]),
                "--start", start, "--end", end,
                "--processes", procs]
        job = start_engine_job(argv=argv)
        return job.job_id, f"Started job {job.job_id}: curve-backtest ({btype}, {start}→{end})"

    raise __import__("dash").exceptions.PreventUpdate


@app.callback(
    Output("an-gen-factor-series-status", "children"),
    Input("an-btn-gen-factor-series", "n_clicks"),
    prevent_initial_call=True,
)
def _gen_factor_series(n_clicks):
    """Full rebuild of factor-rates.pkl on demand."""
    if not n_clicks:
        raise __import__("dash").exceptions.PreventUpdate
    try:
        from multiasset.factor_backtest import generate_factor_rates
        from settings.paths import DIR_INPUT
        df = generate_factor_rates(DIR_INPUT, save=True)
        return f"✅ Saved ({df.shape[1]} factors, {len(df)} days)"
    except Exception as exc:
        return f"❌ {exc}"


# ---------------------------------------------------------------------------
# Tab show/hide callbacks — generated by _make_tab_switcher
# ---------------------------------------------------------------------------
_make_tab_switcher(
    "an-tabs",
    ["market-div", "beta-div", "alpha-div", "risk-div", "run-center-div"],
    ["market",     "beta",     "alpha",     "risk",     "run-center"],
)
_make_tab_switcher(
    "an-beta-subtabs",
    ["beta-candidates-div", "beta-portfolio-div", "beta-backtest-div",
     "beta-factor-div",     "beta-bond-div",      "beta-futures-div"],
    ["candidates",          "portfolio",          "backtest",
     "factor",              "bond",               "futures"],
)
_make_tab_switcher(
    "beta-backtest-inner-tabs",
    ["beta-backtest-indiv-div", "beta-backtest-port-div"],
    ["individual-factors",      "portfolio"],
)
_make_tab_switcher(
    "an-summary-subtabs",
    ["summary-books-div", "summary-risk-div", "summary-tickets-div"],
    ["books",             "risk",             "tickets"],
)
_make_tab_switcher(
    "an-market-subtabs",
    ["market-data-div", "market-trend-div", "market-pricer-div", "market-surface-div", "market-curves-div"],
    ["data",            "trend",            "pricer",            "surface",            "curves"],
)
_make_tab_switcher(
    "an-alpha-subtabs",
    ["alpha-candidates-div", "alpha-portfolio-div", "alpha-backtest-div",
     "alpha-spreads-div",    "alpha-pairs-div",     "alpha-volatility-div"],
    ["candidates",           "portfolio",           "backtest",
     "spreads",              "pairs",               "volatility"],
)


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


# (tab-switcher callbacks registered above via _make_tab_switcher)


# ---------------------------------------------------------------------------
# Run Center: hide/disable Futures-irrelevant fields when Futures Analytics
# is selected as instrument type.
# ---------------------------------------------------------------------------
@app.callback(
    Output("an-bt-update-list", "style"),
    Output("an-bt-update-list", "options"),
    Output("an-bt-update-list", "value"),
    Output("an-bt-processes",   "disabled"),
    Output("an-bt-processes",   "style"),
    Input("an-bt-btype", "value"),
    prevent_initial_call=False,
)
def _adapt_backfill_form(btype: str):
    _dd = _DD_STYLE
    _inp_active   = _INPUT_STYLE
    _inp_disabled = {**_INPUT_STYLE, "opacity": "0.4", "cursor": "not-allowed"}

    if btype == "Futures":
        return (
            {**_dd, "display": "none"},           # hide Update Steps
            [],                                    # clear options (avoid stale state)
            ["rewrite"],                           # default
            True,                                  # Workers disabled
            _inp_disabled,
        )
    return (
        {**_dd, "display": "block"},
        [
            {"label": "pool",  "value": "pool"},
            {"label": "bonds", "value": "bonds"},
            {"label": "cbts",  "value": "cbts"},
        ],
        ["pool"],
        False,
        _inp_active,
    )



if __name__ == "__main__":
    # Delegate to the canonical entry point so there is one startup path.
    import subprocess, sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    raise SystemExit(
        subprocess.call([sys.executable, str(root / "main.py"), "daily-web"])
    )
