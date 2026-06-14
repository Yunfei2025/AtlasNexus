# -*- coding: utf-8 -*-
"""Portfolio (Allocation) tab layout."""

from __future__ import annotations

from dash import dcc, html

from multiasset.storage import load_last_asset_pool

from ..data import THEME


def build_multiasset_portfolio_layout():
    """Build the layout for the Portfolio (Allocation) tab."""

    # Load last saved state
    try:
        last_run_data = load_last_asset_pool()
    except Exception:
        last_run_data = {}

    initial_pool = []
    initial_n_clicks = 0
    initial_capital = 10
    initial_unit = 'billion'

    if last_run_data:
        if 'asset_pool' in last_run_data:
            initial_pool = last_run_data['asset_pool']
            # Note: Do NOT auto-trigger run_analysis on page load
            # User should click 'RUN ANALYSIS' manually to ensure Risk Budgets are loaded
            # initial_n_clicks remains 0

        if 'metadata' in last_run_data:
            meta = last_run_data['metadata']
            if 'capital' in meta:
                initial_capital = meta['capital']
            if 'unit' in meta:
                initial_unit = meta['unit']

    # Generate initial pool display
    if not initial_pool:
        pool_display = [html.Div("No assets selected. Add assets above.",
                           style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px', 'textAlign': 'center', 'padding': '15px'})]
        pool_count_text = "(0)"
    else:
        pool_display = []
        for asset in initial_pool:
            # Using simple styles for pool items, relying on container for bg
            if asset['type'] == 'Commodities':
                bg_col = '#b48b32' # Darker gold
            else:
                bg_col = '#2c5e40' # Darker green

            pool_display.append(
                html.Div([
                    html.Span(f"• {asset['name']}", style={'fontWeight': 'bold', 'color': 'white'}),
                    html.Span(f" ({asset.get('universe','')} - {asset.get('sector','')})", style={'color': '#ddd', 'fontSize': '11px', 'marginLeft': '5px'}),
                ], style={'padding': '5px', 'marginBottom': '5px', 'backgroundColor': bg_col, 'borderRadius': '3px'})
            )
        pool_count_text = f"({len(initial_pool)})"

    return html.Div([
        # Data Stores
        dcc.Store(id='portfolio-data-store'),
        dcc.Store(id='asset-pool-store', data=initial_pool),
        dcc.Store(id='rp-budget-store', data={}),

        html.Div([
            # Section 1: Configuration Header & Capital
            html.Div([
                html.Div([
                    html.H5("Configuration", style={'margin': '0', 'color': THEME['text_main'], 'fontSize': '14px'}),
                ], style={'flex': '1'}),

                html.Div([
                    html.Label("Total Capital:", style={'fontWeight': 'bold', 'marginRight': '10px', 'fontSize': '12px', 'color': THEME['text_main']}),
                    dcc.Input(
                        id='capital-input',
                        type='number',
                        value=initial_capital,
                        style={'width': '100px', 'marginRight': '5px', 'padding': '5px', 'borderRadius': '4px', 'border': '1px solid #444', 'backgroundColor': '#fff', 'color': '#000'}
                    ),
                    dcc.Dropdown(
                        id='capital-unit',
                        options=[
                            {"label": "Million", "value": "million"},
                            {"label": "Billion", "value": "billion"},
                        ],
                        value=initial_unit,
                        clearable=False,
                        style={'width': '100px', 'marginRight': '5px', 'fontSize': '12px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                    ),
                    html.Span("CNY", style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginRight': '20px'}),

                    html.Label("Max Dur:", style={'fontWeight': 'bold', 'marginRight': '5px', 'fontSize': '12px', 'color': THEME['text_main']}),
                    dcc.Input(
                        id='max-duration-input',
                        type='number',
                        value=5,
                        min=0.1, max=50, step=0.1,
                        style={'width': '60px', 'marginRight': '4px', 'padding': '5px', 'borderRadius': '4px', 'border': '1px solid #444', 'backgroundColor': '#fff', 'color': '#000'}
                    ),
                    html.Span(
                        id='max-dv01-display',
                        style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginRight': '20px', 'fontStyle': 'italic'}
                    ),

                    html.Label("Model:", style={'fontWeight': 'bold', 'marginRight': '10px', 'fontSize': '12px', 'color': THEME['text_main']}),
                    html.Span(
                        "Deterministic",
                        style={
                            'fontSize': '12px',
                            'fontWeight': 'bold',
                            'color': THEME['text_main'],
                            'backgroundColor': THEME['bg_card'],
                            'padding': '4px 10px',
                            'borderRadius': '999px',
                            'border': f'1px solid {THEME["accent"]}',
                        }
                    ),
                ], style={'display': 'flex', 'alignItems': 'center'}),
            ], style={'display': 'flex', 'alignItems': 'center', 'padding': '15px 20px', 'backgroundColor': THEME['bg_input'], 'borderBottom': f'1px solid {THEME["table_header"]}', 'borderRadius': '8px 8px 0 0'}),

            # Section 2: Two-column — sidebar (asset controls) | Risk Budgets (primary)
            html.Div([
                # ── Left sidebar: Asset Selection + Pool stacked ──────────────────
                html.Div([
                    # Asset Selection (compact)
                    html.Div([
                        html.H6("Asset Selection", style={'color': THEME['text_main'], 'marginTop': '0', 'marginBottom': '10px', 'fontSize': '13px'}),
                        html.Div([
                            html.Label("Type:", style={'fontWeight': 'bold', 'width': '55px', 'fontSize': '12px', 'color': THEME['text_main']}),
                            dcc.RadioItems(
                                id='asset-type-selector',
                                options=[
                                    {'label': ' Rates', 'value': 'Rates'},
                                    {'label': ' Cmdty', 'value': 'Commodities'},
                                ],
                                value=None,
                                inline=True,
                                labelStyle={'color': THEME['text_main'], 'fontSize': '12px'},
                                inputStyle={'marginRight': '4px', 'marginLeft': '6px'},
                                style={'fontSize': '12px'},
                            ),
                        ], style={'marginBottom': '8px', 'display': 'flex', 'alignItems': 'center'}),
                        html.Div([
                            html.Label("Universe:", style={'fontWeight': 'bold', 'width': '55px', 'fontSize': '12px', 'color': THEME['text_main']}),
                            dcc.Dropdown(
                                id='universe-selector',
                                options=[], value=None,
                                placeholder="Select...", clearable=True,
                                style={'width': '100%', 'fontSize': '12px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']},
                            ),
                        ], id='universe-selection-row', style={'display': 'none', 'marginBottom': '8px', 'alignItems': 'center'}),
                        html.Div([
                            html.Label("Sector:", style={'fontWeight': 'bold', 'width': '55px', 'fontSize': '12px', 'alignSelf': 'flex-start', 'marginTop': '4px', 'color': THEME['text_main']}),
                            html.Div([
                                dcc.Checklist(
                                    id='sector-selector',
                                    options=[
                                        {'label': ' 1Y', 'value': '1Y'},
                                        {'label': ' 2Y', 'value': '2Y'},
                                        {'label': ' 5Y', 'value': '5Y'},
                                        {'label': ' 10Y', 'value': '10Y'},
                                        {'label': ' 20Y', 'value': '20Y'},
                                        {'label': ' 30Y', 'value': '30Y'},
                                    ],
                                    value=[], inline=True,
                                    labelStyle={'color': THEME['text_main'], 'fontSize': '12px'},
                                    inputStyle={'marginRight': '2px', 'marginLeft': '5px'},
                                    style={'fontSize': '12px', 'marginBottom': '6px'},
                                ),
                                html.Button('Add to Pool', id='add-to-pool-btn', n_clicks=0,
                                    style={'backgroundColor': '#2ecc71', 'color': 'white', 'padding': '3px 10px', 'border': 'none', 'borderRadius': '3px', 'cursor': 'pointer', 'fontSize': '12px'}),
                            ], style={'flex': '1'}),
                        ], id='sector-selection-row', style={'display': 'none', 'marginBottom': '8px', 'alignItems': 'flex-start'}),
                        html.Div([
                            html.Label("Items:", style={'fontWeight': 'bold', 'width': '55px', 'fontSize': '12px', 'alignSelf': 'flex-start', 'marginTop': '4px', 'color': THEME['text_main']}),
                            html.Div([
                                dcc.Checklist(
                                    id='commodities-selector',
                                    options=[
                                        {'label': ' Gold', 'value': 'Gold'},
                                        {'label': ' Silver', 'value': 'Silver'},
                                        {'label': ' Alum', 'value': 'Aluminium'},
                                        {'label': ' Copper', 'value': 'Copper'},
                                        {'label': ' Zinc', 'value': 'Zinc'},
                                        {'label': ' Oil', 'value': 'Crude_Oil'},
                                    ],
                                    value=[], inline=True,
                                    labelStyle={'color': THEME['text_main'], 'fontSize': '12px'},
                                    inputStyle={'marginRight': '2px', 'marginLeft': '5px'},
                                    style={'fontSize': '12px', 'marginBottom': '6px'},
                                ),
                                html.Button('Add to Pool', id='add-commodities-btn', n_clicks=0,
                                    style={'backgroundColor': '#f39c12', 'color': 'white', 'padding': '3px 10px', 'border': 'none', 'borderRadius': '3px', 'cursor': 'pointer', 'fontSize': '12px'}),
                            ], style={'flex': '1'}),
                        ], id='commodities-confirm-row', style={'display': 'none', 'marginBottom': '8px', 'alignItems': 'flex-start'}),
                    ], style={'padding': '12px 14px', 'borderBottom': f'1px solid {THEME["table_header"]}'}),
                    # ── Asset Pool ────────────────────────────────────────────────────
                    html.Div([
                        html.Div([
                            html.H6("Asset Pool", style={'color': THEME['text_main'], 'marginTop': '0', 'marginBottom': '0', 'fontSize': '13px'}),
                            html.Span(id='pool-count', children=pool_count_text, style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginLeft': '5px'}),
                            html.Button('Clear', id='clear-pool-btn', n_clicks=0,
                                style={'backgroundColor': THEME['danger'], 'color': 'white', 'padding': '2px 7px', 'border': 'none', 'borderRadius': '3px', 'cursor': 'pointer', 'fontSize': '12px', 'marginLeft': 'auto'}),
                        ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '8px'}),
                        html.Div(
                            id='asset-pool-display', children=pool_display,
                            style={'height': '180px', 'overflowY': 'auto', 'border': f'1px solid {THEME["table_header"]}', 'borderRadius': '4px', 'padding': '6px', 'backgroundColor': THEME['bg_input']},
                        ),
                    ], style={'padding': '12px 14px'}),
                ], style={'width': '45%', 'borderRight': f'1px solid {THEME["table_header"]}', 'display': 'flex', 'flexDirection': 'column'}),

                # ── Right main: Risk Budgets (primary) ───────────────────────────────
                html.Div([
                    html.Div([
                        html.H6("Risk Budgets (Vol√ Risk Parity)", style={'color': THEME['text_main'], 'marginTop': '0', 'marginBottom': '0', 'fontSize': '13px', 'fontWeight': 'bold'}),
                        html.Span("Vol from 1Y EWMA  ·  Budget = vol^0.5  ·  Level > Slope > Curvature  ·  Floor 3%, Cap 25%",
                                  style={'color': THEME['text_sub'], 'fontSize': '10px', 'marginLeft': '12px'}),
                    ], style={'display': 'flex', 'alignItems': 'baseline', 'marginBottom': '8px'}),
                    html.Div([
                        dcc.RadioItems(
                            id='allocation-mode',
                            options=[
                                {'label': ' Factor Model Scaling', 'value': 'factor_scaling'},
                                {'label': ' User Defined', 'value': 'user_defined'},
                            ],
                            value='factor_scaling',
                            inputStyle={'marginRight': '5px'},
                            labelStyle={'display': 'inline', 'marginRight': '16px', 'color': THEME['text_main'], 'fontSize': '12px'},
                            style={'display': 'inline-flex'},
                        ),
                        html.Span(id='factor-signals-toggle-status', style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '8px'}),
                    ], style={'marginBottom': '8px'}),
                    # Column headers: Factor | Vol% ann | ×adj | RP Max (MM) | DV01 (MM/bp) | Coeff | Exposure (MM)
                    html.Div([
                        html.Span("Factor",          style={'color': THEME['text_sub'], 'fontSize': '11px', 'width': '80px', 'fontWeight': 'bold', 'flexShrink': '0'}),
                        html.Span("Vol %ann",        style={'color': THEME['text_sub'], 'fontSize': '11px', 'width': '62px', 'textAlign': 'right', 'flexShrink': '0'}),
                        html.Span("×adj",            style={'color': THEME['text_sub'], 'fontSize': '11px', 'width': '48px', 'textAlign': 'center', 'flexShrink': '0'},
                                  title='Tier weight (default: IRDL=1.0, IRSL=0.6, IRCV=0.3). Scales measured vol before risk parity. Edit to customize tier importance.'),
                        html.Span("RP Max (MM CNY)", style={'color': THEME['text_sub'], 'fontSize': '11px', 'width': '105px', 'textAlign': 'right', 'flexShrink': '0'},
                                  title='Risk Parity Max allocation in millions CNY'),
                        html.Span("DV01 (MM/bp)",    style={'color': THEME['text_sub'], 'fontSize': '11px', 'width': '85px', 'textAlign': 'right', 'flexShrink': '0'},
                                  title='Duration risk in MM CNY per basis point (IR factors only; blank for commodities/FX)'),
                        html.Span("Coeff",           style={'color': THEME['text_sub'], 'fontSize': '11px', 'width': '44px', 'textAlign': 'center', 'flexShrink': '0'}),
                        html.Span("Exposure (MM CNY)",style={'color': THEME['text_sub'], 'fontSize': '11px', 'flex': '1', 'textAlign': 'right'}),
                    ], style={'display': 'flex', 'alignItems': 'center', 'padding': '0 8px 4px 8px',
                              'borderBottom': f'1px solid {THEME["table_header"]}', 'marginBottom': '4px', 'gap': '4px'}),
                    html.Div(
                        id='risk-budget-container',
                        children=[html.Div("Add assets to see risk factors", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px'})] if not initial_pool else [],
                        style={'maxHeight': '280px', 'overflowY': 'auto',
                               'border': f'1px solid {THEME["table_header"]}',
                               'borderRadius': '4px', 'padding': '6px 8px',
                               'backgroundColor': THEME['bg_input']},
                    ),
                    html.Div("Vol auto-refreshes from 1Y EWMA factor history. Run analysis to refresh RP Max from portfolio decomposition.",
                             style={'fontSize': '11px', 'color': THEME['text_sub'], 'marginTop': '5px', 'textAlign': 'center'}),
                ], style={'flex': '1', 'padding': '16px 20px', 'backgroundColor': THEME['bg_card'], 'borderRadius': '0 0 8px 0'}),
            ], style={'display': 'flex'}),

        ], style={'backgroundColor': THEME['bg_card'], 'marginBottom': '20px', 'border': f'1px solid {THEME["table_header"]}', 'borderRadius': '8px'}),

        # Store for the latest signal snapshot (populated by Candidates tab Predict button)
        dcc.Store(id='factor-signals-snapshot-store', data={}),

        # Portfolio Table Results
        html.Div([
            html.Div([
                 html.H4("Portfolio Allocation Results", style={'color': THEME['text_main'], 'fontSize': '15px', 'marginBottom': '10px', 'flex': '1'}),
                 html.Div([
                        html.Button(
                            'RUN ANALYSIS',
                            id='run-button',
                            n_clicks=initial_n_clicks,
                            style={'backgroundColor': THEME['accent'], 'color': 'white', 'padding': '8px 20px', 'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer', 'fontSize': '13px', 'fontWeight': 'bold'}
                        ),
                 ], style={'marginLeft': '20px'})
            ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between'}),

            dcc.Loading(
                type='circle',
                color=THEME['accent'],
                style={'minHeight': '80px'},
                children=html.Div([
                    html.Div([
                        html.Div(id='status-message', style={'fontSize': '12px', 'color': THEME['text_main'], 'marginRight': '20px'}),
                        html.Div(id='timestamp-display', style={'color': THEME['text_sub'], 'fontSize': '11px'})
                    ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '15px', 'justifyContent': 'flex-end'}),
                    html.Div(id='portfolio-table-container'),
                ]),
            ),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'marginBottom': '20px', 'borderRadius': '5px'}),

        # ── IRDL Hedge Overlay (collapsible) ─────────────────────────────────
        html.Details([
            html.Summary([
                html.Span("🛡 IRDL Hedge Overlay",
                          style={'color': THEME['text_main'], 'fontWeight': 'bold', 'fontSize': '13px'}),
                html.Span("  ·  optional post-optimisation duration hedge via bond futures or pay-fixed IRS",
                          style={'color': THEME['text_sub'], 'fontSize': '11px'}),
            ], style={
                'padding': '10px 16px', 'cursor': 'pointer',
                'listStyleType': 'none', 'WebkitAppearance': 'none', 'MozAppearance': 'none',
                'backgroundColor': THEME['bg_input'], 'borderRadius': '5px', 'userSelect': 'none',
            }),
            html.Div([
                # Controls row
                html.Div([
                    # Hedge ratio
                    html.Div([
                        html.Label("Hedge Ratio", style={
                            'color': THEME['text_sub'], 'fontSize': '11px',
                            'marginBottom': '4px', 'display': 'block',
                        }),
                        dcc.Slider(
                            id='irdl-hedge-ratio',
                            min=0, max=100, step=5, value=50,
                            marks={0: '0%', 25: '25%', 50: '50%', 75: '75%', 100: '100%'},
                            tooltip={'placement': 'bottom', 'always_visible': True},
                        ),
                    ], style={'flex': '2', 'minWidth': '220px'}),
                    # Instrument
                    html.Div([
                        html.Label("Instrument", style={
                            'color': THEME['text_sub'], 'fontSize': '11px',
                            'marginBottom': '4px', 'display': 'block',
                        }),
                        dcc.Dropdown(
                            id='irdl-hedge-instrument',
                            options=[
                                {'label': 'Bond Futures (Short)',   'value': 'futures'},
                                {'label': 'Pay-fixed IRS',          'value': 'irs'},
                            ],
                            value='futures', clearable=False,
                            style={'fontSize': '12px', 'backgroundColor': THEME['bg_input'],
                                   'color': THEME['text_main']},
                        ),
                    ], style={'flex': '1', 'minWidth': '180px'}),
                    # IRS maturity (only relevant when IRS selected)
                    html.Div([
                        html.Label("IRS Tenor", style={
                            'color': THEME['text_sub'], 'fontSize': '11px',
                            'marginBottom': '4px', 'display': 'block',
                        }),
                        dcc.Dropdown(
                            id='irdl-hedge-irs-maturity',
                            options=[
                                {'label': '2Y IRS',  'value': '2Y'},
                                {'label': '5Y IRS',  'value': '5Y'},
                                {'label': '10Y IRS', 'value': '10Y'},
                                {'label': '30Y IRS', 'value': '30Y'},
                            ],
                            value='10Y', clearable=False,
                            style={'fontSize': '12px', 'backgroundColor': THEME['bg_input'],
                                   'color': THEME['text_main']},
                        ),
                    ], style={'flex': '0 0 130px'}),
                ], style={
                    'display': 'flex', 'gap': '20px', 'alignItems': 'flex-end',
                    'flexWrap': 'wrap', 'marginBottom': '16px',
                }),
                # DV01 overrides (compact row)
                html.Div([
                    html.Span("DV01 Override (CNY/bp per contract, blank = default):",
                              style={'color': THEME['text_sub'], 'fontSize': '11px',
                                     'marginRight': '12px', 'alignSelf': 'center'}),
                    *[
                        html.Div([
                            html.Label(cty, style={'color': THEME['text_sub'], 'fontSize': '11px',
                                                   'display': 'block', 'marginBottom': '2px'}),
                            dcc.Input(
                                id={'type': 'irdl-dv01-override', 'index': cty},
                                type='number', placeholder=str(default),
                                debounce=True,
                                style={'width': '72px', 'padding': '4px 6px',
                                       'background': THEME['bg_input'], 'color': THEME['text_main'],
                                       'border': f'1px solid {THEME["table_header"]}',
                                       'borderRadius': '4px', 'fontSize': '12px'},
                            ),
                        ], style={'textAlign': 'center'})
                        for cty, default in [('CN', 800), ('US', 640), ('DE', 750),
                                             ('JP', 560), ('UK', 600)]
                    ],
                ], style={
                    'display': 'flex', 'gap': '12px', 'alignItems': 'flex-end',
                    'marginBottom': '16px', 'flexWrap': 'wrap',
                }),
                # Ticket output
                dcc.Loading(
                    type='circle',
                    color=THEME['accent'],
                    style={'minHeight': '60px'},
                    children=html.Div(id='irdl-hedge-ticket-container',
                                      style={'minHeight': '60px'}),
                ),
                html.Div(
                    "Hedge overlay is advisory only — it does not change portfolio weights. "
                    "Negative contracts = short futures; PAY FIXED = pay fixed rate in IRS.",
                    style={'color': THEME['text_sub'], 'fontSize': '11px',
                           'marginTop': '8px', 'fontStyle': 'italic'},
                ),
            ], style={'padding': '14px 16px', 'borderTop': f'1px solid {THEME["table_header"]}'}),
        ], style={
            'backgroundColor': THEME['bg_card'],
            'borderRadius': '5px',
            'border': f'1px solid {THEME["table_header"]}',
            'marginBottom': '20px',
        }),

    ], style={'padding': '10px', 'backgroundColor': THEME['bg_main']})
