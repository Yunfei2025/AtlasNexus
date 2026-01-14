# -*- coding: utf-8 -*-
"""
Bridge for Multi-Asset Dashboard tabs into AtlasNexus Daily.
This module adapts the layouts and callbacks from `multiasset/dashboard.py` and `multiasset/layout.py`
for use within the AtlasNexus Daily application.
"""
from __future__ import annotations

import dash
from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import os
from datetime import datetime
from dateutil.relativedelta import relativedelta
import traceback

# Import from multiasset package
from multiasset.data import (
    load_raw_market_data, calculate_daily_returns_series,
    get_asset_type, get_universe, get_sector
)
from multiasset.layout import prepare_portfolio_table
from multiasset.storage import load_last_asset_pool
from multiasset.main import run_risk_parity_allocation, create_custom_portfolio
from multiasset.storage import save_asset_pool
from multiasset.risk_loader import RiskFactorLoader
from multiasset.factor_optimizer import PCAFactorRiskParityOptimizer
from settings.paths import DIR_INPUT

# --- Theme Constants (AtlasNexus Dark Blue) ---
THEME = {
    'bg_main': '#082255',       # Main Deep Blue Background
    'bg_card': '#0c2b64',       # Slightly lighter blue for cards
    'bg_input': '#112e66',      # Input/Dropdown container background
    'text_main': '#ffffff',     # Main text
    'text_sub': '#aab0c0',      # Secondary text
    'accent': '#3498db',        # Bright blue accent
    'success': '#00cc96',       # Green
    'warning': '#f39c12',       # Orange
    'danger': '#ef553b',        # Red
    'table_header': '#061E44',  # Dark header
    'table_row_odd': '#0c2b64', # Dark row
    'table_row_even': '#082255',# Darker row
    'chart_template': 'plotly_dark'
}

# Global state for allocation results
ALLOCATION_RESULTS = {
    'summary': None,
    'factor_exposures': None,
    'factor_risk': None,
    'portfolio': None,
    'timestamp': None
}

# --- Layout Builders ---

