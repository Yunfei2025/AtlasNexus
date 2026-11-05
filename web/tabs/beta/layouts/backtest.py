# -*- coding: utf-8 -*-
"""Backtest tab layouts: historical allocation, risk-factor backtest, futures backtest."""

from __future__ import annotations

from datetime import datetime, timedelta

from dash import dcc, html
import dash_bootstrap_components as dbc

from ..data import THEME, FUTURES_AVAILABLE, SELECTED_FACTOR_POOL
from ...ui.components import button as an_button

# Conditionally import futures discovery helper
if FUTURES_AVAILABLE:
    from futures.backtest.data_loader import discover_pkl_files
    from futures.backtest.walkforward import DEFAULT_PARAMS


def build_factor_history_layout():
    """Factor Explorer tab — matches BetaFactor.jsx design with sidebar controls + chart."""
    _lbl = {
        'color': 'var(--text-muted)',
        'fontSize': '9px',
        'fontWeight': '600',
        'textTransform': 'uppercase',
        'letterSpacing': '0.06em',
        'marginBottom': '4px',
        'display': 'block',
    }
    _card_header = {
        'padding': '11px 16px',
        'background': 'var(--surface-panel)',
        'borderBottom': '1px solid var(--border-strong)',
        'userSelect': 'none',
    }
    _card_wrap = {
        'border': '1px solid var(--border-strong)',
        'borderRadius': '8px',
        'overflow': 'hidden',
    }

    # LEFT SIDEBAR: Controls card
    sidebar = html.Div([
        html.Div(
            html.Span("Controls", style={'fontSize': '13px', 'fontWeight': '600', 'color': 'var(--text-primary)'}),
            style=_card_header
        ),
        html.Div([
            html.Div([
                html.Div("Asset Class", style=_lbl),
                dcc.Dropdown(
                    id='factor-asset-class-selector',
                    options=[
                        {'label': 'Rates',       'value': 'Rates'},
                        {'label': 'Credit',      'value': 'Credit'},
                        {'label': 'FX',          'value': 'FX'},
                        {'label': 'Equity',      'value': 'Equity'},
                        {'label': 'Commodity',   'value': 'Commodity'},
                    ],
                    value=None,
                    placeholder="Select…",
                    clearable=True,
                    style={'fontSize': '11px'},
                ),
            ], style={'marginBottom': '12px'}),

            html.Div([
                html.Div("Region / Type", style=_lbl),
                dcc.Dropdown(
                    id='factor-region-selector',
                    options=[],
                    value=None,
                    placeholder="Select…",
                    clearable=True,
                    style={'fontSize': '11px'},
                ),
            ], style={'marginBottom': '12px'}),

            html.Div([
                html.Div("Factor(s)", style=_lbl),
                dcc.Dropdown(
                    id='factor-type-selector',
                    options=[],
                    value=[],
                    multi=True,
                    placeholder="Select…",
                    style={'fontSize': '11px'},
                ),
            ], style={'marginBottom': '12px'}),

            html.Div([
                html.Div(
                    "IRDL = Level · IRSL = Slope · IRCV = Curvature\n"
                    "FXDL = FX spot · CMDL = Commodity · EQDL = Equity",
                    style={'color': 'var(--text-muted)', 'fontSize': '9px',
                           'whiteSpace': 'pre-line', 'lineHeight': '1.6'},
                ),
            ], style={'borderTop': '1px solid var(--border-default)', 'paddingTop': '10px'}),
        ], style={'padding': '12px 14px', 'display': 'flex', 'flexDirection': 'column', 'gap': '12px'}),
    ], style={**_card_wrap, 'width': '220px', 'flexShrink': '0'})

    # RIGHT AREA: chart (rangeselector buttons + legend are built into the
    # Plotly figure itself, so no separate period-button row is needed here).
    chart_area = html.Div([
        # Chart card
        html.Div([
            html.Div(
                html.Span("Historical Performance", style={'fontSize': '13px', 'fontWeight': '600', 'color': 'var(--text-primary)'}),
                style=_card_header
            ),
            html.Div([
                dcc.Graph(
                    id='factor-history-chart',
                    config={'displayModeBar': False},
                    style={'height': '540px'},
                ),
            ], style={'padding': '10px 12px'}),
        ], style=_card_wrap),
    ], style={'flex': '1', 'minWidth': '0', 'display': 'flex', 'flexDirection': 'column'})

    return html.Div([
        html.Div([
            html.H1("Factor Explorer", style={'margin': '0 0 3px', 'fontSize': '20px',
                                             'fontWeight': '600', 'color': 'var(--text-primary)'}),
            html.Div("Browse historical factor levels by asset class, region, and type",
                    style={'fontSize': '11px', 'color': 'var(--text-muted)'}),
        ], style={'marginBottom': '12px'}),

        html.Div([
            sidebar,
            chart_area,
        ], style={'display': 'flex', 'gap': '12px', 'alignItems': 'start'}),
    ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '10px', 'padding': '16px', 'margin': '10px'})


def build_beta_backtest_combined_layout():
    """Wrap the Backtest subtab as two inner sheets — Individual Factors and Portfolio.

    Individual Factors: risk-factor model backtest (full controls + enhanced charts).
    Portfolio:          historical allocation analysis (previously the Rebalance subtab).
    """
    return html.Div([
        html.H1("Beta Backtest", style={
            'margin': '0 0 8px', 'fontSize': '22px', 'fontWeight': '600',
            'color': 'var(--text-primary)',
        }),
        html.Div(
            "Backtest individual factor or the full portfolio using historical data. "
            "Evaluate factor-model signal performance with IC-weighted positioning, "
            "risk-parity vol scaling, and transaction cost modelling.",
            style={'fontSize': '13px', 'color': 'var(--text-secondary)',
                   'marginBottom': '20px'}
        ),

        dcc.Tabs(
            id='beta-backtest-inner-tabs',
            value='individual-factors',
            className='tab-container an-pill-toggle',
            children=[
                dcc.Tab(label='Individual Factors', value='individual-factors',
                        className='tab an-pill-toggle', selected_className='tab an-pill-toggle an-pill-toggle--selected'),
                dcc.Tab(label='Portfolio', value='portfolio',
                        className='tab an-pill-toggle', selected_className='tab an-pill-toggle an-pill-toggle--selected'),
            ],
            style={'marginBottom': '20px'},
        ),
        # Both panels are pre-rendered; CSS show/hide via callback.
        html.Div(id='beta-backtest-indiv-div',
                 children=build_risk_factor_backtest_layout(),
                 style={'display': 'block'}),
        html.Div(id='beta-backtest-port-div',
                 children=build_multiasset_backtest_layout(),
                 style={'display': 'none'}),
    ])


