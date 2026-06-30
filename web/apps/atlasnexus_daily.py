# -*- coding: utf-8 -*-
"""AtlasNexus Daily Console (EOD).

A new Dash app that mirrors the styling of web/apps/fi.py,
without modifying existing apps.

Port: 8080
"""

from __future__ import annotations
import sys
import os
import re
from dash import dcc, html, dash_table, callback_context, no_update
from dash.dependencies import Input, Output, State, ALL
from dash.exceptions import PreventUpdate

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

from web.services.artifacts import find_latest_run, format_run_meta, get_data_generation_date
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


# Serve the user manual for new users (linked from the header "Manual" button).
@app.server.route("/user-manual")
def _serve_user_manual():
    from flask import send_file, abort

    manual_file = project_root / "web" / "assets" / "AtlasNexus User Manual.html"
    if manual_file.exists():
        return send_file(str(manual_file))
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
            # ---- Left: title ----
            html.Div(
                [
                    html.H4([
                        "AtlasNexus ",
                        html.Span("·", className="sep"),
                        " Daily",
                    ], className="app__header__title"),
                ],
                className="app__header__desc",
            ),
            # ---- Right: as-of/status chips, live clock, status pill strip ----
            html.Div(
                [
                    dcc.Store(id="an-job-id", storage_type="memory"),
                    html.Div(id="an-header-chips"),
                    html.Div(className="an-header-divider"),
                    html.Div(id="an-header-clock", className="an-live-clock"),
                    html.Div(className="an-header-divider"),
                    html.Div(id="an-header-status", className="an-header-status"),
                    html.Div(className="an-header-divider"),
                    html.A(
                        "Manual",
                        href="/user-manual",
                        target="_blank",
                        className="an-manual-btn",
                        title="Open the AtlasNexus user manual",
                    ),
                ],
                className="app__header__right",
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

                # ── LEFT COLUMN: Daily Pipeline + Data Backfill ──────────────
                html.Div([

                    # Daily Pipeline panel
                    html.Div([
                        html.Div("Daily Pipeline", className="rc-section-label"),
                        html.Div([
                            html.Label("As Of Date", style={**_lbl_style, 'marginBottom': '4px', 'display': 'block'}),
                            dcc.DatePickerSingle(
                                id="an-eod-asof",
                                date=asof_default,
                                display_format='YYYY-MM-DD',
                                first_day_of_week=1,
                                style={'fontSize': '13px', 'width': '100%'},
                            ),
                        ], style={'marginBottom': '14px', 'position': 'relative', 'zIndex': '1001'}),
                        html.Div([
                            html.Div([
                                html.Button("Update Data", id="an-btn-update", n_clicks=0,
                                            style={**_btn_style, 'flex': '1'}),
                                html.Button("Run EOD", id="an-btn-eod", n_clicks=0,
                                            style={**_btn_style, 'flex': '1'}),
                            ], style={'display': 'flex', 'gap': '10px'}),
                            html.Button("Run EOD + Update Data", id="an-btn-eod-update", n_clicks=0,
                                        style={**_btn_style, 'width': '100%'}),
                            html.Button("Refresh Instruments", id="an-btn-refresh-instruments", n_clicks=0,
                                        style={**_btn_style, 'width': '100%'}),
                        ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '8px'}),
                    ], className="rc-panel"),

                    # Data Backfill panel
                    html.Div([
                        html.Div("Data Backfill", className="rc-section-label"),
                        html.Div([
                            html.Div([
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
                                ], style={'flex': '1'}),
                                html.Div([
                                    html.Label("Update Steps", style=_lbl_style),
                                    dcc.Dropdown(
                                        id="an-bt-update-list",
                                        options=[
                                            {'label': 'pool',             'value': 'pool'},
                                            {'label': 'bonds',            'value': 'bonds'},
                                            {'label': 'cbts',             'value': 'cbts'},
                                            {'label': 'rewrite analytics', 'value': 'rewrite'},
                                        ],
                                        value=['pool'],
                                        multi=True,
                                        clearable=False,
                                        style=_dd_style,
                                    ),
                                ], style={'flex': '1'}),
                            ], style={'display': 'flex', 'gap': '10px'}),
                            html.Div([
                                html.Div([
                                    html.Label("Start Date", style=_lbl_style),
                                    dcc.DatePickerSingle(
                                        id="an-bt-start",
                                        date=start_default,
                                        display_format='YYYY-MM-DD',
                                        style={'fontSize': '13px', 'width': '100%'},
                                    ),
                                ], style={'flex': '1', 'position': 'relative', 'zIndex': '1001'}),
                                html.Div([
                                    html.Label("End Date", style=_lbl_style),
                                    dcc.DatePickerSingle(
                                        id="an-bt-end",
                                        date=end_default,
                                        display_format='YYYY-MM-DD',
                                        style={'fontSize': '13px', 'width': '100%'},
                                    ),
                                ], style={'flex': '1', 'position': 'relative', 'zIndex': '1001'}),
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
                                ], style={'width': '56px'}),
                            ], style={'display': 'flex', 'gap': '10px'}),
                            html.Button(
                                "▶  Run Backfill",
                                id="an-btn-backtest",
                                n_clicks=0,
                                style={**_btn_style, 'background': '#0e3a3f', 'borderColor': '#36a6b8',
                                       'fontWeight': '600', 'width': '100%'},
                            ),
                            html.Button(
                                "Generate Factor Series",
                                id="an-btn-gen-factor-series",
                                n_clicks=0,
                                title="Full rebuild of factor-rates.pkl from raw market data. "
                                      "Use on-demand when source data changes.",
                                style={**_btn_style, 'background': 'transparent',
                                       'borderColor': '#2f9d6b', 'color': '#2f9d6b', 'width': '100%'},
                            ),
                            html.Span(
                                id="an-gen-factor-series-status",
                                style={'color': '#aab0c0', 'fontSize': '12px'},
                            ),
                        ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '10px'}),
                    ], className="rc-panel"),

                    # Data Viewer panel
                    html.Div([
                        html.Div("Data Viewer", className="rc-section-label"),
                        html.Div([
                            html.Label("File Path (relative to input/ or database/)", style=_lbl_style),
                            dcc.Input(
                                id="an-dv-filepath",
                                type="text",
                                placeholder="e.g. futures-InstrumentInfo.pkl or pool/CBondPool20260416.pkl",
                                style=_input_style,
                            ),
                        ], style={'marginBottom': '10px'}),
                        html.Button(
                            "Load",
                            id="an-dv-load-btn",
                            n_clicks=0,
                            style={**_btn_style, 'width': '100%', 'marginBottom': '10px'},
                        ),
                        html.Div([
                            html.Div([
                                html.Label("Preview", style=_lbl_style),
                                dcc.RadioItems(
                                    id="an-dv-mode",
                                    options=[
                                        {'label': ' Head', 'value': 'head'},
                                        {'label': ' Tail', 'value': 'tail'},
                                        {'label': ' Row #', 'value': 'row'},
                                    ],
                                    value='head',
                                    inline=True,
                                    style={'color': '#aab0c0', 'fontSize': '12px'},
                                    labelStyle={'marginRight': '12px'},
                                ),
                            ], style={'flex': '1'}),
                            html.Div([
                                html.Label("N", style=_lbl_style),
                                dcc.Input(
                                    id="an-dv-n",
                                    type="number",
                                    value=10,
                                    min=0,
                                    step=1,
                                    style=_input_style,
                                ),
                            ], style={'width': '64px'}),
                        ], style={'display': 'flex', 'gap': '10px', 'alignItems': 'flex-end'}),
                        html.Div(id="an-dv-error", style={'color': '#e06c75', 'fontSize': '12px', 'marginTop': '8px'}),
                    ], className="rc-panel"),

                ], className="rc-left-col"),

                # ── RIGHT COLUMN: Status bar + Log viewer + Data Viewer ──────
                html.Div([
                    html.Div(
                        id="an-job-status",
                        children="No job running.",
                        style={'fontStyle': 'italic', 'color': '#aab0c0', 'fontSize': '12px'},
                    ),
                    html.Div(id="an-run-center-content"),

                    html.Div([
                        html.Div("Data Viewer Preview", className="rc-section-label"),
                        html.Div(id="an-dv-breadcrumb", style={'marginBottom': '10px'}),
                        html.Div(id="an-dv-tree", style={'marginBottom': '10px'}),
                        html.Div(id="an-dv-preview"),
                    ], className="rc-panel"),
                ], className="rc-right-col"),

            ], className="rc-grid", style={'marginTop': '28px'}),

            dcc.Store(id="an-dv-state", storage_type="memory"),
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
                            dcc.Tab(label="Market Monitor",     value="market",     className="an-tab", selected_className="an-tab--selected"),
                            dcc.Tab(label="Beta Portfolio",  value="beta",       className="an-tab", selected_className="an-tab--selected"),
                            dcc.Tab(label="Alpha Portfolio", value="alpha",      className="an-tab", selected_className="an-tab--selected"),
                            dcc.Tab(label="Portfolio Summary",    value="risk",       className="an-tab", selected_className="an-tab--selected"),
                            dcc.Tab(label="Execution Center", value="run-center", className="an-tab", selected_className="an-tab--selected"),
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
    via the --book-accent CSS variable (see design.css)."""
    accent = BOOK_ACCENT.get(tab, BOOK_ACCENT["market"])
    return {"--book-accent": accent}


@app.callback(
    Output("an-header-clock", "children"),
    Output("an-header-chips", "children"),
    Input("an-interval", "n_intervals"),
)
def _tick(n):
    import datetime
    now = datetime.datetime.now().strftime("%H:%M:%S")
    meta = find_latest_run(mode="eod")

    # AS OF reflects the calibration date baked into TBond-cvpx.pkl (the
    # actual curve data date), not the EOD run's nominal as-of date — these
    # can diverge if a calibration step ran on stale/cached data.
    asof_value = get_data_generation_date("TBond") or (meta.asof if meta and meta.asof else "—")
    status_raw = (meta.status if meta and meta.status else "unknown")
    status_ok = status_raw.lower() == "completed"
    status_value = f"✓  {status_raw.upper()}" if status_ok else status_raw.upper()
    status_color = "var(--accent-green)" if status_ok else "var(--text-secondary)"

    chips = html.Div(
        [
            html.Div([
                html.Span("AS OF", className="an-meta-chip__label"),
                html.Span(asof_value, className="an-meta-chip__value"),
            ], className="an-meta-chip"),
            html.Div([
                html.Span("STATUS", className="an-meta-chip__label"),
                html.Span(status_value, className="an-meta-chip__value",
                           style={"color": status_color}),
            ], className="an-meta-chip"),
        ],
        style={"display": "flex", "alignItems": "center", "gap": "10px"},
    )

    return now, chips


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
        # FI_FORCE_NONTRADING=1: bypass the Wind trading-hours/weekday window
        # so manual "Update Data" runs always attempt live retrieval.
        job = start_engine_job(argv=["update-data", "--force"], extra_env={"FI_FORCE_NONTRADING": "1"})
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
        # FI_FORCE_NONTRADING=1: bypass the Wind trading-hours/weekday window
        # so manual "Run EOD + Update Data" runs always attempt live retrieval.
        job = start_engine_job(argv=argv, extra_env={"FI_FORCE_RERUN": "1", "FI_FORCE_NONTRADING": "1"})
        label = f"eod --update-data --asof {asof}" if asof else "eod --update-data"
        return job.job_id, f"Started job {job.job_id}: {label}"

    if trig == "an-btn-backtest":
        btype = bt_btype or "IRS"
        ul = bt_update_list or ["pool"]
        start = (bt_start or "").strip()[:10]
        end = (bt_end or "").strip()[:10]

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


# ---------------------------------------------------------------------------
# Data Viewer (pkl drill-down browser)
# ---------------------------------------------------------------------------

def _dv_resolve_file(rel_path: str):
    """Resolve a user-entered relative path against input/ or database/."""
    from settings.paths import DIR_INPUT, DIR_DATA

    rel_path = (rel_path or "").strip().lstrip("/\\")
    if not rel_path:
        raise ValueError("Enter a file path.")
    for base in (DIR_INPUT, DIR_DATA):
        candidate = (base / rel_path).resolve()
        if str(candidate).startswith(str(base.resolve())) and candidate.is_file():
            return candidate
    raise ValueError(f"File not found under input/ or database/: {rel_path}")


def _dv_load_node(file_path, key_path: list):
    """Load the pickle and walk key_path (list of dict keys / column names / list indices)."""
    import pandas as pd

    with open(file_path, "rb") as f:
        obj = pd.read_pickle(f)

    node = obj
    for key in key_path:
        if isinstance(node, dict):
            node = node[key]
        elif isinstance(node, pd.DataFrame):
            node = node[key]
        elif isinstance(node, (list, tuple)):
            node = node[int(key)]
        else:
            raise ValueError(f"Cannot descend into key {key!r} on {type(node).__name__}")
    return node


def _dv_child_keys(node) -> list:
    """Return the list of drill-down-able child keys for a node, or [] if it's a leaf."""
    import pandas as pd

    if isinstance(node, dict):
        return list(node.keys())
    if isinstance(node, pd.DataFrame):
        return list(node.columns)
    if isinstance(node, (list, tuple)) and node and isinstance(node[0], (dict, list, tuple)):
        return list(range(len(node)))
    return []