def build_multiasset_factor_layout():
    """Build the layout for the Factor (Regime) tab."""
    return html.Div([

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
                html.Button(
                    "Rank Correlations",
                    id='rank-correlations-btn',
                    n_clicks=0,
                    style={'backgroundColor': THEME['accent'], 'color': 'white', 'padding': '5px 15px', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer', 'fontWeight': 'bold'}
                ),
             ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '15px'}),
             
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
        

        dcc.Graph(id='factor-history-chart')
    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px', 'borderRadius': '5px', 'margin': '10px'})


def build_multiasset_portfolio_layout():
    """Build the layout for the Portfolio (Allocation) tab."""
    
    # Load last saved state
    try:
        last_run_data = load_last_asset_pool()
    except Exception:
        last_run_data = {}
        
    initial_pool = []
    initial_n_clicks = 0
    initial_capital = 100
    initial_unit = 'million'
    
    if last_run_data:
        if 'asset_pool' in last_run_data:
            initial_pool = last_run_data['asset_pool']
            if initial_pool:
                initial_n_clicks = 1
        
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

        html.Div([
            # Section 1: Configuration Header & Capital
            html.Div([
                html.Div([
                    html.H5("Configuration", style={'margin': '0', 'color': THEME['text_main'], 'fontSize': '16px'}),
                ], style={'flex': '1'}),
                
                html.Div([
                    html.Label("Total Capital:", style={'fontWeight': 'bold', 'marginRight': '10px', 'fontSize': '14px', 'color': THEME['text_main']}),
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
                        style={'width': '100px', 'marginRight': '5px', 'fontSize': '13px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                    ),
                    html.Span("CNY", style={'color': THEME['text_sub'], 'fontSize': '14px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),
            ], style={'display': 'flex', 'alignItems': 'center', 'padding': '15px 20px', 'backgroundColor': THEME['bg_input'], 'borderBottom': f'1px solid {THEME["table_header"]}', 'borderRadius': '8px 8px 0 0'}),
            
            # Section 2: Main Content (Selection + Pool + Action)
            html.Div([
                # Column 1: Asset Selection
                html.Div([
                    html.H6("Asset Selection", style={'color': THEME['text_main'], 'marginTop': '0', 'marginBottom': '15px'}),
                    
                    # Step 1: Type
                    html.Div([
                        html.Label("Type:", style={'fontWeight': 'bold', 'width': '70px', 'fontSize': '13px', 'color': THEME['text_main']}),
                        dcc.RadioItems(
                            id='asset-type-selector',
                            options=[
                                {'label': ' Rates', 'value': 'Rates'},
                                {'label': ' Spread', 'value': 'Spread'},
                                {'label': ' Commodities', 'value': 'Commodities'},
                            ],
                            value=None,
                            inline=True,
                            labelStyle={'color': THEME['text_main']},
                            inputStyle={'marginRight': '5px', 'marginLeft': '10px'},
                            style={'fontSize': '13px'}
                        ),
                    ], style={'marginBottom': '12px', 'display': 'flex', 'alignItems': 'center'}),
                    
                    # Step 2: Universe (Rates & Spread)
                    html.Div([
                        html.Label("Universe:", style={'fontWeight': 'bold', 'width': '70px', 'fontSize': '13px', 'color': THEME['text_main']}),
                        dcc.Dropdown(
                            id='universe-selector',
                            options=[],
                            value=None,
                            placeholder="Select universe...",
                            clearable=True,
                            style={'width': '100%', 'fontSize': '13px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                        ),
                    ], id='universe-selection-row', style={'display': 'none', 'marginBottom': '12px', 'alignItems': 'center'}),
                    
                    # Step 3: Sectors (Rates & Spread)
                    html.Div([
                        html.Label("Sector:", style={'fontWeight': 'bold', 'width': '70px', 'fontSize': '13px', 'alignSelf': 'flex-start', 'marginTop': '5px', 'color': THEME['text_main']}),
                        html.Div([
                            dcc.Checklist(
                                id='sector-selector',
                                options=[
                                    {'label': ' 1Y', 'value': '1Y'},
                                    {'label': ' 2Y', 'value': '2Y'},
                                    {'label': ' 5Y', 'value': '5Y'},
                                    {'label': ' 10Y', 'value': '10Y'},
                                    {'label': ' 30Y', 'value': '30Y'},
                                ],
                                value=[],
                                inline=True,
                                labelStyle={'color': THEME['text_main']},
                                inputStyle={'marginRight': '3px', 'marginLeft': '8px'},
                                style={'fontSize': '13px', 'marginBottom': '8px'}
                            ),
                            html.Button(
                                'Add to Pool',
                                id='add-to-pool-btn',
                                n_clicks=0,
                                style={'backgroundColor': '#2ecc71', 'color': 'white', 'padding': '4px 12px', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer', 'fontSize': '12px'}
                            ),
                        ], style={'flex': '1'})
                    ], id='sector-selection-row', style={'display': 'none', 'marginBottom': '12px', 'alignItems': 'flex-start'}),
                    
                    # Step 2: Commodities
                    html.Div([
                        html.Label("Items:", style={'fontWeight': 'bold', 'width': '70px', 'fontSize': '13px', 'alignSelf': 'flex-start', 'marginTop': '5px', 'color': THEME['text_main']}),
                        html.Div([
                            dcc.Checklist(
                                id='commodities-selector',
                                options=[
                                    {'label': ' Gold', 'value': 'Gold'},
                                    {'label': ' Aluminium', 'value': 'Aluminium'},
                                    {'label': ' Copper', 'value': 'Copper'},
                                    {'label': ' Crude Oil', 'value': 'Crude_Oil'},
                                ],
                                value=[],
                                inline=True,
                                labelStyle={'color': THEME['text_main']},
                                inputStyle={'marginRight': '3px', 'marginLeft': '8px'},
                                style={'fontSize': '13px', 'marginBottom': '8px'}
                            ),
                            html.Button(
                                'Add to Pool',
                                id='add-commodities-btn',
                                n_clicks=0,
                                style={'backgroundColor': '#f39c12', 'color': 'white', 'padding': '4px 12px', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer', 'fontSize': '12px'}
                            ),
                        ], style={'flex': '1'})
                    ], id='commodities-confirm-row', style={'display': 'none', 'marginBottom': '12px', 'alignItems': 'flex-start'}),
                    
                ], style={'width': '40%', 'padding': '20px', 'borderRight': f'1px solid {THEME["table_header"]}'}),
                
                # Column 2: Asset Pool
                html.Div([
                    html.Div([
                        html.H6("Asset Pool", style={'color': THEME['text_main'], 'marginTop': '0', 'marginBottom': '0'}),
                        html.Span(id='pool-count', children=pool_count_text, style={'color': THEME['text_sub'], 'fontSize': '13px', 'marginLeft': '5px'}),
                        html.Button(
                            'Clear',
                            id='clear-pool-btn',
                            n_clicks=0,
                            style={'backgroundColor': THEME['danger'], 'color': 'white', 'padding': '2px 8px', 'border': 'none', 'borderRadius': '3px', 'cursor': 'pointer', 'fontSize': '11px', 'marginLeft': 'auto'}
                        )
                    ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '10px'}),
                    
                    html.Div(
                        id='asset-pool-display',
                        children=pool_display,
                        style={'height': '150px', 'overflowY': 'auto', 'border': f'1px solid {THEME["table_header"]}', 'borderRadius': '4px', 'padding': '8px', 'backgroundColor': THEME['bg_input']}
                    ),
                ], style={'width': '30%', 'padding': '20px', 'borderRight': f'1px solid {THEME["table_header"]}'}),
                
                # Column 3: Action
                html.Div([
                    html.H6("Analysis", style={'color': THEME['text_main'], 'marginTop': '0', 'marginBottom': '15px'}),
                    html.Div([
                        html.Button(
                            'RUN ANALYSIS',
                            id='run-button',
                            n_clicks=initial_n_clicks,
                            style={'backgroundColor': THEME['accent'], 'color': 'white', 'padding': '12px', 'width': '100%', 'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer', 'fontSize': '14px', 'fontWeight': 'bold', 'boxShadow': '0 2px 5px rgba(0,0,0,0.3)'}
                        ),
                        html.Div(id='status-message', style={'marginTop': '15px', 'fontSize': '13px', 'textAlign': 'center', 'minHeight': '20px', 'color': THEME['text_main']}),
                        html.Div(id='timestamp-display', style={'color': THEME['text_sub'], 'fontSize': '11px', 'textAlign': 'center', 'marginTop': '10px'})
                    ], style={'display': 'flex', 'flexDirection': 'column', 'justifyContent': 'center', 'height': '80%'})
                ], style={'width': '30%', 'padding': '20px', 'backgroundColor': THEME['bg_card'], 'borderRadius': '0 0 8px 0'}),
            ], style={'display': 'flex'}),
            
        ], style={'backgroundColor': THEME['bg_card'], 'marginBottom': '20px', 'border': f'1px solid {THEME["table_header"]}', 'borderRadius': '8px'}),
        
        # Portfolio Table Results
        html.Div([
            html.H4("Portfolio Allocation Results", style={'color': THEME['text_main'], 'marginBottom': '15px'}),
            html.Div(id='portfolio-table-container')
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'marginBottom': '20px', 'borderRadius': '5px'}),
    ], style={'padding': '10px', 'backgroundColor': THEME['bg_main']})


def build_multiasset_risk_layout():
    """Build the layout for the Risk tab."""
    return html.Div([
        html.H4("Factor Exposures & Volatilities", style={'textAlign': 'center', 'color': THEME['text_main'], 'marginTop': '10px', 'marginBottom': '20px'}),
        # Side-by-side layout container
        html.Div([
            # Left column: Heatmap
            html.Div([
                html.H6("Asset Sensitivity to Risk Factors", style={'textAlign': 'center', 'color': THEME['text_main'], 'marginBottom': '15px'}),
                dcc.Graph(id='sensitivity-heatmap', style={'height': '500px', 'margin': '0'})
            ], style={'flex': '1', 'minWidth': '0', 'paddingRight': '10px'}),
            
            # Right column: Factor Volatility Table
            html.Div([
                html.Div(id='factor-vol-table-container')
            ], style={'flex': '1', 'minWidth': '0', 'paddingLeft': '10px'})
        ], style={'display': 'flex', 'gap': '10px', 'justifyContent': 'space-between'})
    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px', 'borderRadius': '5px', 'margin': '10px'})


def build_multiasset_backtest_layout():
    """Build the layout for the Backtest tab."""
    return html.Div([
        html.H4("Historical Allocation Analysis", style={'color': THEME['text_main'], 'marginBottom': '15px'}),
        
        # Date Range Selection and Performance Metrics
        html.Div([
            html.Div([
                html.Label("Backtest Period:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                dcc.DatePickerRange(
                    id='history-date-range',
                    min_date_allowed=datetime(2015, 1, 1),
                    max_date_allowed=datetime.now(),
                    start_date=datetime(datetime.now().year, 1, 1).date(),
                    end_date=datetime.now().date(),
                    display_format='YYYY-MM-DD',
                    style={'backgroundColor': THEME['bg_input'], 'color': '#000'}
                ),
            ], style={'display': 'flex', 'alignItems': 'center'}),
            
            # PCA Factor Risk Parity Option
            html.Div([
                html.Label("Optimization Method:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                dcc.RadioItems(
                    id='optimization-method',
                    options=[
                        {'label': 'Asset Risk Parity (1/Vol)', 'value': 'asset_rp'},
                        {'label': 'PCA Factor Risk Parity', 'value': 'pca_factor_rp'}
                    ],
                    value='asset_rp',
                    inline=True,
                    labelStyle={'color': THEME['text_main']},
                    style={'fontSize': '13px'}
                ),
            ], style={'display': 'flex', 'alignItems': 'center', 'marginLeft': '30px'}),
            
            # Performance Metrics Table
            html.Div(id='performance-metrics-container', style={'marginLeft': '30px'}),
        ], style={'marginBottom': '15px', 'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap', 'gap': '10px'}),

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
                    html.Div(style={'height': '30px'}),
                    dcc.Graph(id='pnl-attribution-chart')
                ]
            )
        ])
    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px', 'borderRadius': '5px', 'margin': '10px'})


# --- Callbacks ---

def register_multiasset_callbacks(app):
    """Register all callbacks for the Multi-Asset Dashboard components."""
    
    # 1. UI Toggles for Asset Type Selection
    @app.callback(
        [Output('universe-selection-row', 'style'),
         Output('sector-selection-row', 'style'),
         Output('commodities-confirm-row', 'style'),
         Output('universe-selector', 'options'),
         Output('universe-selector', 'value'),
         Output('sector-selector', 'value'),
         Output('commodities-selector', 'value')],
        [Input('asset-type-selector', 'value')]
    )
    def toggle_selection_rows(asset_type):
        if asset_type == 'Rates':
            universe_options = [
                {'label': 'China Gov Bond', 'value': 'China Gov Bond'},
                {'label': 'US Gov Bond', 'value': 'US Gov Bond'},
                {'label': 'DE Gov Bond', 'value': 'DE Gov Bond'},
                {'label': 'UK Gov Bond', 'value': 'UK Gov Bond'},
                {'label': 'Japan Gov Bond', 'value': 'Japan Gov Bond'},
            ]
            return (
                {'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'},
                {'display': 'none'},
                {'display': 'none'},
                universe_options, None, [], []
            )
        elif asset_type == 'Spread':
            universe_options = [
                {'label': 'Interest Rate Swap', 'value': 'Interest Rate Swap'},
                {'label': 'China Development Bond', 'value': 'China Development Bond'},
                {'label': 'Interbank Commercial Paper', 'value': 'Interbank Commercial Paper'},
            ]
            return (
                {'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'},
                {'display': 'none'},
                {'display': 'none'},
                universe_options, None, [], []
            )
        elif asset_type == 'Commodities':
            return (
                {'display': 'none'},
                {'display': 'none'},
                {'display': 'flex', 'alignItems': 'flex-start', 'marginBottom': '12px'},
                [], None, [], []
            )
        else:
            return (
                {'display': 'none'},
                {'display': 'none'},
                {'display': 'none'},
                [], None, [], []
            )

    @app.callback(
        Output('sector-selection-row', 'style', allow_duplicate=True),
        [Input('universe-selector', 'value')],
        prevent_initial_call=True
    )
    def show_sector_selection(universe):
        if universe:
            return {'display': 'flex', 'alignItems': 'flex-start', 'marginBottom': '12px'}
        return {'display': 'none'}

    # 2. Asset Pool Management
    @app.callback(
        [Output('asset-pool-store', 'data'),
         Output('asset-pool-display', 'children'),
         Output('pool-count', 'children')],
        [Input('add-to-pool-btn', 'n_clicks'),
         Input('add-commodities-btn', 'n_clicks'),
         Input('clear-pool-btn', 'n_clicks')],
        [State('asset-type-selector', 'value'),
         State('universe-selector', 'value'),
         State('sector-selector', 'value'),
         State('commodities-selector', 'value'),
         State('asset-pool-store', 'data')],
        prevent_initial_call=True
    )
    def manage_asset_pool(add_rates_clicks, add_comm_clicks, clear_clicks, asset_type, universe, sectors, commodities, current_pool):
        ctx = dash.callback_context
        if not ctx.triggered:
            return current_pool, dash.no_update, dash.no_update
        
        button_id = ctx.triggered[0]['prop_id'].split('.')[0]
        
        if button_id == 'clear-pool-btn':
            return [], [html.Div("No assets.", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'padding': '10px'})], "(0)"
        
        if current_pool is None:
            current_pool = []
        
        if button_id == 'add-to-pool-btn' and asset_type in ['Rates', 'Spread']:
            if not universe or not sectors:
                return current_pool, dash.no_update, dash.no_update
            
            universe_code_map = {
                'China Gov Bond': 'CN', 'US Gov Bond': 'US', 'DE Gov Bond': 'EU',
                'UK Gov Bond': 'UK', 'Japan Gov Bond': 'JP',
                'China Credit': 'CN-Credit', 'China Urban': 'CN-Urban'
            }
            universe_code = universe_code_map.get(universe, 'XX')
            
            for sector in sectors:
                asset_name = f"{universe_code}{sector}"
                asset_info = {'name': asset_name, 'type': asset_type, 'universe': universe, 'sector': sector}
                if not any(a['name'] == asset_name for a in current_pool):
                    current_pool.append(asset_info)
        
        elif button_id == 'add-commodities-btn' and asset_type == 'Commodities':
            if not commodities:
                return current_pool, dash.no_update, dash.no_update
            
            for comm in commodities:
                asset_info = {'name': comm, 'type': 'Commodities', 'universe': comm, 'sector': 'N/A'}
                if not any(a['name'] == comm for a in current_pool):
                    current_pool.append(asset_info)
        
        # Update display
        if not current_pool:
            display = [html.Div("No assets selected.", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'padding': '10px'})]
            count_text = "(0)"
        else:
            display = []
            for asset in current_pool:
                if asset['type'] == 'Commodities':
                   bg_col = '#b48b32'
                else:
                   bg_col = '#2c5e40'
                
                display.append(html.Div([
                    html.Span(f"• {asset['name']}", style={'fontWeight': 'bold', 'color': 'white'}),
                    html.Span(f" ({asset.get('universe','')} - {asset.get('sector','')})", style={'color': '#ddd', 'fontSize': '12px'}),
                ], style={'padding': '5px', 'marginBottom': '5px', 'backgroundColor': bg_col, 'borderRadius': '3px'}))
            count_text = f"({len(current_pool)})"
        
        return current_pool, display, count_text

    # 3. Factor Selection Callbacks (Regime Tab)
    @app.callback(
        [Output('factor-region-selector', 'options'),
         Output('factor-region-selector', 'value')],
        [Input('factor-asset-class-selector', 'value')]
    )
    def update_region_options(asset_class):
        if not asset_class:
            return [], None
        
        if asset_class == 'Rates':
            options = [
                {'label': 'China', 'value': 'CN'},
                {'label': 'United States', 'value': 'US'},
                {'label': 'Eurozone', 'value': 'EU'},
                {'label': 'United Kingdom', 'value': 'UK'},
                {'label': 'Japan', 'value': 'JP'},
            ]
        elif asset_class == 'Spread':
            options = [
                {'label': 'Interest Rate Swap', 'value': 'IRS'},
                {'label': 'China Development Bond', 'value': 'CDB'},
                {'label': 'Interbank Commercial Paper', 'value': 'ICP'},
            ]
        elif asset_class == 'FX':
            options = [
                {'label': 'USD/CNY', 'value': 'USDCNY'},
                {'label': 'EUR/CNY', 'value': 'EURCNY'},
                {'label': 'JPY/CNY', 'value': 'JPYCNY'},
                {'label': 'GBP/CNY', 'value': 'GBPCNY'},
            ]
        elif asset_class == 'Commodities':
            options = [
                {'label': 'Gold', 'value': 'AU'},
                {'label': 'Aluminium', 'value': 'AL'},
                {'label': 'Copper', 'value': 'CU'},
                {'label': 'Crude Oil', 'value': 'SC'},
            ]
        else:
            options = []
        
        return options, None

    @app.callback(
        [Output('factor-type-selector', 'options'),
         Output('factor-type-selector', 'value')],
        [Input('factor-asset-class-selector', 'value'),
         Input('factor-region-selector', 'value')]
    )
    def update_factor_type_options(asset_class, region):
        if not asset_class or not region:
            return [], []
        
        if asset_class == 'Rates':
            factor_codes = ['IRDL', 'IRSL', 'IRCV']
            factor_names = ['Level (IRDL)', 'Slope (IRSL)', 'Curvature (IRCV)']
            options = [{'label': f'{name} - {region}', 'value': f'{code}.{region}'} 
                    for code, name in zip(factor_codes, factor_names)]
        elif asset_class == 'Spread':
            if region == 'ICP':
                # ICP only has SPDL
                options = [{'label': f'Level (SPDL) - {region}', 'value': f'SPDL.{region}'}]
            else:
                factor_codes = ['SPDL', 'SPSL']
                factor_names = ['Level (SPDL)', 'Slope (SPSL)']
                options = [{'label': f'{name} - {region}', 'value': f'{code}.{region}'} 
                        for code, name in zip(factor_codes, factor_names)]
        elif asset_class == 'FX':
            options = [{'label': f'Level (FXDL) - {region}', 'value': f'FXDL.{region}'}]
        elif asset_class == 'Commodities':
            options = [{'label': f'Level (CMDL) - {region}', 'value': f'CMDL.{region}'}]
        else:
            options = []
        
        # Auto-select all available factors by default
        default_values = [opt['value'] for opt in options]
        return options, default_values

    @app.callback(
        Output('factor-history-chart', 'figure'),
        [Input('factor-type-selector', 'value')]
    )
    def update_factor_history_chart(selected_factors):
        if not selected_factors:
            empty_fig = go.Figure()
            empty_fig.update_layout(title="Please select factors from the dropdowns above",
                                xaxis={'visible': False}, yaxis={'visible': False}, template=THEME['chart_template'], paper_bgcolor=THEME['bg_main'], plot_bgcolor=THEME['bg_main'], font={'color': THEME['text_main']})
            return empty_fig
        
        try:
            loader = RiskFactorLoader(DIR_INPUT)
            factor_levels = loader.load_risk_factors(use_cache=True)
            
            if factor_levels is None or factor_levels.empty:
                raise ValueError("Cannot load risk factor data")
            
            fig = go.Figure()
            for factor in selected_factors:
                if factor in factor_levels.columns:
                    series = factor_levels[factor].dropna()
                    if not series.empty:
                        fig.add_trace(go.Scatter(x=series.index, y=series.values, mode='lines', name=factor))
            
            fig.update_layout(
                xaxis_title="Date", yaxis_title="Value", hovermode='x unified',
                template=THEME['chart_template'], height=500,
                paper_bgcolor=THEME['bg_main'], plot_bgcolor=THEME['bg_main'],
                font={'color': THEME['text_main']},
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font={'color': THEME['text_main']}),
                xaxis=dict(
                    rangeslider=dict(visible=True, thickness=0.05),
                    rangeselector=dict(
                        buttons=[
                            dict(count=1, label="1M", step="month", stepmode="backward"),
                            dict(count=3, label="3M", step="month", stepmode="backward"),
                            dict(count=6, label="6M", step="month", stepmode="backward"),
                            dict(count=1, label="YTD", step="year", stepmode="todate"),
                            dict(count=1, label="1Y", step="year", stepmode="backward"),
                            dict(count=3, label="3Y", step="year", stepmode="backward"),
                            dict(count=5, label="5Y", step="year", stepmode="backward"),
                            dict(step="all", label="All")
                        ],
                        bgcolor=THEME['bg_card'], activecolor=THEME['accent'], font=dict(size=11, color='#000'), x=0, y=1.15
                    ),
                    type="date",
                    gridcolor=THEME['table_header']
                ),
                yaxis=dict(gridcolor=THEME['table_header']),
                uirevision='constant'
            )
            return fig
        except Exception as e:
            return go.Figure().update_layout(title=f"Error plotting data: {str(e)}", template=THEME['chart_template'])

    # 3.5 Correlation Rank Callback
    @app.callback(
        Output('correlation-results-container', 'children'),
        Input('rank-correlations-btn', 'n_clicks'),
        State('correlation-period-selector', 'value'),
        prevent_initial_call=True
    )
    def update_correlation_ranks(n_clicks, period):
        if not n_clicks:
            return html.Div()
        
        try:
            loader = RiskFactorLoader(DIR_INPUT)
            # Use cached load - this pulls the wide DF of all factors
            factor_levels = loader.load_risk_factors(use_cache=True)
            
            if factor_levels is None or factor_levels.empty:
                return html.Div("No factor data available.", style={'color': THEME['warning']})

            # Determine start date based on period
            end_date = factor_levels.index.max()
            if period == '3M':
                start_date = end_date - relativedelta(months=3)
            elif period == '6M':
                start_date = end_date - relativedelta(months=6)
            elif period == '1Y':
                start_date = end_date - relativedelta(years=1)
            else:
                start_date = end_date - relativedelta(months=3)

            # Filter data
            df_subset = factor_levels.loc[start_date:end_date]
            if df_subset.empty:
                 return html.Div(f"No data for period {period}", style={'color': THEME['warning']})
            
            # Calculate returns for correlation (levels might be non-stationary, but request asked for factors correlation. 
            # Usually we corr changes, but let's stick to simple Correlation of the daily prices/levels if that's what "Factors" implies, 
            # OR better, calculate correlation of daily changes (returns) which is standard for "Correlation". 
            # Let's assume daily pct_change for everything to be safe and standard.)
            # However, some factors might be rates (bp), so diff() is better than pct_change().
            # Given these are 'Risk Factors' like Yields (Rates) or Spreads, diff() is safest for stationarity.
            # But let's check if the generic 'calculate_daily_returns_series' handles this? 
            # It's an internal function. Let's just use diff() for now as it's robust for levels-based time series correlation.
            
            df_changes = df_subset.diff().dropna()
            
            if df_changes.empty:
                 return html.Div("Insufficient data points for correlation.", style={'color': THEME['warning']})

            corr_matrix = df_changes.corr()

            # Identify the unique factors involved in the top 10 lowest correlations
            # Stack and sort for bottom 10 table
            # Mask the upper triangle to avoid duplicates and self-correlation = 1
            mask = np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
            corr_stacked = corr_matrix.where(mask).stack().reset_index()
            corr_stacked.columns = ['Factor A', 'Factor B', 'Correlation']
            
            # Sort by correlation ascending (lowest first)
            bottom_10 = corr_stacked.sort_values('Correlation', ascending=True).head(10)

            # Get unique factors from the bottom 10 pairs
            top_factors = set(bottom_10['Factor A']).union(set(bottom_10['Factor B']))
            
            # If we ended up with more than 10 factors (which is likely if pairs are disjoint),
            # we might want to just pick the factors from the very top few pairs to limit to ~10 factors max 
            # for a 10x10 matrix, OR just show all factors involved in the top 10 pairs.
            # Usually top 10 pairs involve at most 20 factors. Let's filter the matrix to these factors.
            top_factors_list = sorted(list(top_factors))
            
            # Filter the correlation matrix
            filtered_corr_matrix = corr_matrix.loc[top_factors_list, top_factors_list]
            
            # Mask upper triangle (show lower only)
            corr_values = filtered_corr_matrix.values.copy()
            # Set upper triangle to NaN (keep diagonal? np.triu k=1 masks strict upper. k=0 masks diagonal too.)
            # Usually diagonal is 1. User said "avoid repetition". Diagonal is unique.
            # But normally lower triangle heatmaps include diagonal.
            mask_upper = np.triu(np.ones(corr_values.shape), k=1).astype(bool)
            corr_values[mask_upper] = np.nan
            
            # --- Heatmap Plot ---
            heatmap_fig = go.Figure(data=go.Heatmap(
                z=corr_values,
                x=filtered_corr_matrix.columns,
                y=filtered_corr_matrix.index,
                colorscale='RdBu', 
                zmin=-1, zmax=1,
                hovertemplate='Factor A: %{y}<br>Factor B: %{x}<br>Correlation: %{z:.3f}<extra></extra>',
                xgap=1, ygap=1 # Add small gap for better definition
            ))
            
            heatmap_fig.update_layout(
                title=f"Correlation Matrix (Lower Triangle) - Factors from Top 10 Lowest Pairs - {period}",
                height=600,
                template=THEME['chart_template'],
                paper_bgcolor=THEME['bg_card'],
                plot_bgcolor=THEME['bg_card'],
                font={'color': THEME['text_main']},
                margin=dict(l=150, r=50, t=80, b=100),
                xaxis={'side': 'bottom', 'tickangle': -45},
                yaxis={'autorange': 'reversed'} # Standard matrix view
            )
            
            # Format display
            return html.Div([
                html.Div([
                    dcc.Graph(figure=heatmap_fig)
                ], style={'marginBottom': '30px'}),

                html.H6(f"Lowest Correlations (Diversification Opportunities) - Top 10 Pairs", style={'color': THEME['text_main']}),
                dash_table.DataTable(
                    data=bottom_10.to_dict('records'),
                    columns=[
                        {'name': 'Factor A', 'id': 'Factor A'},
                        {'name': 'Factor B', 'id': 'Factor B'},
                        {'name': 'Correlation', 'id': 'Correlation', 'type': 'numeric', 'format': {'specifier': '.3f'}},
                    ],
                    style_cell={
                        'textAlign': 'left', 
                        'padding': '10px', 
                        'fontFamily': 'Arial, sans-serif',
                        'backgroundColor': THEME['table_row_odd'],
                        'color': THEME['text_main'],
                        'border': 'none'
                    },
                    style_header={
                        'backgroundColor': THEME['table_header'], 
                        'color': THEME['text_main'], 
                        'fontWeight': 'bold', 
                        'textAlign': 'left',
                        'border': 'none'
                    },
                    style_data_conditional=[
                         {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']}
                    ]
                )
            ])
            
        except Exception as e:
            return html.Div(f"Error calculating correlations: {str(e)}", style={'color': THEME['danger']})

    # 4. Run Analysis (Portfolio Tab -> Results)
    @app.callback(
        [Output('portfolio-table-container', 'children'),
         Output('status-message', 'children'),
         Output('timestamp-display', 'children'),
         Output('portfolio-data-store', 'data')],
        [Input('run-button', 'n_clicks')],
        [State('capital-input', 'value'),
         State('capital-unit', 'value'),
         State('asset-pool-store', 'data')]
    )
    def run_analysis(n_clicks, total_capital, capital_unit, asset_pool):
        if n_clicks == 0:
            return (html.Div("No data available. Click 'Run Analysis' to start.", style={'color': THEME['text_sub']}),
                    "", "", {})

        try:
            # Validate asset pool
            if not asset_pool or len(asset_pool) == 0:
                error_msg = html.Span("⚠ Please add assets to the pool before running analysis", 
                                    style={'color': THEME['warning'], 'fontWeight': 'bold'})
                return (html.Div("No assets in pool.", style={'color': THEME['warning']}),
                        error_msg, "", {})
            
            # Convert capital to CNY
            multiplier = 1e9 if capital_unit == 'billion' else 1e6
            total_capital_cny = float(total_capital) * multiplier
            
            # Get selected assets
            selected_asset_names = [asset['name'] for asset in asset_pool]
            
            # Run optimization
            summary, returns, vols, factor_exp, factor_risk, portfolio = run_risk_parity_allocation(
                total_capital=total_capital_cny, use_cache=True, selected_assets=selected_asset_names
            )
            
            if summary.empty:
                error_msg = html.Span("⚠ No matching assets found in optimization results", 
                                    style={'color': THEME['warning'], 'fontWeight': 'bold'})
                return (html.Div("No matching assets found.", style={'color': THEME['warning']}),
                        error_msg, "", {})
            
            # Update global state
            ALLOCATION_RESULTS.update({
                'summary': summary, 'factor_exposures': factor_exp,
                'factor_risk': factor_risk, 'portfolio': portfolio,
                'timestamp': datetime.now()
            })
            
            # Prepare portfolio table
            portfolio_df = prepare_portfolio_table(summary, factor_exp, portfolio)
            portfolio_enhanced = []
            total_rounded_capital = 0.0
            
            if not portfolio_df.empty:
                for idx, row in portfolio_df.iterrows():
                    record = row.to_dict()
                    asset_type = row['Asset Type']
                    raw_capital = row['Capital (CNY)']
                    
                    unit = 10_000_000.0 if asset_type == 'Rates' else 1_000_000.0
                    rounded_capital = np.floor(raw_capital / unit) * unit
                    total_rounded_capital += rounded_capital
                    
                    record['Capital (CNY)'] = f"{rounded_capital / 1_000_000:,.2f}"
                    record['Weight (%)'] = f"{row['Weight (%)']:.2f}%"
                    portfolio_enhanced.append(record)
            
            portfolio_table_df = pd.DataFrame(portfolio_enhanced)
            
            # Add totals row
            if not portfolio_table_df.empty:
                totals = {
                    'Asset Type': 'TOTAL', 'Universe': '', 'Sector': '', 'Asset Name': '',
                    'Capital (CNY)': f"{total_rounded_capital / 1_000_000:,.2f}",
                    'Weight (%)': f"{summary['Weight (%)'].sum():.2f}%"
                }
                portfolio_table_df = pd.concat([portfolio_table_df, pd.DataFrame([totals])], ignore_index=True)
            
            # Create table
            portfolio_table = dash_table.DataTable(
                data=portfolio_table_df.to_dict('records'),
                columns=[
                    {'name': 'Asset Type', 'id': 'Asset Type'},
                    {'name': 'Universe', 'id': 'Universe'},
                    {'name': 'Sector', 'id': 'Sector'},
                    {'name': 'Asset Name', 'id': 'Asset Name'},
                    {'name': 'Capital (Million CNY)', 'id': 'Capital (CNY)'},
                    {'name': 'Weight', 'id': 'Weight (%)'},
                ],
                style_cell={
                    'textAlign': 'left', 
                    'padding': '10px', 
                    'fontFamily': 'Arial, sans-serif',
                    'backgroundColor': THEME['table_row_odd'],
                    'color': THEME['text_main'],
                    'border': 'none'
                },
                style_header={
                    'backgroundColor': THEME['table_header'], 
                    'color': THEME['text_main'], 
                    'fontWeight': 'bold', 
                    'textAlign': 'center',
                    'border': 'none'
                },
                style_data_conditional=[
                    {'if': {'filter_query': '{Asset Type} = "TOTAL"'}, 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'fontWeight': 'bold'},
                    {'if': {'row_index': 'even'}, 'backgroundColor': THEME['table_row_even']}
                ],
                style_table={'overflowX': 'auto'}
            )
            
            status_msg = html.Span("✓ Analysis completed successfully!", style={'color': THEME['success'], 'fontWeight': 'bold'})
            timestamp_msg = f"Last updated: {ALLOCATION_RESULTS['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}"
            
            # --- Bond Trading Suggestion List (New Feature) ---
            # Automatically load specific bond data if present
            bond_signal_table = None
            try:
                signal_file = os.path.join(DIR_INPUT, 'CBond-spdsrt.pkl')
                
                # Try to check if "CN1Y" or similar rate asset is in the pool? 
                # User request: "对于一年期国债CN1Y...生成买卖列表".
                # It seems he implies this should appear in Portfolio Results context. 
                # We will check if file exists and try to generate it regardless, or appended to the results section.
                
                if os.path.exists(signal_file):
                    df_signals = pd.read_pickle(signal_file)
                    # Check if 'BondCurve' key exists (User specified key='BondCurve')
                    if isinstance(df_signals, dict) and 'BondCurve' in df_signals:
                        bond_data = df_signals['BondCurve']
                    elif isinstance(df_signals, pd.DataFrame):
                        # Maybe the pickle is just the DF?
                         bond_data = df_signals
                    else:
                        bond_data = None
                    
                    if bond_data is not None and not bond_data.empty:
                        # Ensure columns exist (case insensitive check usually safer but let's stick to user specs first)
                        # User described: ttm < 1, sort by z-score.
                        # Assuming columns 'ttm', 'z-score' exist.
                        cols = {c.lower(): c for c in bond_data.columns}
                        
                        col_ttm = cols.get('ttm')
                        col_z = cols.get('z-score') or cols.get('zscore')
                        col_name = cols.get('name') or cols.get('wind_code') or cols.get('code') # Identifier
                        
                        if col_ttm and col_z:
                            # Filter: ttm < 1
                            target = bond_data[bond_data[col_ttm] < 1].copy()
                            
                            if not target.empty:
                                # Sorting Rule:
                                # Negative z-score (larger magnitude) -> Buy (Rank High)
                                # Positive z-score (larger magnitude) -> Sell (Rank High)
                                
                                # Buy Candidates: Lowest z-score (most negative)
                                # Sell Candidates: Highest z-score (most positive)
                                
                                buy_list = target.sort_values(col_z, ascending=True).head(5)
                                sell_list = target.sort_values(col_z, ascending=False).head(5)
                                
                                # Helper to format a table
                                def make_mini_table(df, title, color):
                                    if df.empty: return html.Div()
                                    display_cols = [c for c in [col_name, col_ttm, col_z] if c]
                                    records = df[display_cols].to_dict('records')
                                    # Format
                                    for r in records:
                                         if col_ttm in r: r[col_ttm] = f"{r[col_ttm]:.2f}Y"
                                         if col_z in r: r[col_z] = f"{r[col_z]:.2f}"
                                    
                                    return html.Div([
                                        html.H6(title, style={'color': color, 'marginBottom': '5px', 'textAlign': 'center'}),
                                        dash_table.DataTable(
                                            data=records,
                                            columns=[{'name': c, 'id': c} for c in display_cols],
                                            style_cell={'textAlign': 'center', 'padding': '5px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'border': 'none', 'fontSize': '12px'},
                                            style_header={'backgroundColor': THEME['bg_card'], 'fontWeight': 'bold', 'color': color, 'border': 'none'}
                                        )
                                    ], style={'flex': '1', 'margin': '5px'})

                                bond_signal_table = html.Div([
                                    html.H5("Short-Term Bond (CN1Y / <1Y) Signal Monitor", style={'color': THEME['text_main'], 'marginTop': '20px', 'borderTop': f'1px dashed {THEME["text_sub"]}', 'paddingTop': '10px'}),
                                    html.Div([
                                        make_mini_table(buy_list, "BUY Candidates (Low Z-Score)", THEME['success']),
                                        make_mini_table(sell_list, "SELL Candidates (High Z-Score)", THEME['danger'])
                                    ], style={'display': 'flex', 'gap': '10px'})
                                ])

            except Exception as e:
                print(f"Error generating bond signals: {e}")
                # Don't fail the whole callback for this optional feature
            
            final_output = html.Div([
                portfolio_table,
                bond_signal_table if bond_signal_table else html.Div()
            ])
            
            return (final_output, status_msg, timestamp_msg, {'status': 'success'})
            
        except Exception as e:
            # Print full traceback for debugging
            print(f"\n{'='*80}")
            print("ERROR in run_analysis callback:")
            print(f"{'='*80}")
            traceback.print_exc()
            print(f"{'='*80}\n")
            
            error_msg = html.Span(f"✗ Error: {str(e)}", style={'color': THEME['danger'], 'fontWeight': 'bold'})
            return (html.Div(f"Error: {str(e)}", style={'color': THEME['danger']}),
                    error_msg, "", {})

    # 5. Historical Analysis (Backtest Tab)
    @app.callback(
        [Output('historical-allocation-chart', 'figure'),
         Output('pnl-attribution-chart', 'figure'),
         Output('performance-metrics-container', 'children')],
        [Input('run-history-button', 'n_clicks')],
        [State('asset-pool-store', 'data'),
         State('capital-input', 'value'),
         State('capital-unit', 'value'),
         State('history-date-range', 'start_date'),
         State('history-date-range', 'end_date'),
         State('optimization-method', 'value')]
    )
    def update_historical_allocation(n_clicks, asset_pool, total_capital, capital_unit, start_date, end_date, optimization_method):
        if n_clicks == 0 or not asset_pool:
            return go.Figure(), go.Figure(), None
        
        try:
            # Parse dates
            start_date = pd.to_datetime(start_date) if start_date else None
            end_date = pd.to_datetime(end_date) if end_date else None
            
            # Load data
            loader = RiskFactorLoader(DIR_INPUT)
            risk_factors = loader.load_risk_factors(use_cache=True)
            risk_factors.index = pd.to_datetime(risk_factors.index)
            market_data = load_raw_market_data()
            
            if risk_factors.empty:
                return go.Figure().update_layout(title="No risk factor data available", template=THEME['chart_template']), go.Figure(), None
            
            # Set date range
            if not end_date:
                end_date = risk_factors.index.max()
            if not start_date:
                start_date = end_date - relativedelta(years=2)
            
            # Generate rebalance dates (monthly)
            rebalance_dates = []
            current_date = start_date.replace(day=1)
            while current_date <= end_date:
                if current_date >= risk_factors.index.min():
                    rebalance_dates.append(current_date)
                current_date += relativedelta(months=1)
            
            # Create portfolio
            selected_asset_names = [asset['name'] for asset in asset_pool]
            portfolio = create_custom_portfolio(selected_asset_names)
            
            # Convert capital
            total_capital = float(total_capital) if total_capital else 10_000_000_000
            if capital_unit == 'billion':
                total_capital *= 1_000
            
            # Initialize optimizer if needed
            pca_optimizer = None
            if optimization_method == 'pca_factor_rp':
                pca_optimizer = PCAFactorRiskParityOptimizer(
                    portfolio=portfolio, input_dir=str(DIR_INPUT),
                    pca_lookback_years=1.0, vol_lookback_months=3, ewma_lambda=0.94
                )
            
            # Calculate allocations for each rebalance date
            history_data = []
            allocations_by_date = {}
            
            for date in rebalance_dates:
                if optimization_method == 'pca_factor_rp' and pca_optimizer is not None:
                    try:
                        weights_series, _ = pca_optimizer.fit_and_calculate(pd.Timestamp(date))
                        weights = weights_series.to_dict()
                    except Exception as e:
                        print(f"PCA optimization failed at {date}: {e}")
                        continue
                else:
                    # Traditional Risk Parity
                    lookback_start = date - relativedelta(months=3)
                    mask = (risk_factors.index <= date) & (risk_factors.index >= lookback_start)
                    filtered_factors = risk_factors.loc[mask]
                    
                    if len(filtered_factors) < 40:
                        continue
                    
                    volatilities = {}
                    for name, asset in portfolio.assets.items():
                        vol = asset.get_volatility(filtered_factors, use_cache=False)
                        volatilities[name] = vol
                    
                    inv_vols = {k: 1.0/v if v > 0 else 0 for k, v in volatilities.items()}
                    sum_inv_vol = sum(inv_vols.values())
                    
                    if sum_inv_vol == 0:
                        continue
                    
                    weights = {k: v/sum_inv_vol for k, v in inv_vols.items()}
                
                # Calculate allocations
                row = {'Date': date}
                current_allocations = {}
                for name, weight in weights.items():
                    alloc = weight * total_capital
                    row[name] = alloc
                    current_allocations[name] = alloc * 1_000_000
                
                history_data.append(row)
                allocations_by_date[date] = current_allocations
            
            if not history_data:
                return go.Figure().update_layout(title="Insufficient data for historical analysis", template=THEME['chart_template']), go.Figure(), None
            
            # Calculate daily PnL
            all_dates = sorted(risk_factors.loc[(risk_factors.index >= start_date) & (risk_factors.index <= end_date)].index)
            sorted_rebalance_dates = sorted(allocations_by_date.keys())
            
            daily_pnl_records = []
            cumulative_pnl = {name: 0.0 for name in selected_asset_names}
            cumulative_pnl['Total'] = 0.0
            
            # Pre-compute daily returns
            asset_daily_returns = {}
            for name in selected_asset_names:
                ret_df = calculate_daily_returns_series(name, market_data, start_date, end_date)
                if not ret_df.empty:
                    ret_df = ret_df.set_index('Date')
                    asset_daily_returns[name] = ret_df
            
            # Calculate daily PnL
            for trading_day in all_dates:
                applicable_alloc = None
                for rb_date in sorted_rebalance_dates:
                    if rb_date <= trading_day:
                        applicable_alloc = allocations_by_date[rb_date]
                    else:
                        break
                
                if applicable_alloc is None:
                    continue
                
                daily_record = {'Date': trading_day}
                total_daily_pnl = 0.0
                
                for name in selected_asset_names:
                    if name in applicable_alloc and name in asset_daily_returns:
                        allocation = applicable_alloc[name]
                        ret_df = asset_daily_returns[name]
                        
                        if trading_day in ret_df.index:
                            daily_ret = ret_df.loc[trading_day, 'total']
                            if pd.notna(daily_ret):
                                daily_pnl = allocation * daily_ret
                                cumulative_pnl[name] += daily_pnl
                                total_daily_pnl += daily_pnl
                    
                    daily_record[name] = cumulative_pnl[name] / 1_000_000
                
                cumulative_pnl['Total'] += total_daily_pnl
                daily_record['Total'] = cumulative_pnl['Total'] / 1_000_000
                daily_pnl_records.append(daily_record)
            
            df_history = pd.DataFrame(history_data)
            df_pnl = pd.DataFrame(daily_pnl_records)
            
            # Create allocation chart
            fig_alloc = go.Figure()
            for asset_name in selected_asset_names:
                if asset_name in df_history.columns:
                    fig_alloc.add_trace(go.Scatter(
                        x=df_history['Date'], y=df_history[asset_name],
                        mode='lines+markers', name=asset_name, stackgroup='one'
                    ))
            
            fig_alloc.update_layout(
                title="Historical Portfolio Allocation (Monthly Rebalancing)",
                xaxis_title="Date", yaxis_title="Allocation",
                hovermode='x unified', template=THEME['chart_template'], height=450,
                paper_bgcolor=THEME['bg_main'], plot_bgcolor=THEME['bg_main'], font={'color': THEME['text_main']},
                legend=dict(orientation="h", y=1.02, x=1, xanchor="right", font={'color': THEME['text_main']}),
                xaxis=dict(gridcolor=THEME['table_header']),
                yaxis=dict(gridcolor=THEME['table_header'])
            )
            
            # Create PnL chart
            fig_pnl = go.Figure()
            if not df_pnl.empty:
                for asset_name in selected_asset_names:
                    if asset_name in df_pnl.columns:
                        fig_pnl.add_trace(go.Scatter(
                            x=df_pnl['Date'], y=df_pnl[asset_name],
                            mode='lines', name=asset_name, stackgroup='one'
                        ))
                
                fig_pnl.add_trace(go.Scatter(
                    x=df_pnl['Date'], y=df_pnl['Total'],
                    mode='lines', name='Total Portfolio PnL',
                    line=dict(color='white', width=2, dash='dash')
                ))
            
            fig_pnl.update_layout(
                title="Daily Cumulative Profit & Loss Attribution (Million CNY)",
                xaxis_title="Date", yaxis_title="Cumulative PnL",
                hovermode='x unified', template=THEME['chart_template'], height=450,
                paper_bgcolor=THEME['bg_main'], plot_bgcolor=THEME['bg_main'], font={'color': THEME['text_main']},
                legend=dict(orientation="h", y=1.02, x=1, xanchor="right", font={'color': THEME['text_main']}),
                xaxis=dict(gridcolor=THEME['table_header']),
                yaxis=dict(gridcolor=THEME['table_header'])
            )
            
            # Calculate performance metrics
            metrics_table = None
            if not df_pnl.empty and len(df_pnl) > 1:
                initial_capital = total_capital
                portfolio_values = initial_capital + df_pnl['Total']
                daily_returns = portfolio_values.pct_change().dropna()
                
                total_days = (df_pnl['Date'].iloc[-1] - df_pnl['Date'].iloc[0]).days
                if total_days > 0:
                    total_return = (portfolio_values.iloc[-1] / portfolio_values.iloc[0]) - 1
                    annualized_return = (1 + total_return) ** (365 / total_days) - 1
                else:
                    annualized_return = 0
                
                risk_free_rate = 0.02
                if len(daily_returns) > 0 and daily_returns.std() > 0:
                    excess_return = annualized_return - risk_free_rate
                    annualized_vol = daily_returns.std() * np.sqrt(252)
                    sharpe_ratio = excess_return / annualized_vol
                else:
                    sharpe_ratio = 0
                
                rolling_max = portfolio_values.expanding().max()
                drawdowns = (portfolio_values - rolling_max) / rolling_max
                max_drawdown = drawdowns.min()
                
                metrics_table = html.Table([
                    html.Tr([
                        html.Th("Annualized Return", style={'padding': '8px 15px', 'backgroundColor': THEME['table_header'], 'color': 'white'}),
                        html.Th("Sharpe Ratio", style={'padding': '8px 15px', 'backgroundColor': THEME['table_header'], 'color': 'white'}),
                        html.Th("Max Drawdown", style={'padding': '8px 15px', 'backgroundColor': THEME['table_header'], 'color': 'white'}),
                    ]),
                    html.Tr([
                        html.Td(f"{annualized_return:.2%}", style={'padding': '8px 15px', 'textAlign': 'center', 'fontWeight': 'bold',
                                                                'color': THEME['success'] if annualized_return >= 0 else THEME['danger'], 'backgroundColor': THEME['bg_input']}),
                        html.Td(f"{sharpe_ratio:.2f}", style={'padding': '8px 15px', 'textAlign': 'center', 'fontWeight': 'bold',
                                                            'color': THEME['success'] if sharpe_ratio >= 1 else THEME['warning'] if sharpe_ratio >= 0 else THEME['danger'], 'backgroundColor': THEME['bg_input']}),
                        html.Td(f"{max_drawdown:.2%}", style={'padding': '8px 15px', 'textAlign': 'center', 'fontWeight': 'bold', 'color': THEME['danger'], 'backgroundColor': THEME['bg_input']}),
                    ]),
                ], style={'borderCollapse': 'collapse', 'fontSize': '14px', 'width': '100%'})
            
            return fig_alloc, fig_pnl, metrics_table
            
        except Exception as e:
            traceback.print_exc()
            err_fig = go.Figure().update_layout(title=f"Error: {str(e)}", template=THEME['chart_template'])
            return err_fig, err_fig, None