def build_multiasset_backtest_layout():
    """Build the layout for the Backtest tab — REDESIGNED VERSION WITH THREE-CARD GRID.

    Strategy:
    - At the beginning of each month, run Cross-Asset Correlation Analysis
    - Select assets with lowest correlations for diversification
    - Run Risk Parity allocation on the selected assets
    - Track asset pool changes over time
    """
    # Shared style tokens — CSS-var based, mirrors the JSX mockup's panels/inputs
    _inp = {
        'background': 'var(--surface-input)', 'border': '1px solid var(--border-default)',
        'borderRadius': '6px', 'padding': '8px 10px', 'color': 'var(--text-primary)',
        'fontSize': '13px', 'boxSizing': 'border-box',
    }
    _card = {
        'background': 'var(--surface-panel)', 'border': '1px solid var(--border-strong)',
        'borderRadius': '6px', 'padding': '14px 16px',
    }
    _hdr = {'margin': '0 0 10px', 'fontSize': '14px', 'fontWeight': '600',
            'color': 'var(--text-primary)'}
    _lbl = {'fontSize': '10px', 'fontWeight': '600', 'letterSpacing': '0.05em',
            'textTransform': 'uppercase', 'color': 'var(--text-muted)',
            'display': 'block', 'marginBottom': '6px'}
    _section_lbl = {
        'fontSize': '9px', 'fontWeight': '700', 'letterSpacing': '0.08em',
        'textTransform': 'uppercase', 'color': 'var(--text-muted)', 'marginBottom': '8px',
    }
    _subsection = {
        'background': 'var(--surface-raised)', 'border': '1px solid var(--border-default)',
        'borderRadius': '6px', 'padding': '10px 12px',
    }

    def _segmented(input_id, options, value):
        """Two-way pill segmented control, styled like the JSX mockup's Date/Allocation mode toggle."""
        return dcc.RadioItems(
            id=input_id,
            options=options,
            value=value,
            inline=True,
            className='an-segmented',
            labelClassName='an-segmented__label',
            inputClassName='an-segmented__input',
        )

    return html.Div([
        html.Div([
            # ============================= LEFT: all controls =============================
            html.Div([
                # --- Strategy ---
                html.Div([
                    html.H2("Strategy", style={**_hdr, 'fontSize': '12px'}),
                    html.Div([
                        html.Div([
                            html.Div("Factor Pool", style={'fontSize': '9px', 'fontWeight': '600',
                                                           'textTransform': 'uppercase', 'color': 'var(--text-muted)',
                                                           'marginBottom': '4px'}),
                            html.Div(id='backtest-strategy-factor-pool',
                                    children=[],
                                    style={'display': 'grid',
                                           'gridTemplateColumns': 'repeat(3, 1fr)',
                                           'gap': '4px'}),
                        ]),
                        html.Div([
                            html.Div("Lookback", style={'fontSize': '9px', 'fontWeight': '600',
                                                        'textTransform': 'uppercase', 'color': 'var(--text-muted)',
                                                        'marginBottom': '4px'}),
                            html.Div(id='backtest-strategy-lookback', children="2 Years",
                                    style={'fontSize': '11px', 'color': 'var(--text-primary)'}),
                        ]),
                        html.Div([
                            html.Div("Capital", style={'fontSize': '9px', 'fontWeight': '600',
                                                       'textTransform': 'uppercase', 'color': 'var(--text-muted)',
                                                       'marginBottom': '4px'}),
                            html.Div(id='backtest-strategy-capital', children="10 Billion CNY",
                                    style={'fontSize': '11px', 'color': 'var(--text-primary)'}),
                        ]),
                    ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '12px'}),
                ], style=_card),

                # --- Parameters ---
                html.Div([
                    html.H2("Parameters", style=_hdr),

                    # --- Capital sub-section: amount + unit are one logical
                    # value, kept side-by-side instead of split across a
                    # generic grid ---
                    html.Div([
                        html.Div("CAPITAL", style=_section_lbl),
                        html.Div([
                            html.Div([
                                html.Label("Amount", style=_lbl),
                                dcc.Input(
                                    id='backtest-capital-input',
                                    type='number',
                                    value=10,
                                    style={**_inp}, className='no-spinner',
                                ),
                            ]),
                            html.Div([
                                html.Label("Unit", style=_lbl),
                                dcc.Dropdown(
                                    id='backtest-capital-unit',
                                    options=[
                                        {"label": "Million", "value": "million"},
                                        {"label": "Billion", "value": "billion"},
                                    ],
                                    value="billion",
                                    clearable=False,
                                    style={'fontSize': '13px'}
                                ),
                            ]),
                        ], style={'display': 'grid', 'gridTemplateColumns': 'repeat(2, minmax(0, 1fr))', 'gap': '8px'}),
                    ], style={**_subsection, 'marginBottom': '10px'}),

                    # --- Lookback windows sub-section ---
                    html.Div([
                        html.Div("LOOKBACK WINDOWS", style=_section_lbl),
                        html.Div([
                            html.Div([
                                html.Label("Backtest Lookback", style=_lbl),
                                dcc.Dropdown(
                                    id='backtest-lookback-preset',
                                    options=[
                                        {'label': '1 Year', 'value': '1Y'},
                                        {'label': '2 Years', 'value': '2Y'},
                                        {'label': '5 Years', 'value': '5Y'},
                                        {'label': '10 Years', 'value': '10Y'},
                                    ],
                                    value='2Y',
                                    clearable=False,
                                    style={'fontSize': '13px'}
                                ),
                            ], id='backtest-lookback-container'),

                            html.Div([
                                html.Label("Correlation Lookback", style=_lbl),
                                dcc.Dropdown(
                                    id='backtest-corr-lookback',
                                    options=[
                                        {'label': '3 Months', 'value': '3M'},
                                        {'label': '6 Months', 'value': '6M'},
                                        {'label': '1 Year', 'value': '1Y'},
                                    ],
                                    value='1Y',
                                    clearable=False,
                                    style={'fontSize': '13px'}
                                ),
                            ]),
                        ], style={'display': 'grid', 'gridTemplateColumns': 'repeat(2, minmax(0, 1fr))', 'gap': '8px', 'marginBottom': '8px'}),

                        html.Div([
                            html.Label("Top Low-Corr Pairs", style=_lbl),
                            dcc.Input(
                                id='backtest-top-pairs',
                                type='number',
                                value=10, min=5, max=20,
                                style={**_inp, 'width': '100%'}, className='no-spinner',
                            ),
                        ]),
                    ], style={**_subsection, 'marginBottom': '10px'}),

                    # --- Mode sub-section: Date Mode + Allocation Mode ---
                    html.Div([
                        html.Div("MODE", style=_section_lbl),
                        html.Div([
                            html.Div([
                                html.Label("Date Mode", style=_lbl),
                                _segmented('backtest-date-mode', [
                                    {'label': 'Preset', 'value': 'preset'},
                                    {'label': 'Custom', 'value': 'custom'},
                                ], 'preset'),
                            ]),

                            html.Div([
                                html.Label("Allocation Mode", style=_lbl),
                                _segmented('backtest-alloc-mode', [
                                    {'label': 'Pure Risk Parity', 'value': 'risk_parity'},
                                    {'label': 'Factor Model Scaling', 'value': 'factor_scaling'},
                                ], 'risk_parity'),
                            ]),
                        ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '10px'}),

                        # Hidden date range picker (shown when date_mode='custom')
                        html.Div([
                            html.Label("Backtest Period:", style=_lbl),
                            html.Div([
                                dcc.DatePickerRange(
                                    id='history-date-range',
                                    min_date_allowed=datetime(2019, 1, 1).date(),
                                    max_date_allowed=datetime.now().date(),
                                    start_date=datetime(2024, 1, 1).date(),
                                    end_date=datetime.now().date(),
                                    display_format='YYYY-MM-DD',
                                    style={'backgroundColor': 'var(--surface-input)', 'color': 'var(--text-primary)'},
                                    updatemode='bothdates',
                                    with_portal=False,
                                )
                            ], style={'display': 'flex', 'gap': '10px', 'position': 'relative', 'zIndex': 999}),
                            html.Div(id='backtest-min-date-info',
                                     style={'fontSize': '11px', 'color': 'var(--text-muted)', 'marginTop': '8px'}),
                        ], id='backtest-period-container', style={'display': 'none', 'marginTop': '12px'}),
                    ], style=_subsection),
                ], style=_card),

                # --- Actions ---
                html.Div([
                    an_button(
                        "▶ Run Historical Analysis", id='run-history-button', n_clicks=0,
                        variant="success", style_overrides={'padding': '10px 12px', 'fontSize': '11px', 'width': '100%'},
                    ),
                    an_button(
                        "💾 Save Result", id='save-history-backtest-button', n_clicks=0,
                        variant="secondary", style_overrides={'padding': '10px 12px', 'fontSize': '11px', 'width': '100%'},
                    ),
                    html.Span(id='save-history-backtest-status',
                              style={'color': 'var(--text-muted)', 'fontSize': '11px', 'display': 'block'}),
                    an_button(
                        "📄 Generate Report", id='gen-report-button', n_clicks=0,
                        variant="secondary", style_overrides={'padding': '10px 12px', 'fontSize': '11px', 'width': '100%'},
                    ),
                    an_button(
                        "⬇️ Download Report", id='dl-report-button', n_clicks=0, disabled=True,
                        variant="success", style_overrides={'padding': '10px 12px', 'fontSize': '11px', 'width': '100%'},
                    ),
                    html.Div(id='report-status-message', style={'marginTop': '10px', 'fontSize': '13px'}),
                ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '10px'}),
            ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '12px',
                      'flex': '0 0 300px', 'minWidth': '260px', 'maxWidth': '320px'}),

            # ============================= RIGHT: metrics + charts =============================
            html.Div([
                html.Div(id='performance-metrics-container',
                         style={'marginBottom': '15px'}),

                dcc.Loading(
                    id="loading-history",
                    type="circle",
                    color=THEME['accent'],
                    children=[
                        dcc.Graph(id='historical-allocation-chart', config={'displayModeBar': False}),
                        html.Div(style={'height': '20px'}),
                        dcc.Graph(id='pnl-attribution-chart', config={'displayModeBar': False}),
                        html.Div(style={'height': '20px'}),
                        # Asset Pool Changes Section
                        html.Div(id='asset-changes-container')
                    ]
                ),

                # ── Section 4: Monthly Report ───────────────────────────
                html.Div(id='risk-budget-allocation-panel', style={'marginTop': '20px'}),

                html.Div([
                    html.H2("本月要点 (Monthly Highlights)", style=_hdr),
                    dcc.Textarea(
                        id='report-commentary-input',
                        style={'width': '100%', 'height': '110px', 'fontSize': '13px',
                               'background': 'var(--surface-input)', 'color': 'var(--text-primary)',
                               'border': '1px solid var(--border-default)', 'borderRadius': '6px',
                               'padding': '8px', 'boxSizing': 'border-box'},
                    ),
                ], id='report-commentary-container', style={**_card, 'display': 'none', 'marginTop': '15px'}),
            ], style={'flex': '1', 'minWidth': '0'}),
        ], style={'display': 'flex', 'gap': '16px', 'alignItems': 'flex-start', 'flexWrap': 'wrap'}),

        dcc.Store(id='backtest-results-store'),
        dcc.Store(id='report-meta-store'),
        dcc.Download(id='report-download'),
    ], style={'padding': '10px'})


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
        # Credit
        {'label': 'CRDL.CDB (CDB Spread Level)',  'value': 'CRDL.CDB'},
        {'label': 'CRSL.CDB (CDB Spread Slope)',  'value': 'CRSL.CDB'},
        {'label': 'CRDL.LGB (LGB Spread Level)',  'value': 'CRDL.LGB'},
        {'label': 'CRDL.MTN (MTN Spread Level)',  'value': 'CRDL.MTN'},
        {'label': 'CRDL.ICP (ICP Spread Level)',  'value': 'CRDL.ICP'},
        # FX
        {'label': 'FXDL.USDCNY',             'value': 'FXDL.USDCNY'},
        {'label': 'FXDL.EURCNY',             'value': 'FXDL.EURCNY'},
        # Commodity
        {'label': 'CMDL.AU (Gold)',           'value': 'CMDL.AU'},
        {'label': 'CMDL.CU (Copper)',         'value': 'CMDL.CU'},
        {'label': 'CMDL.AL (Aluminium)',      'value': 'CMDL.AL'},
        {'label': 'CMDL.SC (Crude Oil)',      'value': 'CMDL.SC'},
    ]

    # Default factors mirror the Factor subtab's active Risk Factor Pool selection
    default_factors = list(dict.fromkeys(
        SELECTED_FACTOR_POOL['ir_factors'] +
        SELECTED_FACTOR_POOL.get('cr_factors', []) +
        SELECTED_FACTOR_POOL['fx_factors'] +
        SELECTED_FACTOR_POOL['cmd_factors']
    )) or ['IRDL.CN', 'IRSL.CN', 'FXDL.USDCNY']

    # Shared dark-input style — CSS-var based, matches the JSX mockup's inputs/dropdowns
    _inp = {
        'width': '100%', 'background': 'var(--surface-input)',
        'border': '1px solid var(--border-default)', 'borderRadius': '6px',
        'padding': '8px 10px', 'color': 'var(--text-primary)', 'fontSize': '13px',
        'boxSizing': 'border-box',
    }
    # Card container — mirrors the JSX mockup's panel styling
    _card = {
        'background': 'var(--surface-panel)', 'border': '1px solid var(--border-strong)',
        'borderRadius': '6px', 'padding': '14px 16px',
    }
    _hdr = {'margin': '0 0 10px', 'fontSize': '14px', 'fontWeight': '600',
            'color': 'var(--text-primary)'}
    _lbl = {'fontSize': '10px', 'fontWeight': '600', 'letterSpacing': '0.05em',
            'textTransform': 'uppercase', 'color': 'var(--text-muted)',
            'display': 'block', 'marginBottom': '6px'}
    _section_lbl = {
        'fontSize': '9px', 'fontWeight': '700', 'letterSpacing': '0.08em',
        'textTransform': 'uppercase', 'color': 'var(--text-muted)', 'marginBottom': '8px',
    }
    _subsection = {
        'background': 'var(--surface-raised)', 'border': '1px solid var(--border-default)',
        'borderRadius': '6px', 'padding': '10px 12px',
    }

    return html.Div([
        html.Div([
            # ============================= LEFT: all controls =============================
            html.Div([
                # --- Factor Selection ---
                html.Div([
                    html.H2("Factor Selection", style=_hdr),

                    html.Div([
                        html.Label("Asset Class:", style=_lbl),
                        dcc.Dropdown(
                            id='rfbt-asset-class',
                            options=[
                                {'label': 'Rates',       'value': 'Rates'},
                                {'label': 'Credit',      'value': 'Credit'},
                                {'label': 'FX',          'value': 'FX'},
                                {'label': 'Commodities', 'value': 'Commodities'},
                            ],
                            value='Rates',
                            clearable=False,
                            style={'fontSize': '13px'},
                        ),
                    ], style={'marginBottom': '10px'}),

                    html.Div([
                        html.Label("Factor:", style=_lbl),
                        dcc.Dropdown(
                            id='rfbt-factor',
                            options=[],
                            value=None,
                            clearable=False,
                            placeholder="Select factor…",
                            style={'fontSize': '13px'},
                        ),
                    ]),

                    # Hidden legacy IDs kept for strategy-param callbacks
                    dcc.Store(id='rfbt-strategy-selector', data='FactorModel'),
                    html.Div(id='rfbt-ma-params', children=[
                        dcc.Input(id='rfbt-ma-short', type='number', value=10, style={'display': 'none'}),
                        dcc.Input(id='rfbt-ma-long',  type='number', value=30, style={'display': 'none'}),
                    ], style={'display': 'none'}),
                    html.Div(id='rfbt-boll-params', children=[
                        dcc.Input(id='rfbt-boll-window', type='number', value=20, style={'display': 'none'}),
                        dcc.Input(id='rfbt-boll-std',    type='number', value=1.5, style={'display': 'none'}),
                    ], style={'display': 'none'}),
                    html.Div(id='rfbt-mom-params', children=[
                        dcc.Input(id='rfbt-mom-window', type='number', value=20, style={'display': 'none'}),
                    ], style={'display': 'none'}),
                    html.Div(id='rfbt-zscore-params', children=[
                        dcc.Input(id='rfbt-zscore-window', type='number', value=60,  style={'display': 'none'}),
                        dcc.Input(id='rfbt-zscore-entry',  type='number', value=1.5, style={'display': 'none'}),
                        dcc.Input(id='rfbt-zscore-exit',   type='number', value=0.5, style={'display': 'none'}),
                    ], style={'display': 'none'}),
                ], style=_card),

                # --- Strategy Parameters ---
                html.Div([
                    html.H2("Strategy Parameters", style=_hdr),
                    html.Div(id='rfbt-fm-params', children=[

                        # --- Model training sub-section ---
                        html.Div([
                            html.Div("MODEL TRAINING", style=_section_lbl),
                            html.Div([
                                html.Div([
                                    html.Label("Train window (mo)", style=_lbl),
                                    dcc.Input(id='rfbt-fm-train', type='number', value=12, min=3,
                                              style={**_inp}, className='no-spinner'),
                                ]),
                                html.Div([
                                    html.Label("IC threshold", style=_lbl),
                                    dcc.Input(id='rfbt-fm-ic', type='number', value=0.05, step=0.01, min=0.01,
                                              style={**_inp}, className='no-spinner'),
                                ]),
                                html.Div([
                                    html.Label("Top N features", style=_lbl),
                                    dcc.Input(id='rfbt-fm-topn', type='number', value=8, min=1,
                                              style={**_inp}, className='no-spinner'),
                                ]),
                            ], style={'display': 'grid', 'gridTemplateColumns': 'repeat(2, minmax(0, 1fr))', 'gap': '8px'}),
                        ], style={**_subsection, 'marginBottom': '10px'}),

                        # --- Position sizing sub-section ---
                        html.Div([
                            html.Div("POSITION SIZING", style=_section_lbl),
                            html.Div([
                                html.Div([
                                    html.Label("Sizing mode", style=_lbl),
                                    dcc.Dropdown(
                                        id='rfbt-fm-sizing',
                                        options=[
                                            {'label': 'Continuous (default)', 'value': 'continuous'},
                                            {'label': 'Discrete 5-level',     'value': 'discrete'},
                                            {'label': 'Tilt (core hold)',     'value': 'tilt'},
                                        ],
                                        value='continuous',
                                        clearable=False,
                                        style={'fontSize': '13px'},
                                    ),
                                ]),
                                html.Div([
                                    html.Label("Smooth window (d)", style=_lbl),
                                    dcc.Input(id='rfbt-fm-possmooth', type='number', value=10, min=1,
                                              style={**_inp}, className='no-spinner'),
                                ]),
                            ], style={'display': 'grid', 'gridTemplateColumns': 'repeat(2, minmax(0, 1fr))', 'gap': '8px'}),

                            # Tilt-only parameters — shown when sizing mode is 'tilt'.
                            html.Div(id='rfbt-fm-tilt-params', children=[
                                html.Div([
                                    html.Div([
                                        html.Label("Baseline exposure", style=_lbl),
                                        dcc.Input(id='rfbt-fm-tiltbase', type='number', value=0.70,
                                                  min=0, max=2, step=0.05,
                                                  style={**_inp}, className='no-spinner'),
                                    ]),
                                    html.Div([
                                        html.Label("Tilt amplitude", style=_lbl),
                                        dcc.Input(id='rfbt-fm-tiltamp', type='number', value=0.10,
                                                  min=0, max=1, step=0.05,
                                                  style={**_inp}, className='no-spinner'),
                                    ]),
                                ], style={'display': 'grid',
                                          'gridTemplateColumns': 'repeat(2, minmax(0, 1fr))',
                                          'gap': '8px', 'marginTop': '8px'}),
                                html.Div(
                                    "Baseline is a duration-policy input, not a fitted value. "
                                    "Holds the baseline when the signal is weak instead of going "
                                    "flat — larger amplitudes reduced return in testing.",
                                    style={'fontSize': '10px', 'color': 'var(--text-muted)',
                                           'marginTop': '6px', 'lineHeight': '1.4'},
                                ),
                            ], style={'display': 'none'}),
                        ], style={**_subsection, 'marginBottom': '10px'}),

                        # --- Backtest period sub-section ---
                        html.Div([
                            html.Div("BACKTEST PERIOD", style=_section_lbl),
                            html.Div([
                                html.Label("Lookback", style=_lbl),
                                dcc.Dropdown(
                                    id='rfbt-period-years',
                                    options=[
                                        {'label': '1 Year',   'value': 1},
                                        {'label': '2 Years',  'value': 2},
                                        {'label': '3 Years',  'value': 3},
                                        {'label': '5 Years',  'value': 5},
                                        {'label': '10 Years', 'value': 10},
                                    ],
                                    value=2,
                                    clearable=False,
                                    style={'fontSize': '13px'},
                                ),
                            ], style={'marginBottom': '8px'}),
                            html.Div([
                                html.Div([
                                    html.Label("Start (optional)", style=_lbl),
                                    dcc.DatePickerSingle(
                                        id='rfbt-custom-start',
                                        placeholder='override start…',
                                        clearable=True,
                                        display_format='YYYY-MM-DD',
                                        style={'fontSize': '12px'},
                                    ),
                                ]),
                                html.Div([
                                    html.Label("End (optional)", style=_lbl),
                                    dcc.DatePickerSingle(
                                        id='rfbt-custom-end',
                                        placeholder='override end…',
                                        clearable=True,
                                        display_format='YYYY-MM-DD',
                                        style={'fontSize': '12px'},
                                    ),
                                ]),
                            ], style={'display': 'grid', 'gridTemplateColumns': 'repeat(2, minmax(0, 1fr))', 'gap': '8px'}),
                        ], style=_subsection),
                    ]),
                ], style=_card),

                html.Div([
                    an_button(
                        "▶ Run Backtest",
                        id='rfbt-run-btn', n_clicks=0,
                        variant="success",
                        title="Runs the walk-forward backtest and shows the diagnostics "
                              "below. Does not write anything to disk — click Save "
                              "afterward to persist the trained model.",
                        style_overrides={'padding': '9px 18px', 'fontSize': '13px', 'flex': '1'},
                    ),
                    an_button(
                        "💾 Save",
                        id='rfbt-save-btn', n_clicks=0,
                        variant="secondary",
                        disabled=True,
                        title="Persists the model from the last Run Backtest to "
                              "factor-backtest.pkl and the monthly .joblib file "
                              "(incremental merge — other factors are preserved). "
                              "Run Backtest first.",
                        style_overrides={'padding': '9px 14px', 'fontSize': '13px', 'flex': '0 0 auto'},
                    ),
                ], style={'display': 'flex', 'gap': '8px'}),
            ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '12px',
                      'flex': '0 0 300px', 'minWidth': '260px', 'maxWidth': '320px'}),

            # ============================= RIGHT: results =============================
            html.Div([
                dcc.Loading(
                    type='circle',
                    color=THEME['accent'],
                    style={'minHeight': '200px'},
                    children=html.Div([
                        html.Div(id='rfbt-status',
                                 style={'color': 'var(--text-secondary)', 'fontSize': '12px',
                                        'marginBottom': '8px'}),
                        html.Div(id='rfbt-results-container', style={'minHeight': '200px'}),
                    ]),
                ),
            ], style={'flex': '1', 'minWidth': '0'}),
        ], style={'display': 'flex', 'gap': '16px', 'alignItems': 'flex-start', 'flexWrap': 'wrap'}),
    ], style={'padding': '10px'})