def _dv_render_tree(node) -> "html.Div":
    keys = _dv_child_keys(node)
    if not keys:
        return html.Div("(leaf node — see preview below)", style={'color': '#6b7280', 'fontSize': '12px'})
    items = [
        html.Button(
            str(k),
            id={'type': 'an-dv-node', 'key': str(k)},
            n_clicks=0,
            style={
                'background': '#112e66', 'color': '#cdd6f4', 'border': '1px solid #2a5298',
                'borderRadius': '4px', 'padding': '4px 10px', 'fontSize': '12px', 'cursor': 'pointer',
                'margin': '0 6px 6px 0',
            },
        )
        for k in keys
    ]
    return html.Div(items, style={'display': 'flex', 'flexWrap': 'wrap'})


def _dv_render_breadcrumb(file_label: str, key_path: list) -> "html.Div":
    crumbs = [html.Button(
        file_label,
        id={'type': 'an-dv-crumb', 'index': 0},
        n_clicks=0,
        style={'background': 'transparent', 'color': '#45b6e6', 'border': 'none',
               'cursor': 'pointer', 'fontSize': '12px', 'padding': '0', 'textDecoration': 'underline'},
    )]
    for i, key in enumerate(key_path, start=1):
        crumbs.append(html.Span(" / ", style={'color': '#6b7280', 'fontSize': '12px'}))
        crumbs.append(html.Button(
            str(key),
            id={'type': 'an-dv-crumb', 'index': i},
            n_clicks=0,
            style={'background': 'transparent', 'color': '#45b6e6', 'border': 'none',
                   'cursor': 'pointer', 'fontSize': '12px', 'padding': '0', 'textDecoration': 'underline'},
        ))
    return html.Div(crumbs, style={'display': 'flex', 'flexWrap': 'wrap', 'alignItems': 'center'})


