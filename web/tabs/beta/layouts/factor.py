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
            'fx': SELECTED_FACTOR_POOL['fx_factors'],
            'cmd': SELECTED_FACTOR_POOL['cmd_factors']
        }),

        # Factor Selection Panel at the top
        html.Div([
            html.H5("🎯 Factor Selection Pool", style={'color': THEME['text_main'], 'marginBottom': '15px'}),
            html.P("Select factors to include in correlation analysis:", style={'color': THEME['text_sub'], 'fontSize': '13px', 'marginBottom': '10px'}),

            # Interest Rate Factors — grouped by domicile
            html.Div([
                html.H6("📊 Interest Rates (IR)", style={'color': THEME['accent'], 'marginBottom': '6px', 'fontSize': '14px'}),
                html.P("Each domicile covers: IRDL (Level · Bullish/Bearish), IRSL (Slope · Flattener/Steepener), IRCV (Curvature · Concave/Convex)",
                       style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '10px', 'fontStyle': 'italic'}),
                html.Div([
                    # ── CN ──────────────────────────────────────────
                    html.Div([
                        html.Div("🇨🇳 CN", style={'fontSize': '12px', 'fontWeight': 'bold',
                                                   'color': THEME['accent'], 'marginBottom': '6px',
                                                   'textAlign': 'center'}),
                        dcc.Checklist(
                            id='factor-selection-ir-cn',
                            options=[{'label': ' IRDL', 'value': 'IRDL.CN'},
                                     {'label': ' IRSL', 'value': 'IRSL.CN'},
                                     {'label': ' IRCV', 'value': 'IRCV.CN'}],
                            value=[v for v in SELECTED_FACTOR_POOL['ir_factors'] if v.endswith('.CN')],
                            labelStyle={'display': 'block', 'color': THEME['text_main'],
                                        'fontSize': '12px', 'marginBottom': '3px'},
                            inputStyle={'marginRight': '5px'},
                        ),
                    ], style={'backgroundColor': THEME['bg_input'],
                              'border': f'1px solid {THEME["table_header"]}',
                              'borderRadius': '6px', 'padding': '10px 14px', 'minWidth': '90px'}),
                    # ── US ──────────────────────────────────────────
                    html.Div([
                        html.Div("🇺🇸 US", style={'fontSize': '12px', 'fontWeight': 'bold',
                                                   'color': THEME['accent'], 'marginBottom': '6px',
                                                   'textAlign': 'center'}),
                        dcc.Checklist(
                            id='factor-selection-ir-us',
                            options=[{'label': ' IRDL', 'value': 'IRDL.US'},
                                     {'label': ' IRSL', 'value': 'IRSL.US'},
                                     {'label': ' IRCV', 'value': 'IRCV.US'}],
                            value=[v for v in SELECTED_FACTOR_POOL['ir_factors'] if v.endswith('.US')],
                            labelStyle={'display': 'block', 'color': THEME['text_main'],
                                        'fontSize': '12px', 'marginBottom': '3px'},
                            inputStyle={'marginRight': '5px'},
                        ),
                    ], style={'backgroundColor': THEME['bg_input'],
                              'border': f'1px solid {THEME["table_header"]}',
                              'borderRadius': '6px', 'padding': '10px 14px', 'minWidth': '90px'}),
                    # ── EU ──────────────────────────────────────────
                    html.Div([
                        html.Div("🇪🇺 EU", style={'fontSize': '12px', 'fontWeight': 'bold',
                                                   'color': THEME['accent'], 'marginBottom': '6px',
                                                   'textAlign': 'center'}),
                        dcc.Checklist(
                            id='factor-selection-ir-eu',
                            options=[{'label': ' IRDL', 'value': 'IRDL.EU'},
                                     {'label': ' IRSL', 'value': 'IRSL.EU'},
                                     {'label': ' IRCV', 'value': 'IRCV.EU'}],
                            value=[v for v in SELECTED_FACTOR_POOL['ir_factors'] if v.endswith('.EU')],
                            labelStyle={'display': 'block', 'color': THEME['text_main'],
                                        'fontSize': '12px', 'marginBottom': '3px'},
                            inputStyle={'marginRight': '5px'},
                        ),
                    ], style={'backgroundColor': THEME['bg_input'],
                              'border': f'1px solid {THEME["table_header"]}',
                              'borderRadius': '6px', 'padding': '10px 14px', 'minWidth': '90px'}),
                    # ── JP ──────────────────────────────────────────
                    html.Div([
                        html.Div("🇯🇵 JP", style={'fontSize': '12px', 'fontWeight': 'bold',
                                                   'color': THEME['accent'], 'marginBottom': '6px',
                                                   'textAlign': 'center'}),
                        dcc.Checklist(
                            id='factor-selection-ir-jp',
                            options=[{'label': ' IRDL', 'value': 'IRDL.JP'},
                                     {'label': ' IRSL', 'value': 'IRSL.JP'},
                                     {'label': ' IRCV', 'value': 'IRCV.JP'}],
                            value=[v for v in SELECTED_FACTOR_POOL['ir_factors'] if v.endswith('.JP')],
                            labelStyle={'display': 'block', 'color': THEME['text_main'],
                                        'fontSize': '12px', 'marginBottom': '3px'},
                            inputStyle={'marginRight': '5px'},
                        ),
                    ], style={'backgroundColor': THEME['bg_input'],
                              'border': f'1px solid {THEME["table_header"]}',
                              'borderRadius': '6px', 'padding': '10px 14px', 'minWidth': '90px'}),
                    # ── UK ──────────────────────────────────────────
                    html.Div([
                        html.Div("🇬🇧 UK", style={'fontSize': '12px', 'fontWeight': 'bold',
                                                   'color': THEME['accent'], 'marginBottom': '6px',
                                                   'textAlign': 'center'}),
                        dcc.Checklist(
                            id='factor-selection-ir-uk',
                            options=[{'label': ' IRDL', 'value': 'IRDL.UK'},
                                     {'label': ' IRSL', 'value': 'IRSL.UK'},
                                     {'label': ' IRCV', 'value': 'IRCV.UK'}],
                            value=[v for v in SELECTED_FACTOR_POOL['ir_factors'] if v.endswith('.UK')],
                            labelStyle={'display': 'block', 'color': THEME['text_main'],
                                        'fontSize': '12px', 'marginBottom': '3px'},
                            inputStyle={'marginRight': '5px'},
                        ),
                    ], style={'backgroundColor': THEME['bg_input'],
                              'border': f'1px solid {THEME["table_header"]}',
                              'borderRadius': '6px', 'padding': '10px 14px', 'minWidth': '90px'}),
                ], style={'display': 'flex', 'gap': '10px', 'flexWrap': 'wrap',
                          'marginBottom': '6px'}),
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
                        {'label': ' CMDL.AG (Silver)', 'value': 'CMDL.AG'},
                        {'label': ' CMDL.AL (Aluminium)', 'value': 'CMDL.AL'},
                        {'label': ' CMDL.CU (Copper)', 'value': 'CMDL.CU'},
                        {'label': ' CMDL.ZN (Zinc)', 'value': 'CMDL.ZN'},
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

        # ── Train Model & Predict ─────────────────────────────────────────
        html.Div([
            html.H5("🤖 Train Model & Predict", style={'color': THEME['text_main'], 'marginBottom': '6px'}),
            html.P(
                "Train the factor model on data up to the first day of the current month "
                "(no recent daily data — reduces overfitting). "
                "Outputs the latest signal state and top driving indicators.",
                style={'color': THEME['text_sub'], 'fontSize': '12px',
                       'marginBottom': '12px', 'fontStyle': 'italic'},
            ),
            html.Div([
                html.Label("Train (months):", style={'fontWeight': 'bold', 'marginRight': '4px',
                                                     'color': THEME['text_main'], 'fontSize': '12px'}),
                dcc.Input(id='factor-fm-train', type='number', value=12, min=3,
                          style={'width': '55px', 'marginRight': '10px', 'padding': '4px',
                                 'borderRadius': '4px', 'border': '1px solid #444',
                                 'backgroundColor': '#fff', 'color': '#000'}),
                html.Label("IC thr:", style={'fontWeight': 'bold', 'marginRight': '4px',
                                             'color': THEME['text_main'], 'fontSize': '12px'}),
                dcc.Input(id='factor-fm-ic', type='number', value=0.05, step=0.01, min=0.01,
                          style={'width': '60px', 'marginRight': '10px', 'padding': '4px',
                                 'borderRadius': '4px', 'border': '1px solid #444',
                                 'backgroundColor': '#fff', 'color': '#000'}),
                html.Label("Top N:", style={'fontWeight': 'bold', 'marginRight': '4px',
                                            'color': THEME['text_main'], 'fontSize': '12px'}),
                dcc.Input(id='factor-fm-topn', type='number', value=8, min=1,
                          style={'width': '55px', 'marginRight': '10px', 'padding': '4px',
                                 'borderRadius': '4px', 'border': '1px solid #444',
                                 'backgroundColor': '#fff', 'color': '#000'}),
                    html.Button(
                      "Train Model", id='factor-train-btn', n_clicks=0,
                      title="Train model using data up to the first day of the current month. "
                          "No recent daily data — reduces overfitting.",
                      style={'backgroundColor': '#7B68EE', 'color': 'white',
                           'padding': '7px 14px', 'border': 'none', 'borderRadius': '5px',
                           'cursor': 'pointer', 'fontSize': '12px', 'fontWeight': 'bold',
                           'marginRight': '8px'}),
                    html.Button(
                      "Predict", id='factor-predict-btn', n_clicks=0,
                      title="Use the latest saved model to refresh the current signal view. "
                          "If parameters changed, retrain first.",
                      style={'backgroundColor': THEME['accent'], 'color': 'white',
                           'padding': '7px 14px', 'border': 'none', 'borderRadius': '5px',
                           'cursor': 'pointer', 'fontSize': '12px', 'fontWeight': 'bold',
                           'marginRight': '10px'}),
            ], style={'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap',
                      'gap': '4px', 'marginBottom': '12px'}),
            dcc.Loading(
                type='circle',
                color=THEME['accent'],
                style={'minHeight': '80px'},
                children=html.Div([
                    html.Div(id='factor-train-status',
                             style={'color': THEME['text_sub'], 'fontSize': '12px',
                                    'marginBottom': '8px'}),
                    html.Div(id='factor-signal-container', style={'minHeight': '80px'}),
                ]),
            ),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'borderRadius': '5px',
                  'border': f'1px solid {THEME["table_header"]}', 'marginBottom': '20px'}),

                # Correlation Analysis Section
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
                    value='1Y',
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
                 type="circle",
                 color=THEME['accent'],
                 style={'minHeight': '60px'},
                 children=html.Div(id='correlation-results-container'),
             )
        ], style={'maxWidth': '800px', 'margin': '0 auto 20px auto', 'padding': '15px', 'backgroundColor': THEME['bg_card'], 'borderRadius': '5px', 'border': f'1px solid {THEME["table_header"]}'}),

    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px', 'borderRadius': '5px', 'margin': '10px'})