def build_factor_backtest_layout():
    """Build the layout for Futures Backtest tab — matches BetaFutures.jsx design.

    3-column top grid: Controls (220px) | Strategy Performance | Regime & Parameters
    Full-width Backtest Results chart at the bottom.
    """
    if not FUTURES_AVAILABLE:
        return html.Div("Futures backtest modules not available.", style={'color': '#f87171'})

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
        'background': 'var(--surface-input)',
        'color': 'var(--text-primary)',
        'border': '1px solid var(--border-default)',
        'fontSize': '11px',
        'borderRadius': '4px',
        'padding': '4px 8px',
    }

    LABEL_STYLE = {
        'fontSize': '9px',
        'fontWeight': '600',
        'textTransform': 'uppercase',
        'letterSpacing': '0.06em',
        'color': 'var(--text-muted)',
        'marginBottom': '3px',
        'display': 'block',
    }

    # Sidebar - single narrow column, ≤25% page width
    _radio_style = {'display': 'inline-block', 'marginRight': '10px',
                    'fontSize': '10px', 'color': 'var(--text-muted)', 'cursor': 'pointer'}
    _radio_input = {"marginRight": "4px", "cursor": 'pointer'}
    _field_mb = {'marginBottom': '8px'}
    _param_lbl = {'fontSize': '9px', 'color': 'var(--text-muted)', 'display': 'block'}
    _param_hd  = {'fontSize': '9px', 'color': 'var(--accent-blue)', 'fontWeight': '600', 'marginBottom': '3px'}
    _inp = {**DARK_INPUT_STYLE, 'fontSize': '10px', 'padding': '3px 5px', 'width': '100%',
            'MozAppearance': 'textfield'}

    # Strategy parameters: one row per strategy, shown as the right column of the Controls card
    def _param_row(name, fields, extra=None):
        return html.Div([
            html.Div(name, style={'fontSize': '10px', 'fontWeight': '600', 'color': 'var(--text-secondary)',
                                  'marginBottom': '3px'}),
            html.Div([html.Div([html.Label(lbl, style=_param_lbl), inp], style={'flex': 1, 'minWidth': '0'})
                      for lbl, inp in fields], style={'display': 'flex', 'gap': '6px'}),
            *([extra] if extra is not None else []),
        ], style={'paddingBottom': '7px', 'borderBottom': '1px solid var(--border-default)'})

    params_column = html.Div([
        html.Div("Parameters", style={
            'color': 'var(--accent-blue)', 'fontSize': '9px', 'fontWeight': '600',
            'textTransform': 'uppercase', 'letterSpacing': '0.08em', 'marginBottom': '-1px',
        }),
        _param_row('MA', [
            ("Short", dcc.Input(id='bf-ma-short', type='number', value=DEFAULT_PARAMS['bf-ma-short'], min=2, style=_inp)),
            ("Long", dcc.Input(id='bf-ma-long', type='number', value=DEFAULT_PARAMS['bf-ma-long'], min=5, style=_inp))]),
        _param_row('Bollinger', [
            ("Period", dcc.Input(id='bf-boll-window', type='number', value=DEFAULT_PARAMS['bf-boll-window'], style=_inp)),
            ("StdDev", dcc.Input(id='bf-boll-std', type='number', value=DEFAULT_PARAMS['bf-boll-std'], step=0.1, style=_inp))],
            extra=dcc.Checklist(id='bf-boll-exit', options=[{'label': ' Exit@MA', 'value': 'exit'}],
                                value=DEFAULT_PARAMS['bf-boll-exit'],
                                labelStyle={'fontSize': '10px', 'color': 'var(--text-muted)'},
                                style={'marginTop': '4px'})),
        _param_row('VWAP', [("Window", dcc.Input(id='bf-vwap-window', type='number', value=DEFAULT_PARAMS['bf-vwap-window'], style=_inp))]),
        _param_row('Momentum', [("Lookback", dcc.Input(id='bf-mom-window', type='number', value=DEFAULT_PARAMS['bf-mom-window'], style=_inp))]),
        _param_row('ATR', [
            ("EMA", dcc.Input(id='bf-atr-ema-window', type='number', value=DEFAULT_PARAMS['bf-atr-ema-window'], style=_inp)),
            ("Win", dcc.Input(id='bf-atr-window', type='number', value=DEFAULT_PARAMS['bf-atr-window'], style=_inp)),
            ("Mult", dcc.Input(id='bf-atr-mult', type='number', value=2.0, step=0.1, style=_inp))]),
        _param_row('SAR', [
            ("AF", dcc.Input(id='bf-sar-af', type='number', value=DEFAULT_PARAMS['bf-sar-af'], step=0.01, style=_inp)),
            ("Max", dcc.Input(id='bf-sar-max-af', type='number', value=DEFAULT_PARAMS['bf-sar-max-af'], step=0.01, style=_inp))]),
    ], id='bf-regime-container', style={'display': 'flex', 'flexDirection': 'column', 'gap': '7px', 'minWidth': '0'})

    sidebar = html.Div([
        html.Div([
            html.Span("Controls", style={
                'color': 'var(--text-primary)',
                'fontSize': '13px',
                'fontWeight': '600',
            }),
        ], style={'padding': '11px 16px', 'background': 'var(--surface-panel)',
                  'borderBottom': '1px solid var(--border-strong)'}),

        html.Div([
        html.Div([

        # ── Data ──────────────────────────────────────────────────────
        html.Div([
            html.Div("Data", style={
                'color': 'var(--accent-blue)', 'fontSize': '9px', 'fontWeight': '600',
                'textTransform': 'uppercase', 'letterSpacing': '0.08em', 'marginBottom': '6px',
            }),

            html.Div([
                html.Label("Source", style={'fontSize': '10px', 'color': 'var(--text-muted)', 'fontWeight': '600',
                                            'marginRight': '10px', 'whiteSpace': 'nowrap', 'flexShrink': '0',
                                            'width': '38px'}),
                dcc.RadioItems(
                    id='bf-data-source',
                    options=[{'label': ' Local', 'value': 'local'}, {'label': ' Wind', 'value': 'wind'}],
                    value='local',
                    labelStyle=_radio_style, inputStyle=_radio_input,
                    style={'display': 'flex', 'flexDirection': 'row'},
                ),
            ], style={'display': 'flex', 'flexDirection': 'row', 'alignItems': 'center', 'marginBottom': '5px'}),

            html.Div([
                html.Label("Mode", style={'fontSize': '10px', 'color': 'var(--text-muted)', 'fontWeight': '600',
                                          'marginRight': '10px', 'whiteSpace': 'nowrap', 'flexShrink': '0',
                                          'width': '38px'}),
                dcc.RadioItems(
                    id='bf-trading-mode',
                    options=[{'label': ' Daily', 'value': 'daily'}, {'label': ' Intraday', 'value': 'intraday'}],
                    value='daily',
                    labelStyle=_radio_style, inputStyle=_radio_input,
                    style={'display': 'flex', 'flexDirection': 'row'},
                ),
            ], style={'display': 'flex', 'flexDirection': 'row', 'alignItems': 'center'}),
        ]),

        # ── Symbol ────────────────────────────────────────────────────
        html.Div(id='bf-wind-inputs', children=[
            html.Label("Symbol", style=LABEL_STYLE),
            dcc.Dropdown(id='bf-wind-code', placeholder="Select symbol",
                         style={'fontSize': '11px'}),
        ]),

        html.Div(id='bf-local-inputs', children=[
            html.Label("Symbol", style=LABEL_STYLE),
            dcc.Dropdown(id='bf-local-symbol', options=pkl_options, placeholder="Select symbol",
                         style={'fontSize': '11px'}),
        ], style={'display': 'none'}),

        html.Div(id='bf-timeframe-container', children=[
            html.Label("Timeframe", style=LABEL_STYLE),
            dcc.Dropdown(
                id='bf-timeframe',
                options=[
                    {'label': '1 Min', 'value': '1T'}, {'label': '5 Min',  'value': '5T'},
                    {'label': '15 Min','value': '15T'}, {'label': '30 Min', 'value': '30T'},
                    {'label': '1 Hour','value': '1H'},
                ],
                value='5T', style={'fontSize': '11px'},
            ),
        ]),

        # ── Date Range ────────────────────────────────────────────────
        html.Div([
            html.Label("Date Range", style=LABEL_STYLE),
            dcc.DatePickerRange(
                id='bf-date-range',
                start_date=(datetime.now() - timedelta(days=30)).date(),
                end_date=datetime.now().date(),
                display_format='YYYY-MM-DD',
                style={'fontSize': '9px', 'width': '100%'},
                with_portal=True, day_size=34,
            ),
        ]),

        # ── Strategies ────────────────────────────────────────────────
        html.Div([
            html.Div("Strategies", style={
                'color': 'var(--accent-blue)', 'fontSize': '9px', 'fontWeight': '600',
                'textTransform': 'uppercase', 'letterSpacing': '0.08em', 'marginBottom': '6px',
            }),
            dcc.Checklist(
                id='bf-strategy-selector',
                options=[
                    {'label': ' MA',           'value': 'MA'},
                    {'label': ' DeMark',       'value': 'DeMark'},
                    {'label': ' Bollinger',    'value': 'Boll'},
                    {'label': ' VWAP',         'value': 'VWAP'},
                    {'label': ' Momentum',     'value': 'Momentum'},
                    {'label': ' ATR',          'value': 'ATR'},
                    {'label': ' SAR',          'value': 'SAR'},
                ],
                value=['MA', 'Boll', 'SAR'],
                labelStyle={'fontSize': '10px', 'color': 'var(--text-muted)', 'cursor': 'pointer',
                            'display': 'flex', 'alignItems': 'center'},
                inputStyle={"marginRight": "5px", "cursor": 'pointer', "flexShrink": "0"},
                style={'display': 'grid', 'gridTemplateColumns': '1fr 1fr', 'gap': '5px 8px'},
            ),
        ]),

        # ── Costs ─────────────────────────────────────────────────────
        html.Div([
            html.Div("Costs", style={
                'color': 'var(--accent-blue)', 'fontSize': '9px', 'fontWeight': '600',
                'textTransform': 'uppercase', 'letterSpacing': '0.08em', 'marginBottom': '6px',
            }),
            html.Div([
                html.Label("bp / side", title=(
                    "Half-spread + exchange fee per side, bp of notional. Blank = measured default "
                    "for the product (AU 0.4, TL 0.5, IC 1.9, else 1.0)."),
                    style={'fontSize': '10px', 'color': 'var(--text-muted)', 'fontWeight': '600',
                           'marginRight': '10px', 'whiteSpace': 'nowrap', 'flexShrink': '0'}),
                dcc.Input(id='bf-cost-bp', type='number', min=0, step=0.1, placeholder='auto', style=_inp),
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '5px'}),
            dcc.Checklist(
                id='bf-legacy',
                options=[{'label': ' Legacy (no cost, held overnight)', 'value': 'legacy'}], value=[],
                labelStyle={'fontSize': '10px', 'color': 'var(--text-muted)', 'cursor': 'pointer'},
                inputStyle={"marginRight": "5px", "cursor": 'pointer'},
            ),
        ]),

        # ── Buttons ───────────────────────────────────────────────────
        html.Button("▶ Run Backtest", id='bf-run-button', style={
            'width': '100%', 'padding': '7px',
            'fontSize': '11px', 'fontWeight': '700',
            'letterSpacing': '0.04em',
            'background': 'var(--positive, #2f9d6b)',
            'color': '#04261a', 'border': 'none',
            'borderRadius': '4px', 'cursor': 'pointer',
        }),
        html.Button("💾 Save Params & Best", id='bf-save-button', title=(
            "Save the current parameters and the best strategy (highest Sharpe) of the last run "
            "for this product; the chart then opens on that strategy."), style={
            'width': '100%', 'padding': '6px',
            'fontSize': '10px', 'fontWeight': '600',
            'background': 'var(--surface-input)',
            'color': 'var(--text-secondary)', 'border': '1px solid var(--border-default)',
            'borderRadius': '4px', 'cursor': 'pointer',
        }),
        html.Div(id='bf-saved-note', style={'fontSize': '9px', 'color': 'var(--text-muted)', 'lineHeight': '1.4'}),
        dcc.Store(id='bf-last-run'),

        ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '10px', 'minWidth': '0'}),
        params_column,
        ], style={'padding': '12px 14px', 'display': 'grid',
                  'gridTemplateColumns': 'minmax(0, 1fr) minmax(0, 1fr)', 'gap': '16px'}),

    ], style={
        'width': '440px', 'flexShrink': '0',
        'border': '1px solid var(--border-strong)',
        'borderRadius': '8px',
        'overflow': 'hidden',
    })

    # Evidence: multi-contract walk-forward; click a candidate to chart it in Backtest Results
    _btn = {'padding': '3px 10px', 'fontSize': '10px', 'fontWeight': '600',
            'background': 'var(--surface-input)', 'color': 'var(--text-secondary)',
            'border': '1px solid var(--border-default)', 'borderRadius': '4px', 'cursor': 'pointer'}
    _badge = {'fontSize': '9px', 'color': 'var(--text-muted)', 'background': 'var(--surface-input)',
              'padding': '2px 7px', 'borderRadius': '3px', 'border': '1px solid var(--border-default)'}
    _head = {'display': 'flex', 'alignItems': 'center', 'gap': '10px', 'padding': '9px 12px 9px 16px',
             'background': 'var(--surface-panel)', 'borderBottom': '1px solid var(--border-strong)',
             'borderRadius': '8px 8px 0 0'}
    _title = {'fontSize': '13px', 'fontWeight': '600', 'color': 'var(--text-primary)'}
    wf_card = html.Div([
        html.Div([
            html.Span("Walk-forward & Approval", style=_title),
            html.Span("all contracts · default params · net of costs · flat at close", style=_badge),
            html.Button("▶ Run walk-forward", id='bf-wf-run', n_clicks=0, title=(
                "Evaluate 7 strategies x 3 bar sizes on every stored contract of this product (intraday mode)."),
                style={**_btn, 'marginLeft': 'auto'}),
        ], style=_head),
        html.Div([
            html.Div(id='bf-wf-approved-note', style={'fontSize': '10px', 'color': 'var(--text-secondary)', 'marginBottom': '8px'}),
            dcc.Loading(type='circle', color='var(--accent-blue)', style={'minHeight': '60px'},
                        children=html.Div(id='bf-wf-container')),
            html.Div([
                dcc.Dropdown(id='bf-wf-pick', placeholder="Candidate to approve (only those passing the gates)",
                             clearable=False, style={'flex': 1, 'fontSize': '10px'}),
                html.Button("✔ Approve", id='bf-wf-approve', n_clicks=0, style=_btn),
            ], style={'display': 'flex', 'gap': '8px', 'alignItems': 'center', 'marginTop': '10px'}),
            html.Div(id='bf-wf-approve-note', style={'fontSize': '9px', 'color': 'var(--text-muted)', 'marginTop': '4px'}),
        ], style={'padding': '10px 16px 12px'}),
    ], style={'border': '1px solid var(--border-strong)', 'borderRadius': '8px', 'minWidth': '0', 'height': '100%',
              'boxSizing': 'border-box'})

    # One results card for whatever ran: a custom run (Run Backtest) or a candidate clicked in the walk-forward
    results_card = html.Div([
        html.Div([
            html.Span("Backtest Results", style=_title),
            html.Span(id='bf-results-symbol', style={**_badge, 'marginLeft': 'auto'}),
        ], style={**_head, 'padding': '11px 16px'}),
        dcc.Loading(
            type='circle', color='var(--accent-blue)', style={'minHeight': '400px'},
            children=html.Div([
                html.Div(id='bf-perf-results-container', style={'padding': '12px 16px 0'}),
                html.Div(id='bf-results-container', style={'padding': '12px 16px'}),
            ]),
        ),
        dcc.Store(id='bf-drill'),
    ], style={'border': '1px solid var(--border-strong)', 'borderRadius': '8px', 'minWidth': '0'})

    return html.Div([
        html.Div([
            html.H1("Futures Strategy Backtest", style={'margin': '0 0 3px', 'fontSize': '20px',
                                                       'fontWeight': '600', 'color': 'var(--text-primary)'}),
            html.Div("Walk-forward evidence · click a candidate to chart it · custom runs in Controls",
                    style={'fontSize': '11px', 'color': 'var(--text-muted)'}),
        ], style={'marginBottom': '12px'}),

        # Top row: Controls (+ parameters) | walk-forward evidence (stretched to the Controls height)
        html.Div([sidebar, wf_card],
                 style={'display': 'grid', 'gridTemplateColumns': '440px minmax(0, 1fr)',
                        'gap': '10px', 'alignItems': 'stretch'}),

        # Full-width results: metrics + chart
        results_card,
    ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '10px', 'padding': '16px', 'margin': '10px'})


