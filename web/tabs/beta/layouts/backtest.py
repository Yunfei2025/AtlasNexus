# -*- coding: utf-8 -*-
"""Backtest tab layouts: historical allocation, risk-factor backtest, futures backtest."""

from __future__ import annotations

from datetime import datetime, timedelta

from dash import dcc, html
import dash_bootstrap_components as dbc

from ..data import THEME, FUTURES_AVAILABLE

# Conditionally import futures discovery helper
if FUTURES_AVAILABLE:
    from futures.backtest.data_loader import discover_pkl_files


def build_multiasset_backtest_layout():
    """Build the layout for the Backtest tab.

    Strategy:
    - At the beginning of each month, run Cross-Asset Correlation Analysis
    - Select assets with lowest correlations for diversification
    - Run Risk Parity allocation on the selected assets
    - Track asset pool changes over time
    """
    return html.Div([
        html.H4("Historical Allocation Analysis (Correlation-Based)", style={'color': THEME['text_main'], 'marginBottom': '10px'}),
        html.P(
            "Strategy: At each month start, run correlation analysis to select diversified assets, then apply factor risk parity allocation.",
            style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginBottom': '10px', 'fontStyle': 'italic'}
        ),

        # Factor Pool Info Banner
        html.Div([
            html.Span("📊 Using Factor Pool from Factor tab: ", style={'fontWeight': 'bold', 'color': THEME['text_main']}),
            html.Span(id='backtest-factor-pool-display', style={'color': THEME['accent'], 'fontSize': '12px'}),
        ], style={'padding': '8px 12px', 'backgroundColor': THEME['bg_input'], 'borderRadius': '4px', 'marginBottom': '10px', 'border': f'1px solid {THEME["accent"]}'}),

        # Dynamic Data Range Info (will be updated based on selected factors)
        html.Div([
            html.Span(id='backtest-min-date-info', children="ℹ️ Calculating minimum supported date...",
                     style={'color': THEME['text_sub'], 'fontSize': '11px', 'fontStyle': 'italic'}),
        ], style={'marginBottom': '15px'}),

        # Row 1: Date Range and Capital
        html.Div([
            # Backtest Period
            html.Div([
                html.Label("Backtest Period:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                html.Div([
                    dcc.DatePickerRange(
                        id='history-date-range',
                        min_date_allowed=datetime(2019, 1, 1).date(),
                        max_date_allowed=datetime.now().date(),
                        start_date=datetime(2024, 1, 1).date(),
                        end_date=datetime.now().date(),
                        display_format='YYYY-MM-DD',
                        style={'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']},
                        updatemode='bothdates'
                    )
                ], style={'display': 'inline-block', 'position': 'relative', 'zIndex': 1000}),
            ], style={'display': 'flex', 'alignItems': 'center'}),

            # Total Capital (dedicated for backtest)
            html.Div([
                html.Label("Capital:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                dcc.Input(
                    id='backtest-capital-input',
                    type='number',
                    value=10,
                    style={'width': '80px', 'marginRight': '5px', 'padding': '5px', 'borderRadius': '4px', 'border': '1px solid #444', 'backgroundColor': '#fff', 'color': '#000'}
                ),
                dcc.Dropdown(
                    id='backtest-capital-unit',
                    options=[
                        {"label": "Million", "value": "million"},
                        {"label": "Billion", "value": "billion"},
                    ],
                    value="billion",
                    clearable=False,
                    style={'width': '100px', 'fontSize': '13px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                ),
                html.Span("CNY", style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginLeft': '5px'}),
            ], style={'display': 'flex', 'alignItems': 'center', 'marginLeft': '20px'}),
        ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap', 'gap': '10px'}),

        # Row 2: Correlation Settings
        html.Div([
            # Correlation Lookback Period
            html.Div([
                html.Label("Correlation Lookback:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                dcc.Dropdown(
                    id='backtest-corr-lookback',
                    options=[
                        {'label': '3 Months', 'value': '3M'},
                        {'label': '6 Months', 'value': '6M'},
                        {'label': '1 Year', 'value': '1Y'},
                    ],
                    value='1Y',
                    clearable=False,
                    style={'width': '120px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                ),
            ], style={'display': 'flex', 'alignItems': 'center'}),

            # Number of low-correlation pairs to use
            html.Div([
                html.Label("Top Low-Corr Pairs:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                dcc.Input(
                    id='backtest-top-pairs',
                    type='number',
                    value=10,
                    min=5,
                    max=20,
                    style={'width': '60px', 'padding': '5px', 'borderRadius': '4px', 'border': '1px solid #444', 'backgroundColor': '#fff', 'color': '#000'}
                ),
            ], style={'display': 'flex', 'alignItems': 'center', 'marginLeft': '20px'}),

            # Performance Metrics Table
            html.Div(id='performance-metrics-container', style={'marginLeft': '20px'}),
        ], style={'marginBottom': '15px', 'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap', 'gap': '10px'}),

        # Row 3: Allocation Mode
        html.Div([
            html.Label("Allocation Mode:", style={'fontWeight': 'bold', 'marginRight': '12px', 'color': THEME['text_main']}),
            dcc.RadioItems(
                id='backtest-alloc-mode',
                options=[
                    {'label': ' Pure Risk Parity', 'value': 'risk_parity'},
                    {'label': ' Factor Model Scaling  (not available — factor backtests pending)', 'value': 'factor_scaling', 'disabled': True},
                ],
                value='risk_parity',
                inline=True,
                inputStyle={'marginRight': '4px'},
                labelStyle={'marginRight': '20px', 'color': THEME['text_main'], 'fontSize': '13px'},
            ),
        ], style={'marginBottom': '15px', 'display': 'flex', 'alignItems': 'center'}),

        html.Div([
            html.Button(
                "Run Historical Analysis",
                id='run-history-button',
                n_clicks=0,
                style={'backgroundColor': THEME['success'], 'color': 'white', 'padding': '10px 20px', 'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer', 'fontSize': '14px', 'fontWeight': 'bold', 'marginBottom': '15px'}
            ),
            dcc.Loading(
                id="loading-history",
                type="default",
                children=[
                    dcc.Graph(id='historical-allocation-chart'),
                    html.Div(style={'height': '20px'}),
                    dcc.Graph(id='pnl-attribution-chart'),
                    html.Div(style={'height': '20px'}),
                    # Asset Pool Changes Section
                    html.Div(id='asset-changes-container')
                ]
            )
        ])
    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px', 'borderRadius': '5px', 'margin': '10px'})


def build_risk_factor_backtest_layout():
    """Build the layout for the Risk Factor Backtest tab (BACKTEST subtab in Beta Book)."""
    all_factor_options = [
        # IR
        {'label': 'IRDL.CN (China Level)',   'value': 'IRDL.CN'},
        {'label': 'IRDL.US (US Level)',       'value': 'IRDL.US'},
        {'label': 'IRDL.DE (Europe Level)',   'value': 'IRDL.DE'},
        {'label': 'IRDL.JP (Japan Level)',    'value': 'IRDL.JP'},
        {'label': 'IRDL.UK (UK Level)',       'value': 'IRDL.UK'},
        {'label': 'IRSL.CN (China Slope)',    'value': 'IRSL.CN'},
        {'label': 'IRSL.US (US Slope)',       'value': 'IRSL.US'},
        {'label': 'IRCV.CN (China Curvature)','value': 'IRCV.CN'},
        # Spread
        {'label': 'SPDL.IRS (IRS Level)',     'value': 'SPDL.IRS'},
        {'label': 'SPSL.IRS (IRS Slope)',     'value': 'SPSL.IRS'},
        {'label': 'SPDL.CDB (CDB Level)',     'value': 'SPDL.CDB'},
        {'label': 'SPSL.CDB (CDB Slope)',     'value': 'SPSL.CDB'},
        {'label': 'SPDL.ICP (ICP Level)',     'value': 'SPDL.ICP'},
        # FX
        {'label': 'FXDL.USDCNY',             'value': 'FXDL.USDCNY'},
        {'label': 'FXDL.EURCNY',             'value': 'FXDL.EURCNY'},
        # Commodity
        {'label': 'CMDL.AU (Gold)',           'value': 'CMDL.AU'},
        {'label': 'CMDL.CU (Copper)',         'value': 'CMDL.CU'},
        {'label': 'CMDL.AL (Aluminium)',      'value': 'CMDL.AL'},
        {'label': 'CMDL.SC (Crude Oil)',      'value': 'CMDL.SC'},
    ]

    default_factors = ['IRDL.CN', 'IRSL.CN', 'SPDL.CDB', 'FXDL.USDCNY']

    return html.Div([
        html.H4("Risk Factor Backtest",
                 style={'color': THEME['text_main'], 'marginBottom': '6px'}),
        html.P("Backtest technical strategies on risk factors from the PORTFOLIO tab. "
               "Yield factors use duration-adjusted returns; FX/Commodity use price returns.",
               style={'color': THEME['text_sub'], 'fontSize': '12px',
                      'marginBottom': '16px', 'fontStyle': 'italic'}),

        # ── Row 1: Factor selection ─────────────────────────────────────
        html.Div([
            html.Div([
                html.Label("Factors:", style={'fontWeight': 'bold', 'marginRight': '10px',
                                              'color': THEME['text_main'], 'fontSize': '13px'}),
                dcc.Dropdown(
                    id='rfbt-factor-selector',
                    options=all_factor_options,
                    value=default_factors,
                    multi=True,
                    placeholder="Select factors…",
                    style={'flex': '1', 'minWidth': '360px',
                           'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']},
                ),
            ], style={'display': 'flex', 'alignItems': 'center', 'flex': '1'}),

            # Hidden store – always FactorModel
            dcc.Store(id='rfbt-strategy-selector', data='FactorModel'),
        ], style={'display': 'flex', 'gap': '20px', 'flexWrap': 'wrap',
                  'marginBottom': '12px'}),

        # ── Row 2: Date range & strategy params ─────────────────────────
        html.Div([
            html.Div([
                html.Label("Period:", style={'fontWeight': 'bold', 'marginRight': '10px',
                                             'color': THEME['text_main'], 'fontSize': '13px'}),
                dcc.DatePickerRange(
                    id='rfbt-date-range',
                    min_date_allowed=datetime(2015, 1, 1).date(),
                    max_date_allowed=datetime.now().date(),
                    start_date=datetime(2023, 1, 1).date(),
                    end_date=datetime.now().date(),
                    display_format='YYYY-MM-DD',
                    style={'backgroundColor': THEME['bg_input']},
                ),
            ], style={'display': 'flex', 'alignItems': 'center'}),

            # Hidden placeholders (keep IDs for callback State refs)
            html.Div(id='rfbt-ma-params', children=[
                dcc.Input(id='rfbt-ma-short', type='number', value=10, style={'display': 'none'}),
                dcc.Input(id='rfbt-ma-long', type='number', value=30, style={'display': 'none'}),
            ], style={'display': 'none'}),

            html.Div(id='rfbt-boll-params', children=[
                dcc.Input(id='rfbt-boll-window', type='number', value=20, style={'display': 'none'}),
                dcc.Input(id='rfbt-boll-std', type='number', value=1.5, style={'display': 'none'}),
            ], style={'display': 'none'}),
            html.Div(id='rfbt-mom-params', children=[
                dcc.Input(id='rfbt-mom-window', type='number', value=20, style={'display': 'none'}),
            ], style={'display': 'none'}),
            html.Div(id='rfbt-zscore-params', children=[
                dcc.Input(id='rfbt-zscore-window', type='number', value=60, style={'display': 'none'}),
                dcc.Input(id='rfbt-zscore-entry', type='number', value=1.5, style={'display': 'none'}),
                dcc.Input(id='rfbt-zscore-exit', type='number', value=0.5, style={'display': 'none'}),
            ], style={'display': 'none'}),

            # Factor Model params
            html.Div(id='rfbt-fm-params', children=[
                html.Label("Train (months):", style={'fontWeight': 'bold', 'marginRight': '4px',
                                                     'color': THEME['text_main'], 'fontSize': '12px'}),
                dcc.Input(id='rfbt-fm-train', type='number', value=12, min=3,
                          style={'width': '55px', 'marginRight': '10px', 'padding': '4px',
                                 'borderRadius': '4px', 'border': '1px solid #444',
                                 'backgroundColor': '#fff', 'color': '#000'}),
                html.Label("IC thr:", style={'fontWeight': 'bold', 'marginRight': '4px',
                                             'color': THEME['text_main'], 'fontSize': '12px'}),
                dcc.Input(id='rfbt-fm-ic', type='number', value=0.05, step=0.01, min=0.01,
                          style={'width': '60px', 'marginRight': '10px', 'padding': '4px',
                                 'borderRadius': '4px', 'border': '1px solid #444',
                                 'backgroundColor': '#fff', 'color': '#000'}),
                html.Label("Top N:", style={'fontWeight': 'bold', 'marginRight': '4px',
                                            'color': THEME['text_main'], 'fontSize': '12px'}),
                dcc.Input(id='rfbt-fm-topn', type='number', value=8, min=1,
                          style={'width': '55px', 'padding': '4px',
                                 'borderRadius': '4px', 'border': '1px solid #444',
                                 'backgroundColor': '#fff', 'color': '#000'}),
            ], style={'display': 'flex', 'alignItems': 'center'}),

        ], style={'display': 'flex', 'gap': '16px', 'flexWrap': 'wrap',
                  'marginBottom': '14px', 'alignItems': 'center'}),

        # ── Row 3: Buttons ──────────────────────────────────────────────
        html.Div([
            html.Button("Generate factor-rates.pkl", id='rfbt-generate-btn', n_clicks=0,
                        style={'backgroundColor': THEME['accent'], 'color': 'white',
                               'padding': '8px 16px', 'border': 'none', 'borderRadius': '5px',
                               'cursor': 'pointer', 'fontSize': '12px', 'fontWeight': 'bold',
                               'marginRight': '12px'}),
            html.Button("Run Backtest & Save", id='rfbt-run-btn', n_clicks=0,
                        style={'backgroundColor': THEME['success'], 'color': 'white',
                               'padding': '8px 16px', 'border': 'none', 'borderRadius': '5px',
                               'cursor': 'pointer', 'fontSize': '12px', 'fontWeight': 'bold'}),
            html.Span(id='rfbt-status', style={'marginLeft': '16px',
                                               'color': THEME['text_sub'], 'fontSize': '12px'}),
        ], style={'marginBottom': '16px'}),

        # ── Results area ────────────────────────────────────────────────
        dcc.Loading(
            type='default',
            children=html.Div(id='rfbt-results-container', style={'minHeight': '200px'}),
        ),

    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px',
              'borderRadius': '5px', 'margin': '10px'})


def build_factor_backtest_layout():
    """Build the layout for the Futures/Factor Backtest tab - uses futures.backtest.layout."""
    if not FUTURES_AVAILABLE:
        return html.Div("Futures backtest modules not available.", style={'color': THEME['danger']})

    try:
        # Ensure futures/backtest is in sys.path so internal imports in layout.py work
        import sys
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # web/tabs/beta/layouts/ -> ../../../../futures/backtest
        backtest_dir = os.path.abspath(os.path.join(current_dir, '..', '..', '..', '..', 'futures', 'backtest'))
        if backtest_dir not in sys.path:
            sys.path.append(backtest_dir)

        pkl_options = discover_pkl_files()
    except Exception as e:
        pkl_options = []
        print(f"Error discovering pkl files: {e}")

    # Compact style definitions for Strategy Config sidebar
    DARK_INPUT_STYLE = {
        'backgroundColor': '#132C56',
        'color': '#E2E8F0',
        'border': '1px solid #2B4C7E',
        'fontSize': '1.0rem',
        'borderRadius': '4px',
        'padding': '4px 8px'
    }

    SECTION_STYLE = {
        'marginBottom': '25px',
    }

    SECTION_TITLE_STYLE = {
        'color': '#90CDF4',
        'fontSize': '1.0rem',
        'fontWeight': '700',
        'textTransform': 'uppercase',
        'letterSpacing': '0.05em',
        'borderBottom': '1px solid #2B4C7E',
        'paddingBottom': '6px',
        'marginBottom': '12px'
    }

    LABEL_STYLE = {
        'fontSize': '0.95rem',
        'color': '#A0AEC0',
        'marginBottom': '4px',
        'fontWeight': '600',
        'display': 'block'
    }

    # Sidebar - Compact optimized layout
    sidebar = html.Div([
        html.H4(
            "Strategy Config",
            style={
                'textAlign': 'left',
                'marginBottom': '22px',
                'color': 'white',
                'fontWeight': '600',
                'fontSize': '1.35rem',
                'letterSpacing': '0.03rem',
                'borderBottom': '1px solid #4A5568',
                'paddingBottom': '12px'
            }
        ),

        # Data Settings
        html.Div([
            html.Div("Data Settings", style=SECTION_TITLE_STYLE),
            dbc.Row([
                dbc.Col([
                    html.Label("Source", style=LABEL_STYLE),
                    dcc.RadioItems(
                        id='bf-data-source',
                        options=[{'label': ' Local', 'value': 'local'}, {'label': ' Wind', 'value': 'wind'}],
                        value='local',
                        labelStyle={'display': 'inline-block', 'marginRight': '12px', 'fontSize': '1.0rem', 'color': '#CBD5E0', 'cursor': 'pointer'},
                        inputStyle={"marginRight": "4px", "cursor": 'pointer'}
                    )
                ], width=6),
                dbc.Col([
                    html.Label("Mode", style=LABEL_STYLE),
                    dcc.RadioItems(
                        id='bf-trading-mode',
                        options=[{'label': ' Daily', 'value': 'daily'}, {'label': ' Intraday', 'value': 'intraday'}],
                        value='daily',
                        labelStyle={'display': 'inline-block', 'marginRight': '12px', 'fontSize': '1.0rem', 'color': '#CBD5E0', 'cursor': 'pointer'},
                        inputStyle={"marginRight": "4px", "cursor": 'pointer'}
                    )
                ], width=6),
            ], className="mb-3"),

            html.Div(id='bf-wind-inputs', children=[
                html.Label("Wind Symbol", style=LABEL_STYLE),
                dcc.Dropdown(
                    id='bf-wind-code',
                    placeholder="Select symbol",
                    style={'fontSize': '1.0rem', 'color': 'black'}
                )
            ], className="mb-2"),

            html.Div(id='bf-local-inputs', children=[
                html.Label("Local Symbol", style=LABEL_STYLE),
                dcc.Dropdown(
                    id='bf-local-symbol',
                    options=pkl_options,
                    placeholder="Select symbol",
                    style={'fontSize': '1.0rem', 'color': 'black'}
                )
            ], style={'display': 'none'}, className="mb-2"),

            html.Label("Date Range", style=LABEL_STYLE),
            html.Div([
                dcc.DatePickerRange(
                    id='bf-date-range',
                    start_date=(datetime.now() - timedelta(days=30)).date(),
                    end_date=datetime.now().date(),
                    display_format='YYYY-MM-DD',
                    style={'fontSize': '1.0rem', 'width': '100%'},
                    className="mb-2",
                    with_portal=True,
                    day_size=39
                )
            ], style={'marginBottom': '10px'}),

            html.Div(id='bf-timeframe-container', children=[
                html.Label("Timeframe", style=LABEL_STYLE),
                dcc.Dropdown(
                    id='bf-timeframe',
                    options=[
                        {'label': '1 Min', 'value': '1T'},
                        {'label': '5 Min', 'value': '5T'},
                        {'label': '15 Min', 'value': '15T'},
                        {'label': '30 Min', 'value': '30T'},
                        {'label': '1 Hour', 'value': '1H'}
                    ],
                    value='5T',
                    style={'fontSize': '1.0rem', 'color': 'black'}
                ),
            ], className="mb-2"),

            dbc.Row([
                dbc.Col([
                    html.Label("OOS Split", style=LABEL_STYLE),
                    dcc.DatePickerSingle(
                        id='bf-oos-split-date',
                        date=datetime.now().date(),
                        display_format='YYYY-MM-DD',
                        style={'fontSize': '1.0rem', 'width': '100%'},
                    ),
                ], width=6),
                dbc.Col([
                    html.Label("In-sample", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id='bf-insample-lookback',
                        options=[
                            {'label': '6 Months', 'value': '6M'},
                            {'label': '1 Year', 'value': '1Y'},
                            {'label': '2 Years', 'value': '2Y'},
                        ],
                        value='1Y',
                        clearable=False,
                        style={'fontSize': '1.0rem', 'color': 'black'}
                    ),
                ], width=6)
            ], className="mb-2"),
        ], style=SECTION_STYLE),

        # Strategy Selection
        html.Div([
            html.Div("Strategies", style=SECTION_TITLE_STYLE),
            dcc.Checklist(
                id='bf-strategy-selector',
                options=[
                    {'label': ' MA', 'value': 'MA'},
                    {'label': ' DeMark', 'value': 'DeMark'},
                    {'label': ' Bollinger', 'value': 'Boll'},
                    {'label': ' VWAP', 'value': 'VWAP'},
                    {'label': ' Momentum', 'value': 'Momentum'},
                    {'label': ' ATR', 'value': 'ATR'},
                    {'label': ' SAR', 'value': 'SAR'},
                    {'label': ' Market Regime', 'value': 'MarketRegime'},
                ],
                value=['MA', 'Boll', 'SAR', 'MarketRegime'],
                # Force a compact 3-column layout inside the narrow sidebar.
                labelStyle={
                    'display': 'inline-block',
                    'width': '33%',
                    'marginBottom': '8px',
                    'fontSize': '1.0rem',
                    'color': '#E2E8F0',
                    'cursor': 'pointer',
                    'verticalAlign': 'top'
                },
                inputStyle={"marginRight": "8px", "cursor": 'pointer'},
                style={'marginTop': '6px'}
            )
        ], style=SECTION_STYLE),

        # Market Regime Configuration - 2 columns side by side (Flexbox)
        html.Div([
            html.Div("Regime Logic", style=SECTION_TITLE_STYLE),
            html.Div([
                html.Div([
                    html.Label("Trending", style={'fontSize': '0.95rem', 'color': '#A0AEC0', 'marginBottom': '2px', 'display': 'block'}),
                    dcc.Dropdown(
                        id='bf-mr-trending-strategy',
                        options=[
                            {'label': 'MA', 'value': 'MA'},
                            {'label': 'SAR', 'value': 'SAR'},
                            {'label': 'ATR', 'value': 'ATR'}
                        ],
                        value='SAR',
                        style={'fontSize': '0.95rem', 'color': 'black'},
                    ),
                ], style={'flex': 1, 'paddingRight': '4px', 'minWidth': '0'}),
                html.Div([
                    html.Label("Mean-Rev", style={'fontSize': '0.95rem', 'color': '#A0AEC0', 'marginBottom': '2px', 'display': 'block'}),
                    dcc.Dropdown(
                        id='bf-mr-meanrev-strategy',
                        options=[
                            {'label': 'Boll', 'value': 'Boll'},
                            {'label': 'VWAP', 'value': 'VWAP'},
                            {'label': 'ATR', 'value': 'ATRMeanRev'}
                        ],
                        value='Boll',
                        style={'fontSize': '0.95rem', 'color': 'black'}
                    )
                ], style={'flex': 1, 'paddingLeft': '4px', 'minWidth': '0'}),
            ], style={'display': 'flex', 'flexDirection': 'row', 'width': '100%'})
        ], style={'marginBottom': '15px'}),

        # Parameters - compact 3-column grid (Flexbox)
        html.Div([
            html.Div("Parameters", style=SECTION_TITLE_STYLE),
            # Row 1: MA | Bollinger | VWAP
            html.Div([
                # MA
                html.Div([
                    html.Div("MA", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Div([
                        html.Div([html.Label("S", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-ma-short', type='number', value=5, min=2, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginRight': '2px'}),
                        html.Div([html.Label("L", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-ma-long', type='number', value=20, min=5, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginLeft': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'row'})
                ], style={'flex': 1, 'paddingRight': '4px', 'minWidth': '0'}),
                # Boll
                html.Div([
                    html.Div("Boll", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Div([
                        html.Div([html.Label("P", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-boll-window', type='number', value=20, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginRight': '2px'}),
                        html.Div([html.Label("σ", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-boll-std', type='number', value=1.0, step=0.1, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginLeft': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'row'}),
                    dcc.Checklist(id='bf-boll-exit', options=[{'label': ' Exit@MA', 'value': 'exit'}], value=[], labelStyle={'fontSize': '0.85rem', 'color': '#CBD5E0'}, style={'marginTop': '2px'})
                ], style={'flex': 1, 'paddingLeft': '4px', 'paddingRight': '4px', 'minWidth': '0'}),
                # VWAP
                html.Div([
                    html.Div("VWAP", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Label("Win", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}),
                    dcc.Input(id='bf-vwap-window', type='number', value=20, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})
                ], style={'flex': 1, 'paddingLeft': '4px', 'minWidth': '0'}),
            ], style={'display': 'flex', 'flexDirection': 'row', 'width': '100%', 'marginBottom': '8px'}),

            # Row 2: Momentum | ATR | SAR
            html.Div([
                # Mom
                html.Div([
                    html.Div("Mom", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Label("LB", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}),
                    dcc.Input(id='bf-mom-window', type='number', value=14, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})
                ], style={'flex': 1, 'paddingRight': '4px', 'minWidth': '0'}),
                # ATR
                html.Div([
                    html.Div("ATR", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Div([
                        html.Div([html.Label("E", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-atr-ema-window', type='number', value=11, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'paddingRight': '2px'}),
                        html.Div([html.Label("A", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-atr-window', type='number', value=14, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'paddingLeft': '2px', 'paddingRight': '2px'}),
                        html.Div([html.Label("M", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-atr-mult', type='number', value=2.0, step=0.1, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'paddingLeft': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'row'})
                ], style={'flex': 1, 'paddingLeft': '4px', 'paddingRight': '4px', 'minWidth': '0'}),
                # SAR
                html.Div([
                    html.Div("SAR", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Div([
                        html.Div([html.Label("AF", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-sar-af', type='number', value=0.02, step=0.01, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginRight': '2px'}),
                        html.Div([html.Label("Max", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-sar-max-af', type='number', value=0.2, step=0.01, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginLeft': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'row'})
                ], style={'flex': 1, 'paddingLeft': '4px', 'minWidth': '0'}),
            ], style={'display': 'flex', 'flexDirection': 'row', 'width': '100%'})
        ], style={'marginBottom': '15px', 'padding': '10px', 'backgroundColor': '#0a1e3d', 'borderRadius': '4px', 'border': '1px solid #2B4C7E'}),

        dbc.Button("Run Backtest", id='bf-run-button', style={
            'width': '100%', 'padding': '12px', 'backgroundColor': '#007ACE',
            'color': 'white', 'border': 'none', 'cursor': 'pointer',
            'fontSize': '1.1rem', 'fontWeight': 'bold', 'letterSpacing': '0.1rem'
        })
    ], style={
        'width': '320px', 'padding': '2rem 1rem', 'backgroundColor': '#082255',
        'color': 'white', 'overflowY': 'auto', 'fontFamily': '"Open Sans", sans-serif'
    })

    # Content area
    content = html.Div([
        dcc.Loading(
            id="bf-loading-results",
            type="default",
            children=html.Div(id='bf-results-container', style={'minHeight': '400px'})
        )
    ], style={'flex': '1', 'padding': '1.5rem 2rem', 'fontFamily': '"Open Sans", sans-serif', 'minWidth': '0'})

    return html.Div([sidebar, content], style={'display': 'flex', 'flexDirection': 'row', 'width': '100%', 'minHeight': 'calc(100vh - 150px)', 'backgroundColor': THEME['bg_main']})
