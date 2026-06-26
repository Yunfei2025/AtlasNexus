# -*- coding: utf-8 -*-
"""Backtest tab layouts: historical allocation, risk-factor backtest, futures backtest."""

from __future__ import annotations

from datetime import datetime, timedelta

from dash import dcc, html
import dash_bootstrap_components as dbc

from ..data import THEME, FUTURES_AVAILABLE, SELECTED_FACTOR_POOL
from ...atlas_components import button as an_button

# Conditionally import futures discovery helper
if FUTURES_AVAILABLE:
    from futures.backtest.data_loader import discover_pkl_files


def build_factor_history_layout():
    """Factor Explorer tab — sidebar controls + full-width history chart."""
    _lbl = {
        'color': 'var(--accent-blue)',
        'fontSize': '9px',
        'fontWeight': '600',
        'textTransform': 'uppercase',
        'letterSpacing': '0.08em',
        'marginBottom': '5px',
        'display': 'block',
    }
    dd_style = {'fontSize': '11px'}

    sidebar = html.Div([
        html.Div("FACTOR EXPLORER", style={
            'color': 'var(--text-primary)',
            'fontSize': '11px',
            'fontWeight': '700',
            'letterSpacing': '0.08em',
            'textTransform': 'uppercase',
        }),
        html.Div(
            "Browse the historical level of any risk factor. "
            "Select asset class → region → factor types.",
            style={'color': 'var(--text-muted)', 'fontSize': '10px', 'lineHeight': '1.5'},
        ),

        html.Div([
            html.Div("Asset Class", style=_lbl),
            dcc.Dropdown(
                id='factor-asset-class-selector',
                options=[
                    {'label': 'Rates',       'value': 'Rates'},
                    {'label': 'Spread',      'value': 'Spread'},
                    {'label': 'FX',          'value': 'FX'},
                    {'label': 'Commodities', 'value': 'Commodities'},
                    {'label': 'Equities',    'value': 'Equities'},
                ],
                value=None,
                placeholder="Select asset class…",
                clearable=True,
                style=dd_style,
            ),
        ]),

        html.Div([
            html.Div("Region / Type", style=_lbl),
            dcc.Dropdown(
                id='factor-region-selector',
                options=[],
                value=None,
                placeholder="Select region…",
                clearable=True,
                style=dd_style,
            ),
        ]),

        html.Div([
            html.Div("Factor(s)", style=_lbl),
            dcc.Dropdown(
                id='factor-type-selector',
                options=[],
                value=[],
                multi=True,
                placeholder="Select factors…",
                style=dd_style,
            ),
        ]),

        html.Div([
            html.Div(
                "Factor naming convention:\n"
                "IRDL = Level · IRSL = Slope · IRCV = Curvature\n"
                "FXDL = FX spot · CMDL = Commodity · EQDL = Equity",
                style={'color': 'var(--text-muted)', 'fontSize': '9px',
                       'whiteSpace': 'pre-line', 'lineHeight': '1.6'},
            ),
        ], style={'borderTop': '1px solid var(--border-default)', 'paddingTop': '10px'}),

    ], style={
        'width': '200px',
        'flexShrink': '0',
        'background': 'var(--surface-panel)',
        'border': '1px solid var(--border-strong)',
        'borderRadius': '8px',
        'padding': '14px',
        'display': 'flex',
        'flexDirection': 'column',
        'gap': '14px',
    })

    chart_area = html.Div([
        html.Div(
            "Historical Performance",
            style={
                'color': 'var(--text-muted)',
                'fontSize': '9px',
                'fontWeight': '600',
                'textTransform': 'uppercase',
                'letterSpacing': '0.08em',
            },
        ),
        dcc.Graph(
            id='factor-history-chart',
            config={'displayModeBar': True},
            style={'height': '580px'},
        ),
    ], style={'flex': '1', 'minWidth': '0', 'display': 'flex', 'flexDirection': 'column', 'gap': '12px'})

    return html.Div([
        sidebar,
        chart_area,
    ], style={
        'display': 'flex',
        'gap': '16px',
        'alignItems': 'start',
        'padding': '16px',
        'margin': '10px',
        'minHeight': '640px',
    })


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
        # ── Three-Card Horizontal Grid (Strategy / Parameters / Actions) ───
        html.Div([
            # STRATEGY OVERVIEW — LEFT (fixed width ~280-320px)
            html.Div([
                html.H2("Strategy", style={**_hdr, 'fontSize': '12px'}),
                html.Div([
                    html.Div([
                        html.Div("Factor Pool", style={'fontSize': '9px', 'fontWeight': '600',
                                                       'textTransform': 'uppercase', 'color': 'var(--text-muted)',
                                                       'marginBottom': '4px'}),
                        html.Div(id='backtest-strategy-factor-pool',
                                children="6 factors: IRDL.CN, IRSL.CN, IRCV.CN, FXDL.USDCNY, CMDL.AU, CMDL.CU",
                                style={'fontSize': '11px', 'color': 'var(--text-primary)', 'lineHeight': '1.4'}),
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
            ], style={**_card, 'minWidth': '280px', 'maxWidth': '320px', 'marginBottom': '0'}),

            # PARAMETERS — MIDDLE (flexible, ~500-700px)
            html.Div([
                html.H2("Parameters", style=_hdr),

                # 4-column grid for lookback, capital, correlation, top pairs
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
                    ]),

                    html.Div([
                        html.Label("Capital", style=_lbl),
                        dcc.Input(
                            id='backtest-capital-input',
                            type='number',
                            value=10,
                            style={**_inp, 'MozAppearance': 'textfield', 'appearance': 'textfield'}
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

                    html.Div([
                        html.Label("Top Low-Corr Pairs", style=_lbl),
                        dcc.Input(
                            id='backtest-top-pairs',
                            type='number',
                            value=10, min=5, max=20,
                            style={**_inp, 'MozAppearance': 'textfield', 'appearance': 'textfield'}
                        ),
                    ]),
                ], style={'display': 'grid', 'gridTemplateColumns': 'repeat(auto-fit, minmax(140px, 1fr))',
                          'gap': '10px', 'marginBottom': '12px'}),

                # Date Mode + Allocation Mode segmented controls (two columns)
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
                ], style={'display': 'grid', 'gridTemplateColumns': '1fr 1fr', 'gap': '10px'}),

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
                ], id='backtest-period-container', style={'display': 'none', 'marginTop': '12px'}),
            ], style={**_card, 'minWidth': '500px', 'maxWidth': '700px', 'marginBottom': '0', 'flex': '1'}),

            # ACTIONS — RIGHT (fixed width ~140-180px, stacked buttons)
            html.Div([
                html.H2("Actions", style={**_hdr, 'fontSize': '12px'}),
                html.Div([
                    an_button(
                        "▶ Run Historical Analysis", id='run-history-button', n_clicks=0,
                        variant="success", style_overrides={'padding': '10px 12px', 'fontSize': '11px', 'width': '100%'},
                    ),
                    an_button(
                        "📄 Generate Report", id='gen-report-button', n_clicks=0,
                        variant="secondary", style_overrides={'padding': '10px 12px', 'fontSize': '11px', 'width': '100%'},
                    ),
                    an_button(
                        "⬇️ Download Report", id='dl-report-button', n_clicks=0, disabled=True,
                        variant="success", style_overrides={'padding': '10px 12px', 'fontSize': '11px', 'width': '100%'},
                    ),
                ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '10px'}),
                html.Div(id='report-status-message', style={'marginTop': '10px', 'fontSize': '13px'}),
            ], style={**_card, 'minWidth': '140px', 'marginBottom': '0', 'display': 'flex',
                      'flexDirection': 'column', 'justifyContent': 'flex-start'}),
        ], style={'display': 'grid', 'gridTemplateColumns': 'auto 1fr auto', 'gap': '16px',
                  'alignItems': 'start', 'marginBottom': '20px', 'maxWidth': '1400px'}),

        # ── Metrics Display ─────────────────────────────────────────────
        html.Div(id='performance-metrics-container',
                 style={'marginTop': '15px', 'marginBottom': '15px'}),

        # ── Results ─────────────────────────────────────────────────────
        dcc.Loading(
            id="loading-history",
            type="circle",
            color=THEME['accent'],
            children=[
                dcc.Graph(id='historical-allocation-chart'),
                html.Div(style={'height': '20px'}),
                dcc.Graph(id='pnl-attribution-chart'),
                html.Div(style={'height': '20px'}),
                # Asset Pool Changes Section
                html.Div(id='asset-changes-container')
            ]
        ),

        # ── Section 4: Monthly Report ───────────────────────────────────
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
        ], id='report-commentary-container', style={**_card, 'display': 'none'}),

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

    return html.Div([
        # ── Factor Selection + Strategy Parameters — two-card grid ──────
        html.Div([
            # Factor Selection — LEFT
            html.Div([
                html.H2("Factor Selection", style=_hdr),

                html.Div([
                    html.Label("Asset Class:", style=_lbl),
                    dcc.Dropdown(
                        id='rfbt-asset-class',
                        options=[
                            {'label': 'Rates',       'value': 'Rates'},
                            {'label': 'Spread',      'value': 'Spread'},
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
            ], style={**_card, 'minWidth': '280px', 'maxWidth': '320px'}),

            # Strategy Parameters — RIGHT
            html.Div([
                html.H2("Strategy Parameters", style=_hdr),
                html.Div(id='rfbt-fm-params', children=[
                    html.Div([
                        html.Label("Train window (months):", style=_lbl),
                        dcc.Input(id='rfbt-fm-train', type='number', value=12, min=3,
                                  style={**_inp, 'MozAppearance': 'textfield', 'appearance': 'textfield'}),
                    ]),
                    html.Div([
                        html.Label("IC threshold:", style=_lbl),
                        dcc.Input(id='rfbt-fm-ic', type='number', value=0.05, step=0.01, min=0.01,
                                  style={**_inp, 'MozAppearance': 'textfield', 'appearance': 'textfield'}),
                    ]),
                    html.Div([
                        html.Label("Top N features:", style=_lbl),
                        dcc.Input(id='rfbt-fm-topn', type='number', value=8, min=1,
                                  style={**_inp, 'MozAppearance': 'textfield', 'appearance': 'textfield'}),
                    ]),
                    html.Div([
                        html.Label("Sizing:", style=_lbl),
                        dcc.Dropdown(
                            id='rfbt-fm-sizing',
                            options=[
                                {'label': 'Discrete 5-level', 'value': 'discrete'},
                                {'label': 'Continuous',       'value': 'continuous'},
                            ],
                            value='discrete',
                            clearable=False,
                            style={'fontSize': '13px'},
                        ),
                    ]),
                    html.Div([
                        html.Label("Smooth window (days):", style=_lbl),
                        dcc.Input(id='rfbt-fm-possmooth', type='number', value=10, min=1,
                                  style={**_inp, 'MozAppearance': 'textfield', 'appearance': 'textfield'}),
                    ]),
                    html.Div([
                        html.Label("Lookback:", style=_lbl),
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
                    ]),
                    html.Div([
                        html.Label("Start Date (optional):", style=_lbl),
                        dcc.DatePickerSingle(
                            id='rfbt-custom-start',
                            placeholder='override start…',
                            clearable=True,
                            display_format='YYYY-MM-DD',
                            style={'fontSize': '12px'},
                        ),
                    ], style={'minWidth': '160px'}),
                    html.Div([
                        html.Label("End Date (optional):", style=_lbl),
                        dcc.DatePickerSingle(
                            id='rfbt-custom-end',
                            placeholder='override end…',
                            clearable=True,
                            display_format='YYYY-MM-DD',
                            style={'fontSize': '12px'},
                        ),
                    ], style={'minWidth': '160px'}),
                ], className='strategy-params-grid', style={'marginBottom': '12px'}),

                an_button(
                    "▶ Run Backtest & Save",
                    id='rfbt-run-btn', n_clicks=0,
                    variant="success",
                    title="Trains selected factors and incrementally merges them into "
                          "the .joblib model file. Previously trained factors are preserved.",
                    style_overrides={'padding': '9px 18px', 'fontSize': '13px'},
                ),
            ], style={**_card, 'flex': '1', 'minWidth': '0'}),
        ], style={'display': 'grid', 'gridTemplateColumns': 'auto 1fr', 'gap': '16px',
                  'alignItems': 'start', 'marginBottom': '20px'}),

        # ── Results ─────────────────────────────────────────────────────
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

    ], style={'padding': '10px'})


def build_factor_backtest_layout():
    """Build the layout for the Futures/Factor Backtest tab - uses futures.backtest.layout."""
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
            'MozAppearance': 'textfield', 'WebkitAppearance': 'none', 'appearance': 'textfield'}

    sidebar = html.Div([
        html.Div([
            html.Span("Strategy Config", style={
                'color': 'var(--text-primary)',
                'fontSize': '11px',
                'fontWeight': '600',
            }),
        ], style={'padding': '10px 14px', 'borderBottom': '1px solid var(--border-strong)'}),

        # ── Data Settings ──────────────────────────────────────────────
        html.Div([
        html.Div("Data Settings", style={
            'color': 'var(--accent-blue)', 'fontSize': '9px', 'fontWeight': '600',
            'textTransform': 'uppercase', 'letterSpacing': '0.08em', 'marginBottom': '8px',
        }),

        html.Div([
            html.Label("Source", style={'fontSize': '10px', 'color': 'var(--text-muted)', 'fontWeight': '600',
                                        'marginRight': '10px', 'whiteSpace': 'nowrap', 'flexShrink': '0'}),
            dcc.RadioItems(
                id='bf-data-source',
                options=[{'label': ' Local', 'value': 'local'}, {'label': ' Wind', 'value': 'wind'}],
                value='local',
                labelStyle=_radio_style, inputStyle=_radio_input,
                style={'display': 'flex', 'flexDirection': 'row'},
            ),
        ], style={**_field_mb, 'display': 'flex', 'flexDirection': 'row', 'alignItems': 'center'}),

        html.Div([
            html.Label("Mode", style={'fontSize': '10px', 'color': 'var(--text-muted)', 'fontWeight': '600',
                                      'marginRight': '10px', 'whiteSpace': 'nowrap', 'flexShrink': '0'}),
            dcc.RadioItems(
                id='bf-trading-mode',
                options=[{'label': ' Daily', 'value': 'daily'}, {'label': ' Intraday', 'value': 'intraday'}],
                value='daily',
                labelStyle=_radio_style, inputStyle=_radio_input,
                style={'display': 'flex', 'flexDirection': 'row'},
            ),
        ], style={**_field_mb, 'display': 'flex', 'flexDirection': 'row', 'alignItems': 'center'}),

        html.Div(id='bf-wind-inputs', children=[
            html.Label("Wind Symbol", style=LABEL_STYLE),
            dcc.Dropdown(id='bf-wind-code', placeholder="Select symbol",
                         style={'fontSize': '11px'}),
        ], style=_field_mb),

        html.Div(id='bf-local-inputs', children=[
            html.Label("Local Symbol", style=LABEL_STYLE),
            dcc.Dropdown(id='bf-local-symbol', options=pkl_options, placeholder="Select symbol",
                         style={'fontSize': '11px'}),
        ], style={'display': 'none', **_field_mb}),

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
        ], style=_field_mb),

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
        ], style=_field_mb),

        html.Div([
            html.Div([
                html.Label("OOS Split", style=LABEL_STYLE),
                dcc.DatePickerSingle(
                    id='bf-oos-split-date', date=datetime.now().date(),
                    display_format='YYYY-MM-DD',
                    style={'fontSize': '9px', 'width': '100%'},
                ),
            ], style={'flex': 1, 'paddingRight': '4px', 'position': 'relative', 'zIndex': '1001'}),
            html.Div([
                html.Label("In-sample", style=LABEL_STYLE),
                dcc.Dropdown(
                    id='bf-insample-lookback',
                    options=[{'label': '6 Mo','value': '6M'}, {'label': '1 Yr','value': '1Y'}, {'label': '2 Yr','value': '2Y'}],
                    value='1Y', clearable=False, style={'fontSize': '10px'},
                ),
            ], style={'flex': 1, 'paddingLeft': '4px'}),
        ], style={'display': 'flex'}),
        ], style={'padding': '12px 14px', 'borderBottom': '1px solid var(--border-default)'}),

        # ── Strategies ─────────────────────────────────────────────────
        html.Div([
        html.Div("Strategies", style={
            'color': 'var(--accent-blue)', 'fontSize': '9px', 'fontWeight': '600',
            'textTransform': 'uppercase', 'letterSpacing': '0.08em', 'marginBottom': '8px',
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
                {'label': ' Mkt Regime',   'value': 'MarketRegime'},
            ],
            value=['MA', 'Boll', 'SAR', 'MarketRegime'],
            labelStyle={'fontSize': '10px', 'color': 'var(--text-muted)', 'cursor': 'pointer',
                        'display': 'flex', 'alignItems': 'center'},
            inputStyle={"marginRight": "5px", "cursor": 'pointer', "flexShrink": "0"},
            style={'display': 'grid', 'gridTemplateColumns': '1fr 1fr', 'gap': '5px 10px'},
        ),
        ], style={'padding': '10px 14px', 'borderBottom': '1px solid var(--border-default)'}),

        # ── Regime Logic ───────────────────────────────────────────────
        html.Div([
        html.Div("Regime Logic", style={
            'color': 'var(--accent-blue)', 'fontSize': '9px', 'fontWeight': '600',
            'textTransform': 'uppercase', 'letterSpacing': '0.08em', 'marginBottom': '8px',
        }),
        html.Div([
            html.Div([
                html.Label("Trending", style=LABEL_STYLE),
                dcc.Dropdown(
                    id='bf-mr-trending-strategy',
                    options=[{'label': 'MA','value': 'MA'}, {'label': 'SAR','value': 'SAR'}, {'label': 'ATR','value': 'ATR'}],
                    value='SAR', style={'fontSize': '10px'},
                ),
            ], style={'flex': 1, 'paddingRight': '4px', 'minWidth': '0'}),
            html.Div([
                html.Label("Mean-Rev", style=LABEL_STYLE),
                dcc.Dropdown(
                    id='bf-mr-meanrev-strategy',
                    options=[{'label': 'Boll','value': 'Boll'}, {'label': 'VWAP','value': 'VWAP'}, {'label': 'ATR M-R','value': 'ATRMeanRev'}],
                    value='Boll', style={'fontSize': '10px'},
                ),
            ], style={'flex': 1, 'paddingLeft': '4px', 'minWidth': '0'}),
        ], style={'display': 'flex'}),
        ], style={'padding': '10px 14px', 'borderBottom': '1px solid var(--border-default)'}),

        # ── Parameters (collapsible per-strategy) ───────────────────────
        html.Div([
            html.Div("Parameters", style={
                'color': 'var(--accent-blue)', 'fontSize': '9px', 'fontWeight': '600',
                'textTransform': 'uppercase', 'letterSpacing': '0.08em', 'marginBottom': '8px',
            }),

            html.Details([
                html.Summary('MA'),
                html.Div([
                    html.Div([html.Label("Short", style=_param_lbl), dcc.Input(id='bf-ma-short', type='number', value=5,   min=2, style=_inp)], style={'flex': 1, 'marginRight': '4px'}),
                    html.Div([html.Label("Long",  style=_param_lbl), dcc.Input(id='bf-ma-long',  type='number', value=20, min=5, style=_inp)], style={'flex': 1, 'marginLeft':  '4px'}),
                ], style={'display': 'flex'}),
            ], className='param-group', open=True),

            html.Details([
                html.Summary('Bollinger'),
                html.Div([
                    html.Div([html.Label("Period", style=_param_lbl), dcc.Input(id='bf-boll-window', type='number', value=20,  style=_inp)], style={'flex': 1, 'marginRight': '4px'}),
                    html.Div([html.Label("StdDev", style=_param_lbl), dcc.Input(id='bf-boll-std',    type='number', value=1.0, step=0.1, style=_inp)], style={'flex': 1, 'marginLeft': '4px'}),
                ], style={'display': 'flex', 'marginBottom': '4px'}),
                dcc.Checklist(id='bf-boll-exit', options=[{'label': ' Exit@MA', 'value': 'exit'}], value=[],
                              labelStyle={'fontSize': '10px', 'color': 'var(--text-muted)'}),
            ], className='param-group'),

            html.Details([
                html.Summary('VWAP'),
                html.Div([html.Label("Window", style=_param_lbl), dcc.Input(id='bf-vwap-window', type='number', value=20, style=_inp)]),
            ], className='param-group'),

            html.Details([
                html.Summary('Momentum'),
                html.Div([html.Label("Lookback", style=_param_lbl), dcc.Input(id='bf-mom-window', type='number', value=14, style=_inp)]),
            ], className='param-group'),

            html.Details([
                html.Summary('ATR'),
                html.Div([
                    html.Div([html.Label("EMA", style=_param_lbl), dcc.Input(id='bf-atr-ema-window', type='number', value=11, style=_inp)], style={'flex': 1, 'marginRight': '4px'}),
                    html.Div([html.Label("Win", style=_param_lbl), dcc.Input(id='bf-atr-window',     type='number', value=14, style=_inp)], style={'flex': 1, 'marginLeft': '4px', 'marginRight': '4px'}),
                    html.Div([html.Label("Mult",style=_param_lbl), dcc.Input(id='bf-atr-mult',       type='number', value=2.0, step=0.1, style=_inp)], style={'flex': 1, 'marginLeft': '4px'}),
                ], style={'display': 'flex'}),
            ], className='param-group'),

            html.Details([
                html.Summary('SAR'),
                html.Div([
                    html.Div([html.Label("AF",  style=_param_lbl), dcc.Input(id='bf-sar-af',     type='number', value=0.02, step=0.01, style=_inp)], style={'flex': 1, 'marginRight': '4px'}),
                    html.Div([html.Label("Max", style=_param_lbl), dcc.Input(id='bf-sar-max-af', type='number', value=0.2,  step=0.01, style=_inp)], style={'flex': 1, 'marginLeft':  '4px'}),
                ], style={'display': 'flex'}),
            ], className='param-group'),

        ], style={'padding': '10px 14px', 'borderBottom': '1px solid var(--border-default)'}),

        # ── Run button ─────────────────────────────────────────────────
        html.Div([
            html.Button("Run Backtest", id='bf-run-button', style={
                'width': '100%', 'padding': '9px',
                'fontSize': '11px', 'fontWeight': '700',
                'letterSpacing': '0.04em',
                'background': 'var(--accent-blue)',
                'color': '#fff', 'border': 'none',
                'borderRadius': '5px', 'cursor': 'pointer',
            }),
        ], style={'padding': '12px 14px'}),

    ], style={
        'width': '220px', 'flexShrink': '0',
        'background': 'var(--surface-panel)',
        'border': '1px solid var(--border-strong)',
        'borderRadius': '8px',
        'overflow': 'hidden',
    })

    # Content area
    content = html.Div([
        dcc.Loading(
            id="bf-loading-results",
            type="circle",
            color='var(--accent-blue)',
            children=html.Div(id='bf-results-container', style={'minHeight': '400px'})
        )
    ], style={'flex': '1', 'minWidth': '0', 'background': 'var(--surface-panel)',
              'border': '1px solid var(--border-strong)', 'borderRadius': '8px',
              'padding': '14px 16px'})

    return html.Div([sidebar, content],
                    style={'display': 'flex', 'gap': '14px', 'alignItems': 'start',
                           'padding': '16px', 'margin': '10px'})
