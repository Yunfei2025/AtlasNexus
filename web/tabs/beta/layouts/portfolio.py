# -*- coding: utf-8 -*-
"""Portfolio (Allocation) tab layout."""

from __future__ import annotations

from dash import dcc, html

from multiasset.storage import load_last_asset_pool

from ...atlas_components import asset_pool_item


_CARD_WRAP = {
    'border': '1px solid var(--border-strong)',
    'borderRadius': '8px',
    'overflow': 'hidden',
}

_CARD_TITLE = {
    'fontSize': '13px',
    'fontWeight': '600',
    'color': 'var(--text-primary)',
}

_INLINE_LBL = {
    'color': 'var(--text-muted)',
    'fontSize': '9px',
    'textTransform': 'uppercase',
    'letterSpacing': '0.06em',
}

_BADGE = {
    'fontSize': '9px',
    'color': 'var(--text-muted)',
    'background': 'var(--surface-input)',
    'padding': '2px 7px',
    'borderRadius': '3px',
    'border': '1px solid var(--border-default)',
}


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
                           style={'color': 'var(--text-muted)', 'fontStyle': 'italic',
                                  'fontSize': '11px', 'textAlign': 'center', 'padding': '15px'})]
        pool_count_text = "(0)"
    else:
        pool_display = [
            asset_pool_item(asset['name'])
            for asset in initial_pool
        ]
        pool_count_text = f"({len(initial_pool)})"

    # ── Configuration: inline inputs bar ───────────────────────────────────
    config_bar = html.Div([
        html.Div([
            html.Span("Total Capital:", style=_INLINE_LBL),
            dcc.Input(
                id='capital-input', type='number', value=initial_capital,
                style={'width': '60px', 'background': 'var(--surface-input)',
                       'border': '1px solid var(--border-default)', 'borderRadius': '4px',
                       'padding': '6px 8px', 'fontSize': '10px', 'color': 'var(--text-primary)',
                       'textAlign': 'right'},
            ),
            dcc.Dropdown(
                id='capital-unit',
                options=[{"label": "Million", "value": "million"}, {"label": "Billion", "value": "billion"}],
                value=initial_unit, clearable=False,
                style={'width': '110px', 'fontSize': '10px'},
            ),
            html.Span("CNY", style={'color': 'var(--text-muted)', 'fontSize': '9px'}),
        ], style={'display': 'flex', 'alignItems': 'center', 'gap': '8px'}),

        html.Div([
            html.Span("Max Dur:", style=_INLINE_LBL),
            dcc.Input(
                id='max-duration-input', type='number', value=5, min=0.1, max=50, step=0.1,
                style={'width': '48px', 'background': 'var(--surface-input)',
                       'border': '1px solid var(--border-default)', 'borderRadius': '4px',
                       'padding': '6px 8px', 'fontSize': '10px', 'color': 'var(--text-primary)',
                       'textAlign': 'right'},
            ),
            html.Span(id='max-dv01-display', style={'color': 'var(--text-muted)', 'fontSize': '9px'}),
        ], style={'display': 'flex', 'alignItems': 'center', 'gap': '8px'}),

        html.Div([
            html.Span("Model:", style=_INLINE_LBL),
            html.Span("Deterministic", style={
                'fontSize': '10px', 'color': 'var(--accent-blue)',
                'background': 'var(--surface-input)', 'border': '1px solid var(--accent-blue)',
                'borderRadius': '4px', 'padding': '5px 10px',
            }),
        ], style={'display': 'flex', 'alignItems': 'center', 'gap': '8px'}),
    ], style={'display': 'flex', 'alignItems': 'center', 'gap': '20px', 'flexWrap': 'wrap',
              'padding': '10px 16px', 'borderBottom': '1px solid var(--border-strong)',
              'background': 'rgba(255,255,255,0.02)'})

    # ── LEFT: Asset Selection ───────────────────────────────────────────────
    asset_selection = html.Div([
        html.Div("Asset Selection", style={**_CARD_TITLE, 'marginBottom': '12px'}),
        html.Div([
            html.Span("Type:", style=_INLINE_LBL),
            dcc.RadioItems(
                id='asset-type-selector',
                options=[
                    {'label': ' Rates', 'value': 'Rates'},
                    {'label': ' Credit', 'value': 'Credit'},
                    {'label': ' Cmdty', 'value': 'Commodities'},
                ],
                value=None, inline=True,
                labelStyle={'color': 'var(--text-primary)', 'fontSize': '11px', 'marginRight': '16px'},
                inputStyle={'marginRight': '5px', 'marginLeft': '12px'},
            ),
        ], style={'display': 'flex', 'alignItems': 'center', 'gap': '4px', 'marginBottom': '14px'}),

        html.Div([
            html.Label("Universe:", style={**_INLINE_LBL, 'width': '60px', 'flexShrink': '0'}),
            dcc.Dropdown(
                id='universe-selector', options=[], value=None,
                placeholder="Select...", clearable=True,
                style={'width': '100%', 'fontSize': '11px'},
            ),
        ], id='universe-selection-row', style={'display': 'none', 'marginBottom': '8px',
                                                'alignItems': 'center'}),

        html.Div([
            html.Label("Sector:", style={**_INLINE_LBL, 'width': '60px', 'flexShrink': '0',
                                          'alignSelf': 'flex-start', 'marginTop': '4px'}),
            html.Div([
                dcc.Checklist(
                    id='sector-selector',
                    options=[{'label': f' {s}', 'value': s} for s in ('1Y', '2Y', '5Y', '10Y', '20Y', '30Y')],
                    value=[], inline=True,
                    labelStyle={'color': 'var(--text-primary)', 'fontSize': '11px'},
                    inputStyle={'marginRight': '4px', 'marginLeft': '8px'},
                    style={'marginBottom': '8px'},
                ),
                html.Button('Add to Pool', id='add-to-pool-btn', n_clicks=0, style={
                    'background': '#34d399', 'color': '#06281c', 'padding': '4px 12px',
                    'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer', 'fontSize': '11px',
                    'fontWeight': '700',
                }),
            ], style={'flex': '1'}),
        ], id='sector-selection-row', style={'display': 'none', 'marginBottom': '8px',
                                              'alignItems': 'flex-start'}),

        html.Div([
            html.Label("Items:", style={**_INLINE_LBL, 'width': '60px', 'flexShrink': '0',
                                         'alignSelf': 'flex-start', 'marginTop': '4px'}),
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
                    labelStyle={'color': 'var(--text-primary)', 'fontSize': '11px'},
                    inputStyle={'marginRight': '4px', 'marginLeft': '8px'},
                    style={'marginBottom': '8px'},
                ),
                html.Button('Add to Pool', id='add-commodities-btn', n_clicks=0, style={
                    'background': 'var(--accent-amber)', 'color': '#06281c', 'padding': '4px 12px',
                    'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer', 'fontSize': '11px',
                    'fontWeight': '700',
                }),
            ], style={'flex': '1'}),
        ], id='commodities-confirm-row', style={'display': 'none', 'marginBottom': '8px',
                                                 'alignItems': 'flex-start'}),

        html.Div([
            html.Div([
                html.Span("Asset Pool ", style={'fontSize': '11px', 'fontWeight': '600',
                                                 'color': 'var(--text-primary)'}),
                html.Span(id='pool-count', children=pool_count_text,
                          style={'fontSize': '10px', 'color': 'var(--text-muted)'}),
            ]),
            html.Button('Clear', id='clear-pool-btn', n_clicks=0, style={
                'background': 'rgba(239,68,68,0.15)', 'color': '#f87171', 'padding': '3px 10px',
                'border': '1px solid rgba(239,68,68,0.3)', 'borderRadius': '4px',
                'cursor': 'pointer', 'fontSize': '10px',
            }),
        ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between',
                  'marginBottom': '8px', 'marginTop': '4px'}),
        html.Div(
            id='asset-pool-display', children=pool_display,
            className='asset-pool-list',
            style={'minHeight': '120px', 'overflowY': 'auto', 'display': 'grid',
                   'gridTemplateColumns': 'repeat(4, 1fr)', 'gap': '4px',
                   'border': '1px solid var(--border-default)', 'borderRadius': '5px',
                   'padding': '6px', 'background': 'var(--surface-input)'},
        ),
    ], style={'flex': '1', 'padding': '16px 18px', 'borderRight': '1px solid var(--border-strong)'})

    # ── RIGHT: Risk Budgets ─────────────────────────────────────────────────
    risk_budgets = html.Div([
        html.Div([
            html.Span("Risk Budgets", style=_CARD_TITLE),
            html.Span("Vol from 1Y EWMA · Budget = vol^0.5 · Level > Slope > Curvature · Floor 3%, Cap 25%",
                      style={'fontSize': '9px', 'color': 'var(--text-muted)'}),
        ], style={'display': 'flex', 'alignItems': 'baseline', 'gap': '10px', 'marginBottom': '10px',
                  'flexWrap': 'wrap'}),

        html.Div([
            dcc.RadioItems(
                id='allocation-mode',
                options=[
                    {'label': ' Risk Parity', 'value': 'risk_parity'},
                    {'label': ' Factor Model Scaling', 'value': 'factor_scaling'},
                    {'label': ' User Defined', 'value': 'user_defined'},
                ],
                value='risk_parity', inline=True,
                labelStyle={'color': 'var(--text-primary)', 'fontSize': '11px', 'marginRight': '16px'},
                inputStyle={'marginRight': '5px', 'marginLeft': '12px'},
            ),
            html.Span(id='factor-signals-toggle-status',
                      style={'color': 'var(--text-muted)', 'fontSize': '10px', 'marginLeft': '8px'}),
        ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap'}),

        html.Div(id='risk-budget-header-row',
                 style={'display': 'flex', 'alignItems': 'center', 'padding': '0 8px 4px 8px',
                        'borderBottom': '1px solid var(--border-strong)', 'marginBottom': '4px', 'gap': '4px'}),
        html.Div(
            id='risk-budget-container',
            children=([html.Div("Add assets to see risk factors",
                                 style={'color': 'var(--text-muted)', 'fontStyle': 'italic', 'fontSize': '11px'})]
                      if not initial_pool else []),
            style={'maxHeight': '280px', 'overflowY': 'auto',
                   'padding': '6px 8px'},
        ),
        html.Div("Vol auto-refreshes from 1Y EWMA factor history. Run analysis to refresh RP Max from "
                 "portfolio decomposition.",
                 style={'fontSize': '9px', 'color': 'var(--text-muted)', 'marginTop': '8px',
                        'textAlign': 'right', 'lineHeight': '1.5'}),
    ], style={'flex': '1', 'padding': '16px 18px'})

    configuration_card = html.Div([
        html.Div(html.Span("Configuration", style=_CARD_TITLE),
                 style={'padding': '11px 16px', 'background': 'var(--surface-panel)',
                        'borderBottom': '1px solid var(--border-strong)'}),
        config_bar,
        html.Div([asset_selection, risk_budgets], style={'display': 'flex'}),
    ], style=_CARD_WRAP)

    # ── Results card ─────────────────────────────────────────────────────
    results_card = html.Div([
        html.Div([
            html.Span("Portfolio Allocation Results", style=_CARD_TITLE),
            html.Button(
                'RUN ANALYSIS', id='run-button', n_clicks=initial_n_clicks,
                style={'padding': '7px 18px', 'background': 'var(--accent-blue)', 'color': '#fff',
                       'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer',
                       'fontSize': '10px', 'fontWeight': '700', 'letterSpacing': '0.05em'},
            ),
        ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between',
                  'padding': '11px 16px', 'background': 'var(--surface-panel)',
                  'borderBottom': '1px solid var(--border-strong)'}),

        dcc.Loading(
            type='circle',
            color='var(--accent-blue)',
            style={'minHeight': '80px'},
            children=html.Div([
                html.Div([
                    html.Div(id='status-message', style={'fontSize': '11px', 'color': 'var(--text-primary)'}),
                    html.Div(id='timestamp-display', style={'color': 'var(--text-muted)', 'fontSize': '10px'}),
                ], style={'padding': '7px 16px', 'background': 'rgba(255,255,255,0.02)',
                          'borderBottom': '1px solid var(--border-strong)', 'display': 'flex',
                          'alignItems': 'center', 'justifyContent': 'space-between', 'flexWrap': 'wrap',
                          'gap': '8px'}),
                html.Div(id='portfolio-table-container'),
            ]),
        ),
    ], style=_CARD_WRAP)

    # ── IRDL Hedge Overlay (collapsible) ─────────────────────────────────
    hedge_overlay = html.Details([
        html.Summary([
            html.Span("🛡", style={'marginRight': '8px'}),
            html.Span("IRDL", style={'color': 'var(--accent-blue)', 'fontFamily': 'monospace',
                                      'fontWeight': '700', 'fontSize': '12px'}),
            html.Span(" Hedge", style={'color': 'var(--accent-amber)', 'fontWeight': '700', 'fontSize': '12px'}),
            html.Span(" Overlay", style={'color': 'var(--text-primary)', 'fontWeight': '600', 'fontSize': '12px'}),
            html.Span("  ·  optional post-optimisation duration hedge via bond futures or pay-fixed IRS",
                      style={'color': 'var(--text-muted)', 'fontStyle': 'italic', 'fontSize': '10px'}),
        ], style={
            'padding': '10px 16px', 'cursor': 'pointer',
            'listStyleType': 'none', 'WebkitAppearance': 'none', 'MozAppearance': 'none',
            'background': 'var(--surface-panel)', 'userSelect': 'none', 'display': 'flex', 'alignItems': 'center',
        }),
        html.Div([
            html.Div([
                html.Div([
                    html.Label("Hedge Ratio", style={
                        'color': 'var(--text-muted)', 'fontSize': '10px', 'marginBottom': '4px', 'display': 'block',
                    }),
                    dcc.Slider(
                        id='irdl-hedge-ratio',
                        min=0, max=100, step=5, value=50,
                        marks={0: '0%', 25: '25%', 50: '50%', 75: '75%', 100: '100%'},
                        tooltip={'placement': 'bottom', 'always_visible': True},
                    ),
                ], style={'flex': '2', 'minWidth': '220px'}),
                html.Div([
                    html.Label("Instrument", style={
                        'color': 'var(--text-muted)', 'fontSize': '10px', 'marginBottom': '4px', 'display': 'block',
                    }),
                    dcc.Dropdown(
                        id='irdl-hedge-instrument',
                        options=[
                            {'label': 'Bond Futures (Short)', 'value': 'futures'},
                            {'label': 'Pay-fixed IRS', 'value': 'irs'},
                        ],
                        value='futures', clearable=False, style={'fontSize': '11px'},
                    ),
                ], style={'flex': '1', 'minWidth': '180px'}),
                html.Div([
                    html.Label("IRS Tenor", style={
                        'color': 'var(--text-muted)', 'fontSize': '10px', 'marginBottom': '4px', 'display': 'block',
                    }),
                    dcc.Dropdown(
                        id='irdl-hedge-irs-maturity',
                        options=[
                            {'label': '2Y IRS', 'value': '2Y'},
                            {'label': '5Y IRS', 'value': '5Y'},
                            {'label': '10Y IRS', 'value': '10Y'},
                            {'label': '30Y IRS', 'value': '30Y'},
                        ],
                        value='10Y', clearable=False, style={'fontSize': '11px'},
                    ),
                ], style={'flex': '0 0 130px'}),
            ], style={'display': 'flex', 'gap': '20px', 'alignItems': 'flex-end',
                      'flexWrap': 'wrap', 'marginBottom': '16px'}),

            html.Div([
                html.Span("DV01 Override (CNY/bp per contract, blank = default):",
                          style={'color': 'var(--text-muted)', 'fontSize': '10px',
                                 'marginRight': '12px', 'alignSelf': 'center'}),
                *[
                    html.Div([
                        html.Label(cty, style={'color': 'var(--text-muted)', 'fontSize': '10px',
                                                'display': 'block', 'marginBottom': '2px'}),
                        dcc.Input(
                            id={'type': 'irdl-dv01-override', 'index': cty},
                            type='number', placeholder=str(default), debounce=True,
                            style={'width': '72px', 'padding': '4px 6px',
                                   'background': 'var(--surface-input)', 'color': 'var(--text-primary)',
                                   'border': '1px solid var(--border-default)',
                                   'borderRadius': '4px', 'fontSize': '11px'},
                        ),
                    ], style={'textAlign': 'center'})
                    for cty, default in [('CN', 800), ('US', 640), ('DE', 750), ('JP', 560), ('UK', 600)]
                ],
            ], style={'display': 'flex', 'gap': '12px', 'alignItems': 'flex-end',
                      'marginBottom': '16px', 'flexWrap': 'wrap'}),

            dcc.Loading(
                type='circle',
                color='var(--accent-blue)',
                style={'minHeight': '60px'},
                children=html.Div(id='irdl-hedge-ticket-container', style={'minHeight': '60px'}),
            ),
            html.Div(
                "Hedge overlay is advisory only — it does not change portfolio weights. "
                "Negative contracts = short futures; PAY FIXED = pay fixed rate in IRS.",
                style={'color': 'var(--text-muted)', 'fontSize': '10px', 'marginTop': '8px', 'fontStyle': 'italic'},
            ),
        ], style={'padding': '14px 16px', 'borderTop': '1px solid var(--border-strong)'}),
    ], style=_CARD_WRAP)

    return html.Div([
        dcc.Store(id='portfolio-data-store'),
        dcc.Store(id='asset-pool-store', data=initial_pool),
        dcc.Store(id='rp-budget-store', data={}),
        dcc.Store(id='allocation-results-store', data={}),
        dcc.Store(id='factor-signals-snapshot-store', data={}),

        html.Div([
            html.H1("Beta Book Portfolio", style={'margin': '0 0 4px', 'fontSize': '20px',
                                                    'fontWeight': '600', 'color': 'var(--text-primary)'}),
            html.Div("Asset selection · risk budgets · optimised allocation",
                     style={'fontSize': '11px', 'color': 'var(--text-muted)'}),
        ]),

        configuration_card,
        results_card,
        hedge_overlay,

    ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '12px', 'padding': '16px', 'margin': '10px'})
