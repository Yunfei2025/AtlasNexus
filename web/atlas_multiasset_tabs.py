# -*- coding: utf-8 -*-
"""
Bridge for Multi-Asset Dashboard tabs into AtlasNexus Daily.
This module adapts the layouts and callbacks from `multiasset/dashboard.py` and `multiasset/layout.py`
for use within the AtlasNexus Daily application.
"""
from __future__ import annotations

import dash
from dash import dcc, html, dash_table, ALL
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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

# --- Import from futures.backtest for Backtest-Factor tab ---
import dash_bootstrap_components as dbc
try:
    from futures.backtest.data_loader import (
        discover_pkl_files, load_wind_data, 
        load_local_data_processed, resample_data, get_local_file_path
    )
    from futures.backtest.strategies import (
        run_ma_strategy, run_bollinger_strategy, run_vwap_strategy,
        run_intraday_momentum_strategy, run_atr_band_strategy, run_sar_strategy
    )
    from futures.backtest.metrics import calculate_metrics
    from futures.backtest.regime import RegimeDetector
    from settings.futures import FuturesConfig
    FUTURES_AVAILABLE = True
except ImportError:
    FUTURES_AVAILABLE = False
    print("Warning: futures.backtest modules not found.")

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

# Global state for low-correlation diversification recommendations
# This persists across tab switches (unlike dcc.Store which is tab-scoped)
DIVERSIFICATION_RECOMMENDATIONS = {
    'factors': [],      # List of factor names from low-correlation analysis
    'assets': [],       # List of recommended asset dictionaries
    'timestamp': None   # When the analysis was run
}

# Global state for selected factor pool (shared between Factor tab and Backtest tab)
SELECTED_FACTOR_POOL = {
    'ir_factors': ['IRDL.CN', 'IRDL.US', 'IRSL.CN', 'IRSL.US'],  # Default selection
    'sp_factors': ['SPDL.IRS', 'SPDL.CDB'],
    'fx_factors': ['FXDL.USDCNY'],
    'cmd_factors': ['CMDL.AU', 'CMDL.CU'],
    'timestamp': None
}