def build_pool_correlation_card():
    """Heat map of the 5 least-correlated futures in the pool (daily continuous contracts)."""
    _radio_input = {"marginRight": "4px", "cursor": 'pointer'}
    # Pool correlation: the 5 least-correlated futures (daily, continuous contracts)
    _seg_label = {'fontSize': '10px', 'color': 'var(--text-muted)', 'cursor': 'pointer', 'marginRight': '8px'}
    corr_card = html.Div([
        html.Div([
            html.Span("Pool Correlation", style={'fontSize': '13px', 'fontWeight': '600', 'color': 'var(--text-primary)'}),
            html.Span("5 least correlated", id='bf-corr-badge', style={'fontSize': '9px', 'color': 'var(--text-muted)',
                     'background': 'var(--surface-input)', 'padding': '2px 7px', 'borderRadius': '3px',
                     'border': '1px solid var(--border-default)'}),
            html.Button("↻ Reload", id='bf-corr-refresh', title=(
                "Re-read the local daily data file and recompute (nothing is fetched)."), style={
                'marginLeft': 'auto', 'padding': '3px 9px', 'fontSize': '10px', 'fontWeight': '600',
                'background': 'var(--surface-input)', 'color': 'var(--text-secondary)',
                'border': '1px solid var(--border-default)', 'borderRadius': '4px', 'cursor': 'pointer',
            }),
        ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px',
                  'padding': '9px 12px 9px 16px', 'background': 'var(--surface-panel)',
                  'borderBottom': '1px solid var(--border-strong)'}),
        html.Div([
            html.Div([
                dcc.RadioItems(
                    id='bf-corr-basis',
                    options=[{'label': ' Returns', 'value': 'returns'}, {'label': ' Level', 'value': 'level'},
                             {'label': ' Strategy P&L', 'value': 'pnl'},
                             {'label': " Today's book", 'value': 'book'}],
                    value='returns', labelStyle=_seg_label, inputStyle=_radio_input,
                    style={'display': 'flex'},
                ),
                dcc.RadioItems(
                    id='bf-corr-lookback',
                    options=[{'label': f' {k}', 'value': k} for k in ('6M', '1Y', '3Y')],
                    value='1Y', labelStyle=_seg_label, inputStyle=_radio_input,
                    style={'display': 'flex', 'marginLeft': 'auto'},
                ),
            ], style={'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap', 'gap': '4px 12px'}),
            dcc.Loading(type='circle', color='var(--accent-blue)', children=[
                dcc.Graph(id='bf-corr-graph', config={'displayModeBar': False}, style={'height': '230px'}),
                html.Div(id='bf-corr-note', style={'fontSize': '9px', 'color': 'var(--text-muted)', 'lineHeight': '1.4'}),
            ]),
        ], style={'padding': '8px 12px 10px'}),
    ], style={'border': '1px solid var(--border-strong)', 'borderRadius': '8px', 'overflow': 'hidden'})
    return corr_card
