# -*- coding: utf-8 -*-
"""Factor (Regime) tab layout."""

from __future__ import annotations

from dash import dcc, html

from ..data import THEME, SELECTED_FACTOR_POOL
from ...atlas_components import card


def build_multiasset_factor_layout():
    """Build the layout for the Factor (Regime) tab."""
    return html.Div([

        # Hidden store to persist factor selections across tab switches
        dcc.Store(id='factor-selection-store', storage_type='session', data={
            'ir': SELECTED_FACTOR_POOL['ir_factors'],
            'fx': SELECTED_FACTOR_POOL['fx_factors'],
            'cmd': SELECTED_FACTOR_POOL['cmd_factors'],
            'eq': SELECTED_FACTOR_POOL['eq_factors'],
        }),

        # Factor Selection Panel at the top
        html.Div([
            html.H5("🎯 Factor Selection Pool", style={'color': THEME['text_main'], 'marginBottom': '15px'}),
            html.P("Select factors to include in correlation analysis:", style={'color': THEME['text_sub'], 'fontSize': '13px', 'marginBottom': '10px'}),

            # Interest Rate Factors — grouped by domicile
            html.Div([
                html.H6("📊 Interest Rates (IR)", className='factor-pool-section__heading'),
                html.P("Each domicile covers: IRDL (Level · Bullish/Bearish), IRSL (Slope · Flattener/Steepener), IRCV (Curvature · Concave/Convex)",
                       className='factor-pool-section__note'),
                html.Div([
                    html.Div([
                        html.Div(f"{flag} {code}", className='ir-country-grid__col-head'),
                        dcc.Checklist(
                            id=f'factor-selection-ir-{code.lower()}',
                            options=[{'label': ' IRDL', 'value': f'IRDL.{code}'},
                                     {'label': ' IRSL', 'value': f'IRSL.{code}'},
                                     {'label': ' IRCV', 'value': f'IRCV.{code}'}],
                            value=[v for v in SELECTED_FACTOR_POOL['ir_factors'] if v.endswith(f'.{code}')],
                            labelStyle={'display': 'block', 'color': THEME['text_main'],
                                        'fontSize': '12px', 'marginBottom': '3px'},
                            inputStyle={'marginRight': '5px'},
                        ),
                    ]) for flag, code in [
                        ('🇨🇳', 'CN'), ('🇺🇸', 'US'), ('🇪🇺', 'EU'), ('🇯🇵', 'JP'), ('🇬🇧', 'UK'),
                    ]
                ], className='ir-country-grid'),
            ], className='factor-pool-section'),

            # FX Factors
            html.Div([
                html.H6("💱 Foreign Exchange (FX)", className='factor-pool-section__heading'),
                dcc.Checklist(
                    id='factor-selection-fx',
                    options=[
                        {'label': ' FXDL.USDCNY', 'value': 'FXDL.USDCNY'},
                        {'label': ' FXDL.EURCNY', 'value': 'FXDL.EURCNY'},
                        {'label': ' FXDL.JPYCNY', 'value': 'FXDL.JPYCNY'},
                        {'label': ' FXDL.GBPCNY', 'value': 'FXDL.GBPCNY'},
                    ],
                    value=SELECTED_FACTOR_POOL['fx_factors'],
                    labelStyle={'color': THEME['text_main'], 'fontSize': '12px'},
                    inputStyle={'marginRight': '5px'},
                    className='factor-inline-row',
                ),
            ], className='factor-pool-section'),

            # Equity Factors
            html.Div([
                html.H6("📈 Equities (EQ)", className='factor-pool-section__heading'),
                html.P("CSI equity index futures — price return factors",
                       className='factor-pool-section__note'),
                dcc.Checklist(
                    id='factor-selection-eq',
                    options=[
                        {'label': ' EQDL.IF (CSI 300)', 'value': 'EQDL.IF'},
                        {'label': ' EQDL.IC (CSI 500)', 'value': 'EQDL.IC'},
                        {'label': ' EQDL.IH (SSE 50)',  'value': 'EQDL.IH'},
                        {'label': ' EQDL.IM (CSI 1000)', 'value': 'EQDL.IM'},
                    ],
                    value=SELECTED_FACTOR_POOL['eq_factors'],
                    labelStyle={'color': THEME['text_main'], 'fontSize': '12px'},
                    inputStyle={'marginRight': '5px'},
                    className='factor-inline-row',
                ),
            ], className='factor-pool-section'),

            # Commodity Factors
            html.Div([
                html.H6("🪙 Commodities (CM)", className='factor-pool-section__heading'),
                dcc.Checklist(
                    id='factor-selection-cmd',
                    options=[
                        {'label': ' CMDL.AU (Gold)',        'value': 'CMDL.AU'},
                        {'label': ' CMDL.AG (Silver)',      'value': 'CMDL.AG'},
                        {'label': ' CMDL.AL (Aluminium)',   'value': 'CMDL.AL'},
                        {'label': ' CMDL.CU (Copper)',      'value': 'CMDL.CU'},
                        {'label': ' CMDL.ZN (Zinc)',        'value': 'CMDL.ZN'},
                        {'label': ' CMDL.SC (Crude Oil)',   'value': 'CMDL.SC'},
                        {'label': ' CMDL.RB (Rebar)',       'value': 'CMDL.RB'},
                        {'label': ' CMDL.LC (Live Hog)',    'value': 'CMDL.LC'},
                        {'label': ' CMDL.SA (Soda Ash)',    'value': 'CMDL.SA'},
                        {'label': ' CMDL.JM (Coking Coal)', 'value': 'CMDL.JM'},
                        {'label': ' CMDL.EC (Euro Gas)',    'value': 'CMDL.EC'},
                    ],
                    value=SELECTED_FACTOR_POOL['cmd_factors'],
                    labelStyle={'color': THEME['text_main'], 'fontSize': '12px',
                                'display': 'flex', 'alignItems': 'center'},
                    inputStyle={'marginRight': '5px'},
                    className='cmd-grid',
                ),
            ], className='factor-pool-section'),

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
                                 'borderRadius': '4px', 'border': f'1px solid {THEME["bg_input"]}',
                                 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'],
                                 'MozAppearance': 'textfield', 'appearance': 'textfield'}),
                html.Label("IC thr:", style={'fontWeight': 'bold', 'marginRight': '4px',
                                             'color': THEME['text_main'], 'fontSize': '12px'}),
                dcc.Input(id='factor-fm-ic', type='number', value=0.05, step=0.01, min=0.01,
                          style={'width': '60px', 'marginRight': '10px', 'padding': '4px',
                                 'borderRadius': '4px', 'border': f'1px solid {THEME["bg_input"]}',
                                 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'],
                                 'MozAppearance': 'textfield', 'appearance': 'textfield'}),
                html.Label("Top N:", style={'fontWeight': 'bold', 'marginRight': '4px',
                                            'color': THEME['text_main'], 'fontSize': '12px'}),
                dcc.Input(id='factor-fm-topn', type='number', value=8, min=1,
                          style={'width': '55px', 'marginRight': '10px', 'padding': '4px',
                                 'borderRadius': '4px', 'border': f'1px solid {THEME["bg_input"]}',
                                 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'],
                                 'MozAppearance': 'textfield', 'appearance': 'textfield'}),
                    html.Button(
                      "Train Model", id='factor-train-btn', n_clicks=0,
                      title="Train model using data up to the first day of the current month. "
                          "No recent daily data — reduces overfitting.",
                      style={'backgroundColor': '#7c70d6', 'color': 'white',
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
        ], style={'margin': '0 0 20px 0', 'padding': '15px', 'backgroundColor': THEME['bg_card'], 'borderRadius': '5px', 'border': f'1px solid {THEME["table_header"]}'}),

    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px', 'borderRadius': '5px', 'margin': '10px'})