# ============================================================================
# Factor to Asset Mapping Table
# ============================================================================
# This mapping converts risk factors to their corresponding tradable assets.
# Each factor (e.g., IRDL.US = US Treasury Curve Level) maps to specific assets
# that are exposed to that factor.
#
# Factor Naming Convention:
#   - IRDL: Interest Rate Delta Level (整条收益率曲线的加权平均变动)
#   - IRSL: Interest Rate Slope (2Y-10Y spread 斜率)
#   - IRCV: Interest Rate Curvature (凸度)
#   - SPDL: Spread Delta Level (利差水平)
#   - SPSL: Spread Slope (利差斜率)
#   - FXDL: FX Delta Level (汇率水平)
#   - CMDL: Commodity Delta Level (商品价格水平)
# ============================================================================
FACTOR_TO_ASSET_MAP = {
    # ==================== Interest Rates (Government Bonds) ====================
    # China Government Bonds
    'IRDL.CN': [
        {'name': 'CN1Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '1Y'},
        {'name': 'CN2Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '2Y'},
        {'name': 'CN5Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '5Y'},
        {'name': 'CN10Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '10Y'},
        {'name': 'CN30Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '30Y'},
    ],
    'IRSL.CN': [
        {'name': 'CN2Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '2Y'},
        {'name': 'CN10Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '10Y'},
    ],
    'IRCV.CN': [
        {'name': 'CN2Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '2Y'},
        {'name': 'CN5Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '5Y'},
        {'name': 'CN10Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '10Y'},
    ],
    
    # US Government Bonds (Treasury)
    'IRDL.US': [
        {'name': 'US1Y', 'type': 'Rates', 'universe': 'US Gov Bond', 'sector': '1Y'},
        {'name': 'US2Y', 'type': 'Rates', 'universe': 'US Gov Bond', 'sector': '2Y'},
        {'name': 'US5Y', 'type': 'Rates', 'universe': 'US Gov Bond', 'sector': '5Y'},
        {'name': 'US10Y', 'type': 'Rates', 'universe': 'US Gov Bond', 'sector': '10Y'},
        {'name': 'US30Y', 'type': 'Rates', 'universe': 'US Gov Bond', 'sector': '30Y'},
    ],
    'IRSL.US': [
        {'name': 'US2Y', 'type': 'Rates', 'universe': 'US Gov Bond', 'sector': '2Y'},
        {'name': 'US10Y', 'type': 'Rates', 'universe': 'US Gov Bond', 'sector': '10Y'},
    ],
    'IRCV.US': [
        {'name': 'US2Y', 'type': 'Rates', 'universe': 'US Gov Bond', 'sector': '2Y'},
        {'name': 'US5Y', 'type': 'Rates', 'universe': 'US Gov Bond', 'sector': '5Y'},
        {'name': 'US10Y', 'type': 'Rates', 'universe': 'US Gov Bond', 'sector': '10Y'},
    ],
    
    # German Government Bonds (Bund) - EU
    'IRDL.DE': [
        {'name': 'EU1Y', 'type': 'Rates', 'universe': 'DE Gov Bond', 'sector': '1Y'},
        {'name': 'EU2Y', 'type': 'Rates', 'universe': 'DE Gov Bond', 'sector': '2Y'},
        {'name': 'EU5Y', 'type': 'Rates', 'universe': 'DE Gov Bond', 'sector': '5Y'},
        {'name': 'EU10Y', 'type': 'Rates', 'universe': 'DE Gov Bond', 'sector': '10Y'},
        {'name': 'EU30Y', 'type': 'Rates', 'universe': 'DE Gov Bond', 'sector': '30Y'},
    ],
    'IRSL.DE': [
        {'name': 'EU2Y', 'type': 'Rates', 'universe': 'DE Gov Bond', 'sector': '2Y'},
        {'name': 'EU10Y', 'type': 'Rates', 'universe': 'DE Gov Bond', 'sector': '10Y'},
    ],
    'IRCV.DE': [
        {'name': 'EU2Y', 'type': 'Rates', 'universe': 'DE Gov Bond', 'sector': '2Y'},
        {'name': 'EU5Y', 'type': 'Rates', 'universe': 'DE Gov Bond', 'sector': '5Y'},
        {'name': 'EU10Y', 'type': 'Rates', 'universe': 'DE Gov Bond', 'sector': '10Y'},
    ],
    
    # UK Government Bonds (Gilt)
    'IRDL.UK': [
        {'name': 'UK1Y', 'type': 'Rates', 'universe': 'UK Gov Bond', 'sector': '1Y'},
        {'name': 'UK2Y', 'type': 'Rates', 'universe': 'UK Gov Bond', 'sector': '2Y'},
        {'name': 'UK5Y', 'type': 'Rates', 'universe': 'UK Gov Bond', 'sector': '5Y'},
        {'name': 'UK10Y', 'type': 'Rates', 'universe': 'UK Gov Bond', 'sector': '10Y'},
        {'name': 'UK30Y', 'type': 'Rates', 'universe': 'UK Gov Bond', 'sector': '30Y'},
    ],
    'IRSL.UK': [
        {'name': 'UK2Y', 'type': 'Rates', 'universe': 'UK Gov Bond', 'sector': '2Y'},
        {'name': 'UK10Y', 'type': 'Rates', 'universe': 'UK Gov Bond', 'sector': '10Y'},
    ],
    'IRCV.UK': [
        {'name': 'UK2Y', 'type': 'Rates', 'universe': 'UK Gov Bond', 'sector': '2Y'},
        {'name': 'UK5Y', 'type': 'Rates', 'universe': 'UK Gov Bond', 'sector': '5Y'},
        {'name': 'UK10Y', 'type': 'Rates', 'universe': 'UK Gov Bond', 'sector': '10Y'},
    ],
    
    # Japan Government Bonds (JGB)
    'IRDL.JP': [
        {'name': 'JP1Y', 'type': 'Rates', 'universe': 'Japan Gov Bond', 'sector': '1Y'},
        {'name': 'JP2Y', 'type': 'Rates', 'universe': 'Japan Gov Bond', 'sector': '2Y'},
        {'name': 'JP5Y', 'type': 'Rates', 'universe': 'Japan Gov Bond', 'sector': '5Y'},
        {'name': 'JP10Y', 'type': 'Rates', 'universe': 'Japan Gov Bond', 'sector': '10Y'},
        {'name': 'JP30Y', 'type': 'Rates', 'universe': 'Japan Gov Bond', 'sector': '30Y'},
    ],
    'IRSL.JP': [
        {'name': 'JP2Y', 'type': 'Rates', 'universe': 'Japan Gov Bond', 'sector': '2Y'},
        {'name': 'JP10Y', 'type': 'Rates', 'universe': 'Japan Gov Bond', 'sector': '10Y'},
    ],
    'IRCV.JP': [
        {'name': 'JP2Y', 'type': 'Rates', 'universe': 'Japan Gov Bond', 'sector': '2Y'},
        {'name': 'JP5Y', 'type': 'Rates', 'universe': 'Japan Gov Bond', 'sector': '5Y'},
        {'name': 'JP10Y', 'type': 'Rates', 'universe': 'Japan Gov Bond', 'sector': '10Y'},
    ],
    
    # ==================== Spread Products ====================
    # Interest Rate Swap
    'SPDL.IRS': [
        {'name': 'IRS1Y', 'type': 'Spread', 'universe': 'Interest Rate Swap', 'sector': '1Y'},
        {'name': 'IRS2Y', 'type': 'Spread', 'universe': 'Interest Rate Swap', 'sector': '2Y'},
        {'name': 'IRS5Y', 'type': 'Spread', 'universe': 'Interest Rate Swap', 'sector': '5Y'},
        {'name': 'IRS10Y', 'type': 'Spread', 'universe': 'Interest Rate Swap', 'sector': '10Y'},
    ],
    'SPSL.IRS': [
        {'name': 'IRS2Y', 'type': 'Spread', 'universe': 'Interest Rate Swap', 'sector': '2Y'},
        {'name': 'IRS10Y', 'type': 'Spread', 'universe': 'Interest Rate Swap', 'sector': '10Y'},
    ],
    
    # China Development Bond
    'SPDL.CDB': [
        {'name': 'CDB1Y', 'type': 'Spread', 'universe': 'China Development Bond', 'sector': '1Y'},
        {'name': 'CDB2Y', 'type': 'Spread', 'universe': 'China Development Bond', 'sector': '2Y'},
        {'name': 'CDB5Y', 'type': 'Spread', 'universe': 'China Development Bond', 'sector': '5Y'},
        {'name': 'CDB10Y', 'type': 'Spread', 'universe': 'China Development Bond', 'sector': '10Y'},
    ],
    'SPSL.CDB': [
        {'name': 'CDB2Y', 'type': 'Spread', 'universe': 'China Development Bond', 'sector': '2Y'},
        {'name': 'CDB10Y', 'type': 'Spread', 'universe': 'China Development Bond', 'sector': '10Y'},
    ],
    
    # Interbank Commercial Paper (only Level, no Slope)
    'SPDL.ICP': [
        {'name': 'ICP3M', 'type': 'Spread', 'universe': 'Interbank Commercial Paper', 'sector': '3M'},
        {'name': 'ICP6M', 'type': 'Spread', 'universe': 'Interbank Commercial Paper', 'sector': '6M'},
        {'name': 'ICP1Y', 'type': 'Spread', 'universe': 'Interbank Commercial Paper', 'sector': '1Y'},
    ],
    
    # ==================== FX (Foreign Exchange) ====================
    'FXDL.USDCNY': [
        {'name': 'USDCNY', 'type': 'FX', 'universe': 'USD/CNY', 'sector': 'Spot'},
    ],
    'FXDL.EURCNY': [
        {'name': 'EURCNY', 'type': 'FX', 'universe': 'EUR/CNY', 'sector': 'Spot'},
    ],
    'FXDL.JPYCNY': [
        {'name': 'JPYCNY', 'type': 'FX', 'universe': 'JPY/CNY', 'sector': 'Spot'},
    ],
    'FXDL.GBPCNY': [
        {'name': 'GBPCNY', 'type': 'FX', 'universe': 'GBP/CNY', 'sector': 'Spot'},
    ],
    
    # ==================== Commodities ====================
    'CMDL.AU': [
        {'name': 'Gold', 'type': 'Commodities', 'universe': 'Gold', 'sector': 'N/A'},
    ],
    'CMDL.AL': [
        {'name': 'Aluminium', 'type': 'Commodities', 'universe': 'Aluminium', 'sector': 'N/A'},
    ],
    'CMDL.CU': [
        {'name': 'Copper', 'type': 'Commodities', 'universe': 'Copper', 'sector': 'N/A'},
    ],
    'CMDL.SC': [
        {'name': 'Crude_Oil', 'type': 'Commodities', 'universe': 'Crude Oil', 'sector': 'N/A'},
    ],
}


def get_assets_from_factors(factor_list: list) -> list:
    """
    Convert a list of factor names to their corresponding tradable assets.
    
    Args:
        factor_list: List of factor names (e.g., ['IRDL.US', 'CMDL.AU'])
    
    Returns:
        List of unique asset dictionaries ready for the asset pool.
    """
    assets = []
    seen_names = set()
    
    for factor in factor_list:
        if factor in FACTOR_TO_ASSET_MAP:
            for asset in FACTOR_TO_ASSET_MAP[factor]:
                if asset['name'] not in seen_names:
                    assets.append(asset.copy())
                    seen_names.add(asset['name'])
    
    return assets

# --- Layout Builders ---

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
                    html.Span("CNY", style={'color': THEME['text_sub'], 'fontSize': '14px', 'marginRight': '20px'}),
                    
                    # Risk Factor Model Selection
                    html.Label("Model:", style={'fontWeight': 'bold', 'marginRight': '10px', 'fontSize': '14px', 'color': THEME['text_main']}),
                    dcc.RadioItems(
                        id='risk-model-selector',
                        options=[
                            {'label': ' Deterministic', 'value': 'deterministic'},
                            {'label': ' PCA', 'value': 'pca'},
                        ],
                        value='deterministic',
                        inline=True,
                        labelStyle={'color': THEME['text_main'], 'marginRight': '15px'},
                        inputStyle={'marginRight': '5px'},
                        style={'fontSize': '13px'}
                    ),
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
                
                # Column 3: Risk Budgets
                html.Div([
                    html.H6("Risk Budgets", style={'color': THEME['text_main'], 'marginTop': '0', 'marginBottom': '15px'}),
                    html.Div(
                        id='risk-budget-container',
                        children=[html.Div("Add assets to see risk factors", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px'})] if not initial_pool else [],
                        style={'height': '150px', 'overflowY': 'auto', 'border': f'1px solid {THEME["table_header"]}', 'borderRadius': '4px', 'padding': '8px', 'backgroundColor': THEME['bg_input']}
                    ),
                    html.Div("Default max risk budget: 1M CNY", style={'fontSize': '11px', 'color': THEME['text_sub'], 'marginTop': '5px', 'textAlign': 'center'})
                ], style={'width': '30%', 'padding': '20px', 'backgroundColor': THEME['bg_card'], 'borderRadius': '0 0 8px 0'}),
            ], style={'display': 'flex'}),
            
        ], style={'backgroundColor': THEME['bg_card'], 'marginBottom': '20px', 'border': f'1px solid {THEME["table_header"]}', 'borderRadius': '8px'}),
        
        # Portfolio Table Results
        html.Div([
            html.Div([
                 html.H4("Portfolio Allocation Results", style={'color': THEME['text_main'], 'marginBottom': '15px', 'flex': '1'}),
                 html.Div([
                        html.Button(
                            'RUN ANALYSIS',
                            id='run-button',
                            n_clicks=initial_n_clicks,
                            style={'backgroundColor': THEME['accent'], 'color': 'white', 'padding': '8px 20px', 'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer', 'fontSize': '14px', 'fontWeight': 'bold'}
                        ),
                 ], style={'marginLeft': '20px'})
            ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between'}),
            
            html.Div([
                html.Div(id='status-message', style={'fontSize': '13px', 'color': THEME['text_main'], 'marginRight': '20px'}),
                html.Div(id='timestamp-display', style={'color': THEME['text_sub'], 'fontSize': '11px'})
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '15px', 'justifyContent': 'flex-end'}),

            html.Div(id='portfolio-table-container')
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'marginBottom': '20px', 'borderRadius': '5px'}),
    ], style={'padding': '10px', 'backgroundColor': THEME['bg_main']})


def build_multiasset_risk_layout():
    """
    Build the layout for the Risk/Summary tab.
    Structure:
    1. Combination: Beta/Alpha composition (Total = Rf + Beta + Alpha)
    2. Exposure: Risk Factor sensitivities (Heatmap)
    3. Ticket: Detailed allocation/trade list
    """
    
    # --- 1. Combination Data (Placeholders as requested) ---
    # TODO: Connect these to actual backtest/optimization metrics in the future
    risk_free_rate = 1.5
    
    # Beta (Strategic Asset Allocation)
    beta_vol = 15.0
    beta_sharpe = 0.4
    beta_ret = beta_vol * beta_sharpe  # 6.0%

    # Alpha (Tactical Adjustments)
    alpha_vol = 5.0
    alpha_ir = 0.5
    alpha_ret = alpha_vol * alpha_ir   # 2.5%
    
    total_ret = risk_free_rate + beta_ret + alpha_ret
    
    # Styling helpers
    def card_style(bg_color=THEME['bg_card']):
        return {
            'backgroundColor': bg_color,
            'padding': '15px',
            'borderRadius': '6px',
            'textAlign': 'center',
            'border': f'1px solid {THEME["table_header"]}',
            'flex': '1',
            'margin': '0 5px',
            'minWidth': '150px'
        }
        
    def value_style(color=THEME['success']):
        return {'fontSize': '24px', 'fontWeight': 'bold', 'color': color, 'margin': '5px 0'}
        
    def label_style():
        return {'color': THEME['text_sub'], 'fontSize': '12px', 'textTransform': 'uppercase', 'letterSpacing': '1px'}

    # --- Prepare Data for Exposure ---
    heatmap_fig = go.Figure()
    vol_table = None
    
    if ALLOCATION_RESULTS['portfolio'] is not None and ALLOCATION_RESULTS['factor_exposures'] is not None:
        try:
            summary = ALLOCATION_RESULTS['summary']
            factor_exp = ALLOCATION_RESULTS['factor_exposures']
            factor_risk = ALLOCATION_RESULTS['factor_risk']
            portfolio = ALLOCATION_RESULTS['portfolio']
            
            # --- Heatmap Logic ---
            assets_with_allocation = summary[summary['Allocation (CNY)'] >= 1000].nlargest(15, 'Allocation (CNY)')
            # Factor filtering
            factor_names = sorted([f for f in factor_exp['Risk Factor'].unique() if f.startswith(('IRDL', 'IRSL', 'IRCV', 'FXDL', 'CMDL', 'SPDL', 'SPSL'))])
            asset_names = assets_with_allocation['Asset'].tolist()
            
            sensitivity_matrix = []
            for asset_name in asset_names:
                if asset_name in portfolio.assets:
                    asset = portfolio.assets[asset_name]
                    # Direct dictionary access if available, else 0
                    row = [asset.factors.get(factor, 0.0) for factor in factor_names]
                    sensitivity_matrix.append(row)
                else:
                    sensitivity_matrix.append([0.0] * len(factor_names))
            
            if asset_names and factor_names:
                heatmap_fig = go.Figure(data=go.Heatmap(
                    z=sensitivity_matrix, x=factor_names, y=asset_names,
                    colorscale='RdBu', zmid=0, text=sensitivity_matrix,
                    texttemplate="%{text:.2f}", textfont={"size": 10}
                ))
                heatmap_fig.update_layout(
                    title=None, height=400, margin=dict(l=10, r=10, t=10, b=10),
                    xaxis_title="Risk Factor", yaxis_title="Asset",
                    template=THEME['chart_template'], paper_bgcolor=THEME['bg_card'], plot_bgcolor=THEME['bg_card'], font={'color': THEME['text_main']}
                )
            
            # --- Volatility Table Logic ---
            factor_vol_df = factor_risk[factor_risk['Risk Factor'].isin(factor_names)].copy()
            factor_vol_df = factor_vol_df[['Risk Factor', 'Volatility (% ann.)']].copy()
            # Format
            factor_vol_df['Volatility (% ann.)'] = factor_vol_df['Volatility (% ann.)'].apply(lambda x: f"{x:.2f}%")
            factor_vol_df = factor_vol_df.sort_values('Risk Factor')
            
            vol_table = dash_table.DataTable(
                data=factor_vol_df.to_dict('records'),
                columns=[{'name': 'Risk Factor', 'id': 'Risk Factor'}, {'name': 'Vol', 'id': 'Volatility (% ann.)'}],
                style_cell={'textAlign': 'center', 'padding': '8px', 'fontSize': '12px', 
                          'backgroundColor': THEME['table_row_odd'], 'color': THEME['text_main'], 'border': 'none'},
                style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_main'], 'fontWeight': 'bold', 'border': 'none'},
                style_data_conditional=[{'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']}],
                 style_table={'overflowY': 'auto', 'maxHeight': '400px'}
            )

        except Exception as e:
            print(f"Error generating Risk Layout: {e}")
            heatmap_fig.update_layout(title=f"Error: {e}")
            vol_table = html.Div(f"Error generating table: {str(e)}", style={'color': THEME['danger'], 'padding': '10px'})

    # --- Assemble Layout ---
    return html.Div([
        
        # 1. Combination Section
        html.H4("1. Portfolio Combination", style={'color': THEME['text_main'], 'marginBottom': '15px', 'borderBottom': f'2px solid {THEME["accent"]}', 'paddingBottom': '5px'}),
        html.Div([
            # Equation Row
            html.Div([
                 # Target Return
                 html.Div([
                     html.Div("Target Return", style=label_style()),
                     html.Div(f"{total_ret:.1f}%", style=value_style(THEME['accent'])),
                     html.Div("Total Portfolio Target", style={'fontSize': '11px', 'color': THEME['text_sub']})
                 ], style=card_style()),
                 
                 html.Div("=", style={'fontSize': '24px', 'color': THEME['text_sub'], 'alignSelf': 'center', 'padding': '0 10px'}),
                 
                 # Risk Free
                 html.Div([
                     html.Div("Risk Free Rate", style=label_style()),
                     html.Div(f"{risk_free_rate:.1f}%", style=value_style(THEME['success'])),
                     html.Div("Cash / Treasury", style={'fontSize': '11px', 'color': THEME['text_sub']})
                 ], style=card_style()),
                 
                 html.Div("+", style={'fontSize': '24px', 'color': THEME['text_sub'], 'alignSelf': 'center', 'padding': '0 10px'}),
                 
                 # Beta
                 html.Div([
                     html.Div("Beta Allocation", style=label_style()),
                     html.Div(f"{beta_ret:.1f}%", style=value_style(THEME['warning'])),
                     html.Div([
                         html.Span("Strategic Asset Allocation", style={'display': 'block', 'marginBottom': '5px'}),
                         html.Span(f"{beta_vol}% Vol", style={'fontWeight': 'bold', 'color': THEME['warning']}),
                         html.Span(" × "),
                         html.Span(f"{beta_sharpe} Sharpe", style={'fontWeight': 'bold', 'color': THEME['warning']}),
                     ], style={'fontSize': '11px', 'color': THEME['text_sub'], 'backgroundColor': 'rgba(255,255,255,0.05)', 'padding': '5px', 'borderRadius': '4px'})
                 ], style=card_style()),
                 
                 html.Div("+", style={'fontSize': '24px', 'color': THEME['text_sub'], 'alignSelf': 'center', 'padding': '0 10px'}),
                 
                 # Alpha
                 html.Div([
                     html.Div("Alpha Overlay", style=label_style()),
                     html.Div(f"{alpha_ret:.1f}%", style=value_style(THEME['danger'])),
                     html.Div([
                         html.Span("Tactical Adjustments", style={'display': 'block', 'marginBottom': '5px'}),
                         html.Span(f"{alpha_vol}% Vol", style={'fontWeight': 'bold', 'color': THEME['danger']}),
                         html.Span(" × "),
                         html.Span(f"{alpha_ir} IR", style={'fontWeight': 'bold', 'color': THEME['danger']}),
                     ], style={'fontSize': '11px', 'color': THEME['text_sub'], 'backgroundColor': 'rgba(255,255,255,0.05)', 'padding': '5px', 'borderRadius': '4px'})
                 ], style=card_style()),
            ], style={'display': 'flex', 'flexWrap': 'wrap', 'justifyContent': 'center', 'alignItems': 'stretch'}),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'borderRadius': '5px', 'marginBottom': '30px'}),

        # 2. Exposure Section
        html.H4("2. Risk Exposure Analysis", style={'color': THEME['text_main'], 'marginBottom': '15px', 'borderBottom': f'2px solid {THEME["accent"]}', 'paddingBottom': '5px'}),
        html.Div([
            # Heatmap
            html.Div([
                html.H6("Asset Sensitivity (Beta to Factors)", style={'textAlign': 'center', 'color': THEME['text_main']}),
                html.Div(
                    id='risk-heatmap-container',
                    children=[
                        dcc.Graph(id='sensitivity-heatmap', figure=heatmap_fig, style={'height': '400px'}) if heatmap_fig and heatmap_fig.data else html.Div("Run Optimization First", style={'padding': '40px', 'textAlign': 'center', 'color': THEME['text_sub']})
                    ]
                )
            ], style={'flex': '3', 'minWidth': '300px', 'backgroundColor': THEME['bg_card'], 'padding': '10px', 'borderRadius': '5px', 'marginRight': '10px'}),
            
        ], style={'display': 'flex', 'flexWrap': 'wrap', 'marginBottom': '30px'}),

        # 3. Ticket Section (Placeholder)
        html.H4("3. Trade Tickets / Allocation", style={'color': THEME['text_main'], 'marginBottom': '15px', 'borderBottom': f'2px solid {THEME["accent"]}', 'paddingBottom': '5px'}),
        html.Div([
            html.Div("Ticket implementation pending...", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'textAlign': 'center', 'padding': '30px'})
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'borderRadius': '5px'})

    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px', 'borderRadius': '5px', 'margin': '10px'})


def build_multiasset_backtest_layout():
    """Build the layout for the Backtest tab.
    
    Strategy: 
    - At the beginning of each month, run Cross-Asset Correlation Analysis
    - Select assets with lowest correlations for diversification
    - Run Risk Parity allocation on the selected assets
    - Track asset pool changes over time
    """
    return html.Div([
        html.H4("Historical Allocation Analysis (Correlation-Based)", style={'color': THEME['text_main'], 'marginBottom': '10px'}),
        html.P(
            "Strategy: At each month start, run correlation analysis to select diversified assets, then apply PCA Factor Risk Parity allocation.",
            style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginBottom': '10px', 'fontStyle': 'italic'}
        ),
        
        # Factor Pool Info Banner
        html.Div([
            html.Span("📊 Using Factor Pool from Factor tab: ", style={'fontWeight': 'bold', 'color': THEME['text_main']}),
            html.Span(id='backtest-factor-pool-display', style={'color': THEME['accent'], 'fontSize': '12px'}),
        ], style={'padding': '8px 12px', 'backgroundColor': THEME['bg_input'], 'borderRadius': '4px', 'marginBottom': '10px', 'border': f'1px solid {THEME["accent"]}'}),
        
        # Dynamic Data Range Info (will be updated based on selected factors)
        html.Div([
            html.Span(id='backtest-min-date-info', children="ℹ️ Calculating minimum supported date...", 
                     style={'color': THEME['text_sub'], 'fontSize': '11px', 'fontStyle': 'italic'}),
        ], style={'marginBottom': '15px'}),
        
        # Row 1: Date Range and Capital
        html.Div([
            # Backtest Period
            html.Div([
                html.Label("Backtest Period:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                html.Div([
                    dcc.DatePickerRange(
                        id='history-date-range',
                        min_date_allowed=datetime(2019, 1, 1).date(),
                        max_date_allowed=datetime.now().date(),
                        start_date=datetime(2024, 1, 1).date(),
                        end_date=datetime.now().date(),
                        display_format='YYYY-MM-DD',
                        style={'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']},
                        updatemode='bothdates'
                    )
                ], style={'display': 'inline-block', 'position': 'relative', 'zIndex': 1000}),
            ], style={'display': 'flex', 'alignItems': 'center'}),
            
            # Total Capital (dedicated for backtest)
            html.Div([
                html.Label("Capital:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                dcc.Input(
                    id='backtest-capital-input',
                    type='number',
                    value=100,
                    style={'width': '80px', 'marginRight': '5px', 'padding': '5px', 'borderRadius': '4px', 'border': '1px solid #444', 'backgroundColor': '#fff', 'color': '#000'}
                ),
                dcc.Dropdown(
                    id='backtest-capital-unit',
                    options=[
                        {"label": "Million", "value": "million"},
                        {"label": "Billion", "value": "billion"},
                    ],
                    value="million",
                    clearable=False,
                    style={'width': '100px', 'fontSize': '13px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                ),
                html.Span("CNY", style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginLeft': '5px'}),
            ], style={'display': 'flex', 'alignItems': 'center', 'marginLeft': '20px'}),
        ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap', 'gap': '10px'}),
        
        # Row 2: Correlation Settings
        html.Div([
            # Correlation Lookback Period
            html.Div([
                html.Label("Correlation Lookback:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                dcc.Dropdown(
                    id='backtest-corr-lookback',
                    options=[
                        {'label': '3 Months', 'value': '3M'},
                        {'label': '6 Months', 'value': '6M'},
                        {'label': '1 Year', 'value': '1Y'},
                    ],
                    value='3M',
                    clearable=False,
                    style={'width': '120px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                ),
            ], style={'display': 'flex', 'alignItems': 'center'}),
            
            # Number of low-correlation pairs to use
            html.Div([
                html.Label("Top Low-Corr Pairs:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                dcc.Input(
                    id='backtest-top-pairs',
                    type='number',
                    value=10,
                    min=5,
                    max=20,
                    style={'width': '60px', 'padding': '5px', 'borderRadius': '4px', 'border': '1px solid #444', 'backgroundColor': '#fff', 'color': '#000'}
                ),
            ], style={'display': 'flex', 'alignItems': 'center', 'marginLeft': '20px'}),
            
            # Performance Metrics Table
            html.Div(id='performance-metrics-container', style={'marginLeft': '20px'}),
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
                    html.Div(style={'height': '20px'}),
                    dcc.Graph(id='pnl-attribution-chart'),
                    html.Div(style={'height': '20px'}),
                    # Asset Pool Changes Section
                    html.Div(id='asset-changes-container')
                ]
            )
        ])
    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px', 'borderRadius': '5px', 'margin': '10px'})


def build_factor_backtest_layout():
    """Build the layout for the Futures/Factor Backtest tab - uses futures.backtest.layout."""
    from datetime import timedelta
    if not FUTURES_AVAILABLE:
        return html.Div("Futures backtest modules not available.", style={'color': THEME['danger']})

    try:
        # Ensure futures/backtest is in sys.path so that internal imports in layout.py (e.g. 'from data_loader ...') work
        import sys
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # web/ -> ../futures/backtest
        backtest_dir = os.path.abspath(os.path.join(current_dir, '..', 'futures', 'backtest'))
        if backtest_dir not in sys.path:
            sys.path.append(backtest_dir)

        from futures.backtest.layout import DARK_CARD_STYLE, DARK_INPUT_STYLE
        pkl_options = discover_pkl_files()
    except Exception as e:
        pkl_options = []
        DARK_CARD_STYLE = {'backgroundColor': '#0f3174', 'border': '1px solid #007ACE', 'color': 'white'}
        DARK_INPUT_STYLE = {'backgroundColor': '#061E44', 'color': 'white', 'border': '1px solid #007ACE'}
        print(f"Error loading backtest layout: {e}")

    # Sidebar (from futures.backtest.layout.create_sidebar)
    sidebar = html.Div([
        html.H4("Strategy Config", style={'textAlign': 'center', 'marginBottom': '20px', 'color': 'white', 'letterSpacing': '0.1rem'}),
        
        # Data Settings
        dbc.Card([
            dbc.CardHeader("Data Settings", className="fw-bold", style={'padding': '8px 12px', 'backgroundColor': '#007ACE', 'color': 'white', 'fontSize': '1rem'}),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("Source", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '8px'}),
                        dcc.RadioItems(
                            id='bf-data-source',
                            options=[{'label': ' Local', 'value': 'local'}, {'label': ' Wind', 'value': 'wind'}],
                            value='local',
                            labelStyle={'display': 'block', 'fontSize': '1rem', 'marginBottom': '4px'},
                            inputStyle={"marginRight": "6px"}
                        )
                    ], width=6),
                    dbc.Col([
                        html.Label("Mode", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '8px'}),
                        dcc.RadioItems(
                            id='bf-trading-mode',
                            options=[{'label': ' Daily', 'value': 'daily'}, {'label': ' Intraday', 'value': 'intraday'}],
                            value='daily',
                            labelStyle={'display': 'block', 'fontSize': '1rem', 'marginBottom': '4px'},
                            inputStyle={"marginRight": "6px"}
                        )
                    ], width=6),
                ], className="mb-3"),
                
                html.Div(id='bf-wind-inputs', children=[
                    html.Label("Symbol", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '6px'}),
                    dcc.Dropdown(id='bf-wind-code', placeholder="Select symbol", style={'fontSize': '1rem', 'color': 'black'})
                ], className="mb-3"),
                
                html.Div(id='bf-local-inputs', children=[
                    html.Label("Symbol", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '6px'}),
                    dcc.Dropdown(id='bf-local-symbol', options=pkl_options, placeholder="Select symbol", style={'fontSize': '1rem', 'color': 'black'})
                ], style={'display': 'none'}, className="mb-3"),
                
                html.Label("Date Range", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '6px'}),
                html.Div([
                    dcc.DatePickerRange(
                        id='bf-date-range',
                        start_date=(datetime.now() - timedelta(days=30)).date(),
                        end_date=datetime.now().date(),
                        display_format='YYYY-MM-DD',
                        style={'fontSize': '1rem', 'width': '100%', 'color': 'white'},
                        className="mb-3",
                        # Style for better visibility in dark theme
                        with_portal=True,
                        day_size=39
                    )
                ], style={'position': 'relative', 'zIndex': 1000, 'marginBottom': '12px', 'backgroundColor': 'black', 'color': 'white', 'borderRadius': '4px', 'padding': '4px'}),
                
                html.Div(id='bf-timeframe-container', children=[
                    html.Label("Timeframe", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '6px'}),
                    dcc.Dropdown(
                        id='bf-timeframe',
                        options=[
                            {'label': '1 Min', 'value': '1T'},
                            {'label': '5 Min', 'value': '5T'},
                            {'label': '15 Min', 'value': '15T'},
                            {'label': '30 Min', 'value': '30T'},
                            {'label': '1 Hour', 'value': '1H'}
                        ],
                        value='5T',
                        style={'fontSize': '1rem', 'color': 'black'}
                    ),
                ]),
            ], style={'padding': '15px'})
        ], className="mb-3", style=DARK_CARD_STYLE),

        # Strategy Selection
        dbc.Card([
            dbc.CardHeader("Strategies", className="fw-bold", style={'padding': '8px 12px', 'backgroundColor': '#007ACE', 'color': 'white', 'fontSize': '1rem'}),
            dbc.CardBody([
                dcc.Checklist(
                    id='bf-strategy-selector',
                    options=[
                        {'label': ' MA', 'value': 'MA'},
                        {'label': ' Bollinger', 'value': 'Boll'},
                        {'label': ' VWAP', 'value': 'VWAP'},
                        {'label': ' Momentum', 'value': 'Momentum'},
                        {'label': ' ATR', 'value': 'ATR'},
                        {'label': ' SAR', 'value': 'SAR'},
                    ],
                    value=['MA', 'Boll', 'SAR'],
                    labelStyle={'display': 'inline-block', 'marginRight': '12px', 'fontSize': '1rem', 'marginBottom': '6px'},
                    inputStyle={"marginRight": "5px"}
                )
            ], style={'padding': '15px'})
        ], className="mb-3", style=DARK_CARD_STYLE),

        # Parameters Accordion
        dbc.Accordion([
            dbc.AccordionItem([
                dbc.Row([
                    dbc.Col([html.Label("Short", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '6px'}), dcc.Input(id='bf-ma-short', type='number', value=5, min=2, className="form-control", style=DARK_INPUT_STYLE)]),
                    dbc.Col([html.Label("Long", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '6px'}), dcc.Input(id='bf-ma-long', type='number', value=20, min=5, className="form-control", style=DARK_INPUT_STYLE)])
                ])
            ], title="MA Params", style=DARK_CARD_STYLE),
            
            dbc.AccordionItem([
                dbc.Row([
                    dbc.Col([html.Label("Period", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '6px'}), dcc.Input(id='bf-boll-window', type='number', value=20, className="form-control", style=DARK_INPUT_STYLE)]),
                    dbc.Col([html.Label("Std Dev", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '6px'}), dcc.Input(id='bf-boll-std', type='number', value=1.0, step=0.1, className="form-control", style=DARK_INPUT_STYLE)])
                ]),
                html.Div(style={'height': '8px'}),
                dcc.Checklist(id='bf-boll-exit', options=[{'label': ' Exit at MA', 'value': 'exit'}], value=[], labelStyle={'fontSize': '1rem'})
            ], title="Bollinger Params", style=DARK_CARD_STYLE),

            dbc.AccordionItem([
                html.Label("Window", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '6px'}),
                dcc.Input(id='bf-vwap-window', type='number', value=20, className="form-control", style=DARK_INPUT_STYLE)
            ], title="VWAP Params", style=DARK_CARD_STYLE),

            dbc.AccordionItem([
                html.Label("Lookback", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '6px'}),
                dcc.Input(id='bf-mom-window', type='number', value=14, className="form-control", style=DARK_INPUT_STYLE)
            ], title="Momentum Params", style=DARK_CARD_STYLE),
            
            dbc.AccordionItem([
                dbc.Row([
                    dbc.Col([html.Label("EMA", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '6px'}), dcc.Input(id='bf-atr-ema-window', type='number', value=20, className="form-control", style=DARK_INPUT_STYLE)]),
                    dbc.Col([html.Label("ATR", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '6px'}), dcc.Input(id='bf-atr-window', type='number', value=20, className="form-control", style=DARK_INPUT_STYLE)])
                ])
            ], title="ATR Params", style=DARK_CARD_STYLE),
            
            dbc.AccordionItem([
                dbc.Row([
                    dbc.Col([html.Label("AF", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '6px'}), dcc.Input(id='bf-sar-af', type='number', value=0.02, step=0.01, className="form-control", style=DARK_INPUT_STYLE)]),
                    dbc.Col([html.Label("Max AF", style={'fontSize': '1rem', 'fontWeight': '500', 'marginBottom': '6px'}), dcc.Input(id='bf-sar-max-af', type='number', value=0.2, step=0.01, className="form-control", style=DARK_INPUT_STYLE)])
                ])
            ], title="SAR Params", style=DARK_CARD_STYLE),
        ], start_collapsed=True, className="mb-3", flush=True, style={"backgroundColor": "#082255"}),
        
        dbc.Button("Run Backtest", id='bf-run-button', style={
            'width': '100%', 'padding': '12px', 'backgroundColor': '#007ACE', 
            'color': 'white', 'border': 'none', 'cursor': 'pointer',
            'fontSize': '1.1rem', 'fontWeight': 'bold', 'letterSpacing': '0.1rem'
        })
    ], style={
        'width': '320px', 'padding': '2rem 1rem', 'backgroundColor': '#082255',
        'color': 'white', 'overflowY': 'auto', 'fontFamily': '"Open Sans", sans-serif'
    })
    
    # Content area
    content = html.Div([
        dcc.Loading(
            id="bf-loading-results",
            type="default",
            children=html.Div(id='bf-results-container', style={'minHeight': '400px'})
        )
    ], style={'flex': '1', 'padding': '1.5rem 2rem', 'fontFamily': '"Open Sans", sans-serif', 'minWidth': '0'})
    
    return html.Div([sidebar, content], style={'display': 'flex', 'flexDirection': 'row', 'width': '100%', 'minHeight': 'calc(100vh - 150px)', 'backgroundColor': THEME['bg_main']})
   


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
        
        # Save to persistent storage
        try:
            save_asset_pool(current_pool)
        except Exception as e:
            print(f"Error saving asset pool: {e}")

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
        [Input('factor-type-selector', 'value'),
         Input('factor-history-chart', 'relayoutData')]
    )
    def update_factor_history_chart(selected_factors, relayout_data):
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
            
            # Ensure index is DatetimeIndex for robust comparison
            if not isinstance(factor_levels.index, pd.DatetimeIndex):
                factor_levels.index = pd.to_datetime(factor_levels.index)

            fig = go.Figure()
            
            # Determine date range from relayoutData
            start_date = None
            end_date = None
            
            if relayout_data:
                if 'xaxis.range[0]' in relayout_data:
                    start_date = relayout_data['xaxis.range[0]']
                    end_date = relayout_data['xaxis.range[1]']
                elif 'xaxis.range' in relayout_data:
                    start_date = relayout_data['xaxis.range'][0]
                    end_date = relayout_data['xaxis.range'][1]
            
            # Calculate dynamic Y-axis range
            y_min = float('inf')
            y_max = float('-inf')
            has_data = False
            
            for factor in selected_factors:
                if factor in factor_levels.columns:
                    series = factor_levels[factor].dropna()
                    if not series.empty:
                        fig.add_trace(go.Scatter(x=series.index, y=series.values, mode='lines', name=factor))
                        
                        # Filter for min/max calculation
                        if start_date and end_date:
                            try:
                                # Convert strings to compatible timestamps
                                ts_start = pd.to_datetime(start_date)
                                ts_end = pd.to_datetime(end_date)
                                
                                mask = (series.index >= ts_start) & (series.index <= ts_end)
                                visible_series = series.loc[mask]
                            except Exception:
                                # Fallback if date parsing fails
                                visible_series = series
                        else:
                            visible_series = series
                            
                        if not visible_series.empty:
                            current_min = visible_series.min()
                            current_max = visible_series.max()
                            y_min = min(y_min, current_min)
                            y_max = max(y_max, current_max)
                            has_data = True
            
            yaxis_config = dict(gridcolor=THEME['table_header'])
            
            if has_data:
                # Add 5% padding
                y_range = y_max - y_min
                if y_range == 0:
                    y_range = abs(y_min) * 0.1 if y_min != 0 else 1.0
                
                # If relayout triggered this, we should enforce the y-range
                # But if we don't restrict it, autoscale usually works on the full data, not visible data.
                # Plotly's default autoscale considers all data points unless manually set.
                # So we must manually set it for "zoom-dependent auto-scale".
                yaxis_config['range'] = [y_min - y_range * 0.05, y_max + y_range * 0.05]
                # yaxis_config['autorange'] = False # Implicit if range is set
            
            # Persist the x-range if it exists
            xaxis_config = dict(
                # Disable rangeslider to allow effective Y-axis auto-scaling on zoom
                rangeslider=dict(visible=False),
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
            )
            
            if start_date and end_date:
                 xaxis_config['range'] = [start_date, end_date]

            fig.update_layout(
                xaxis_title="Date", yaxis_title="Value", hovermode='x unified',
                template=THEME['chart_template'], height=500,
                paper_bgcolor=THEME['bg_main'], plot_bgcolor=THEME['bg_main'],
                font={'color': THEME['text_main']},
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font={'color': THEME['text_main']}),
                xaxis=xaxis_config,
                yaxis=yaxis_config,
                # Removed constant uirevision to allow the Y-axis range update to take precedence
            )
            return fig
        except Exception as e:
            return go.Figure().update_layout(title=f"Error plotting data: {str(e)}", template=THEME['chart_template'])

    # 3.4 Factor Selection State Restoration (from Store)
    @app.callback(
        [Output('factor-selection-ir', 'value'),
         Output('factor-selection-sp', 'value'),
         Output('factor-selection-fx', 'value'),
         Output('factor-selection-cmd', 'value')],
        Input('factor-selection-store', 'data')
    )
    def restore_factor_selections(stored_data):
        """Restore factor selections from store when tab is reloaded."""
        if not stored_data:
            return (
                SELECTED_FACTOR_POOL['ir_factors'],
                SELECTED_FACTOR_POOL['sp_factors'],
                SELECTED_FACTOR_POOL['fx_factors'],
                SELECTED_FACTOR_POOL['cmd_factors']
            )
        return (
            stored_data.get('ir', SELECTED_FACTOR_POOL['ir_factors']),
            stored_data.get('sp', SELECTED_FACTOR_POOL['sp_factors']),
            stored_data.get('fx', SELECTED_FACTOR_POOL['fx_factors']),
            stored_data.get('cmd', SELECTED_FACTOR_POOL['cmd_factors'])
        )
    
    # 3.5 Factor Pool Counter and Store Updater
    @app.callback(
        [Output('factor-pool-count', 'children'),
         Output('factor-selection-store', 'data')],
        [Input('factor-selection-ir', 'value'),
         Input('factor-selection-sp', 'value'),
         Input('factor-selection-fx', 'value'),
         Input('factor-selection-cmd', 'value')],
        prevent_initial_call=True
    )
    def update_factor_pool_count(ir_factors, sp_factors, fx_factors, cmd_factors):
        # Store selected factors in global state for cross-tab access
        SELECTED_FACTOR_POOL['ir_factors'] = ir_factors or []
        SELECTED_FACTOR_POOL['sp_factors'] = sp_factors or []
        SELECTED_FACTOR_POOL['fx_factors'] = fx_factors or []
        SELECTED_FACTOR_POOL['cmd_factors'] = cmd_factors or []
        SELECTED_FACTOR_POOL['timestamp'] = datetime.now()
        
        # Prepare data for store
        store_data = {
            'ir': ir_factors or [],
            'sp': sp_factors or [],
            'fx': fx_factors or [],
            'cmd': cmd_factors or []
        }
        
        total = len(ir_factors or []) + len(sp_factors or []) + len(fx_factors or []) + len(cmd_factors or [])
        if total == 0:
            message = "⚠️ No factors selected. Please select at least 2 factors for correlation analysis."
        elif total == 1:
            message = f"ℹ️ {total} factor selected. Need at least 2 for correlation analysis."
        else:
            message = f"✅ {total} factors selected in pool (shared with Backtest tab)"
        
        return message, store_data
    
    # 3.6 Correlation Rank Callback
    @app.callback(
        [Output('correlation-results-container', 'children'),
         Output('low-corr-factors-store', 'data')],
        Input('rank-correlations-btn', 'n_clicks'),
        [State('correlation-period-selector', 'value'),
         State('correlation-top-pairs-selector', 'value'),
         State('factor-selection-ir', 'value'),
         State('factor-selection-sp', 'value'),
         State('factor-selection-fx', 'value'),
         State('factor-selection-cmd', 'value')],
        prevent_initial_call=True
    )
    def update_correlation_ranks(n_clicks, period, top_pairs, ir_factors, sp_factors, fx_factors, cmd_factors):
        if not n_clicks:
            return html.Div(), []
        
        # Combine all selected factors
        selected_factors = []
        if ir_factors:
            selected_factors.extend(ir_factors)
        if sp_factors:
            selected_factors.extend(sp_factors)
        if fx_factors:
            selected_factors.extend(fx_factors)
        if cmd_factors:
            selected_factors.extend(cmd_factors)
        
        if len(selected_factors) < 2:
            return html.Div("⚠️ Please select at least 2 factors for correlation analysis.", 
                          style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'}), []
        
        try:
            loader = RiskFactorLoader(DIR_INPUT)
            # Use cached load - this pulls the wide DF of all factors
            factor_levels = loader.load_risk_factors(use_cache=True)
            
            if factor_levels is None or factor_levels.empty:
                return html.Div("No factor data available.", style={'color': THEME['warning']}), []
            
            # Filter to only selected factors
            available_factors = [f for f in selected_factors if f in factor_levels.columns]
            if len(available_factors) < 2:
                return html.Div(f"⚠️ Only {len(available_factors)} of selected factors have data. Need at least 2.", 
                              style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'}), []
            
            factor_levels = factor_levels[available_factors]

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
                 return html.Div(f"No data for period {period}", style={'color': THEME['warning']}), []
            
            # Exclude IRCV (Curvature) factors from correlation analysis
            # Curvature factors are less meaningful for diversification and can add noise
            ircv_cols = [col for col in df_subset.columns if col.startswith('IRCV')]
            df_subset = df_subset.drop(columns=ircv_cols, errors='ignore')
            
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
                 return html.Div("Insufficient data points for correlation.", style={'color': THEME['warning']}), []

            corr_matrix = df_changes.corr()

            # Identify the unique factors involved in the top 10 lowest correlations
            # Stack and sort for bottom 10 table
            # Mask the upper triangle to avoid duplicates and self-correlation = 1
            mask = np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
            corr_stacked = corr_matrix.where(mask).stack().reset_index()
            corr_stacked.columns = ['Factor A', 'Factor B', 'Correlation']
            
            # Sort by absolute correlation ascending (closest to 0 first)
            corr_stacked['AbsCorrelation'] = corr_stacked['Correlation'].abs()
            top_pairs = int(top_pairs) if top_pairs else 10
            bottom_pairs = corr_stacked.sort_values('AbsCorrelation', ascending=True).head(top_pairs)

            # Get unique factors from the lowest correlation pairs
            top_factors = set(bottom_pairs['Factor A']).union(set(bottom_pairs['Factor B']))
            
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
                title=f"Correlation Matrix (Lower Triangle) - Factors from Lowest Abs Correlation Pairs - {period}",
                height=600,
                template=THEME['chart_template'],
                paper_bgcolor=THEME['bg_card'],
                plot_bgcolor=THEME['bg_card'],
                font={'color': THEME['text_main']},
                margin=dict(l=150, r=50, t=80, b=100),
                xaxis={'side': 'bottom', 'tickangle': -45},
                yaxis={'autorange': 'reversed'} # Standard matrix view
            )
            
            # Get the assets corresponding to these low-correlation factors
            diversified_assets = get_assets_from_factors(top_factors_list)
            
            # Store in global variable for cross-tab access (dcc.Store doesn't persist across tabs)
            DIVERSIFICATION_RECOMMENDATIONS['factors'] = top_factors_list
            DIVERSIFICATION_RECOMMENDATIONS['assets'] = diversified_assets
            DIVERSIFICATION_RECOMMENDATIONS['timestamp'] = datetime.now()
            
            # Build complete asset display list (grouped by type)
            asset_display_items = []
            if diversified_assets:
                # Group assets by type
                assets_by_type = {}
                for asset in diversified_assets:
                    a_type = asset.get('type', 'Other')
                    if a_type not in assets_by_type:
                        assets_by_type[a_type] = []
                    assets_by_type[a_type].append(asset)
                
                # Create display for each type
                type_colors = {
                    'Rates': '#2c5e40',
                    'Spread': '#2c5e40',
                    'Commodities': '#b48b32',
                    'FX': '#6b4b8a'
                }
                
                for a_type, assets_list in assets_by_type.items():
                    bg_col = type_colors.get(a_type, '#2c5e40')
                    asset_names = [a['name'] for a in assets_list]
                    asset_display_items.append(
                        html.Div([
                            html.Span(f"{a_type}: ", style={'fontWeight': 'bold', 'color': '#fff', 'marginRight': '5px'}),
                            html.Span(", ".join(asset_names), style={'color': '#ddd'})
                        ], style={
                            'padding': '8px 12px', 
                            'marginBottom': '5px', 
                            'backgroundColor': bg_col, 
                            'borderRadius': '4px',
                            'fontSize': '12px'
                        })
                    )
            
            # Format display
            return html.Div([
                html.Div([
                    dcc.Graph(figure=heatmap_fig)
                ], style={'marginBottom': '30px'}),

                html.H6(f"Lowest Absolute Correlations (Diversification Opportunities) - Top {top_pairs} Pairs", style={'color': THEME['text_main']}),
                dash_table.DataTable(
                    data=bottom_pairs.drop(columns=['AbsCorrelation']).to_dict('records'),
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
                ),
                
                # Add to Asset Pool Section
                html.Div([
                    html.Hr(style={'borderColor': THEME['text_sub'], 'margin': '20px 0'}),
                    html.H6("📊 Diversified Asset Recommendation", style={'color': THEME['success'], 'marginBottom': '10px'}),
                    html.P(
                        f"Based on {len(top_factors_list)} low-correlation factors, {len(diversified_assets)} assets are recommended:",
                        style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginBottom': '10px'}
                    ),
                    # Complete asset list display
                    html.Div(
                        asset_display_items if asset_display_items else html.Div("No mappable assets found.", style={'color': THEME['warning']}),
                        style={
                            'backgroundColor': THEME['bg_input'], 
                            'padding': '10px', 
                            'borderRadius': '4px',
                            'marginBottom': '15px',
                            'maxHeight': '200px',
                            'overflowY': 'auto'
                        }
                    ),
                    html.Button(
                        f"🔄 Replace Asset Pool with {len(diversified_assets)} Recommended Assets",
                        id='add-diversified-assets-btn',
                        n_clicks=0,
                        disabled=len(diversified_assets) == 0,
                        style={
                            'backgroundColor': THEME['success'] if diversified_assets else THEME['text_sub'],
                            'color': 'white', 
                            'padding': '10px 25px', 
                            'border': 'none', 
                            'borderRadius': '5px', 
                            'cursor': 'pointer' if diversified_assets else 'not-allowed',
                            'fontWeight': 'bold',
                            'fontSize': '14px'
                        }
                    ),
                    html.Span(
                        id='add-diversified-status',
                        style={'marginLeft': '15px', 'color': THEME['text_sub'], 'fontSize': '12px'}
                    )
                ], style={'marginTop': '15px'})
            ]), top_factors_list
            
        except Exception as e:
            return html.Div(f"Error calculating correlations: {str(e)}", style={'color': THEME['danger']}), []


    # 3.55 Add Diversified Assets to Pool Callback
    # Uses global variable instead of dcc.Store because dcc.Store data doesn't persist across tab switches
    @app.callback(
        Output('add-diversified-status', 'children'),
        Input('add-diversified-assets-btn', 'n_clicks'),
        prevent_initial_call=True
    )
    def add_diversified_assets_to_pool(n_clicks):
        """
        Replace the asset pool with recommended diversified assets.
        Uses global DIVERSIFICATION_RECOMMENDATIONS instead of dcc.Store.
        Saves directly to persistent storage file - Portfolio tab will pick up changes on next load.
        """
        if not n_clicks or n_clicks == 0:
            return ""
        
        # Get assets from global variable (set by correlation analysis)
        recommended_assets = DIVERSIFICATION_RECOMMENDATIONS.get('assets', [])
        
        if not recommended_assets:
            return "⚠ No recommended assets available. Please run correlation analysis first."
        
        # REPLACE the entire asset pool with recommended assets (as user requested)
        new_pool = [asset.copy() for asset in recommended_assets]
        
        # Save to persistent storage immediately
        # This will be picked up by Portfolio tab when it loads/refreshes
        try:
            save_asset_pool(new_pool)
            
            # Count assets by type for status message
            type_counts = {}
            for asset in new_pool:
                a_type = asset.get('type', 'Other')
                type_counts[a_type] = type_counts.get(a_type, 0) + 1
            
            type_summary = ", ".join([f"{count} {t}" for t, count in type_counts.items()])
            status_msg = f"✓ Saved {len(new_pool)} assets to pool ({type_summary}). Switch to Portfolio tab to view."
            
            return status_msg
            
        except Exception as e:
            print(f"Error saving asset pool: {e}")
            return f"✗ Error saving: {str(e)}"

    # 3.6 Risk Factor Budget Input Generator
    @app.callback(
        Output('risk-budget-container', 'children'),
        [Input('asset-pool-store', 'data')]
    )
    def update_risk_budget_inputs(asset_pool):
        if not asset_pool:
             return [html.Div("Add assets to see risk factors", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px', 'textAlign': 'center'})]

        active_factors = set()
        
        # Mappings based on MultiAsset logic
        rates_map = {'CN': 'CN', 'US': 'US', 'EU': 'DE', 'UK': 'UK', 'JP': 'JP'}
        # comm_map keys should match asset names in pool
        comm_map = {'Gold': 'AU', 'Aluminium': 'AL', 'Copper': 'CU', 'Crude Oil': 'SC', 'Crude_Oil': 'SC'}

        for asset in asset_pool:
            a_type = asset.get('type')
            # Fallback if universe is code not name
            
            if a_type == 'Rates':
                asset_name = asset.get('name', '')
                prefix = asset_name[:2] # CN1Y -> CN
                rf_country = rates_map.get(prefix)
                # Handle EU case: EU->DE explicitly if map didn't catch (EU is in map keys as DE output)
                
                if rf_country:
                    active_factors.add(f"IRDL.{rf_country}")
                    active_factors.add(f"IRSL.{rf_country}")
                    active_factors.add(f"IRCV.{rf_country}")
            
            elif a_type == 'Spread':
                 # Name prefixes: IRS, CDB, ICP
                 asset_name = asset.get('name', '')
                 if asset_name.startswith('IRS'): code = 'IRS'
                 elif asset_name.startswith('CDB'): code = 'CDB'
                 elif asset_name.startswith('ICP'): code = 'ICP'
                 else: code = None
                 
                 if code:
                     active_factors.add(f"SPDL.{code}")
                     if code != 'ICP':
                         active_factors.add(f"SPSL.{code}")
            
            elif a_type == 'Commodities':
                 asset_name = asset.get('name', '')
                 # Map name to code
                 code = comm_map.get(asset_name)
                 if code:
                     active_factors.add(f"CMDL.{code}")

        if not active_factors:
             return [html.Div("No risk factors identified.", style={'color': THEME['text_sub'], 'fontSize': '12px'})]

        # Sort factors
        sorted_factors = sorted(list(active_factors))
        
        # Build Inputs
        inputs = []
        for factor in sorted_factors:
            inputs.append(
                html.Div([
                    html.Label(factor, style={'color': THEME['text_main'], 'fontSize': '12px', 'width': '80px', 'fontWeight': 'bold'}),
                    dcc.Input(
                        id={'type': 'risk-budget-input', 'index': factor},
                        type='number',
                        value=1,
                        min=0,
                        step=0.1,
                        style={'width': '60px', 'fontSize': '12px', 'padding': '2px', 'backgroundColor': '#fff', 'color': '#000', 'border': 'none', 'borderRadius': '2px'}
                    ),
                    html.Span("M", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '3px'})
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '5px', 'justifyContent': 'space-between'})
            )
        
        return inputs

    # 4. Run Analysis (Portfolio Tab -> Results)
    @app.callback(
        [Output('portfolio-table-container', 'children'),
         Output('status-message', 'children'),
         Output('timestamp-display', 'children'),
         Output('portfolio-data-store', 'data')],
        [Input('run-button', 'n_clicks')],
        [State('capital-input', 'value'),
         State('capital-unit', 'value'),
         State('risk-model-selector', 'value'),
         State('asset-pool-store', 'data'),
         State({'type': 'risk-budget-input', 'index': ALL}, 'value'),
         State({'type': 'risk-budget-input', 'index': ALL}, 'id')]
    )
    def run_analysis(n_clicks, total_capital, capital_unit, risk_model, asset_pool, budget_values, budget_ids):
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
            
            # Parse Risk Budgets
            risk_budgets = None
            if budget_ids and budget_values:
                risk_budgets = {}
                for val, id_dict in zip(budget_values, budget_ids):
                    factor_name = id_dict['index']
                    try:
                        risk_budgets[factor_name] = float(val) if val is not None else 1.0
                    except (ValueError, TypeError):
                        pass

            # Determine use_deterministic flag
            use_deterministic = (risk_model == 'deterministic')

            # Run optimization
            summary, returns, vols, factor_exp, factor_risk, portfolio = run_risk_parity_allocation(
                total_capital=total_capital_cny, use_cache=True, selected_assets=selected_asset_names,
                risk_budgets=risk_budgets, use_deterministic=use_deterministic
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
                    'textAlign': 'center', 
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
                        # The bond code is in the index. promote it to a column 'Code'
                        bond_data = bond_data.copy()
                        bond_data['Code'] = bond_data.index

                        # Ensure columns exist (case insensitive check)
                        cols = {c.lower(): c for c in bond_data.columns}
                        
                        col_ttm = cols.get('ttm')
                        col_z = cols.get('zscore') or cols.get('z-score')
                        col_id = cols.get('code') # Should resolve to 'Code'
                        col_name = cols.get('name') or cols.get('wind_code') or col_id # Fallback to Code if Name missing

                        if col_ttm and col_z and col_id:
                            # User Logic:
                            # CN1Y: 0 < ttm <= 1
                            # CN2Y: 1 < ttm <= 2
                            # CN5Y: 2 < ttm <= 5
                            # CN10Y: 5 < ttm <= 10
                            
                            # Identify which "Rates" assets are in the selected pool to decide which buckets to show
                            # OR just show all relevant signals for buckets that have data and signals.
                            # User requested logic maps asset names to TTM buckets.
                            
                            pool_asset_sectors = []
                            for asset in asset_pool:
                                if asset.get('type') == 'Rates' and asset.get('universe') in ['China Gov Bond', 'CN']:
                                     sec = asset.get('sector', '')
                                     if sec: pool_asset_sectors.append(sec.strip())
                            
                            # Define buckets
                            buckets = {
                                '1Y': (0, 1),
                                '2Y': (1, 2),
                                '5Y': (2, 5),
                                '10Y': (5, 10),
                                '30Y': (10, 30) # Added 30Y just in case, though user didn't explicitly ask for signal logic yet.
                            }
                            
                            # If no specific Rates assets selected, maybe show nothing or just 1Y? 
                            # User context: "When asset allocation HAS other term treasuries..." -> implies filtering by pool.
                            # If pool is empty of CN Rates, we might default to showing nothing or just 1Y as before?
                            # Let's show buckets present in the pool.
                            
                            target_sectors = [s for s in pool_asset_sectors if s in buckets]
                            # If user manually added "CN1Y" (which is 'Rates' 'China Gov Bond' '1Y'), we process '1Y'.
                            
                            signal_tables = []
                            
                            for sector in target_sectors:
                                min_t, max_t = buckets[sector]
                                # Filter data for this bucket
                                # Assuming bond_data has all bonds.
                                df_bucket = bond_data[(bond_data[col_ttm] > min_t) & (bond_data[col_ttm] <= max_t)].copy()
                                
                                if df_bucket.empty: continue

                                # Buy Candidates: Lowest z-score (most negative)
                                # Sell Candidates: Highest z-score (most positive)
                                buy_list = df_bucket.sort_values(col_z, ascending=True).head(5)
                                sell_list = df_bucket.sort_values(col_z, ascending=False).head(5)
                                
                                # Helper to format a table
                                def make_mini_table(df, title, color):
                                    if df.empty: return html.Div()
                                    
                                    # Define target columns, avoiding duplicates if Name fallback calls to Code
                                    target_cols = [col_id]
                                    if col_name != col_id:
                                        target_cols.append(col_name)
                                    target_cols.extend([col_ttm, col_z])
                                    
                                    # Ensure columns exist
                                    valid_cols = [c for c in target_cols if c in df.columns]
                                    
                                    # Map to display names
                                    display_cols_map = {col_id: 'Code', col_name: 'Name', col_ttm: 'TTM', col_z: 'Z-Score'}
                                    
                                    records = df[valid_cols].to_dict('records')
                                    
                                    formatted_records = []
                                    for r in records:
                                        # Data Formatting
                                        if col_ttm in r: r[col_ttm] = f"{r[col_ttm]:.2f}Y"
                                        if col_z in r: r[col_z] = f"{r[col_z]:.2f}"
                                        
                                        # Rename keys
                                        new_r = {}
                                        for c in valid_cols:
                                            d_name = display_cols_map.get(c, c)
                                            new_r[d_name] = r[c]
                                        formatted_records.append(new_r)
                                    
                                    final_cols = [{'name': display_cols_map.get(c, c), 'id': display_cols_map.get(c, c)} for c in valid_cols]

                                    return html.Div([
                                        html.H6(title, style={'color': color, 'marginBottom': '5px', 'textAlign': 'center', 'fontSize': '11px'}),
                                        dash_table.DataTable(
                                            data=formatted_records,
                                            columns=final_cols,
                                            style_cell={'textAlign': 'center', 'padding': '4px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'border': 'none', 'fontSize': '11px'},
                                            style_header={'backgroundColor': THEME['bg_card'], 'fontWeight': 'bold', 'color': color, 'border': 'none'}
                                        )
                                    ], style={'flex': '1', 'margin': '2px'})

                                sector_div = html.Div([
                                    html.H5(f"CN {sector} ({min_t}-{max_t}Y) Signals", style={'color': THEME['text_main'], 'marginTop': '10px', 'fontSize': '13px', 'borderBottom': f'1px dashed {THEME["text_sub"]}'}),
                                    html.Div([
                                        make_mini_table(buy_list, "BUY (Low Z)", THEME['success']),
                                        make_mini_table(sell_list, "SELL (High Z)", THEME['danger'])
                                    ], style={'display': 'flex', 'gap': '5px'})
                                ], style={'marginBottom': '10px', 'backgroundColor': 'rgba(255,255,255,0.03)', 'padding': '5px', 'borderRadius': '5px', 'flex': '1 1 30%', 'minWidth': '300px'})
                                
                                signal_tables.append(sector_div)

                            if signal_tables:
                                bond_signal_table = html.Div([
                                    html.H5("Bond Trading Signals (Z-Score)", style={'color': THEME['text_main'], 'marginTop': '20px', 'borderTop': f'1px solid {THEME["text_sub"]}', 'paddingTop': '10px'}),
                                    html.Div(signal_tables, style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '10px', 'justifyContent': 'flex-start'})
                                ])
                            else:
                                bond_signal_table = None

                        else:
                            print("Missing required columns for bond signals (ttm, z-score, code)")
                            bond_signal_table = None


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

    # 4.5 Backtest Factor Pool Display and Min Date Info
    @app.callback(
        [Output('backtest-factor-pool-display', 'children'),
         Output('backtest-min-date-info', 'children')],
        [Input('run-history-button', 'n_clicks')],
        [State('backtest-corr-lookback', 'value')],
        prevent_initial_call=False
    )
    def update_backtest_factor_pool_display(n_clicks, corr_lookback):
        """Display the current factor pool from Factor tab and calculate minimum supported date."""
        all_factors = []
        all_factors.extend(SELECTED_FACTOR_POOL.get('ir_factors', []))
        all_factors.extend(SELECTED_FACTOR_POOL.get('sp_factors', []))
        all_factors.extend(SELECTED_FACTOR_POOL.get('fx_factors', []))
        all_factors.extend(SELECTED_FACTOR_POOL.get('cmd_factors', []))
        
        if not all_factors:
            return ("⚠️ No factors selected. Go to Factor tab to select factors.",
                    "ℹ️ Select factors first to see minimum supported date.")
        
        # Calculate minimum supported date based on selected factors
        try:
            loader = RiskFactorLoader(DIR_INPUT)
            risk_factors = loader.load_risk_factors(use_cache=True)
            risk_factors.index = pd.to_datetime(risk_factors.index)
            
            available_factors = [f for f in all_factors if f in risk_factors.columns]
            if len(available_factors) >= 2:
                # Find the latest start date among selected factors
                factor_data = risk_factors[available_factors].dropna(how='any')
                factor_data_start = factor_data.index.min()
                factor_data_end = factor_data.index.max()
                
                # Determine lookback period
                if corr_lookback == '6M':
                    lookback_delta = relativedelta(months=6)
                elif corr_lookback == '1Y':
                    lookback_delta = relativedelta(years=1)
                else:
                    lookback_delta = relativedelta(months=3)
                
                earliest_valid_date = factor_data_start + lookback_delta
                
                # Find the limiting factor (the one with latest start date)
                latest_factor = None
                latest_start = None
                for f in available_factors:
                    f_start = risk_factors[f].dropna().index.min()
                    if latest_start is None or f_start > latest_start:
                        latest_start = f_start
                        latest_factor = f
                
                min_date_info = (f"ℹ️ Min supported date: {earliest_valid_date.strftime('%Y-%m-%d')} "
                               f"(Data: {factor_data_start.strftime('%Y-%m-%d')} ~ {factor_data_end.strftime('%Y-%m-%d')}, "
                               f"limited by {latest_factor})")
            else:
                min_date_info = "⚠️ Not enough factors available in data."
        except Exception as e:
            min_date_info = f"⚠️ Error calculating date range: {str(e)}"
        
        factor_display = f"{len(all_factors)} factors: {', '.join(all_factors)}"
        return factor_display, min_date_info

    # 5. Historical Analysis (Backtest Tab) - Correlation-Based Strategy
    @app.callback(
        [Output('historical-allocation-chart', 'figure'),
         Output('pnl-attribution-chart', 'figure'),
         Output('performance-metrics-container', 'children'),
         Output('asset-changes-container', 'children')],
        [Input('run-history-button', 'n_clicks')],
        [State('backtest-capital-input', 'value'),
         State('backtest-capital-unit', 'value'),
         State('history-date-range', 'start_date'),
         State('history-date-range', 'end_date'),
         State('backtest-corr-lookback', 'value'),
         State('backtest-top-pairs', 'value')]
    )
    def update_historical_allocation(n_clicks, total_capital, capital_unit, start_date, end_date, corr_lookback, top_pairs):
        """
        Correlation-Based Historical Allocation Strategy:
        1. At each month start, run correlation analysis on risk factors
        2. Select assets with lowest correlations for diversification
        3. Run Risk Parity (1/Vol) allocation on the selected assets
        4. Track asset pool changes over time
        """
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="Click 'Run Historical Analysis' to start",
            template=THEME['chart_template'],
            paper_bgcolor=THEME['bg_main'],
            plot_bgcolor=THEME['bg_main'],
            font={'color': THEME['text_main']}
        )
        
        if n_clicks == 0:
            return empty_fig, empty_fig, None, None
        
        try:
            # Parse dates
            print(f"\n[DEBUG] Received dates: start_date={start_date}, end_date={end_date}")
            start_date = pd.to_datetime(start_date) if start_date else None
            end_date = pd.to_datetime(end_date) if end_date else None
            print(f"[DEBUG] Parsed dates: start_date={start_date}, end_date={end_date}")
            top_pairs = int(top_pairs) if top_pairs else 10
            
            # Load risk factor data
            loader = RiskFactorLoader(DIR_INPUT)
            risk_factors = loader.load_risk_factors(use_cache=True)
            risk_factors.index = pd.to_datetime(risk_factors.index)
            market_data = load_raw_market_data()
            
            if risk_factors.empty:
                err_fig = go.Figure().update_layout(title="No risk factor data available", template=THEME['chart_template'])
                return err_fig, err_fig, None, html.Div("No data", style={'color': THEME['warning']})
            
            # Get selected factors from global factor pool (set in Factor tab)
            selected_factors = []
            selected_factors.extend(SELECTED_FACTOR_POOL.get('ir_factors', []))
            selected_factors.extend(SELECTED_FACTOR_POOL.get('sp_factors', []))
            selected_factors.extend(SELECTED_FACTOR_POOL.get('fx_factors', []))
            selected_factors.extend(SELECTED_FACTOR_POOL.get('cmd_factors', []))
            
            if len(selected_factors) < 2:
                err_fig = go.Figure().update_layout(
                    title="⚠️ Please select at least 2 factors in the Factor tab first",
                    template=THEME['chart_template'],
                    paper_bgcolor=THEME['bg_main'],
                    plot_bgcolor=THEME['bg_main'],
                    font={'color': THEME['text_main']}
                )
                return err_fig, err_fig, None, html.Div(
                    "Go to Factor tab and select factors for the analysis pool.", 
                    style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'}
                )
            
            print(f"Using factor pool from Factor tab: {selected_factors}")
            
            # Filter risk_factors to only include selected factors that exist in data
            available_factors = [f for f in selected_factors if f in risk_factors.columns]
            if len(available_factors) < 2:
                err_fig = go.Figure().update_layout(
                    title=f"⚠️ Only {len(available_factors)} of selected factors found in data",
                    template=THEME['chart_template'],
                    paper_bgcolor=THEME['bg_main'],
                    plot_bgcolor=THEME['bg_main'],
                    font={'color': THEME['text_main']}
                )
                missing = [f for f in selected_factors if f not in risk_factors.columns]
                return err_fig, err_fig, None, html.Div(
                    f"Missing factors: {missing}", 
                    style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'}
                )
            
            # Get the actual data range for selected factors
            # Use dropna(how='any') to ensure ALL selected factors have data
            selected_factor_data = risk_factors[available_factors].dropna(how='any')
            factor_data_start = selected_factor_data.index.min()
            factor_data_end = selected_factor_data.index.max()
            
            # Find which factor limits the start date (latest starting factor)
            limiting_factors = []
            for f in available_factors:
                f_start = risk_factors[f].dropna().index.min()
                if f_start is not None and f_start >= factor_data_start - pd.Timedelta(days=30):
                    limiting_factors.append((f, f_start.date()))
            limiting_factors.sort(key=lambda x: x[1], reverse=True)
            
            print(f"Available factors in data: {available_factors}")
            print(f"Selected factor data range (ALL factors): {factor_data_start.date()} to {factor_data_end.date()}")
            if limiting_factors:
                print(f"Limiting factors (latest start): {limiting_factors[:3]}")
            
            # Set date range
            if not end_date:
                end_date = factor_data_end
            if not start_date:
                start_date = end_date - relativedelta(years=1)
            
            # Determine correlation lookback period
            if corr_lookback == '3M':
                corr_lookback_delta = relativedelta(months=3)
            elif corr_lookback == '6M':
                corr_lookback_delta = relativedelta(months=6)
            elif corr_lookback == '1Y':
                corr_lookback_delta = relativedelta(years=1)
            else:
                corr_lookback_delta = relativedelta(months=3)
            
            # Calculate earliest valid rebalance date based on selected factor data
            earliest_valid_date = factor_data_start + corr_lookback_delta
            
            print(f"[DEBUG] factor_data_start={factor_data_start.date()}, lookback={corr_lookback}")
            print(f"[DEBUG] earliest_valid_date={earliest_valid_date.date()}")
            print(f"[DEBUG] User start_date={start_date.date()}, end_date={end_date.date()}")
            
            # Check if user's selected start date is before minimum supported date
            if start_date < earliest_valid_date:
                limiting_factor_info = f" (limited by {limiting_factors[0][0]})" if limiting_factors else ""
                err_fig = go.Figure().update_layout(
                    title=f"⚠️ Selected start date {start_date.strftime('%Y-%m-%d')} is before minimum supported date {earliest_valid_date.strftime('%Y-%m-%d')}{limiting_factor_info}",
                    template=THEME['chart_template'],
                    paper_bgcolor=THEME['bg_main'],
                    plot_bgcolor=THEME['bg_main'],
                    font={'color': THEME['text_main']}
                )
                return err_fig, err_fig, None, html.Div(
                    f"Please select a start date on or after {earliest_valid_date.strftime('%Y-%m-%d')}. "
                    f"The minimum date is determined by factor data availability (starts {factor_data_start.strftime('%Y-%m-%d')}) "
                    f"plus the correlation lookback period ({corr_lookback}).",
                    style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'}
                )
            
            # Generate rebalance dates (beginning of each month) - now starting from user's selected date
            rebalance_dates = []
            current_date = start_date.replace(day=1)
            while current_date <= end_date:
                rebalance_dates.append(current_date)
                current_date += relativedelta(months=1)
            
            print(f"[DEBUG] Rebalance dates: {len(rebalance_dates)} from {rebalance_dates[0].date()} to {rebalance_dates[-1].date()}")
            
            if not rebalance_dates:
                err_fig = go.Figure().update_layout(title="Not enough historical data for the selected period", template=THEME['chart_template'])
                return err_fig, err_fig, None, html.Div("Insufficient data", style={'color': THEME['warning']})
            
            # Convert capital
            total_capital_value = float(total_capital) if total_capital else 100
            if capital_unit == 'billion':
                total_capital_value *= 1_000
            total_capital_cny = total_capital_value * 1_000_000  # Convert to CNY
            
            # Track allocations and asset changes
            history_data = []
            allocations_by_date = {}
            asset_pools_by_date = {}  # Track asset pool changes
            all_assets_ever = set()
            
            print(f"\n{'='*60}")
            print(f"Running Correlation-Based Backtest: {start_date.date()} to {end_date.date()}")
            print(f"Rebalance dates: {len(rebalance_dates)}")
            print(f"First rebalance: {rebalance_dates[0].date() if rebalance_dates else 'N/A'}")
            print(f"Last rebalance: {rebalance_dates[-1].date() if rebalance_dates else 'N/A'}")
            print(f"{'='*60}")
            
            for rebalance_date in rebalance_dates:
                # --- Step 1: Run Correlation Analysis on Selected Factor Pool ---
                corr_end = rebalance_date
                corr_start = rebalance_date - corr_lookback_delta
                
                df_subset = risk_factors.loc[corr_start:corr_end]
                if df_subset.empty or len(df_subset) < 20:
                    print(f"  {rebalance_date.date()}: Skipped (insufficient data)")
                    continue
                
                # Filter to only selected factors from the Factor tab
                available_factors = [f for f in selected_factors if f in df_subset.columns]
                if len(available_factors) < 2:
                    print(f"  {rebalance_date.date()}: Skipped (not enough factors in data)")
                    continue
                df_subset = df_subset[available_factors]
                
                # Calculate daily changes for correlation
                df_changes = df_subset.diff().dropna()
                if df_changes.empty:
                    continue
                
                corr_matrix = df_changes.corr()
                
                # Find lowest correlation pairs
                mask = np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
                corr_stacked = corr_matrix.where(mask).stack().reset_index()
                corr_stacked.columns = ['Factor A', 'Factor B', 'Correlation']
                corr_stacked['AbsCorrelation'] = corr_stacked['Correlation'].abs()
                bottom_pairs = corr_stacked.sort_values('AbsCorrelation', ascending=True).head(top_pairs)
                
                # Get unique factors from lowest correlation pairs
                low_corr_factors = set(bottom_pairs['Factor A']).union(set(bottom_pairs['Factor B']))
                low_corr_factors_list = sorted(list(low_corr_factors))
                
                # --- Step 2: Map Factors to Assets ---
                selected_assets = get_assets_from_factors(low_corr_factors_list)
                
                if not selected_assets:
                    print(f"  {rebalance_date.date()}: Skipped (no mappable assets)")
                    continue
                
                selected_asset_names = [a['name'] for a in selected_assets]
                all_assets_ever.update(selected_asset_names)
                
                # --- Step 3: Run PCA Factor Risk Parity Allocation ---
                # Create portfolio for these assets
                try:
                    portfolio = create_custom_portfolio(selected_asset_names)
                except Exception as e:
                    print(f"  {rebalance_date.date()}: Portfolio creation failed: {e}")
                    continue
                
                # Use PCA Factor Risk Parity optimizer
                try:
                    pca_optimizer = PCAFactorRiskParityOptimizer(
                        portfolio=portfolio, 
                        input_dir=str(DIR_INPUT),
                        pca_lookback_years=1.0, 
                        vol_lookback_months=3, 
                        ewma_lambda=0.94
                    )
                    weights_series, _ = pca_optimizer.fit_and_calculate(pd.Timestamp(rebalance_date))
                    weights = weights_series.to_dict()
                except Exception as e:
                    print(f"  {rebalance_date.date()}: PCA optimization failed: {e}")
                    continue
                
                if not weights or sum(weights.values()) == 0:
                    print(f"  {rebalance_date.date()}: Skipped (invalid weights)")
                    continue
                
                # Filter out negligible weights (floating point precision artifacts)
                weights = {k: v for k, v in weights.items() if abs(v) >= 1e-6}
                
                # Renormalize weights after filtering
                weight_sum = sum(weights.values())
                if weight_sum > 0:
                    weights = {k: v / weight_sum for k, v in weights.items()}
                else:
                    continue
                
                # Store only assets with non-negligible weights in asset pool tracking
                filtered_assets = [a for a in selected_assets if a['name'] in weights]
                asset_pools_by_date[rebalance_date] = filtered_assets
                
                # Calculate allocations
                row = {'Date': rebalance_date}
                current_allocations = {}
                for name, weight in weights.items():
                    alloc = weight * total_capital_cny
                    row[name] = alloc / 1_000_000  # Store in millions for chart
                    current_allocations[name] = alloc
                
                history_data.append(row)
                allocations_by_date[rebalance_date] = current_allocations
                
                print(f"  {rebalance_date.date()}: {len(selected_asset_names)} assets, {len(low_corr_factors_list)} factors")
            
            if not history_data:
                err_fig = go.Figure().update_layout(title="No valid rebalance periods found", template=THEME['chart_template'])
                return err_fig, err_fig, None, html.Div("No valid periods", style={'color': THEME['warning']})
            
            # Use user-selected date range for display (we already validated it's valid)
            display_start = start_date
            display_end = end_date
            
            # --- Calculate Daily PnL ---
            all_dates = sorted(risk_factors.loc[(risk_factors.index >= start_date) & (risk_factors.index <= end_date)].index)
            sorted_rebalance_dates = sorted(allocations_by_date.keys())
            
            # Pre-compute daily returns for all assets ever held
            asset_daily_returns = {}
            for name in all_assets_ever:
                try:
                    ret_df = calculate_daily_returns_series(name, market_data, start_date, end_date)
                    if not ret_df.empty:
                        ret_df = ret_df.set_index('Date')
                        asset_daily_returns[name] = ret_df
                except Exception as e:
                    print(f"  Warning: Could not load returns for {name}: {e}")
            
            daily_pnl_records = []
            cumulative_pnl = {name: 0.0 for name in all_assets_ever}
            cumulative_pnl['Total'] = 0.0
            
            for trading_day in all_dates:
                # Find applicable allocation (most recent rebalance before this day)
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
                
                for name in all_assets_ever:
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
            
            # --- Create Allocation Chart ---
            fig_alloc = go.Figure()
            for asset_name in sorted(all_assets_ever):
                if asset_name in df_history.columns:
                    fig_alloc.add_trace(go.Scatter(
                        x=df_history['Date'], 
                        y=df_history[asset_name].fillna(0),
                        mode='lines+markers', 
                        name=asset_name, 
                        stackgroup='one'
                    ))
            
            fig_alloc.update_layout(
                title=f"Historical Portfolio Allocation ({display_start.strftime('%Y-%m-%d')} to {display_end.strftime('%Y-%m-%d')})",
                xaxis_title="Date", 
                yaxis_title="Allocation (Million CNY)",
                hovermode='x unified', 
                template=THEME['chart_template'], 
                height=400,
                paper_bgcolor=THEME['bg_main'], 
                plot_bgcolor=THEME['bg_main'], 
                font={'color': THEME['text_main']},
                legend=dict(orientation="h", y=1.02, x=1, xanchor="right", font={'color': THEME['text_main'], 'size': 10}),
                xaxis=dict(gridcolor=THEME['table_header']),
                yaxis=dict(gridcolor=THEME['table_header'])
            )
            
            # --- Create PnL Chart ---
            fig_pnl = go.Figure()
            if not df_pnl.empty:
                # Add total line prominently
                fig_pnl.add_trace(go.Scatter(
                    x=df_pnl['Date'], 
                    y=df_pnl['Total'],
                    mode='lines', 
                    name='Total Portfolio',
                    line=dict(color='#00cc96', width=3)
                ))
            
            fig_pnl.update_layout(
                title=f"Cumulative PnL ({display_start.strftime('%Y-%m-%d')} to {display_end.strftime('%Y-%m-%d')})",
                xaxis_title="Date", 
                yaxis_title="Cumulative PnL (Million CNY)",
                hovermode='x unified', 
                template=THEME['chart_template'], 
                height=350,
                paper_bgcolor=THEME['bg_main'], 
                plot_bgcolor=THEME['bg_main'], 
                font={'color': THEME['text_main']},
                legend=dict(orientation="h", y=1.02, x=1, xanchor="right", font={'color': THEME['text_main']}),
                xaxis=dict(gridcolor=THEME['table_header']),
                yaxis=dict(gridcolor=THEME['table_header'])
            )
            
            # --- Calculate Performance Metrics ---
            metrics_table = None
            if not df_pnl.empty and len(df_pnl) > 1:
                initial_capital = total_capital_cny / 1_000_000
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
                        html.Th("# Rebalances", style={'padding': '8px 15px', 'backgroundColor': THEME['table_header'], 'color': 'white'}),
                    ]),
                    html.Tr([
                        html.Td(f"{annualized_return:.2%}", style={'padding': '8px 15px', 'textAlign': 'center', 'fontWeight': 'bold',
                                                                'color': THEME['success'] if annualized_return >= 0 else THEME['danger'], 'backgroundColor': THEME['bg_input']}),
                        html.Td(f"{sharpe_ratio:.2f}", style={'padding': '8px 15px', 'textAlign': 'center', 'fontWeight': 'bold',
                                                            'color': THEME['success'] if sharpe_ratio >= 1 else THEME['warning'] if sharpe_ratio >= 0 else THEME['danger'], 'backgroundColor': THEME['bg_input']}),
                        html.Td(f"{max_drawdown:.2%}", style={'padding': '8px 15px', 'textAlign': 'center', 'fontWeight': 'bold', 'color': THEME['danger'], 'backgroundColor': THEME['bg_input']}),
                        html.Td(f"{len(allocations_by_date)}", style={'padding': '8px 15px', 'textAlign': 'center', 'fontWeight': 'bold', 'color': THEME['text_main'], 'backgroundColor': THEME['bg_input']}),
                    ]),
                ], style={'borderCollapse': 'collapse', 'fontSize': '14px'})
            
            # --- Build Monthly Holdings Table ---
            asset_holdings_rows = []
            
            for rb_date in sorted_rebalance_dates:
                assets = asset_pools_by_date.get(rb_date, [])
                current_assets = sorted([a['name'] for a in assets])
                
                asset_holdings_rows.append({
                    'Date': rb_date.strftime('%Y-%m'),
                    'Asset Count': len(current_assets),
                    'Holdings': ", ".join(current_assets) if current_assets else "-"
                })
            
            asset_holdings_df = pd.DataFrame(asset_holdings_rows)
            
            asset_changes_table = html.Div([
                html.H5("📅 Monthly Asset Holdings", style={'color': THEME['text_main'], 'marginBottom': '10px', 'marginTop': '20px'}),
                dash_table.DataTable(
                    data=asset_holdings_df.to_dict('records'),
                    columns=[
                        {'name': 'Month', 'id': 'Date'},
                        {'name': '# Assets', 'id': 'Asset Count'},
                        {'name': 'Holdings', 'id': 'Holdings'},
                    ],
                    style_cell={
                        'textAlign': 'left', 
                        'padding': '8px 10px', 
                        'fontFamily': 'Arial, sans-serif',
                        'backgroundColor': THEME['table_row_odd'],
                        'color': THEME['text_main'],
                        'border': 'none',
                        'fontSize': '12px',
                        'whiteSpace': 'normal',
                        'height': 'auto',
                    },
                    style_cell_conditional=[
                        {'if': {'column_id': 'Date'}, 'width': '80px'},
                        {'if': {'column_id': 'Asset Count'}, 'width': '80px', 'textAlign': 'center'},
                        {'if': {'column_id': 'Holdings'}, 'minWidth': '300px'},
                    ],
                    style_header={
                        'backgroundColor': THEME['table_header'], 
                        'color': THEME['text_main'], 
                        'fontWeight': 'bold', 
                        'textAlign': 'left',
                        'border': 'none'
                    },
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                    ],
                    style_table={'overflowX': 'auto', 'maxHeight': '400px', 'overflowY': 'auto'}
                )
            ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px'})
            
            return fig_alloc, fig_pnl, metrics_table, asset_changes_table
            
        except Exception as e:
            traceback.print_exc()
            err_fig = go.Figure().update_layout(title=f"Error: {str(e)}", template=THEME['chart_template'])
            return err_fig, err_fig, None, html.Div(f"Error: {str(e)}", style={'color': THEME['danger']})

    # 6. Futures Backtest Callbacks
    @app.callback(
        [Output('bf-wind-inputs', 'style'), Output('bf-local-inputs', 'style')],
        [Input('bf-data-source', 'value')]
    )
    def bf_toggle_inputs(source):
        if source == 'wind':
            return {'display': 'block'}, {'display': 'none'}
        return {'display': 'none'}, {'display': 'block'}
    
    @app.callback(
        Output('bf-timeframe-container', 'style'),
        [Input('bf-trading-mode', 'value')]
    )
    def bf_toggle_timeframe(mode):
        if mode == 'daily':
            return {'display': 'none'}
        return {'display': 'block'}
    
    @app.callback(
        [Output('bf-wind-code', 'options'), Output('bf-wind-code', 'value')],
        [Input('bf-trading-mode', 'value')]
    )
    def bf_update_wind_options(mode):
        if not FUTURES_AVAILABLE: return [], None
        try:
            if mode == 'daily':
                opts = [{'label': s, 'value': s} for s in FuturesConfig.SYMBOLS]
                def_val = 'TL.CFE' if 'TL.CFE' in FuturesConfig.SYMBOLS else FuturesConfig.SYMBOLS[0]
            else:
                contract_list = FuturesConfig.get_contract_no()
                opts = [{'label': c, 'value': c} for c in contract_list]
                def_val = contract_list[0] if contract_list else None
            return opts, def_val
        except Exception:
             return [], None

    @app.callback(
        [Output('bf-local-symbol', 'options'),
         Output('bf-local-symbol', 'value')],
        [Input('bf-trading-mode', 'value')]
    )
    def bf_update_local_symbol_options(mode):
        if not FUTURES_AVAILABLE: return [], None
        try:
            if mode == 'daily':
                opts = [{'label': s, 'value': s} for s in FuturesConfig.SYMBOLS]
                def_val = 'TL.CFE' if 'TL.CFE' in FuturesConfig.SYMBOLS else FuturesConfig.SYMBOLS[0]
            else:
                contract_list = FuturesConfig.get_contract_no()
                opts = [{'label': c, 'value': c} for c in contract_list]
                def_val = contract_list[0] if contract_list else None
            return opts, def_val
        except Exception:
             return [], None

    @app.callback(
        Output('bf-results-container', 'children'),
        [Input('bf-run-button', 'n_clicks')],
        [State('bf-data-source', 'value'),
         State('bf-trading-mode', 'value'),
         State('bf-wind-code', 'value'),
         State('bf-local-symbol', 'value'),
         State('bf-date-range', 'start_date'),
         State('bf-date-range', 'end_date'),
         State('bf-timeframe', 'value'),
         State('bf-strategy-selector', 'value'),
         State('bf-ma-short', 'value'),
         State('bf-ma-long', 'value'),
         State('bf-boll-window', 'value'),
         State('bf-boll-std', 'value'),
         State('bf-boll-exit', 'value'),
         State('bf-vwap-window', 'value'),
         State('bf-mom-window', 'value'),
         State('bf-atr-ema-window', 'value'),
         State('bf-atr-window', 'value'),
         State('bf-sar-af', 'value'),
         State('bf-sar-max-af', 'value')]
    )
    def bf_update_dashboard(n_clicks, source, trading_mode, wind_code, local_symbol, start_date, end_date, tf, 
                         selected_strategies,
                         ma_s, ma_l, boll_w, boll_std, boll_exit, vwap_w, mom_w, atr_ema_w, atr_w,
                         sar_af, sar_max_af):
        if n_clicks == 0:
            return html.Div('Please configure parameters and click "Start Backtest"', style={'text-align': 'center', 'marginTop': '50px', 'color': THEME['text_sub']})
        
        if not FUTURES_AVAILABLE:
            return html.Div("Modules not loaded.", style={'color': THEME['danger']})

        selected_strategies = selected_strategies or []
        effective_tf = '1D' if trading_mode == 'daily' else tf
        
        # Load Data
        df = None
        err_msg = None
        
        try:
            if source == 'wind':
                if not wind_code: return html.Div("Please enter Wind symbol", style={'color': THEME['danger']})
                s_str = f"{start_date} 00:00:00"
                e_str = f"{end_date} 23:59:59"
                df, err_msg = load_wind_data(wind_code, s_str, e_str)
            else:
                if not local_symbol: return html.Div("Please enter symbol", style={'color': THEME['danger']})
                file_path = get_local_file_path(local_symbol, effective_tf)
                if not file_path:
                    return html.Div("Unable to construct file path", style={'color': THEME['danger']})
                
                contract_key = local_symbol if trading_mode == 'daily' else None
                df, err_msg = load_local_data_processed(file_path, contract_key)
                if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                    s_ts = pd.to_datetime(start_date)
                    e_ts = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                    df = df[(df.index >= s_ts) & (df.index <= e_ts)]
                
            if err_msg:
                return html.Div(f"Data loading error: {err_msg}", style={'color': THEME['danger']})
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                return html.Div("Data is empty (please check date range)", style={'color': THEME['danger']})

            # Resample
            if effective_tf == '1D':
                if not isinstance(df.index, pd.DatetimeIndex):
                    df.index = pd.to_datetime(df.index, errors='coerce')
                df_resampled = df.copy()
                df_resampled = df_resampled[~df_resampled.index.duplicated(keep='last')]
            else:
                df_resampled = resample_data(df, effective_tf)
                
            if df_resampled.empty:
                return html.Div("Data is empty after resampling", style={'color': THEME['danger']})
                
            # Run strategies
            results = {}
            if 'MA' in selected_strategies:
                results['MA'] = run_ma_strategy(df_resampled, ma_s, ma_l)
            if 'Boll' in selected_strategies:
                exit_at_ma = 'exit' in (boll_exit or [])
                results['Boll'] = run_bollinger_strategy(df_resampled, boll_w, boll_std, exit_at_ma)
            if 'VWAP' in selected_strategies:
                results['VWAP'] = run_vwap_strategy(df_resampled, vwap_w)
            if 'Mom' in selected_strategies:
                results['Mom'] = run_intraday_momentum_strategy(df_resampled, mom_w)
            if 'ATR' in selected_strategies:
                results['ATR'] = run_atr_band_strategy(df_resampled, atr_ema_w, atr_w)
            if 'SAR' in selected_strategies:
                results['SAR'] = run_sar_strategy(df_resampled, sar_af, sar_max_af)

            # Create Plotly Chart
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                vertical_spacing=0.03, row_heights=[0.7, 0.3])

            # Candlestick
            fig.add_trace(go.Candlestick(
                x=df_resampled.index,
                open=df_resampled['open'], high=df_resampled['high'],
                low=df_resampled['low'], close=df_resampled['close'],
                name='Price'
            ), row=1, col=1)
            
            # Strategy Equity Curves
            for name, res in results.items():
                fig.add_trace(go.Scatter(
                    x=res.index, 
                    y=res['cumulative_returns'],
                    mode='lines', name=f'{name} Equity'
                ), row=2, col=1)

            fig.update_layout(
                height=600, 
                title="Backtest Results",
                template=THEME['chart_template'],
                paper_bgcolor=THEME['bg_card'],
                plot_bgcolor=THEME['bg_card'],
                font={'color': THEME['text_main']},
                margin=dict(l=50, r=50, t=50, b=50),
                legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center"),
                xaxis_rangeslider_visible=False
            )
            fig.update_xaxes(gridcolor=THEME['table_header'])
            fig.update_yaxes(gridcolor=THEME['table_header'])

            # Helper for local Metric Card (redefined here or duplicated logic)
            def create_metric_card_local(title, metrics):
                return html.Div([
                    html.H6(title, style={'color': THEME['text_sub'], 'marginBottom': '5px', 'fontSize': '14px'}),
                    html.Div([
                        html.Div(f"Ret: {metrics.get('Total Return', 'N/A')}", style={'fontWeight': 'bold', 'color': THEME['success'] if str(metrics.get('Total Return')).startswith('+') else THEME['text_main']}),
                        html.Div(f"DD: {metrics.get('Max Drawdown', 'N/A')}", style={'color': THEME['danger']}),
                        html.Div(f"Sharpe: {metrics.get('Sharpe Ratio', 'N/A')}"),
                        html.Div(f"Trades: {metrics.get('Trades', 'N/A')}"),
                    ], style={'fontSize': '12px', 'lineHeight': '1.5', 'display': 'grid', 'gridTemplateColumns': '1fr 1fr', 'gap': '5px'})
                ], style={'backgroundColor': THEME['bg_input'], 'padding': '10px', 'borderRadius': '4px', 'marginBottom': '10px', 'flex': '1', 'minWidth': '150px'})

            # Card Display
            cards = []
            
            for name, res in results.items():
                m = calculate_metrics(res)
                cards.append(create_metric_card_local(name, m))
                
            return html.Div([
                html.Div(cards, style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '10px', 'marginBottom': '15px'}),
                dcc.Graph(figure=fig)
            ])

        except Exception as e:
            import traceback
            traceback.print_exc()
            return html.Div(f"Error running backtest: {str(e)}", style={'color': THEME['danger']})