def _dv_render_preview(node, mode: str, n) -> "html.Div":
    import pandas as pd

    if isinstance(node, (pd.DataFrame, pd.Series)):
        df = node.to_frame() if isinstance(node, pd.Series) else node
        n = int(n) if n is not None else 10
        if mode == "head":
            view = df.head(n)
        elif mode == "tail":
            view = df.tail(n)
        else:  # row
            view = df.iloc[[n]] if 0 <= n < len(df) else df.iloc[0:0]
        view = view.reset_index()
        return html.Div([
            html.Div(f"shape: {df.shape[0]} rows x {df.shape[1]} cols", style={'color': '#aab0c0', 'fontSize': '11px', 'marginBottom': '6px'}),
            dash_table.DataTable(
                columns=[{'name': str(c), 'id': str(c)} for c in view.columns],
                data=view.astype(object).where(pd.notnull(view), None).to_dict('records'),
                style_table={'overflowX': 'auto'},
                style_cell={'textAlign': 'center', 'fontSize': '12px', 'padding': '4px 8px',
                            'backgroundColor': '#0d1b3d', 'color': '#cdd6f4', 'border': '1px solid #2a5298'},
                style_header={'backgroundColor': '#112e66', 'fontWeight': '600'},
                page_size=50,
            ),
        ])

    # Non-tabular leaf (scalar, array, nested without further drill-down, etc.)
    from utils.dataviewer import preview_object
    return html.Pre(preview_object(node), className="rc-log-viewer", style={'maxHeight': '480px'})


