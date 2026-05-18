# -*- coding: utf-8 -*-
"""Factor (Regime) tab layout."""

from __future__ import annotations

from dash import dcc, html

from ..data import THEME, SELECTED_FACTOR_POOL


def build_multiasset_factor_layout():
    """Build the layout for the Factor (Regime) tab."""
    return html.Div([

        # Hidden store to persist factor selections across tab switches
        dcc.Store(id='factor-selection-store', storage_type='session', data={
            'ir': SELECTED_FACTOR_POOL['ir_factors'],
            'sp': SELECTED_FACTOR_POOL['sp_factors'],
            'fx': SELECTED_FACTOR_POOL['fx_factors'],
            'cmd': SELECTED_FACTOR_POOL['cmd_factors']
        }),

        # Factor Selection Panel at the top
        html.Div([
            html.H5("🎯 Factor Selection Pool", style={'color': THEME['text_main'], 'marginBottom': '15px'}),
            html.P("Select factors to include in correlation analysis:", style={'color': THEME['text_sub'], 'fontSize': '13px', 'marginBottom': '10px'}),

            # Interest Rate Factors
            html.Div([
                html.H6("📊 Interest Rates (IR)", style={'color': THEME['accent'], 'marginBottom': '8px', 'fontSize': '14px'}),
                dcc.Checklist(
                    id='factor-selection-ir',
                    options=[
                        {'label': ' IRDL.CN (China Level)', 'value': 'IRDL.CN'},
                        {'label': ' IRDL.US (US Level)', 'value': 'IRDL.US'},
                        {'label': ' IRDL.EU (Europe Level)', 'value': 'IRDL.EU'},
                        {'label': ' IRDL.JP (Japan Level)', 'value': 'IRDL.JP'},
                        {'label': ' IRDL.UK (UK Level)', 'value': 'IRDL.UK'},
                        {'label': ' IRSL.CN (China Slope)', 'value': 'IRSL.CN'},
                        {'label': ' IRSL.US (US Slope)', 'value': 'IRSL.US'},
                        {'label': ' IRSL.EU (Europe Slope)', 'value': 'IRSL.EU'},
                        {'label': ' IRSL.JP (Japan Slope)', 'value': 'IRSL.JP'},
                        {'label': ' IRSL.UK (UK Slope)', 'value': 'IRSL.UK'},
                    ],
                    value=SELECTED_FACTOR_POOL['ir_factors'],
                    inline=True,
                    labelStyle={'color': THEME['text_main'], 'marginRight': '15px', 'fontSize': '12px'},
                    inputStyle={'marginRight': '5px'},
                    style={'marginBottom': '12px'}
                ),
            ], style={'marginBottom': '15px'}),

            # Spread Factors
            html.Div([
                html.H6("📈 Spreads (SP)", style={'color': THEME['accent'], 'marginBottom': '8px', 'fontSize': '14px'}),
                dcc.Checklist(
                    id='factor-selection-sp',
                    options=[
                        {'label': ' SPDL.IRS (IRS Level)', 'value': 'SPDL.IRS'},
                        {'label': ' SPSL.IRS (IRS Slope)', 'value': 'SPSL.IRS'},
                        {'label': ' SPDL.CDB (CDB Level)', 'value': 'SPDL.CDB'},
                        {'label': ' SPSL.CDB (CDB Slope)', 'value': 'SPSL.CDB'},
                        {'label': ' SPDL.ICP (ICP Level)', 'value': 'SPDL.ICP'},
                    ],
                    value=SELECTED_FACTOR_POOL['sp_factors'],
                    inline=True,
                    labelStyle={'color': THEME['text_main'], 'marginRight': '15px', 'fontSize': '12px'},
                    inputStyle={'marginRight': '5px'},
                    style={'marginBottom': '12px'}
                ),
            ], style={'marginBottom': '15px'}),

            # FX Factors
            html.Div([
                html.H6("💱 FX", style={'color': THEME['accent'], 'marginBottom': '8px', 'fontSize': '14px'}),
                dcc.Checklist(
                    id='factor-selection-fx',
                    options=[
                        {'label': ' FXDL.USDCNY', 'value': 'FXDL.USDCNY'},
                        {'label': ' FXDL.EURCNY', 'value': 'FXDL.EURCNY'},
                        {'label': ' FXDL.JPYCNY', 'value': 'FXDL.JPYCNY'},
                        {'label': ' FXDL.GBPCNY', 'value': 'FXDL.GBPCNY'},
                    ],
                    value=SELECTED_FACTOR_POOL['fx_factors'],
                    inline=True,
                    labelStyle={'color': THEME['text_main'], 'marginRight': '15px', 'fontSize': '12px'},
                    inputStyle={'marginRight': '5px'},
                    style={'marginBottom': '12px'}
                ),
            ], style={'marginBottom': '15px'}),

            # Commodity Factors
            html.Div([
                html.H6("🪙 Commodities (CMD)", style={'color': THEME['accent'], 'marginBottom': '8px', 'fontSize': '14px'}),
                dcc.Checklist(
                    id='factor-selection-cmd',
                    options=[
                        {'label': ' CMDL.AU (Gold)', 'value': 'CMDL.AU'},
                        {'label': ' CMDL.AL (Aluminium)', 'value': 'CMDL.AL'},
                        {'label': ' CMDL.CU (Copper)', 'value': 'CMDL.CU'},
                        {'label': ' CMDL.SC (Crude Oil)', 'value': 'CMDL.SC'},
                    ],
                    value=SELECTED_FACTOR_POOL['cmd_factors'],
                    inline=True,
                    labelStyle={'color': THEME['text_main'], 'marginRight': '15px', 'fontSize': '12px'},
                    inputStyle={'marginRight': '5px'},
                    style={'marginBottom': '12px'}
                ),
            ], style={'marginBottom': '10px'}),

            html.Div([
                html.Span(id='factor-pool-count', style={'color': THEME['text_sub'], 'fontSize': '12px', 'fontStyle': 'italic'}),
            ]),

        ], style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'borderRadius': '5px', 'border': f'1px solid {THEME["table_header"]}', 'marginBottom': '20px'}),

                # New Correlation Analysis Section
        html.Div([
             html.H5("Cross-Asset Correlation Analysis", style={'color': THEME['text_main'], 'marginBottom': '15px'}),
             html.Div([
                html.Label("Lookback Period:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                dcc.Dropdown(
                    id='correlation-period-selector',
                    options=[
                        {'label': '3 Months', 'value': '3M'},
                        {'label': '6 Months', 'value': '6M'},
                        {'label': '1 Year', 'value': '1Y'},
                    ],
                    value='3M',
                    clearable=False,
                    style={'width': '150px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'marginRight': '20px'}
                ),
                html.Label("Top Pairs:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                dcc.Dropdown(
                    id='correlation-top-pairs-selector',
                    options=[
                        {'label': '5', 'value': 5},
                        {'label': '10', 'value': 10},
                        {'label': '15', 'value': 15},
                        {'label': '20', 'value': 20},
                    ],
                    value=10,
                    clearable=False,
                    style={'width': '100px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'marginRight': '20px'}
                ),
                html.Button(
                    "Rank Correlations",
                    id='rank-correlations-btn',
                    n_clicks=0,
                    style={'backgroundColor': THEME['accent'], 'color': 'white', 'padding': '5px 15px', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer', 'fontWeight': 'bold'}
                ),
             ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '15px'}),

             # Store for tracking the lowest correlation factors
             dcc.Store(id='low-corr-factors-store', data=[]),

             dcc.Loading(
                 id="loading-correlations",
                 type="default",
                 children=html.Div(id='correlation-results-container')
             )
        ], style={'maxWidth': '800px', 'margin': '0 auto 20px auto', 'padding': '15px', 'backgroundColor': THEME['bg_card'], 'borderRadius': '5px', 'border': f'1px solid {THEME["table_header"]}'}),

        html.H4("Risk Factor Historical Performance", style={'textAlign': 'center', 'color': THEME['text_main'], 'marginTop': '10px', 'marginBottom': '20px'}),

        # Cascaded dropdown selection
        html.Div([
            # Row 1: Asset Class Selection
            html.Div([
                html.Label("Asset Class:", style={'fontWeight': 'bold', 'marginRight': '10px', 'width': '100px', 'color': THEME['text_main']}),
                dcc.Dropdown(
                    id='factor-asset-class-selector',
                    options=[
                        {'label': 'Rates', 'value': 'Rates'},
                        {'label': 'Spread', 'value': 'Spread'},
                        {'label': 'FX', 'value': 'FX'},
                        {'label': 'Commodities', 'value': 'Commodities'},
                    ],
                    value=None,
                    placeholder="Select asset class...",
                    clearable=True,
                    style={'flex': '1', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                )
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'}),

            # Row 2: Region/Type Selection
            html.Div([
                html.Label("Region/Type:", style={'fontWeight': 'bold', 'marginRight': '10px', 'width': '100px', 'color': THEME['text_main']}),
                dcc.Dropdown(
                    id='factor-region-selector',
                    options=[],
                    value=None,
                    placeholder="Select region or type...",
                    clearable=True,
                    style={'flex': '1', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                )
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'}),

            # Row 3: Factor Selection
            html.Div([
                html.Label("Factors:", style={'fontWeight': 'bold', 'marginRight': '10px', 'width': '100px', 'color': THEME['text_main']}),
                dcc.Dropdown(
                    id='factor-type-selector',
                    options=[],
                    value=[],
                    multi=True,
                    placeholder="Select factors...",
                    style={'flex': '1', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                )
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'}),
        ], style={'maxWidth': '800px', 'margin': '0 auto 20px auto', 'padding': '15px', 'backgroundColor': THEME['bg_card'], 'borderRadius': '5px', 'border': f'1px solid {THEME["table_header"]}'}),


        dcc.Graph(id='factor-history-chart'),

    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px', 'borderRadius': '5px', 'margin': '10px'})
