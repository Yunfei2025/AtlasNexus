# -*- coding: utf-8 -*-
"""Layout builders for the Alpha Book tabs."""

from __future__ import annotations

from typing import Dict, List

from dash import dcc, html, dash_table

from .data import THEME, SPREAD_CATEGORIES


_BACKTEST_SPREAD_TYPE_OPTIONS = [
    {'label': 'Bond-Curve (Treasury)', 'value': 'TBondCurve'},
    {'label': 'Bond-Curve (Policybank)', 'value': 'CBondCurve'},
    {'label': 'Bond-Swap (Treasury)', 'value': 'TBondSwap'},
    {'label': 'Bond-Swap (Policybank)', 'value': 'CBondSwap'},
    {'label': 'Swap Spread', 'value': 'SwapSpread'},
    {'label': 'Tenor Spreads', 'value': 'TenorSpread'},
    {'label': 'Bond-Futures (IRR−Repo)', 'value': 'NetBasis'},
    {'label': 'Term Basis (Futures)', 'value': 'TermBasis'},
    {'label': 'Futures vs Swap (FYTM−IRS)', 'value': 'FuturesSwap'},
    {'label': 'PCA Spread', 'value': 'PCASpread'},
]


def build_diversified_trades_display(trades: List[Dict]) -> html.Div:
    """Build display for diversification suggestions."""
    if not trades or len(trades) == 0:
        return html.Div(
            "No diversification suggestions available. Run scan to generate them.",
            style={'color': THEME['text_sub'], 'fontSize': '12px', 'padding': '10px'}
        )

    type_counts = {}
    for trade in trades:
        t_type = trade.get('spread_type', 'Other')
        type_counts[t_type] = type_counts.get(t_type, 0) + 1

    summary_items = []
    for t_type, count in sorted(type_counts.items()):
        summary_items.append(
            html.Span(
                f"{count} {t_type}",
                style={
                    'backgroundColor': THEME['bg_input'],
                    'padding': '4px 10px',
                    'borderRadius': '3px',
                    'marginRight': '8px',
                    'fontSize': '11px',
                    'display': 'inline-block',
                    'marginBottom': '5px',
                }
            )
        )

    trade_items = []
    for i, trade in enumerate(trades[:10], 1):
        trade_id = trade.get('ID', 'N/A')
        spread_type = trade.get('spread_type', 'N/A')
        style = trade.get('style', 'N/A')
        direction = trade.get('direction', 'N/A')
        zscore = trade.get('Zscore', 0)
        score = trade.get('score', 0)

        dir_color = THEME['success'] if direction == 'BUY' else THEME['danger']

        trade_items.append(
            html.Div([
                html.Span(f"{i}. ", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginRight': '5px'}),
                html.Span(f"{trade_id}", style={'color': THEME['text_main'], 'fontWeight': 'bold', 'marginRight': '8px'}),
                html.Span(f"[{spread_type}]", style={'color': THEME['accent'], 'fontSize': '11px', 'marginRight': '8px'}),
                html.Span(f"{style}", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginRight': '8px'}),
                html.Span(f"{direction}", style={'color': dir_color, 'fontWeight': 'bold', 'fontSize': '11px', 'marginRight': '8px'}),
                html.Span(f"Z={zscore:.2f}", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginRight': '8px'}),
                html.Span(f"Score={score:.2f}", style={'color': THEME['success'] if score > 0 else THEME['text_sub'], 'fontSize': '11px'}),
            ], style={'marginBottom': '6px'})
        )

    return html.Div([
        html.P(
            f"Based on scan results, {len(trades)} trades are available for diversification:",
            style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginBottom': '10px'}
        ),
        html.Div(summary_items, style={'marginBottom': '12px'}),
        html.Div(
            trade_items,
            style={
                'backgroundColor': THEME['bg_input'],
                'padding': '10px',
                'borderRadius': '4px',
                'maxHeight': '250px',
                'overflowY': 'auto'
            }
        ),
    ])


def build_candidates_layout() -> html.Div:
    """Build the CANDIDATES subtab layout."""
    _label_style = {
        'color': THEME['text_sub'], 'fontSize': '11px', 'fontWeight': '600',
        'textTransform': 'uppercase', 'letterSpacing': '0.06em',
        'marginBottom': '8px', 'display': 'block',
    }
    return html.Div([
        html.H6("Alpha Candidates Scanner", style={'color': THEME['text_main'], 'marginBottom': '15px'}),
        html.P(
            "Scan for relative value opportunities across spread types. "
            "Filter by z-score deviation and check correlations before sizing.",
            style={'color': THEME['text_sub'], 'fontSize': '13px', 'marginBottom': '20px'}
        ),

        # ── 2a: Spread Categories panel — surface-raised ──────────────────
        html.Div([
            html.Div([
                html.Label("Spread Categories", style=_label_style),
                dcc.Checklist(
                    id='alpha-spread-categories',
                    options=[
                        {'label': ' Bond-Curve', 'value': 'Bond-Curve'},
                        {'label': ' Bond-Swap', 'value': 'Bond-Swap'},
                        {'label': ' Swap Spreads', 'value': 'Swap-Spread'},
                        {'label': ' Tenor Spreads', 'value': 'Tenor-Spread'},
                        {'label': ' Bond-Futures', 'value': 'Bond-Futures'},
                        {'label': ' Calendar Spreads', 'value': 'Futures-Term'},
                        {'label': ' Futures-Swap', 'value': 'Futures-Swap'},
                    ],
                    value=['Bond-Curve', 'Bond-Swap', 'Swap-Spread', 'Tenor-Spread'],
                    inline=True,
                    inputStyle={'marginRight': '7px', 'accentColor': THEME['purple']},
                    labelStyle={'color': THEME['text_main'], 'marginRight': '22px', 'fontSize': '13px', 'cursor': 'pointer'},
                ),
            ], style={'flex': '1'}),
        ], style={'background': THEME['bg_raised'], 'border': f"1px solid {THEME['border']}",
                  'borderRadius': '8px', 'padding': '12px 22px', 'marginBottom': '15px'}),

        # ── 2b: Z-Score + Direction — unified panel ────────────────────────
        html.Div([
            html.Div([
                html.Label("Z-Score Threshold (MR candidates only)", style=_label_style),
                dcc.Slider(
                    id='alpha-zscore-threshold',
                    min=1.0, max=3.5, step=0.25, value=2.0,
                    marks={i: f'{i:.1f}σ' for i in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5]},
                    tooltip={'placement': 'bottom', 'always_visible': False},
                ),
            ], style={'flex': '1', 'paddingRight': '22px', 'borderRight': f"1px solid {THEME['border']}"}),

            html.Div([
                html.Label("Direction", style=_label_style),
                dcc.RadioItems(
                    id='alpha-direction-filter',
                    options=[
                        {'label': ' All', 'value': 'all'},
                        {'label': ' BUY (z < -thd)', 'value': 'buy'},
                        {'label': ' SELL (z > +thd)', 'value': 'sell'},
                    ],
                    value='all',
                    inputStyle={'marginRight': '7px', 'accentColor': THEME['purple']},
                    labelStyle={'color': THEME['text_main'], 'display': 'block', 'marginBottom': '5px', 'fontSize': '13px', 'cursor': 'pointer'},
                ),
            ], style={'width': '260px', 'paddingLeft': '22px', 'flexShrink': '0'}),
        ], style={'display': 'flex', 'alignItems': 'flex-start', 'background': THEME['bg_raised'],
                  'border': f"1px solid {THEME['border']}", 'borderRadius': '8px',
                  'padding': '12px 22px', 'marginBottom': '15px'}),

        # ── 2c: Seasonal Gate — collapsible <details> ──────────────────────
        html.Details([
            html.Summary([
                dcc.Checklist(
                    id='seasonal-prefilter-toggle',
                    options=[{'label': ' Apply seasonal gate before scan (exclude noise months)', 'value': 'on'}],
                    value=[],
                    inputStyle={'marginRight': '6px', 'accentColor': THEME['purple']},
                    labelStyle={'color': THEME['text_main'], 'fontSize': '14px', 'fontWeight': '600', 'cursor': 'pointer'},
                ),
                html.Span("▾ expand", style={'fontSize': '11px', 'color': THEME['text_sub'], 'marginLeft': 'auto'}),
            ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px', 'listStyle': 'none',
                      'padding': '11px 22px', 'cursor': 'pointer'}),

            html.Div([
                html.P(
                    "When ON: instruments whose current-month seasonality is statistically weak "
                    "(low consistency or high p-value) are excluded from scan results.",
                    style={'fontStyle': 'italic', 'fontSize': '12px', 'color': THEME['text_sub'], 'marginTop': '4px'},
                ),
                html.Div([
                    html.Div([
                        html.Label("Min consistency (%)", style=_label_style),
                        dcc.Slider(
                            id='seasonal-prefilter-min-consistency',
                            min=50, max=100, step=5, value=75,
                            marks={v: f'{v}%' for v in [50, 60, 70, 80, 90, 100]},
                            tooltip={'placement': 'bottom', 'always_visible': False},
                        ),
                    ], style={'flex': '1'}),
                    html.Div([
                        html.Label("p-value threshold", style=_label_style),
                        dcc.Dropdown(
                            id='seasonal-prefilter-p-thresh',
                            options=[
                                {'label': '0.05 (strict)', 'value': 0.05},
                                {'label': '0.10',           'value': 0.10},
                                {'label': '0.20 (loose)',   'value': 0.20},
                            ],
                            value=0.10,
                            clearable=False,
                            style={'width': '150px', 'fontSize': '12px'},
                        ),
                    ], style={'flexShrink': '0', 'width': '150px'}),
                ], style={'display': 'flex', 'gap': '20px', 'alignItems': 'flex-end'}),
            ], style={'padding': '4px 22px 14px', 'borderTop': f"1px solid {THEME['border_sub']}"}),
        ], className='seasonal-gate', style={
            'background': THEME['bg_raised'], 'border': f"1px solid {THEME['border']}",
            'borderRadius': '8px', 'overflow': 'hidden', 'marginBottom': '15px',
        }),

        # ── 2d: Scan button — amber accent ─────────────────────────────────
        html.Div([
            html.Button(
                "🔍 SCAN CANDIDATES",
                id='alpha-scan-btn', n_clicks=0,
                style={'background': THEME['accent'], 'color': '#0c0c00', 'padding': '10px 20px',
                       'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer',
                       'fontWeight': '700', 'fontSize': '12px', 'letterSpacing': '0.05em',
                       'marginRight': '15px'}
            ),
            html.Span(id='alpha-scan-status', style={'color': THEME['text_sub'], 'fontSize': '12px'}),
        ], style={'marginBottom': '20px'}),

        html.Div([
            html.H6("Candidates", style={'color': THEME['text_main'], 'marginBottom': '10px'}),
            dcc.Loading(
                id='loading-candidates', type='circle',
                color=THEME['accent'],
                style={'minHeight': '60px'},
                children=html.Div(id='alpha-candidates-table-container'),
            ),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '20px'}),

        html.Div([
            html.H6("Correlation Check", style={'color': THEME['text_main'], 'marginBottom': '10px'}),
            html.P("Verify selected candidates have low correlation before adding to basket.", style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginBottom': '15px'}),

            html.Div([
                html.Label("Lookback:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                dcc.Dropdown(
                    id='alpha-corr-lookback',
                    options=[
                        {'label': '3 Months', 'value': 63},
                        {'label': '6 Months', 'value': 126},
                        {'label': '1 Year', 'value': 252},
                        {'label': '2 Years', 'value': 504},
                    ],
                    value=252, clearable=False,
                    style={'width': '140px', 'marginRight': '20px'},
                ),
                html.Label("Max |Corr|:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                dcc.Dropdown(
                    id='alpha-max-corr',
                    options=[
                        {'label': '0.3', 'value': 0.3},
                        {'label': '0.4', 'value': 0.4},
                        {'label': '0.5', 'value': 0.5},
                        {'label': '0.6', 'value': 0.6},
                        {'label': '0.7', 'value': 0.7},
                    ],
                    value=0.5, clearable=False,
                    style={'width': '100px', 'marginRight': '20px'},
                ),
                html.Button(
                    "📊 Check Correlation",
                    id='alpha-corr-btn', n_clicks=0,
                    style={'backgroundColor': THEME['warning'], 'color': 'white', 'padding': '8px 15px', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer', 'fontWeight': 'bold'}
                ),
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '15px'}),

            dcc.Loading(
                id='loading-corr', type='circle',
                color=THEME['accent'],
                style={'minHeight': '60px'},
                children=html.Div(id='alpha-corr-results'),
            ),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px'}),

        dcc.Store(id='alpha-corr-pairs-store', data=[]),
        dcc.Store(id='alpha-corr-matrix-store', storage_type='memory', data={}),
        dcc.Store(id='alpha-curated-instruments-store', storage_type='memory', data=[]),
        dcc.Store(id='alpha-book-positions-store', storage_type='session', data=[]),
        dcc.Store(id='alpha-regime-store', storage_type='session', data={}),

    ], style={'padding': '10px'})


def build_portfolio_layout() -> html.Div:
    """Build the PORTFOLIO subtab layout."""
    return html.Div([
        html.Div([
            dcc.Input(id='alpha-mom-k', type='number', value=1.0, style={'display': 'none'}),
            dcc.Input(id='alpha-mom-window', type='number', value=20, style={'display': 'none'}),
            dcc.Input(id='alpha-alloc-method', type='text', value='risk_parity', style={'display': 'none'}),
            dcc.Checklist(id='alpha-enforce-corr', options=[], value=[], style={'display': 'none'}),
        ], style={'display': 'none'}),

        html.Div([
            html.H5("Step 1 — Instrument Selection & Correlation", style={'color': THEME['text_main'], 'marginBottom': '6px'}),
            html.P(
                "Run Check Correlation in the Candidates subtab first to populate the candidate list. "
                "Saved positions from alpha_book_positions.parquet are shown separately below. "
                "Both tables feed into the correlation matrix and portfolio optimisation.",
                style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '14px'},
            ),

            html.Div([
                html.Div([
                    html.Label("Spread Type", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '4px', 'display': 'block'}),
                    dcc.Dropdown(
                        id='alpha-add-spread-type',
                        options=[
                            {'label': stype, 'value': stype}
                            for cat_info in SPREAD_CATEGORIES.values()
                            for stype in cat_info['types']
                        ],
                        placeholder='Select type…', clearable=False,
                        style={'width': '170px', 'fontSize': '13px'},
                    ),
                ]),
                html.Div([
                    html.Label("Instrument", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '4px', 'display': 'block'}),
                    dcc.Dropdown(
                        id='alpha-add-instrument',
                        options=[], placeholder='Select instrument…', clearable=False,
                        style={'width': '210px', 'fontSize': '13px'},
                    ),
                ]),
                html.Button(
                    "+ Add Trade", id='alpha-add-trade-btn', n_clicks=0,
                    style={'backgroundColor': THEME['success'], 'color': 'white', 'border': 'none', 'borderRadius': '4px', 'padding': '6px 16px', 'cursor': 'pointer', 'fontWeight': '600', 'fontSize': '13px', 'alignSelf': 'flex-end'},
                ),
            ], style={'display': 'flex', 'gap': '12px', 'alignItems': 'flex-end', 'marginBottom': '14px', 'flexWrap': 'wrap'}),

            html.Div(id='alpha-curated-table-div'),
            html.Div(id='alpha-curated-corr-div', style={'marginTop': '16px'}),

            html.Div([
                html.Button(
                    "↻ Recalculate Correlation", id='alpha-curated-recalc-btn', n_clicks=0,
                    style={'backgroundColor': THEME['warning'], 'color': 'white', 'border': 'none', 'borderRadius': '4px', 'padding': '6px 16px', 'cursor': 'pointer', 'fontWeight': '600', 'fontSize': '13px'},
                ),
                html.Span(id='alpha-curated-recalc-status', style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginLeft': '12px'}),
            ], style={'marginTop': '14px', 'display': 'flex', 'alignItems': 'center'}),

        ], id='alpha-curated-panel',
           style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'marginBottom': '20px', 'borderRadius': '5px'}),

        html.Div([
            html.Div([
                html.H5("Step 2 — Configuration", style={'margin': '0', 'color': THEME['text_main']}),
            ], style={'flex': '1'}),

            html.Div([
                html.Label("Total Capital:", style={'fontWeight': 'bold', 'marginRight': '10px', 'fontSize': '14px', 'color': THEME['text_main']}),
                dcc.Input(
                    id='alpha-total-capital', type='number', value=10, min=1,
                    style={'width': '100px', 'marginRight': '5px', 'padding': '5px', 'borderRadius': '4px', 'border': f"1px solid {THEME['border']}", 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                ),
                html.Span("Billion CNY", style={'color': THEME['text_sub'], 'fontSize': '14px', 'marginRight': '20px'}),

                html.Label("Total Single Side DV01:", style={'fontWeight': 'bold', 'marginRight': '10px', 'fontSize': '14px', 'color': THEME['text_main']}),
                dcc.Input(
                    id='alpha-dv01-budget', type='number', value=5, min=0,
                    style={'width': '80px', 'marginRight': '5px', 'padding': '5px', 'borderRadius': '4px', 'border': f"1px solid {THEME['border']}", 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                ),
                html.Span("Million CNY", style={'color': THEME['text_sub'], 'fontSize': '14px', 'marginRight': '20px'}),

                html.Label("Method:", style={'fontWeight': 'bold', 'marginRight': '10px', 'fontSize': '14px', 'color': THEME['text_main']}),
                html.Span("Risk Parity", style={'color': THEME['accent'], 'fontSize': '14px', 'fontWeight': 'bold'}),
            ], style={'display': 'flex', 'alignItems': 'center'}),
        ], style={'display': 'flex', 'alignItems': 'center', 'padding': '15px 20px',
                  'backgroundColor': THEME['bg_input'],
                  'borderBottom': f'1px solid {THEME["table_header"]}',
                  'borderRadius': '8px 8px 0 0', 'marginBottom': '20px'}),

        html.Div([
            html.Div([
                html.H5("Step 3 — Portfolio Allocation Results", style={'color': THEME['text_main'], 'marginBottom': '15px', 'flex': '1'}),
                html.Div([
                    html.Button(
                        'RUN OPTIMIZATION', id='alpha-score-btn', n_clicks=0,
                        style={'backgroundColor': THEME['accent'], 'color': '#0c0c00', 'padding': '8px 20px', 'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer', 'fontSize': '13px', 'fontWeight': '700', 'letterSpacing': '0.05em'}
                    ),
                ], style={'marginLeft': '20px'})
            ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between'}),

            dcc.Store(id='alpha-optimized-weights', storage_type='session'),

            html.Div([
                html.Div(id='alpha-portfolio-summary', style={'color': THEME['text_sub'], 'fontSize': '11px'})
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '15px', 'justifyContent': 'flex-end'}),

            dcc.Loading(
                id='loading-portfolio', type='circle',
                color=THEME['accent'],
                style={'minHeight': '80px'},
                children=[
                    html.Div(id='alpha-scored-table-container'),
                    html.Div(id='alpha-risk-chart-container', style={'marginTop': '20px'}),
                ]
            )
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'marginBottom': '20px', 'borderRadius': '5px'}),

    ], style={'padding': '10px'})


def build_basket_layout() -> html.Div:
    """Build the BASKET subtab layout."""
    return html.Div([
        html.H6("Alpha Basket", style={'color': THEME['text_main'], 'marginBottom': '15px'}),
        html.P(
            "Final selected trades ready for execution. Review positions, adjust sizes, and export tickets.",
            style={'color': THEME['text_sub'], 'fontSize': '13px', 'marginBottom': '20px'}
        ),

        html.Div([
            html.H6("Current Basket", style={'color': THEME['accent'], 'marginBottom': '10px'}),
            html.Div(id='alpha-basket-table-container', children=[
                html.P("No trades in basket. Optimize portfolio in the Portfolio tab and add to basket.",
                       style={'color': THEME['text_sub'], 'padding': '20px'})
            ]),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}),

        html.Div([
            html.Button("📋 Export to Clipboard", id='alpha-export-btn', n_clicks=0,
                        style={'backgroundColor': THEME['accent'], 'color': 'white', 'padding': '10px 20px', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer', 'marginRight': '10px'}),
            html.Button("🗑️ Clear Basket", id='alpha-clear-basket-btn', n_clicks=0,
                        style={'backgroundColor': THEME['danger'], 'color': 'white', 'padding': '10px 20px', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer'}),
        ], style={'marginBottom': '15px'}),

        dcc.Store(id='alpha-basket-store', data=[]),

    ], style={'padding': '10px'})


def build_backtest_layout() -> html.Div:
    """Build the BACKTEST subtab layout."""
    return html.Div([
        html.H6("Alpha Backtest", style={'color': THEME['text_main'], 'marginBottom': '15px'}),
        html.P(
            "Backtest individual spread trades or the full portfolio using historical data. "
            "Evaluate strategy performance with z-score (mean-reversion or momentum) or directional-change trend rules.",
            style={'color': THEME['text_sub'], 'fontSize': '13px', 'marginBottom': '20px'}
        ),

        dcc.Tabs(
            id='backtest-mode-tabs', value='individual',
            className='tab-container an-subtab',
            children=[
                dcc.Tab(label='Individual Spread', value='individual',
                        className='tab an-subtab', selected_className='tab an-subtab an-subtab--selected'),
                dcc.Tab(label='Portfolio', value='portfolio',
                        className='tab an-subtab', selected_className='tab an-subtab an-subtab--selected'),
            ],
            style={'marginBottom': '0px'},
        ),

        html.Div(id='backtest-mode-content'),

    ], style={'padding': '10px'})


def build_individual_backtest_panel() -> html.Div:
    """Build the individual spread backtest panel."""
    return html.Div([
        html.Div([
            html.H6("Spread Selection", style={'color': THEME['accent'], 'marginBottom': '15px'}),

            html.Div([
                html.Div([
                    html.Label("Spread Type:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginBottom': '5px', 'display': 'block'}),
                    dcc.Dropdown(
                        id='bt-spread-type',
                        options=_BACKTEST_SPREAD_TYPE_OPTIONS,
                        value='TBondCurve', clearable=False,
                        style={'width': '250px'},
                    ),
                ], style={'marginRight': '20px'}),

                html.Div([
                    html.Label("Instrument:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginBottom': '5px', 'display': 'block'}),
                    dcc.Dropdown(id='bt-instrument', options=[], placeholder="Select instrument...", style={'width': '250px'}),
                ], style={'marginRight': '20px'}),
            ], style={'display': 'flex', 'marginBottom': '15px'}),

            html.Div([
                html.Label("Trade Style:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginBottom': '5px', 'display': 'block'}),
                dcc.RadioItems(
                    id='bt-trade-style',
                    options=[
                        {'label': ' Mean-Reversion', 'value': 'mr'},
                        {'label': ' Trend (Directional-Change)', 'value': 'trend'},
                    ],
                    value='mr', inline=True,
                    labelStyle={'color': THEME['text_main'], 'marginRight': '15px'},
                ),
            ], id='bt-trade-style-div', style={'marginBottom': '5px', 'display': 'none'}),
            html.Div(id='bt-regime-badge', style={'marginBottom': '10px', 'minHeight': '22px'}),

            html.Div([
                html.Label("Min Holding (days):", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                dcc.Input(id='bt-min-hold', type='number', value=7, min=1, max=30, step=1,
                          style={'width': '80px', 'padding': '5px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'border': f"1px solid {THEME['border']}"}),
            ], style={'display': 'flex', 'alignItems': 'center', 'paddingTop': '10px', 'borderTop': f"1px solid {THEME['border_sub']}"}),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}),

        html.Div([
            html.H6("Strategy Parameters", style={'color': THEME['accent'], 'marginBottom': '15px'}),

            html.Div([
                html.Div([html.Label("Entry Z-Score:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}), dcc.Input(id='bt-entry-z', type='number', value=2.0, min=0.5, max=4.0, step=0.25, style={'width': '80px', 'marginRight': '30px', 'padding': '5px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'border': f"1px solid {THEME['border']}"})], style={'display': 'flex', 'alignItems': 'center'}),
                html.Div([html.Label("Exit Z-Score:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}), dcc.Input(id='bt-exit-z', type='number', value=0.5, min=0, max=2.0, step=0.25, style={'width': '80px', 'marginRight': '30px', 'padding': '5px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'border': f"1px solid {THEME['border']}"})], style={'display': 'flex', 'alignItems': 'center'}),
                html.Div([html.Label("Stop Loss (σ):", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}), dcc.Input(id='bt-stop-z', type='number', value=4.0, min=2.0, max=6.0, step=0.5, style={'width': '80px', 'marginRight': '30px', 'padding': '5px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'border': f"1px solid {THEME['border']}"})], style={'display': 'flex', 'alignItems': 'center'}),
            ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '15px', 'marginBottom': '15px'}),

            html.Div([
                html.Label("Backtest Period:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                dcc.Dropdown(id='bt-period', options=[{'label': '1 Year', 'value': 252}, {'label': '2 Years', 'value': 504}, {'label': '3 Years', 'value': 756}, {'label': '5 Years', 'value': 1260}], value=504, clearable=False, style={'width': '150px'}),
            ], style={'display': 'flex', 'alignItems': 'center'}),
        ], id='bt-mr-params-div', style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}),

        html.Div([
            html.H6("Trend Parameters (Directional-Change)", style={'color': THEME['accent'], 'marginBottom': '15px'}),
            html.Div([
                html.Div([html.Label("Theta", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'fontSize': '12px', 'marginBottom': '4px', 'display': 'block'}), dcc.Input(id='bt-theta', type='number', value=0.02, min=0.001, max=0.2, step=0.001, style={'width': '100%', 'padding': '5px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'border': f"1px solid {THEME['border']}", 'textAlign': 'right', 'fontFamily': 'monospace'})]),
                html.Div([html.Label("Mom window", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'fontSize': '12px', 'marginBottom': '4px', 'display': 'block'}), dcc.Input(id='bt-mom-window', type='number', value=20, min=5, max=120, step=1, style={'width': '100%', 'padding': '5px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'border': f"1px solid {THEME['border']}", 'textAlign': 'right', 'fontFamily': 'monospace'})]),
                html.Div([html.Label("Vol window", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'fontSize': '12px', 'marginBottom': '4px', 'display': 'block'}), dcc.Input(id='bt-vol-window', type='number', value=60, min=20, max=252, step=1, style={'width': '100%', 'padding': '5px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'border': f"1px solid {THEME['border']}", 'textAlign': 'right', 'fontFamily': 'monospace'})]),
                html.Div([html.Label("Trail mult", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'fontSize': '12px', 'marginBottom': '4px', 'display': 'block'}), dcc.Input(id='bt-trailing-mult', type='number', value=1.5, min=0.5, max=5.0, step=0.1, style={'width': '100%', 'padding': '5px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'border': f"1px solid {THEME['border']}", 'textAlign': 'right', 'fontFamily': 'monospace'})]),
                html.Div([html.Label("Momentum buffer", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'fontSize': '12px', 'marginBottom': '4px', 'display': 'block'}), dcc.Input(id='bt-carry-buffer', type='number', value=0.0, step=0.0001, style={'width': '100%', 'padding': '5px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'border': f"1px solid {THEME['border']}", 'textAlign': 'right', 'fontFamily': 'monospace'})]),
            ], className='alpha-trend-params'),

            html.Div([
                dcc.Checklist(id='bt-allow-short', options=[{'label': ' Allow short-spread trades', 'value': 'allow'}], value=['allow'], labelStyle={'color': THEME['text_main'], 'fontSize': '13px'}),
            ], style={'marginTop': '12px'}),
        ], id='bt-trend-params-div', style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px', 'display': 'none'}),

        html.Div([
            html.Button("▶ Run Individual Backtest", id='bt-run-individual-btn', n_clicks=0,
                        style={'backgroundColor': THEME['success'], 'color': '#fff', 'padding': '10px 24px', 'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer', 'fontWeight': '700', 'fontSize': '13px', 'letterSpacing': '0.03em'}),
        ], style={'marginBottom': '20px'}),

        dcc.Loading(id='loading-bt-individual', type='circle', color=THEME['accent'], style={'minHeight': '60px'}, children=html.Div([
            html.Span(id='bt-individual-status', style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginBottom': '8px', 'display': 'block'}),
            html.Div(id='bt-individual-results'),
        ])),
    ])


def build_portfolio_backtest_panel() -> html.Div:
    """Build the portfolio backtest panel."""
    return html.Div([
        html.Div([
            html.H6("Portfolio Data", style={'color': THEME['accent'], 'marginBottom': '10px'}),
            html.Div(id='bt-portfolio-data-preview', children=[
                html.P("No portfolio data loaded. Please go to the 'Portfolio' tab and run 'Calculate Score & Allocation' first.",
                       style={'color': THEME['warning'], 'fontStyle': 'italic'})
            ]),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}),

        html.Div([
            html.H6("Backtest Settings", style={'color': THEME['accent'], 'marginBottom': '15px'}),
            html.Div([
                html.Div([html.Label("Backtest Period:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}), dcc.Dropdown(id='bt-port-period', options=[{'label': '1 Year', 'value': 252}, {'label': '2 Years', 'value': 504}, {'label': '3 Years', 'value': 756}, {'label': '5 Years', 'value': 1260}], value=504, clearable=False, style={'width': '150px', 'marginRight': '30px'})], style={'display': 'flex', 'alignItems': 'center'}),
                html.Div([html.Label("Initial Capital (MM):", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}), dcc.Input(id='bt-initial-capital', type='number', value=100, min=10, max=1000, step=10, style={'width': '100px', 'marginRight': '30px', 'padding': '5px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'border': f"1px solid {THEME['border']}"})], style={'display': 'flex', 'alignItems': 'center'}),
                html.Div([html.Label("Transaction Cost (bp):", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}), dcc.Input(id='bt-txn-cost', type='number', value=0.5, min=0, max=5, step=0.1, style={'width': '80px', 'padding': '5px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'border': f"1px solid {THEME['border']}"})], style={'display': 'flex', 'alignItems': 'center'}),
            ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '15px'}),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}),

        html.Div([
            html.Button("▶ Run Portfolio Backtest", id='bt-run-portfolio-btn', n_clicks=0,
                        style={'backgroundColor': THEME['success'], 'color': '#fff', 'padding': '10px 24px', 'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer', 'fontWeight': '700', 'fontSize': '13px', 'letterSpacing': '0.03em'}),
        ], style={'marginBottom': '20px'}),

        dcc.Loading(id='loading-bt-portfolio', type='circle', color=THEME['accent'], style={'minHeight': '60px'}, children=html.Div([
            html.Span(id='bt-portfolio-status', style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginBottom': '8px', 'display': 'block'}),
            html.Div(id='bt-portfolio-results'),
        ])),
    ])