@app.callback(
    Output("an-dv-state", "data"),
    Output("an-dv-error", "children"),
    Input("an-dv-load-btn", "n_clicks"),
    Input({'type': 'an-dv-crumb', 'index': ALL}, "n_clicks"),
    Input({'type': 'an-dv-node', 'key': ALL}, "n_clicks"),
    State("an-dv-filepath", "value"),
    State("an-dv-state", "data"),
    prevent_initial_call=True,
)
def _dv_update_state(load_clicks, crumb_clicks, node_clicks, filepath, state):
    ctx = callback_context
    if not ctx.triggered:
        raise PreventUpdate
    trig = ctx.triggered_id

    if trig == "an-dv-load-btn":
        try:
            resolved = _dv_resolve_file(filepath)
        except ValueError as exc:
            return None, str(exc)
        return {"file": str(resolved), "label": (filepath or "").strip(), "path": []}, ""

    if not state or not state.get("file"):
        raise PreventUpdate

    if isinstance(trig, dict) and trig.get("type") == "an-dv-crumb":
        new_path = state["path"][: trig["index"]]
        return {**state, "path": new_path}, ""

    if isinstance(trig, dict) and trig.get("type") == "an-dv-node":
        new_path = state["path"] + [trig["key"]]
        return {**state, "path": new_path}, ""

    raise PreventUpdate


