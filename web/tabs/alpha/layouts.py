# -*- coding: utf-8 -*-
"""Layout builders for the Alpha Book tabs."""

from __future__ import annotations

from typing import Dict, List

from dash import dcc, html, dash_table

from .data import THEME, SPREAD_CATEGORIES
from ..ui.components import button as an_button


_BACKTEST_SPREAD_TYPE_OPTIONS = [
    {'label': 'Treasury Bond', 'value': 'TBondCurve'},
    {'label': 'Policybank Bond', 'value': 'CBondCurve'},
    {'label': 'Treasury BondSwap', 'value': 'TBondSwap'},
    {'label': 'Policybank BondSwap', 'value': 'CBondSwap'},
    {'label': 'New-Issue OTR/OFR Event', 'value': 'BondNewIssue'},
    {'label': 'Swaps', 'value': 'SwapSpread'},
    {'label': 'Curve & Cross-Asset Spreads', 'value': 'TenorSpread'},
    {'label': 'Cash-and-Carry', 'value': 'NetBasis'},
    {'label': 'Calendar Spread', 'value': 'TermBasis'},
    {'label': 'Futures Swap', 'value': 'FuturesSwap'},
    {'label': 'Sector PCA', 'value': 'SectorPCASpread'},
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


def _alpha_card_header(title: str, badge_text: str | None = None, action=None) -> html.Div:
    """Card header row — title + optional meta badge + optional right-aligned action."""
    children_left = [
        html.Span(title, style={'fontSize': '13px', 'fontWeight': '600', 'color': 'var(--text-primary)'}),
    ]
    if badge_text:
        children_left.append(html.Span(badge_text, style={
            'fontSize': '9px', 'color': 'var(--text-muted)', 'background': 'var(--surface-input)',
            'padding': '2px 7px', 'borderRadius': '3px', 'border': '1px solid var(--border-default)',
        }))
    return html.Div([
        html.Div(children_left, style={'display': 'flex', 'alignItems': 'center', 'gap': '10px'}),
        html.Div(action or [], style={'display': 'flex', 'alignItems': 'center', 'gap': '12px'}),
    ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between',
              'padding': '11px 16px', 'background': 'var(--surface-panel)',
              'borderBottom': '1px solid var(--border-strong)'})


def build_candidates_layout() -> html.Div:
    """Build the CANDIDATES subtab layout."""
    _label_style = {
        'color': THEME['text_sub'], 'fontSize': '10px', 'fontWeight': '600',
        'textTransform': 'uppercase', 'letterSpacing': '0.06em',
        'marginBottom': '8px', 'display': 'block',
    }
    _filter_panel = {
        'background': 'var(--surface-raised)', 'border': '1px solid var(--border-strong)',
        'borderRadius': '6px', 'padding': '12px 14px',
    }

    return html.Div([
        html.Div([
            html.H1("Alpha Candidates Scanner", style={
                'margin': '0 0 3px', 'fontSize': '20px', 'fontWeight': '600',
                'color': 'var(--text-primary)',
            }),
            html.Div(
                "Scan for relative value opportunities · filter by z-score · check correlation before sizing",
                style={'fontSize': '11px', 'color': 'var(--text-muted)'},
            ),
        ], style={'marginBottom': '4px'}),

        # ── Card 1: Filters ─────────────────────────────────────────────────
        html.Div([
            _alpha_card_header(
                "Filters", badge_text="Spread Categories · Direction · Z-Score",
                action=html.Button(
                    "🔍 Scan Candidates", id='alpha-scan-btn', n_clicks=0,
                    style={'padding': '5px 14px', 'background': 'var(--accent-amber)', 'color': 'var(--navy-950)',
                           'border': 'none', 'borderRadius': '4px', 'fontSize': '10px', 'fontWeight': '700',
                           'letterSpacing': '0.05em', 'cursor': 'pointer'},
                ),
            ),
            html.Div([
                # Spread Categories
                html.Div([
                    html.Label("Spread Categories", style={**_label_style, 'fontSize': '11px', 'marginBottom': '10px'}),
                    dcc.Checklist(
                        id='alpha-spread-categories',
                        options=[
                            {'label': ' Bond-Curve', 'value': 'Bond-Curve'},
                            {'label': ' Bond-Swap', 'value': 'Bond-Swap'},
                            {'label': ' Swap Spreads', 'value': 'Swap-Spread'},
                            {'label': ' Curve & Cross-Asset', 'value': 'Tenor-Spread'},
                            {'label': ' New-Issue Event', 'value': 'New-Issue'},
                            {'label': ' Bond-Futures', 'value': 'Bond-Futures'},
                            {'label': ' Calendar Spreads', 'value': 'Futures-Term'},
                            {'label': ' Futures-Swap', 'value': 'Futures-Swap'},
                        ],
                        value=['Bond-Curve', 'Bond-Swap', 'Swap-Spread', 'Tenor-Spread'],
                        inputStyle={'marginRight': '7px', 'accentColor': THEME['accent']},
                        labelStyle={'color': 'var(--text-primary)', 'fontSize': '13px', 'cursor': 'pointer'},
                        style={'display': 'grid', 'gridTemplateColumns': '1fr 1fr', 'gap': '6px 16px'},
                    ),
                ], style=_filter_panel),

                # Direction + Z-Score side by side
                html.Div([
                    html.Div([
                        html.Label("Direction", style=_label_style),
                        dcc.RadioItems(
                            id='alpha-direction-filter',
                            options=[
                                {'label': ' All', 'value': 'all'},
                                {'label': ' BUY candidates', 'value': 'buy'},
                                {'label': ' SELL candidates', 'value': 'sell'},
                            ],
                            value='all',
                            inputStyle={'marginRight': '7px', 'accentColor': THEME['accent']},
                            labelStyle={'color': 'var(--text-primary)', 'display': 'block', 'marginBottom': '6px',
                                        'fontSize': '11px', 'cursor': 'pointer'},
                        ),
                    ], style={'flex': '1', 'paddingRight': '20px', 'borderRight': '1px solid var(--border-strong)'}),

                    html.Div([
                        html.Label("Z-Score Threshold", style=_label_style),
                        dcc.Slider(
                            id='alpha-zscore-threshold',
                            min=1.0, max=3.5, step=0.25, value=2.0,
                            marks={i: f'{i:.1f}' for i in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5]},
                            tooltip={'placement': 'bottom', 'always_visible': False},
                        ),
                        html.P(
                            "Mean-reversion: BUY when z > +σ; SELL when z < −σ. Momentum/Carry uses MAD-normalized momentum hysteresis for intramonth entry and exit.",
                            style={'color': THEME['text_sub'], 'fontSize': '10px', 'fontStyle': 'italic', 'marginTop': '8px'},
                        ),
                    ], style={'flex': '1', 'paddingLeft': '20px'}),
                ], style={'display': 'flex', 'alignItems': 'flex-start', **_filter_panel}),
            ], style={'padding': '14px 16px', 'display': 'grid', 'gridTemplateColumns': '1fr 1fr', 'gap': '14px'}),

            # ── Seasonal Gate — collapsible <details> ──────────────────────
            html.Details([
                html.Summary([
                    dcc.Checklist(
                        id='seasonal-prefilter-toggle',
                        options=[{'label': ' Apply seasonal gate before scan (exclude noise months)', 'value': 'on'}],
                        value=[],
                        inputStyle={'marginRight': '6px', 'accentColor': THEME['accent']},
                        labelStyle={'color': 'var(--text-primary)', 'fontSize': '12px', 'fontWeight': '600', 'cursor': 'pointer'},
                    ),
                    html.Span("▾ expand", style={'fontSize': '10px', 'color': THEME['text_sub'], 'marginLeft': 'auto'}),
                ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px', 'listStyle': 'none',
                          'padding': '10px 16px', 'cursor': 'pointer'}),

                html.Div([
                    html.P(
                        "When ON: only trend/uncertain trades are pre-filtered. "
                        "Mean-reversion trades are not blocked by this seasonal gate.",
                        style={'fontStyle': 'italic', 'fontSize': '11px', 'color': THEME['text_sub'], 'marginTop': '4px'},
                    ),
                    html.Div([
                        html.Div([
                            html.Label("Min consistency (%)", style=_label_style),
                            dcc.Dropdown(
                                id='seasonal-prefilter-min-consistency',
                                options=[
                                    {'label': f'{v}%', 'value': v}
                                    for v in [50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]
                                ],
                                value=75,
                                clearable=False,
                                style={'minWidth': '180px', 'fontSize': '12px'},
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
                ], style={'padding': '4px 16px 14px', 'borderTop': '1px solid var(--border-default)'}),
            ], className='seasonal-gate', style={'borderTop': '1px solid var(--border-strong)'}),
        ], style={'border': '1px solid var(--border-strong)', 'borderRadius': '8px', 'overflow': 'hidden',
                  'marginBottom': '10px'}),

        html.Div(id='alpha-scan-status', style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '4px'}),

        # ── Card 2: Candidates & Correlation Check ──────────────────────────
        html.Div([
            _alpha_card_header("Candidates & Correlation Check"),
            html.Div([
                # Left: Candidates signals
                html.Div([
                    dcc.Loading(
                        id='loading-candidates', type='circle',
                        color=THEME['accent'],
                        style={'minHeight': '60px'},
                        children=html.Div(id='alpha-candidates-table-container'),
                    ),
                ], style={'flex': '1', 'minWidth': '0', 'padding': '14px 16px',
                          'borderRight': '1px solid var(--border-strong)'}),

                # Right: Correlation Check
                html.Div([
                    html.Div([
                        html.Div(
                            "Verify low correlation before sizing.",
                            style={'fontSize': '10px', 'color': THEME['text_sub'], 'marginBottom': '8px'},
                        ),
                        html.Div([
                            html.Div([
                                html.Span("Lookback:", style={'fontSize': '9px', 'color': THEME['text_sub'],
                                                               'whiteSpace': 'nowrap'}),
                                dcc.Dropdown(
                                    id='alpha-corr-lookback',
                                    options=[
                                        {'label': '3 Months', 'value': 63},
                                        {'label': '6 Months', 'value': 126},
                                        {'label': '1 Year', 'value': 252},
                                        {'label': '2 Years', 'value': 504},
                                    ],
                                    value=252, clearable=False,
                                    style={'width': '120px', 'fontSize': '11px'},
                                ),
                            ], style={'display': 'flex', 'alignItems': 'center', 'gap': '6px'}),
                            html.Div([
                                html.Span("Max |Corr|:", style={'fontSize': '9px', 'color': THEME['text_sub'],
                                                                 'whiteSpace': 'nowrap'}),
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
                                    style={'width': '80px', 'fontSize': '11px'},
                                ),
                            ], style={'display': 'flex', 'alignItems': 'center', 'gap': '6px'}),
                            html.Div([
                                html.Span("Candidates:", style={'fontSize': '9px', 'color': THEME['text_sub'],
                                                                 'whiteSpace': 'nowrap'}),
                                dcc.Input(
                                    id='alpha-corr-candidate-count',
                                    type='number',
                                    value=10,
                                    min=1,
                                    step=1,
                                    debounce=True,
                                    style={'width': '72px', 'fontSize': '11px'},
                                ),
                            ], style={'display': 'flex', 'alignItems': 'center', 'gap': '6px'}),
                            html.Button(
                                "📊 Check Correlation",
                                id='alpha-corr-btn', n_clicks=0,
                                style={'background': 'rgba(224,162,60,0.15)', 'color': THEME['accent'],
                                       'border': f"1px solid {THEME['accent']}", 'borderRadius': '4px',
                                       'fontSize': '10px', 'fontWeight': '700', 'padding': '5px 14px',
                                       'cursor': 'pointer'},
                            ),
                        ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px', 'flexWrap': 'wrap'}),
                    ], style={'padding': '10px 14px', 'background': 'rgba(255,255,255,0.02)',
                              'borderBottom': '1px solid var(--border-strong)'}),

                    dcc.Loading(
                        id='loading-corr', type='circle',
                        color=THEME['accent'],
                        style={'minHeight': '60px'},
                        children=html.Div(id='alpha-corr-results', style={'padding': '10px 14px'}),
                    ),
                ], style={'flex': '1', 'minWidth': '0', 'display': 'flex', 'flexDirection': 'column'}),
            ], style={'display': 'flex', 'alignItems': 'flex-start'}),
        ], style={'border': '1px solid var(--border-strong)', 'borderRadius': '8px', 'overflow': 'hidden'}),

        dcc.Store(id='alpha-corr-pairs-store', data=[]),
        dcc.Store(id='alpha-corr-matrix-store', storage_type='memory', data={}),
        dcc.Store(id='alpha-curated-instruments-store', storage_type='memory', data=[]),
        dcc.Store(id='alpha-book-positions-store', storage_type='memory', data=[]),
        dcc.Store(id='alpha-regime-store', storage_type='memory', data={}),

    ], style={'padding': '10px', 'display': 'flex', 'flexDirection': 'column', 'gap': '4px'})


def build_portfolio_layout() -> html.Div:
    """Build the PORTFOLIO subtab layout."""
    _label_style = {
        'color': THEME['text_sub'], 'fontSize': '9px', 'fontWeight': '600',
        'textTransform': 'uppercase', 'letterSpacing': '0.06em',
        'marginBottom': '4px', 'display': 'block',
    }

    return html.Div([
        html.Div([
            dcc.Input(id='alpha-mom-k', type='number', value=1.0, style={'display': 'none'}),
            dcc.Input(id='alpha-mom-window', type='number', value=20, style={'display': 'none'}),
            dcc.Input(id='alpha-alloc-method', type='text', value='risk_parity', style={'display': 'none'}),
            dcc.Checklist(id='alpha-enforce-corr', options=[], value=[], style={'display': 'none'}),
            dcc.Input(id='alpha-bond-margin-rate', type='number', value=5.0, style={'display': 'none'}),
            dcc.Input(id='alpha-swap-margin-rate', type='number', value=3.0, style={'display': 'none'}),
        ], style={'display': 'none'}),

        html.Div([
            html.H1("Alpha Book Portfolio", style={
                'margin': '0 0 3px', 'fontSize': '20px', 'fontWeight': '600',
                'color': 'var(--text-primary)',
            }),
            html.Div(
                "Instrument selection · portfolio configuration · optimised allocation",
                style={'fontSize': '11px', 'color': 'var(--text-muted)'},
            ),
        ], style={'marginBottom': '4px'}),

        # ── Card 1: Selection ────────────────────────────────────────────────
        html.Div([
            _alpha_card_header("Selection"),
            html.Div([
                html.P(
                    "Run Check Correlation in the Candidates subtab first to populate the candidate list. "
                    "Saved positions from alpha_book_positions.parquet are shown separately below. "
                    "Both tables feed into the correlation matrix and portfolio optimisation.",
                    style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '10px'}
                ),

                # Add trade row
                html.Div([
                    html.Div([
                        html.Label("Spread Type", style=_label_style),
                        dcc.Dropdown(
                            id='alpha-add-spread-type',
                            options=[
                                {'label': stype, 'value': stype}
                                for cat_info in SPREAD_CATEGORIES.values()
                                for stype in cat_info['types']
                            ],
                            placeholder='Select type…', clearable=False,
                            style={'width': '180px', 'fontSize': '11px'},
                        ),
                    ]),
                    html.Div([
                        html.Label("Instrument", style=_label_style),
                        dcc.Dropdown(
                            id='alpha-add-instrument',
                            options=[], placeholder='Select instrument…', clearable=False,
                            style={'width': '210px', 'fontSize': '11px'},
                        ),
                    ]),
                    html.Button(
                        "+ Add Trade", id='alpha-add-trade-btn', n_clicks=0,
                        style={'padding': '7px 14px', 'background': 'var(--accent-green)', 'color': 'var(--navy-950)',
                               'border': 'none', 'borderRadius': '4px', 'fontSize': '11px', 'fontWeight': '700',
                               'cursor': 'pointer', 'alignSelf': 'flex-end'},
                    ),
                ], style={'display': 'flex', 'gap': '10px', 'alignItems': 'flex-end', 'flexWrap': 'wrap'}),

                # Candidates + Saved (left, stacked) | Correlation matrix (right, fixed ~1/2 width)
                html.Div([
                    html.Div(id='alpha-curated-table-div', style={'flex': '1', 'minWidth': '0'}),
                    html.Div(id='alpha-curated-corr-div', style={'flex': '0 0 50%', 'minWidth': '300px'}),
                ], style={'display': 'flex', 'alignItems': 'flex-start', 'gap': '18px'}),

                html.Div([
                    html.Button(
                        "↻ Recalculate Correlation", id='alpha-curated-recalc-btn', n_clicks=0,
                        style={'padding': '7px 16px', 'background': THEME['accent'], 'color': 'var(--navy-950)',
                               'border': 'none', 'borderRadius': '4px', 'fontSize': '11px', 'fontWeight': '700',
                               'cursor': 'pointer'},
                    ),
                    html.Span(id='alpha-curated-recalc-status', style={'color': THEME['text_sub'], 'fontSize': '10px', 'marginLeft': '14px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),
            ], id='alpha-curated-panel', style={'padding': '14px 16px', 'display': 'flex', 'flexDirection': 'column', 'gap': '14px'}),
        ], style={'border': '1px solid var(--border-strong)', 'borderRadius': '8px', 'overflow': 'hidden'}),

        # ── Card 2: Portfolio Allocation Results ─────────────────────────────
        html.Div([
            _alpha_card_header(
                "Portfolio Allocation Results",
                action=html.Div([
                    html.Button(
                        "RUN ANALYSIS", id='alpha-score-btn', n_clicks=0,
                        style={'padding': '6px 16px', 'background': THEME['accent'], 'color': 'var(--navy-950)',
                               'border': 'none', 'borderRadius': '4px', 'fontSize': '11px', 'fontWeight': '700',
                               'letterSpacing': '0.04em', 'cursor': 'pointer'},
                    ),
                    html.Button(
                        "ADD TO PORTFOLIO", id='alpha-add-to-portfolio-btn', n_clicks=0,
                        style={'padding': '6px 16px', 'background': 'transparent', 'color': THEME['accent'],
                               'border': f"1px solid {THEME['accent']}", 'borderRadius': '4px', 'fontSize': '11px', 'fontWeight': '700',
                               'letterSpacing': '0.04em', 'cursor': 'pointer'},
                    ),
                    html.Button(
                        "DOWNLOAD TABLE", id='alpha-download-portfolio-btn', n_clicks=0,
                        style={'padding': '6px 16px', 'background': 'transparent', 'color': THEME['accent'],
                               'border': f"1px solid {THEME['accent']}", 'borderRadius': '4px', 'fontSize': '11px', 'fontWeight': '700',
                               'letterSpacing': '0.04em', 'cursor': 'pointer'},
                    ),
                ], style={'display': 'flex', 'alignItems': 'center', 'gap': '8px'}),
            ),

            # Configuration (was its own card) — now the top section of this card
            html.Div([
                html.Div([
                    html.Label("Total Capital", style=_label_style),
                    html.Div([
                        dcc.Input(
                            id='alpha-total-capital', type='text', value='1000', inputMode='numeric',
                            style={'width': '70px', 'padding': '6px 8px', 'background': 'var(--surface-input)',
                                   'border': '1px solid var(--border-default)', 'borderRadius': '4px',
                                   'color': 'var(--text-primary)', 'fontSize': '12px', 'fontWeight': '600',
                                   'textAlign': 'right'},
                        ),
                        html.Span("Million CNY", style={'color': THEME['text_sub'], 'fontSize': '10px'}),
                    ], style={'display': 'flex', 'alignItems': 'center', 'gap': '8px'}),
                ]),
                html.Div([
                    html.Label("Max Single Side DV01", style=_label_style),
                    html.Div([
                        dcc.Input(
                            id='alpha-dv01-budget', type='text', value='10', inputMode='decimal',
                            style={'width': '70px', 'padding': '6px 8px', 'background': 'var(--surface-input)',
                                   'border': '1px solid var(--border-default)', 'borderRadius': '4px',
                                   'color': 'var(--text-primary)', 'fontSize': '12px', 'fontWeight': '600',
                                   'textAlign': 'right'},
                        ),
                        html.Span("Million CNY", style={'color': THEME['text_sub'], 'fontSize': '10px'}),
                    ], style={'display': 'flex', 'alignItems': 'center', 'gap': '8px'}),
                ]),
                html.Div([
                    html.Label("Method", style=_label_style),
                    html.Span("Risk Parity", style={'color': THEME['accent'], 'fontSize': '12px', 'fontWeight': '700'}),
                ]),
                html.Div(style={'alignSelf': 'stretch', 'width': '1px', 'background': 'var(--border-strong)'}),
                html.Div([
                    html.Label("Repo Leverage", style=_label_style),
                    html.Div([
                        dcc.Input(
                            id='alpha-repo-leverage', type='number', value=15.0, min=1.0, step=0.5,
                            style={'width': '64px', 'padding': '6px 8px', 'background': 'var(--surface-input)',
                                   'border': '1px solid var(--border-default)', 'borderRadius': '4px',
                                   'color': 'var(--text-primary)', 'fontSize': '12px', 'fontWeight': '600',
                                   'textAlign': 'right'},
                        ),
                        html.Span("x", style={'color': THEME['text_sub'], 'fontSize': '10px'}),
                    ], style={'display': 'flex', 'alignItems': 'center', 'gap': '6px'}),
                ]),
                html.Div(id='alpha-financing-summary', style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '16px',
                                                              'alignItems': 'flex-end'}),
            ], style={'padding': '14px 16px', 'display': 'flex', 'flexWrap': 'wrap', 'gap': '24px',
                      'alignItems': 'flex-end', 'borderBottom': '1px solid var(--border-strong)'}),

            dcc.Store(id='alpha-optimized-weights', storage_type='session'),
            dcc.Store(id='alpha-portfolio-export-store', storage_type='session'),
            dcc.Download(id='alpha-portfolio-download'),

            html.Div(
                id='alpha-add-to-portfolio-status',
                style={'padding': '0 16px', 'color': THEME['text_sub'], 'fontSize': '11px'},
            ),

            html.Div(
                id='alpha-portfolio-summary',
                style={'padding': '10px 16px', 'background': 'rgba(255,255,255,0.02)',
                       'borderBottom': '1px solid var(--border-strong)',
                       'color': THEME['text_sub'], 'fontSize': '11px'},
            ),

            dcc.Loading(
                id='loading-portfolio', type='circle',
                color=THEME['accent'],
                style={'minHeight': '80px'},
                    children=html.Div([
                    html.Div(id='alpha-scored-table-container', style={'overflowX': 'auto'}),
                    html.Div(id='alpha-risk-chart-container'),
                    ]),
            ),
        ], style={'border': '1px solid var(--border-strong)', 'borderRadius': '8px', 'overflow': 'hidden'}),

    ], style={'padding': '10px', 'display': 'flex', 'flexDirection': 'column', 'gap': '10px'})


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
        html.H1("Alpha Backtest", style={
            'margin': '0 0 6px', 'fontSize': '22px', 'fontWeight': '600',
            'color': 'var(--text-primary)',
        }),
        html.Div(
            "Backtest individual spread trades or the full portfolio using historical data. "
            "Evaluate strategy performance with z-score (mean-reversion or momentum) or directional-change trend rules.",
            style={'fontSize': '13px', 'color': 'var(--text-secondary)', 'maxWidth': '800px',
                   'marginBottom': '16px'}
        ),

        dcc.Tabs(
            id='backtest-mode-tabs', value='individual',
            className='tab-container an-pill-toggle',
            children=[
                dcc.Tab(label='Individual Spread', value='individual',
                        className='tab an-pill-toggle', selected_className='tab an-pill-toggle an-pill-toggle--selected'),
                dcc.Tab(label='Portfolio', value='portfolio',
                        className='tab an-pill-toggle', selected_className='tab an-pill-toggle an-pill-toggle--selected'),
            ],
            style={'marginBottom': '16px', 'width': 'fit-content'},
        ),

        # Persists 'bt-spread-type' / 'bt-instrument' / 'bt-portfolio-source'
        # selections across a page reload (both panels below now stay mounted
        # across mode-tab switches, so a live session doesn't need this to
        # preserve results -- see the visibility-toggle note below).
        dcc.Store(id='bt-selection-store', storage_type='session', data={}),

        # Both panels are built once and kept mounted; switching
        # 'backtest-mode-tabs' only toggles which one is visible (CSS
        # display, see toggle_backtest_mode_visibility), instead of tearing
        # one down and rebuilding the other from scratch. That's what lets a
        # run's charts/results, dropdown selections, and parameter inputs
        # survive switching back and forth -- e.g. to compare an individual
        # spread's backtest against the portfolio's on the same screen.
        html.Div(id='backtest-individual-panel', children=build_individual_backtest_panel()),
        html.Div(id='backtest-portfolio-panel', children=build_portfolio_backtest_panel()),

    ], style={'padding': '10px', 'display': 'flex', 'flexDirection': 'column', 'gap': '4px'})


def build_individual_backtest_panel(saved_selection: dict | None = None) -> html.Div:
    """Build the individual spread backtest panel."""
    saved_selection = saved_selection or {}
    _card = {
        'background': 'var(--surface-panel)', 'border': '1px solid var(--border-strong)',
        'borderRadius': '6px', 'padding': '14px 16px',
    }
    _hdr = {'margin': '0 0 12px', 'fontSize': '14px', 'fontWeight': '600',
            'color': 'var(--text-primary)'}
    _lbl = {'fontSize': '10px', 'fontWeight': '600', 'letterSpacing': '0.05em',
            'textTransform': 'uppercase', 'color': 'var(--text-muted)',
            'display': 'block', 'marginBottom': '5px'}
    _inp = {
        'width': '100%', 'background': 'var(--surface-input)',
        'border': '1px solid var(--border-default)', 'borderRadius': '6px',
        'padding': '7px 10px', 'color': 'var(--text-primary)', 'fontSize': '13px',
        'boxSizing': 'border-box',
    }
    _inp_mono = {**_inp, 'textAlign': 'right', 'fontFamily': 'var(--font-mono, monospace)',
                 'padding': '6px 8px', 'fontSize': '12px'}
    _lbl_xs = {**_lbl, 'fontSize': '8px', 'marginBottom': '4px'}
    _section_lbl = {
        'fontSize': '9px', 'fontWeight': '700', 'letterSpacing': '0.08em',
        'textTransform': 'uppercase', 'color': 'var(--text-muted)', 'marginBottom': '8px',
    }
    _subsection = {
        'background': 'var(--surface-raised)', 'border': '1px solid var(--border-default)',
        'borderRadius': '6px', 'padding': '10px 12px',
        'alignSelf': 'flex-start', 'display': 'inline-block',
    }

    return html.Div([
        html.Div([
            # ============================= LEFT: all controls =============================
            html.Div([
                # --- Spread Selection ---
                html.Div([
                    html.H2("Spread Selection", style=_hdr),
                    html.Div([
                        html.Div([
                            html.Label("Spread Type", style=_lbl),
                            dcc.Dropdown(
                                id='bt-spread-type',
                                options=_BACKTEST_SPREAD_TYPE_OPTIONS,
                                value=saved_selection.get('spread_type') or 'TBondCurve', clearable=False,
                                style={'fontSize': '13px'},
                            ),
                        ]),
                        html.Div([
                            html.Label("Instrument", style=_lbl),
                            dcc.Dropdown(id='bt-instrument', options=[], placeholder="Select instrument...",
                                         value=saved_selection.get('instrument'),
                                         style={'fontSize': '13px'}),
                        ]),
                    ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '10px'}),
                ], style=_card),

                # --- Automatic Monthly Regime (compact, single column) ---
                html.Div([
                    html.H2("Automatic Monthly Regime", style={**_hdr, 'fontSize': '13px'}),
                    html.Div(id='bt-regime-badge', style={'marginBottom': '4px'}),
                    html.Div(id='bt-saved-state-badge', style={'minHeight': '16px', 'marginBottom': '10px'}),

                    # --- Trend sub-section ---
                    html.Div([
                        html.Div("TREND", style=_section_lbl),
                        html.Div([
                            html.Div([html.Label("Theta z", style=_lbl_xs), dcc.Input(id='bt-theta', type='number', value=1.25, min=0.25, max=4.0, step=0.05, style=_inp_mono, className='no-spinner')]),
                            html.Div([html.Label("Mom window", style=_lbl_xs), dcc.Input(id='bt-mom-window', type='number', value=20, min=5, max=120, step=1, style=_inp_mono, className='no-spinner')]),
                            html.Div([html.Label("Vol window", style=_lbl_xs), dcc.Input(id='bt-vol-window', type='number', value=60, min=20, max=252, step=1, style=_inp_mono, className='no-spinner')]),
                            html.Div([html.Label("Trail mult", style=_lbl_xs), dcc.Input(id='bt-trailing-mult', type='number', value=3.0, min=0.5, max=5.0, step=0.1, style=_inp_mono, className='no-spinner')]),
                        ], style={'display': 'grid', 'gridTemplateColumns': 'repeat(2, minmax(0, 1fr))', 'gap': '8px'}),
                    ], style={**_subsection, 'display': 'block', 'width': '100%', 'boxSizing': 'border-box', 'marginBottom': '8px'}),

                    # --- Mean-reversion / strategy sub-section ---
                    html.Div([
                        html.Div("MEAN-REVERSION", style=_section_lbl),
                        html.Div([
                            html.Div([html.Label("Entry Z", style=_lbl_xs), dcc.Input(id='bt-entry-z', type='number', value=2.0, min=0.5, max=4.0, step=0.25, style=_inp_mono, className='no-spinner')]),
                            html.Div([html.Label("Exit Z", style=_lbl_xs), dcc.Input(id='bt-exit-z', type='number', value=0.5, min=0, max=2.0, step=0.25, style=_inp_mono, className='no-spinner')]),
                            html.Div([html.Label("Stop (σ)", style=_lbl_xs), dcc.Input(id='bt-stop-z', type='number', value=3.0, min=2.0, max=6.0, step=0.5, style=_inp_mono, className='no-spinner')]),
                            html.Div([
                                html.Label("Carry weight", style={**_lbl_xs, 'color': THEME['accent']}),
                                dcc.Input(id='bt-carry-z-weight', type='number', value=0.5, min=0.0, max=2.0, step=0.05, style=_inp_mono, className='no-spinner'),
                            ]),
                        ], style={'display': 'grid', 'gridTemplateColumns': 'repeat(2, minmax(0, 1fr))', 'gap': '8px'}),
                    ], style={**_subsection, 'display': 'block', 'width': '100%', 'boxSizing': 'border-box', 'marginBottom': '10px'}),

                    # --- Shared controls: min-hold, period, lookback window, allow-short ---
                    html.Div([
                        html.Div([html.Label("Min Hold (d)", style=_lbl_xs), dcc.Input(id='bt-min-hold', type='number', value=7, min=1, max=30, step=1, style={**_inp_mono, 'width': '100%'}, className='no-spinner')]),
                        html.Div([
                            html.Label("Backtest Period", style=_lbl_xs),
                            dcc.Dropdown(id='bt-period', options=[{'label': '1 Year', 'value': 252}, {'label': '2 Years', 'value': 504}, {'label': '3 Years', 'value': 756}, {'label': '5 Years', 'value': 1260}, {'label': '10 Years', 'value': 2520}], value=504, clearable=False, style={'fontSize': '12px'}),
                        ]),
                        html.Div([
                            html.Label("Lookback Window", style=_lbl_xs),
                            dcc.Dropdown(
                                id='bt-mr-lookback',
                                options=[
                                    {'label': '3 Months', 'value': 90},
                                    {'label': '6 Months', 'value': 120},
                                    {'label': '1 Year', 'value': 252},
                                    {'label': '2 Years', 'value': 504},
                                ],
                                value=120, clearable=False, style={'fontSize': '12px'},
                            ),
                        ]),
                    ], style={'display': 'grid', 'gridTemplateColumns': 'repeat(2, minmax(0, 1fr))', 'gap': '10px', 'marginBottom': '10px'}),
                    dcc.Checklist(
                        id='bt-allow-short',
                        options=[{'label': ' Allow short-spread trades', 'value': 'allow'}], value=['allow'],
                        labelStyle={'color': 'var(--text-secondary)', 'fontSize': '11px', 'cursor': 'pointer'},
                        inputStyle={'accentColor': 'var(--accent-amber)', 'cursor': 'pointer', 'marginRight': '6px'},
                    ),

                    # Keep the parameter grid responsive so Windows font metrics do not clip
                    # numeric values in the Monthly Regime inputs even when the tab is narrow.

                    # Legacy, unused — kept only so old saved layouts/State wiring don't break.
                    dcc.Input(id='bt-carry-buffer', type='number', value=0.0, style={'display': 'none'}),
                ], style=_card),

                # --- Run / Save buttons ---
                html.Div([
                    an_button(
                        "▶ Run Individual Backtest", id='bt-run-individual-btn', n_clicks=0,
                        variant="success", style_overrides={'padding': '10px 14px', 'fontSize': '12px', 'width': '100%'},
                    ),
                    an_button(
                        "💾 Save Parameters", id='bt-save-params-btn', n_clicks=0,
                        variant="secondary", style_overrides={'padding': '10px 14px', 'fontSize': '12px', 'width': '100%'},
                    ),
                    html.Span(id='bt-save-params-status', style={'color': 'var(--text-muted)', 'fontSize': '11px', 'display': 'block'}),
                ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '8px'}),
            ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '12px',
                      'flex': '0 0 300px', 'minWidth': '260px', 'maxWidth': '320px'}),

            # ============================= RIGHT: charts + trade history =============================
            html.Div([
                dcc.Loading(id='loading-bt-individual', type='circle', color=THEME['accent'], style={'minHeight': '60px'}, children=html.Div([
                    html.Span(id='bt-individual-status', style={'color': 'var(--text-muted)', 'fontSize': '12px', 'marginBottom': '8px', 'display': 'block'}),
                    html.Div(id='bt-individual-results'),
                ])),
            ], style={'flex': '1', 'minWidth': '0'}),
        ], style={'display': 'flex', 'gap': '16px', 'alignItems': 'flex-start', 'flexWrap': 'wrap'}),
    ])


def build_portfolio_backtest_panel(saved_selection: dict | None = None) -> html.Div:
    """Build the portfolio backtest panel."""
    saved_selection = saved_selection or {}
    _card = {
        'background': 'var(--surface-panel)', 'border': '1px solid var(--border-strong)',
        'borderRadius': '6px', 'padding': '14px 16px',
    }
    _hdr = {'margin': '0 0 10px', 'fontSize': '14px', 'fontWeight': '600',
            'color': 'var(--text-primary)'}
    _lbl = {'fontSize': '10px', 'fontWeight': '600', 'letterSpacing': '0.05em',
            'textTransform': 'uppercase', 'color': 'var(--text-muted)',
            'display': 'block', 'marginBottom': '6px'}
    _inp = {
        'width': '100%', 'background': 'var(--surface-input)',
        'border': '1px solid var(--border-default)', 'borderRadius': '6px',
        'padding': '8px 10px', 'color': 'var(--text-primary)', 'fontSize': '13px',
        'boxSizing': 'border-box',
    }

    return html.Div([
        html.Div([
            # ============================= LEFT: all controls =============================
            html.Div([
                # --- Portfolio Data ---
                html.Div([
                    html.H2("Portfolio Data", style=_hdr),
                    html.Div([
                        html.Label("Portfolio Source", style=_lbl),
                        dcc.Dropdown(
                            id='bt-portfolio-source',
                            options=[
                                {'label': "Client Portfolio (from Portfolio tab)", 'value': 'client'},
                                {'label': "Default: Curve & Cross-Asset Spreads", 'value': 'default_tenor_spread'},
                            ],
                            value=saved_selection.get('portfolio_source') or 'client', clearable=False,
                            style={'fontSize': '13px'},
                        ),
                        html.P(
                            "Default portfolios are a fixed, risk-parity-weighted book across every "
                            "long-history instrument in the category — direction (BUY/SELL) is set by "
                            "each instrument's current z-score, not a saved scan. Independent of the "
                            "Portfolio tab.",
                            style={'color': 'var(--text-muted)', 'fontSize': '11px', 'marginTop': '6px', 'marginBottom': '0'},
                        ),
                    ], style={'marginBottom': '10px'}),
                    dcc.Loading(id='loading-bt-portfolio-source', type='circle', color=THEME['accent'],
                                style={'minHeight': '20px'}, children=
                        html.Div(id='bt-portfolio-data-preview', children=[
                            html.P("No portfolio data loaded. Please go to the 'Portfolio' tab and run 'Calculate Score & Allocation' first.",
                                   style={'color': 'var(--accent-amber)', 'fontStyle': 'italic', 'fontSize': '12px'})
                        ]),
                    ),
                    # Holds the built default-portfolio records (client mode uses
                    # alpha-optimized-weights / the saved snapshot directly, see
                    # _load_portfolio_snapshot / _resolve_portfolio_source).
                    dcc.Store(id='bt-default-portfolio-store', data=None),
                ], style=_card),

                # --- Backtest Settings ---
                html.Div([
                    html.H2("Backtest Settings", style=_hdr),
                    html.Div([
                        html.Div([
                            html.Label("Backtest Period", style=_lbl),
                            dcc.Dropdown(id='bt-port-period', options=[{'label': '1 Year', 'value': 252}, {'label': '2 Years', 'value': 504}, {'label': '3 Years', 'value': 756}, {'label': '5 Years', 'value': 1260}, {'label': '10 Years', 'value': 2520}], value=504, clearable=False, style={'fontSize': '13px'}),
                        ]),
                        html.Div([
                            html.Label("Initial Capital (MM)", style=_lbl),
                            dcc.Input(id='bt-initial-capital', type='number', value=100, min=10, max=1000, step=10, style=_inp, className='no-spinner'),
                        ]),
                        html.Div([
                            html.Label("Transaction Cost (bp)", style=_lbl),
                            dcc.Input(id='bt-txn-cost', type='number', value=0.5, min=0, max=5, step=0.1, style=_inp, className='no-spinner'),
                        ]),
                    ], style={'display': 'grid', 'gridTemplateColumns': 'repeat(2, minmax(0, 1fr))', 'gap': '10px'}),
                    # Signal settings for instruments with no saved per-instrument
                    # params (see run_portfolio_backtest) come from the Individual
                    # Spread tab's own 'bt-entry-z'/'bt-exit-z'/'bt-stop-z'/
                    # 'bt-min-hold' inputs — both panels are mounted at once (see
                    # build_backtest_layout), so the portfolio callback reads those
                    # directly as State instead of carrying its own hidden copies.
                    # Tune them per instrument on the Individual Spread tab and
                    # Save Parameters instead of setting one value for the whole
                    # book.
                ], style=_card),

                # --- Trend filter (efficiency-ratio entry gate) ---
                html.Div([
                    html.H2("Trend Filter", style=_hdr),
                    dcc.Checklist(
                        id='bt-port-er-gate-on',
                        options=[{'label': ' Block trend-y entries (efficiency ratio)', 'value': 'on'}], value=[],
                        labelStyle={'color': 'var(--text-secondary)', 'fontSize': '12px', 'cursor': 'pointer'},
                        inputStyle={'accentColor': 'var(--accent-amber)', 'cursor': 'pointer', 'marginRight': '6px'},
                    ),
                    html.Div([
                        html.Div([
                            html.Label("ER Max", style=_lbl),
                            dcc.Input(id='bt-port-er-max', type='number', value=0.45, min=0.1, max=1.0, step=0.05, style=_inp, className='no-spinner'),
                        ]),
                        html.Div([
                            html.Label("ER Window (d)", style=_lbl),
                            dcc.Input(id='bt-port-er-window', type='number', value=20, min=5, max=120, step=5, style=_inp, className='no-spinner'),
                        ]),
                    ], style={'display': 'grid', 'gridTemplateColumns': 'repeat(2, minmax(0, 1fr))', 'gap': '10px', 'marginTop': '10px'}),
                    html.P(
                        "Skips new entries while the spread's recent move looks one-directional "
                        "(trending) rather than choppy — see Individual Spread tab for per-instrument tuning.",
                        style={'color': 'var(--text-muted)', 'fontSize': '11px', 'marginTop': '8px', 'marginBottom': '0'},
                    ),
                ], style=_card),

                # --- Actions ---
                html.Div([
                    an_button(
                        "▶ Run Portfolio Backtest", id='bt-run-portfolio-btn', n_clicks=0,
                        variant="success", style_overrides={'padding': '10px 14px', 'fontSize': '12px', 'width': '100%'},
                    ),
                    an_button(
                        "💾 Save Result", id='bt-save-portfolio-result-btn', n_clicks=0,
                        variant="secondary", style_overrides={'padding': '10px 14px', 'fontSize': '12px', 'width': '100%', 'marginTop': '8px'},
                    ),
                    html.Span(id='bt-save-portfolio-result-status', style={'color': 'var(--text-muted)', 'fontSize': '11px', 'marginTop': '6px', 'display': 'block'}),
                ], style=_card),
            ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '12px',
                      'flex': '0 0 300px', 'minWidth': '260px', 'maxWidth': '320px'}),

            # ============================= RIGHT: charts + results =============================
            html.Div([
                dcc.Loading(id='loading-bt-portfolio', type='circle', color=THEME['accent'], style={'minHeight': '60px'}, children=html.Div([
                    html.Span(id='bt-portfolio-status', style={'color': 'var(--text-muted)', 'fontSize': '12px', 'marginBottom': '8px', 'display': 'block'}),
                    html.Div(id='bt-portfolio-results'),
                ])),
                # Holds the last run's result (equity curve + summary stats +
                # instrument snapshot) so the "Save Result" button can persist
                # it without re-running the backtest.
                dcc.Store(id='bt-portfolio-last-result-store', data=None),
            ], style={'flex': '1', 'minWidth': '0'}),
        ], style={'display': 'flex', 'gap': '16px', 'alignItems': 'flex-start', 'flexWrap': 'wrap'}),
    ])