@app.callback(
    Output("an-dv-breadcrumb", "children"),
    Output("an-dv-tree", "children"),
    Output("an-dv-preview", "children"),
    Output("an-dv-error", "children", allow_duplicate=True),
    Input("an-dv-state", "data"),
    Input("an-dv-mode", "value"),
    Input("an-dv-n", "value"),
    prevent_initial_call=True,
)
def _dv_render(state, mode, n):
    if not state or not state.get("file"):
        # Leave an-dv-error untouched: _dv_update_state may have just set an
        # error message (e.g. file-not-found) and cleared state in the same tick.
        return None, None, None, no_update
    try:
        node = _dv_load_node(state["file"], state["path"])
    except Exception as exc:
        return _dv_render_breadcrumb(state.get("label", state["file"]), state["path"]), None, None, f"Failed to load: {exc}"

    breadcrumb = _dv_render_breadcrumb(state.get("label", state["file"]), state["path"])
    tree = _dv_render_tree(node)
    try:
        preview = _dv_render_preview(node, mode or "head", n)
    except Exception as exc:
        return breadcrumb, tree, None, f"Failed to render preview: {exc}"
    return breadcrumb, tree, preview, ""


@app.callback(
    Output("an-gen-factor-series-status", "children"),
    Input("an-btn-gen-factor-series", "n_clicks"),
    prevent_initial_call=True,
)
def _gen_factor_series(n_clicks):
    """Full rebuild of factor-rates.pkl (and factor-credit.pkl) on demand."""
    if not n_clicks:
        raise __import__("dash").exceptions.PreventUpdate
    try:
        from multiasset.factor_backtest import generate_factor_rates, generate_factor_credit
        from settings.paths import DIR_INPUT
        df = generate_factor_rates(DIR_INPUT, save=True)
        df_cr = generate_factor_credit(DIR_INPUT, save=True)
        return f"✅ Saved ({df.shape[1]} factors, {len(df)} days; credit: {df_cr.shape[1]} factors, {len(df_cr)} days)"
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


_LOG_LEVEL_RE = re.compile(r"^(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL):\s*(.*)$")
_LOG_LEVEL_COLOR = {
    "INFO": "#4a9eff", "DEBUG": "#6b7fa0",
    "WARNING": "#e0a23c", "WARN": "#e0a23c",
    "ERROR": "#e05c5c", "CRITICAL": "#e05c5c",
}
_LOG_MSG_COLOR = {
    "WARNING": "#c8944a", "WARN": "#c8944a",
    "ERROR": "#d56b6b", "CRITICAL": "#d56b6b",
}


def _render_log_line(line: str):
    m = _LOG_LEVEL_RE.match(line)
    if not m:
        return html.Div(line, className="rc-log-line")
    level, msg = m.group(1), m.group(2)
    return html.Div(
        [
            html.Span(level, className="rc-log-level",
                      style={"color": _LOG_LEVEL_COLOR.get(level, "#6b7fa0")}),
            html.Span(msg, style={"color": _LOG_MSG_COLOR.get(level, "var(--text-secondary)")}),
        ],
        className="rc-log-line",
    )


@app.callback(
    Output("an-run-center-content", "children"),
    Input("an-run-center-interval", "n_intervals"),
    State("an-job-id", "data"),
)
def _update_run_center(n, job_id):
    """Update Run Center status bar + log viewer on interval.

    Each tick:
    - Auto-finalizes any RUNNING jobs whose PID has exited.
    - Renders an IDLE/RUNNING status bar with last-run summary.
    - Renders the tailed log as individually colored, level-coded lines.
    """
    meta = find_latest_run(mode="eod")
    running_jobs = list_running_jobs()  # already finalizes stale entries internally
    is_running = bool(running_jobs)

    status = finalize_job_if_done(job_id) if job_id else None

    if is_running:
        jtype = _cmd_type(running_jobs[0].get("cmd", [])) or "job"
        dot_color, status_text, status_color = "#e0a23c", f"RUNNING ({jtype})", "#e0a23c"
    else:
        dot_color, status_text, status_color = "#41b078", "IDLE", "#41b078"

    if status:
        state   = status.get("state", "UNKNOWN")
        started = status.get("started_at", "")[:19]
        ended   = (status.get("ended_at", "") or "")[:19] or "—"
        jtype   = _cmd_type(status.get("cmd", [])) or "?"
        last_run_text = f"Last: {jtype} | {started} → {ended} | {state}"
    else:
        last_run_text = f"Latest EOD: {format_run_meta(meta)}"

    status_bar = html.Div(
        [
            html.Div([
                html.Span(className="rc-status-dot",
                          style={"background": dot_color, "boxShadow": f"0 0 6px {dot_color}"}),
                html.Span(status_text, className="rc-status-text", style={"color": status_color}),
            ], style={"display": "flex", "alignItems": "center", "gap": "8px"}),
            html.Span(last_run_text, className="rc-status-meta"),
        ],
        className="rc-status-bar",
    )

    log_text = tail_log(job_id, max_lines=200) if job_id else ""
    lines = [ln for ln in log_text.splitlines() if ln.strip()]
    if lines:
        log_children = [_render_log_line(ln) for ln in lines]
    else:
        log_children = [html.Div(
            "No logs. Start a job to see output here.", className="rc-log-empty",
        )]

    log_viewer = html.Div(log_children, id="an-run-center-log-viewer", className="rc-log-viewer")

    return html.Div([status_bar, html.Div(log_viewer, className="rc-panel-flush")],
                     style={"display": "flex", "flexDirection": "column", "gap": "14px"})


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
            {**_dd, "display": "block"},
            [{"label": "rewrite analytics", "value": "rewrite"}],
            [],                                    # not selected by default
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
