# -*- coding: utf-8 -*-
"""
Bridge for Multi-Asset Dashboard tabs into AtlasNexus Daily.
This module adapts the layouts and callbacks from `multiasset/dashboard.py` and `multiasset/layout.py`
for use within the AtlasNexus Daily application.
"""
from __future__ import annotations

import dash
from dash import dcc, html, dash_table, ALL, Patch
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
from multiasset.main import run_risk_parity_allocation, create_custom_portfolio, compute_irdl_hedge
from multiasset.storage import save_asset_pool
from multiasset.risk_loader import RiskFactorLoader
from multiasset.factor_optimizer import FactorRiskParityOptimizer
from multiasset.factor_backtest import compute_ewma_factor_vols
from multiasset.config import RiskModelConfig
from settings.paths import DIR_INPUT, DIR_MODELS, DIR_OUTPUT

# --- Import from futures.backtest for Backtest-Factor tab ---
import dash_bootstrap_components as dbc
try:
    from futures.backtest.data_loader import (
        discover_pkl_files, load_wind_data, 
        load_local_data_processed, resample_data, get_local_file_path
    )
    from futures.backtest.strategies import (
        run_ma_strategy, run_bollinger_strategy, run_vwap_strategy,
        run_intraday_momentum_strategy, run_atr_band_strategy, run_sar_strategy,
        run_demark_strategy
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

BOND_SIGNAL_FILE_MAP = {
    'TBond': 'TBond-spdsrt.pkl',
    'CBond': 'CBond-spdsrt.pkl',
    'GBond': 'GBond-spdsrt.pkl',
    'LBond': 'LBond-spdsrt.pkl',
    'BBond': 'BBond-spdsrt.pkl',
    'MNote': 'MNote-spdsrt.pkl',
}

BOND_SIGNAL_LABELS = {
    'TBond': 'Treasury Bond',
    'CBond': 'Policybank Bond',
    'GBond': 'Government-backed Bond',
    'LBond': 'Local Treasury Bond',
    'BBond': 'Commercial Bank Bond',
    'MNote': 'Medium Term Note',
}

BOND_SIGNAL_BUCKETS = [
    ('0-1Y', 0.0, 1.0),
    ('1-3Y', 1.0, 3.0),
    ('3-5Y', 3.0, 5.0),
    ('5-7Y', 5.0, 7.0),
    ('7-10Y', 7.0, 10.0),
]

# Global state for allocation results
ALLOCATION_RESULTS = {
    'summary': None,
    'factor_exposures': None,
    'factor_risk': None,
    'portfolio': None,
    'timestamp': None
}

RISK_BUDGET_VOL_LOOKBACK_YEARS = 1
RISK_BUDGET_EWMA_LAMBDA = 0.94

# Global state for low-correlation diversification recommendations
# This persists across tab switches (unlike dcc.Store which is tab-scoped)
DIVERSIFICATION_RECOMMENDATIONS = {
    'factors': [],      # List of factor names from low-correlation analysis
    'assets': [],       # List of recommended asset dictionaries
    'timestamp': None   # When the analysis was run
}

# ── Summary tab: portfolio snapshot file paths ─────────────────────────────
_SUMMARY_BETA_PARQUET  = str(DIR_INPUT / 'summary_beta_portfolio.parquet')
_SUMMARY_ALPHA_PARQUET = str(DIR_OUTPUT / 'summary_alpha_portfolio.parquet')

# Map asset-name prefix → primary risk factor (used for close-price lookup)
_ASSET_PREFIX_TO_FACTOR: dict[str, str] = {
    'CN':  'IRDL.CN',  'US':  'IRDL.US',  'EU':  'IRDL.DE',
    'JP':  'IRDL.JP',  'UK':  'IRDL.UK',
    'IRS': 'SPDL.IRS', 'CDB': 'SPDL.CDB', 'ICP': 'SPDL.ICP',
}


def _get_beta_close_prices() -> dict[str, float]:
    """Return {asset_name_prefix: last_factor_level} for Beta-Book close prices.

    Uses the most-recent row of the risk-factor level time series as a proxy.
    IR / Spread factors are reported in %; FX / Commodity not yet supported.
    """
    try:
        loader = RiskFactorLoader(DIR_INPUT)
        factor_levels = loader.load_risk_factors(use_cache=True)
        if factor_levels is None or factor_levels.empty:
            return {}
        last_row = factor_levels.iloc[-1]
        return {
            prefix: round(float(last_row[factor]), 4)
            for prefix, factor in _ASSET_PREFIX_TO_FACTOR.items()
            if factor in last_row.index and pd.notna(last_row[factor])
        }
    except Exception:
        return {}


# Global state for selected factor pool (shared between Factor tab and Backtest tab)
SELECTED_FACTOR_POOL = {
    'ir_factors': ['IRDL.CN', 'IRDL.US', 'IRSL.CN', 'IRSL.US'],  # Default selection
    'sp_factors': ['SPDL.IRS', 'SPDL.CDB'],
    'fx_factors': ['FXDL.USDCNY'],
    'cmd_factors': ['CMDL.AU', 'CMDL.CU'],
    'timestamp': None
}


def compute_factor_vol_map(
    factor_names: list[str],
    lookback_years: int = RISK_BUDGET_VOL_LOOKBACK_YEARS,
    ewma_lambda: float = RISK_BUDGET_EWMA_LAMBDA,
) -> dict[str, float]:
    """Compute annualized EWMA factor vol in price-return percent space."""
    if not factor_names:
        return {}

    loader = RiskFactorLoader(DIR_INPUT)
    factor_levels = loader.load_risk_factors(use_cache=True)

    if factor_levels is None or factor_levels.empty:
        return {}

    if not isinstance(factor_levels.index, pd.DatetimeIndex):
        factor_levels.index = pd.to_datetime(factor_levels.index)
    factor_levels = factor_levels.sort_index()

    available_factors = [factor for factor in factor_names if factor in factor_levels.columns]
    if not available_factors:
        return {}

    end_date = factor_levels.index.max()
    start_date = end_date - relativedelta(years=lookback_years)
    window = factor_levels.loc[factor_levels.index >= start_date, available_factors]
    if isinstance(window, pd.Series):
        window = window.to_frame()

    return compute_ewma_factor_vols(window, ewma_lambda=ewma_lambda)

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
                                    {'label': ' Spread', 'value': 'Spread'},
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
                                        {'label': ' Alum', 'value': 'Aluminium'},
                                        {'label': ' Copper', 'value': 'Copper'},
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
                        html.H6("Risk Budgets", style={'color': THEME['text_main'], 'marginTop': '0', 'marginBottom': '0', 'fontSize': '13px', 'fontWeight': 'bold'}),
                        html.Span("Vol from 1Y EWMA  ·  RP Max = inv-vol weights (or user value)  ·  Exposure = RP Max × Coeff",
                                  style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '12px'}),
                    ], style={'display': 'flex', 'alignItems': 'baseline', 'marginBottom': '8px'}),
                    html.Div([
                        dcc.RadioItems(
                            id='allocation-mode',
                            options=[
                                {'label': ' Pure Risk Parity', 'value': 'risk_parity'},
                                {'label': ' Factor Model Scaling', 'value': 'factor_scaling'},
                                {'label': ' User Defined', 'value': 'user_defined'},
                            ],
                            value='risk_parity',
                            inputStyle={'marginRight': '5px'},
                            labelStyle={'display': 'inline', 'marginRight': '16px', 'color': THEME['text_main'], 'fontSize': '12px'},
                            style={'display': 'inline-flex'},
                        ),
                        html.Span(id='factor-signals-toggle-status', style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '8px'}),
                    ], style={'marginBottom': '8px'}),
                    # Column headers: Factor | Vol% ann | RP Max | Coeff | Exposure
                    html.Div([
                        html.Span("Factor",   style={'color': THEME['text_sub'], 'fontSize': '11px', 'width': '80px', 'fontWeight': 'bold', 'flexShrink': '0'}),
                        html.Span("Vol %ann", style={'color': THEME['text_sub'], 'fontSize': '11px', 'width': '62px', 'textAlign': 'right', 'flexShrink': '0'}),
                        html.Span("RP Max",   style={'color': THEME['text_sub'], 'fontSize': '11px', 'width': '54px', 'textAlign': 'right', 'flexShrink': '0'}),
                        html.Span("Coeff",    style={'color': THEME['text_sub'], 'fontSize': '11px', 'width': '44px', 'textAlign': 'center', 'flexShrink': '0'}),
                        html.Span("Exposure", style={'color': THEME['text_sub'], 'fontSize': '11px', 'flex': '1', 'textAlign': 'right'}),
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

        # ── Factor Model Signals Panel (collapsible) ─────────────────────────
        html.Details([
            html.Summary([
                html.Span("📡 Factor Model Signals",
                          style={'color': THEME['text_main'], 'fontWeight': 'bold', 'fontSize': '13px'}),
                html.Span("  ·  expand to refresh live signal buckets from the factor prediction engine",
                          style={'color': THEME['text_sub'], 'fontSize': '11px'}),
            ], style={'padding': '10px 16px', 'cursor': 'pointer', 'listStyleType': 'none',
                      'WebkitAppearance': 'none', 'MozAppearance': 'none',
                      'backgroundColor': THEME['bg_input'], 'borderRadius': '5px',
                      'userSelect': 'none'}),
            html.Div([
                html.Div([
                    html.Button(
                        "Refresh Signals",
                        id='refresh-factor-signals-btn',
                        n_clicks=0,
                        style={
                            'backgroundColor': THEME['accent'],
                            'color': 'white', 'padding': '5px 15px',
                            'border': 'none', 'borderRadius': '4px',
                            'cursor': 'pointer', 'fontWeight': 'bold',
                            'fontSize': '12px', 'marginRight': '15px',
                        }),
                    html.Span(id='factor-signals-status',
                              style={'color': THEME['text_sub'], 'fontSize': '12px'}),
                ], style={'marginBottom': '12px'}),
                dcc.Loading(
                    id='loading-factor-signals',
                    type='default',
                    children=html.Div(id='factor-signals-table-container'),
                ),
            ], style={'padding': '14px 16px', 'borderTop': f'1px solid {THEME["table_header"]}'}),
        ], style={
            'backgroundColor': THEME['bg_card'],
            'borderRadius': '5px',
            'border': f'1px solid {THEME["table_header"]}',
            'marginBottom': '20px',
        }),
        # Store for the latest signal snapshot (consumed by Portfolio allocation)
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
            
            html.Div([
                html.Div(id='status-message', style={'fontSize': '12px', 'color': THEME['text_main'], 'marginRight': '20px'}),
                html.Div(id='timestamp-display', style={'color': THEME['text_sub'], 'fontSize': '11px'})
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '15px', 'justifyContent': 'flex-end'}),

            html.Div(id='portfolio-table-container')
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
                    type='default',
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


def _load_bond_signal_frame(bond_type: str):
    """Load realtime bond spread data for the requested bond type."""
    file_name = BOND_SIGNAL_FILE_MAP.get(bond_type, f'{bond_type}-spdsrt.pkl')
    signal_file = os.path.join(DIR_INPUT, file_name)

    if not os.path.exists(signal_file):
        return None, f"No realtime file found for {bond_type} ({file_name})."

    data = pd.read_pickle(signal_file)
    source_key = 'table'

    if isinstance(data, dict):
        if isinstance(data.get('BondCurve'), pd.DataFrame):
            data = data['BondCurve']
            source_key = 'BondCurve'
        else:
            first_frame = next((value for value in data.values() if isinstance(value, pd.DataFrame)), None)
            if first_frame is None:
                return None, f"{file_name} does not contain a tabular signal payload."
            data = first_frame

    if not isinstance(data, pd.DataFrame) or data.empty:
        return None, f"{file_name} does not contain usable bond signals."

    frame = data.copy()
    frame['Code'] = frame.index.astype(str)
    return frame, source_key


def _resolve_bond_signal_columns(frame: pd.DataFrame):
    def _normalize_column_name(col) -> str:
        return ''.join(ch for ch in str(col).lower() if ch.isalnum())

    normalized = {
        _normalize_column_name(col): col
        for col in frame.columns
    }
    col_ttm = normalized.get('ttm') or normalized.get('term') or normalized.get('ptmyear')
    col_z = normalized.get('zscore') or normalized.get('z')
    col_id = normalized.get('code') or normalized.get('windcode') or 'Code'
    col_name = normalized.get('name') or normalized.get('windcode') or col_id
    col_mid = (
        normalized.get('mid')
        or normalized.get('midprice')
        or normalized.get('price')
        or normalized.get('lastprice')
        or normalized.get('close')
        or normalized.get('cleanprice')
        or normalized.get('dirtyprice')
    )
    col_bid = (
        normalized.get('bid')
        or normalized.get('bidprice')
        or normalized.get('rtbid1')
        or normalized.get('rtbid')
    )
    col_ofr = (
        normalized.get('ofr')
        or normalized.get('offer')
        or normalized.get('ask')
        or normalized.get('askprice')
        or normalized.get('rtask1')
        or normalized.get('rtask')
    )
    col_carry_3m = normalized.get('carry3mbp') or normalized.get('carry3m')
    col_roll_3m = normalized.get('roll3mbp') or normalized.get('roll3m')
    col_cr3m = (
        normalized.get('cr3m')
        or normalized.get('cr3mbp')
        or normalized.get('carryroll3m')
        or normalized.get('carryroll3mbp')
        or normalized.get('carryroll')
        or normalized.get('carry')
        or normalized.get('bondcarry')
    )
    col_carry = (
        normalized.get('cr3mbp')
        or normalized.get('carryroll3m')
        or normalized.get('carryroll3mbp')
        or normalized.get('carryroll')
        or normalized.get('carry')
        or normalized.get('bondcarry')
    )

    required = all(col in frame.columns for col in [col_ttm, col_z, col_id] if col is not None)
    if not required or col_ttm is None or col_z is None:
        return None

    return {
        'ttm': col_ttm,
        'z': col_z,
        'id': col_id,
        'name': col_name,
        'mid': col_mid,
        'bid': col_bid,
        'ofr': col_ofr,
        'cr3m': col_cr3m,
        'carry_3m': col_carry_3m,
        'roll_3m': col_roll_3m,
        'carry': col_carry,
    }


def _build_bond_signal_mini_table(df: pd.DataFrame, columns: dict, title: str, color: str):
    if df.empty:
        return html.Div(
            "No signals in this bucket.",
            style={
                'color': THEME['text_sub'],
                'fontSize': '12px',
                'padding': '18px 12px',
                'textAlign': 'center',
                'backgroundColor': THEME['bg_input'],
                'borderRadius': '8px',
                'border': f'1px solid {THEME["table_header"]}',
            },
        )

    col_id = columns['id']
    col_name = columns['name']
    col_ttm = columns['ttm']
    col_z = columns['z']
    col_mid = columns.get('mid')
    col_cr3m = columns.get('cr3m')

    target_cols = [col_id]
    if col_name != col_id:
        target_cols.append(col_name)
    if col_mid and col_mid in df.columns:
        target_cols.append(col_mid)
    if col_cr3m and col_cr3m in df.columns:
        target_cols.append(col_cr3m)
    target_cols.extend([col_ttm, col_z])
    valid_cols = [col for col in target_cols if col in df.columns]

    display_cols_map = {
        col_id: 'Code',
        col_name: 'Name',
        col_mid: 'Mid Price',
        col_cr3m: 'C+R,3m',
        col_ttm: 'TTM',
        col_z: 'Z-Score',
    }

    records = []
    for record in df[valid_cols].to_dict('records'):
        formatted = {}
        for col in valid_cols:
            value = record.get(col)
            if col == col_ttm and pd.notna(value):
                value = f"{float(value):.2f}Y"
            elif col == col_mid and pd.notna(value):
                value = f"{float(value):.3f}"
            elif col == col_cr3m and pd.notna(value):
                value = f"{float(value):.2f}"
            elif col == col_z and pd.notna(value):
                value = round(float(value), 4)   # keep numeric for bar gradient
            formatted[display_cols_map.get(col, col)] = value
        records.append(formatted)

    # ── Z-Score bar styles (center-anchored, green right / red left) ──────────
    z_vals = pd.to_numeric(df[col_z], errors='coerce')
    _pos_clr = "rgba(39,174,96,0.55)"
    _neg_clr = "rgba(231,76,60,0.55)"
    _max_abs = max(abs(z_vals.dropna()).max() if not z_vals.dropna().empty else 1.0, 0.1)
    z_bar_styles: list[dict] = []
    for _i, _v in enumerate(z_vals):
        try:
            _v = float(_v)
        except (TypeError, ValueError):
            continue
        _norm = max(-1.0, min(1.0, _v / _max_abs))
        _half = abs(_norm) * 50
        if _norm >= 0:
            _grad = (f"transparent 50%, "
                     f"{_pos_clr} 50%, {_pos_clr} {50 + _half:.1f}%, "
                     f"transparent {50 + _half:.1f}%")
        else:
            _grad = (f"transparent {50 - _half:.1f}%, "
                     f"{_neg_clr} {50 - _half:.1f}%, {_neg_clr} 50%, "
                     f"transparent 50%")
        z_bar_styles.append({
            "if": {"row_index": _i, "column_id": "Z-Score"},
            "background": f"linear-gradient(to right, {_grad})",
        })

    return html.Div([
        html.Div(title, style={
            'color': color,
            'fontSize': '12px',
            'fontWeight': '700',
            'letterSpacing': '0.04em',
            'marginBottom': '8px',
            'textTransform': 'uppercase',
        }),
        dash_table.DataTable(
            data=records,
            columns=[
                (
                    {'name': display_cols_map.get(col, col), 'id': display_cols_map.get(col, col),
                     'type': 'numeric', 'format': {'specifier': '.2f'}}
                    if col == col_z else
                    {'name': display_cols_map.get(col, col), 'id': display_cols_map.get(col, col)}
                )
                for col in valid_cols
            ],
            style_cell={
                'textAlign': 'center',
                'padding': '7px 8px',
                'backgroundColor': THEME['bg_input'],
                'color': THEME['text_main'],
                'border': 'none',
                'fontSize': '11px',
                'whiteSpace': 'normal',
                'height': 'auto',
            },
            style_header={
                'backgroundColor': THEME['table_header'],
                'fontWeight': 'bold',
                'color': color,
                'border': 'none',
            },
            style_data_conditional=[
                {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['table_row_even']},
                *z_bar_styles,
            ],
            style_table={'overflowX': 'auto'},
        ),
    ])


def _build_bond_signal_cards(bond_type: str):
    frame, source_key = _load_bond_signal_frame(bond_type)
    if frame is None:
        empty_state = html.Div([
            html.H5(
                f"{BOND_SIGNAL_LABELS.get(bond_type, bond_type)} signals unavailable",
                style={'color': THEME['warning'], 'marginBottom': '8px'},
            ),
            html.P(
                source_key,
                style={'color': THEME['text_sub'], 'margin': '0', 'fontSize': '13px'},
            ),
        ], style={
            'padding': '28px',
            'backgroundColor': THEME['bg_card'],
            'borderRadius': '12px',
            'border': f'1px dashed {THEME["table_header"]}',
            'textAlign': 'center',
        })
        return empty_state, None

    columns = _resolve_bond_signal_columns(frame)
    if columns is None:
        return html.Div(
            "Missing required columns for bond signals (ttm, z-score, code).",
            style={'color': THEME['danger'], 'padding': '20px', 'textAlign': 'center'},
        ), None

    col_ttm = columns['ttm']
    col_z = columns['z']
    col_mid = columns.get('mid')
    col_bid = columns.get('bid')
    col_ofr = columns.get('ofr')
    col_cr3m = columns.get('cr3m')
    col_carry_3m = columns.get('carry_3m')
    col_roll_3m = columns.get('roll_3m')
    col_carry = columns.get('carry')
    frame[col_ttm] = pd.to_numeric(frame[col_ttm], errors='coerce')
    frame[col_z] = pd.to_numeric(frame[col_z], errors='coerce')
    if col_mid and col_mid in frame.columns:
        frame[col_mid] = pd.to_numeric(frame[col_mid], errors='coerce')
    elif col_bid and col_ofr and col_bid in frame.columns and col_ofr in frame.columns:
        frame['__mid_price__'] = (
            pd.to_numeric(frame[col_bid], errors='coerce')
            + pd.to_numeric(frame[col_ofr], errors='coerce')
        ) / 2.0
        columns['mid'] = '__mid_price__'
        col_mid = '__mid_price__'
    if col_cr3m and col_cr3m in frame.columns:
        frame[col_cr3m] = pd.to_numeric(frame[col_cr3m], errors='coerce')
    if col_carry_3m and col_carry_3m in frame.columns:
        frame[col_carry_3m] = pd.to_numeric(frame[col_carry_3m], errors='coerce')
    if col_roll_3m and col_roll_3m in frame.columns:
        frame[col_roll_3m] = pd.to_numeric(frame[col_roll_3m], errors='coerce')
    if (not col_cr3m or col_cr3m not in frame.columns) and col_carry_3m and col_roll_3m and col_carry_3m in frame.columns and col_roll_3m in frame.columns:
        frame['__cr_3m__'] = frame[col_carry_3m] + frame[col_roll_3m]
        columns['cr3m'] = '__cr_3m__'
    elif (not col_cr3m or col_cr3m not in frame.columns) and col_carry and col_carry in frame.columns:
        columns['cr3m'] = col_carry
    if col_carry and col_carry in frame.columns:
        frame[col_carry] = pd.to_numeric(frame[col_carry], errors='coerce')
    frame = frame.dropna(subset=[col_ttm, col_z]).copy()

    if frame.empty:
        return html.Div(
            "No valid numeric signal rows found in the realtime dataset.",
            style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'},
        ), None

    bucket_cards = []
    for bucket_label, min_ttm, max_ttm in BOND_SIGNAL_BUCKETS:
        bucket_df = frame[(frame[col_ttm] > min_ttm) & (frame[col_ttm] <= max_ttm)].copy()
        if bucket_df.empty:
            sell_candidates = bucket_df
            buy_candidates = bucket_df
            avg_z = None
        else:
            sell_candidates = bucket_df.sort_values(col_z, ascending=True).head(5)
            buy_candidates = bucket_df.sort_values(col_z, ascending=False).head(5)
            avg_z = bucket_df[col_z].mean()

        stats = [
            html.Span(
                f"{len(bucket_df)} bonds",
                style={
                    'padding': '4px 10px',
                    'borderRadius': '999px',
                    'backgroundColor': THEME['bg_input'],
                    'color': THEME['text_sub'],
                    'fontSize': '11px',
                },
            )
        ]
        if avg_z is not None and pd.notna(avg_z):
            stats.append(
                html.Span(
                    f"Avg Z {avg_z:+.2f}",
                    style={
                        'padding': '4px 10px',
                        'borderRadius': '999px',
                        'backgroundColor': 'rgba(52, 152, 219, 0.15)',
                        'color': THEME['accent'],
                        'fontSize': '11px',
                    },
                )
            )

        bucket_cards.append(
            html.Div([
                html.Div([
                    html.Div(bucket_label, style={
                        'color': THEME['text_main'],
                        'fontSize': '16px',
                        'fontWeight': '700',
                    }),
                    html.Div(f"TTM in ({min_ttm:.0f}, {max_ttm:.0f}] years", style={
                        'color': THEME['text_sub'],
                        'fontSize': '12px',
                        'marginTop': '2px',
                    }),
                ]),
                html.Div(stats, style={'display': 'flex', 'gap': '8px', 'flexWrap': 'wrap'}),
                html.Div([
                    html.Div(
                        _build_bond_signal_mini_table(
                            sell_candidates,
                            columns,
                            'SELL (Low Z)',
                            THEME['danger'],
                        ),
                        style={'flex': '1 1 0'},
                    ),
                    html.Div(
                        _build_bond_signal_mini_table(
                            buy_candidates,
                            columns,
                            'BUY (High Z)',
                            THEME['success'],
                        ),
                        style={'flex': '1 1 0'},
                    ),
                ], style={'display': 'flex', 'gap': '12px', 'flexWrap': 'wrap', 'marginTop': '16px'}),
            ], style={
                'background': 'linear-gradient(180deg, rgba(12,43,100,0.98), rgba(8,34,85,0.98))',
                'border': f'1px solid {THEME["table_header"]}',
                'borderRadius': '14px',
                'padding': '18px',
                'boxShadow': '0 10px 24px rgba(0, 0, 0, 0.18)',
            })
        )

    return html.Div(
        bucket_cards,
        style={
            'display': 'grid',
            'gridTemplateColumns': 'repeat(auto-fit, minmax(360px, 1fr))',
            'gap': '16px',
            'alignItems': 'start',
        },
    ), len(frame)


def build_multiasset_bond_layout():
    """Build the layout for the dedicated Bond signals tab."""
    dropdown_options = [
        {'label': f"{BOND_SIGNAL_LABELS.get(bond_type, bond_type)} ({bond_type})", 'value': bond_type}
        for bond_type in ['TBond', 'CBond', 'GBond', 'LBond', 'BBond', 'MNote']
    ]

    return html.Div([
        html.Div([
            html.Div([
                html.H4("Bond Trading Signals (Z-Score)", style={
                    'margin': '0 0 6px 0',
                    'color': THEME['text_main'],
                }),
                html.P(
                    "Realtime relative-value signals by maturity bucket. Labels are inverted per request: low Z shows SELL and high Z shows BUY.",
                    style={'margin': '0', 'color': THEME['text_sub'], 'fontSize': '13px'},
                ),
            ], style={'flex': '1 1 auto', 'minWidth': '280px'}),
            html.Div([
                html.Div([
                    html.Label('Bond Type', style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '6px', 'display': 'block'}),
                    dcc.Dropdown(
                        id='beta-bond-type-selector',
                        options=dropdown_options,
                        value='TBond',
                        clearable=False,
                        style={'minWidth': '240px', 'fontSize': '13px'},
                    ),
                ], style={'minWidth': '240px'}),
                html.Button(
                    'Refresh Data',
                    id='beta-bond-refresh-btn',
                    n_clicks=0,
                    style={
                        'backgroundColor': THEME['accent'],
                        'color': 'white',
                        'padding': '10px 16px',
                        'border': 'none',
                        'borderRadius': '8px',
                        'cursor': 'pointer',
                        'fontSize': '13px',
                        'fontWeight': 'bold',
                        'height': '40px',
                        'alignSelf': 'flex-end',
                    },
                ),
            ], style={
                'display': 'flex',
                'gap': '12px',
                'alignItems': 'stretch',
                'flexWrap': 'wrap',
                'justifyContent': 'flex-end',
            }),
        ], style={
            'display': 'flex',
            'justifyContent': 'space-between',
            'gap': '16px',
            'flexWrap': 'wrap',
            'marginBottom': '14px',
        }),
        html.Div(id='beta-bond-status', style={
            'color': THEME['text_sub'],
            'fontSize': '12px',
            'marginBottom': '16px',
        }),
        dcc.Loading(
            id='beta-bond-loading',
            type='default',
            children=html.Div(id='beta-bond-signals-container', style={'minHeight': '420px'}),
        ),
    ], style={
        'padding': '18px',
        'backgroundColor': THEME['bg_main'],
        'borderRadius': '10px',
    })


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
            display_cols = ['Risk Factor', 'Volatility (% ann.)']
            if 'Net Exposure' in factor_vol_df.columns:
                display_cols.append('Net Exposure')
            if 'Risk Contribution (%)' in factor_vol_df.columns:
                display_cols.append('Risk Contribution (%)')
            factor_vol_df = factor_vol_df[display_cols].copy()
            # Format
            factor_vol_df['Volatility (% ann.)'] = factor_vol_df['Volatility (% ann.)'].apply(lambda x: f"{x:.2f}%")
            if 'Net Exposure' in factor_vol_df.columns:
                factor_vol_df['Net Exposure'] = factor_vol_df['Net Exposure'].apply(
                    lambda x: f"{x:+.3f}"  # always show sign
                )
            if 'Risk Contribution (%)' in factor_vol_df.columns:
                factor_vol_df['Risk Contribution (%)'] = factor_vol_df['Risk Contribution (%)'].apply(lambda x: f"{x:.1f}%")
            factor_vol_df = factor_vol_df.sort_values('Risk Factor')

            tbl_columns = [
                {'name': 'Risk Factor', 'id': 'Risk Factor'},
                {'name': 'Vol', 'id': 'Volatility (% ann.)'},
            ]
            if 'Net Exposure' in factor_vol_df.columns:
                tbl_columns.append({'name': 'Net Exp', 'id': 'Net Exposure'})
            if 'Risk Contribution (%)' in factor_vol_df.columns:
                tbl_columns.append({'name': 'RC %', 'id': 'Risk Contribution (%)'})

            vol_table = dash_table.DataTable(
                data=factor_vol_df.to_dict('records'),
                columns=tbl_columns,
                style_cell={'textAlign': 'center', 'padding': '8px', 'fontSize': '12px',
                          'backgroundColor': THEME['table_row_odd'], 'color': THEME['text_main'], 'border': 'none'},
                style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_main'], 'fontWeight': 'bold', 'border': 'none'},
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                    # Colour Net Exposure: negative = red (short factor), positive = green (long factor)
                    {'if': {'filter_query': '{Net Exposure} contains "-"', 'column_id': 'Net Exposure'},
                     'color': THEME.get('danger', '#e74c3c')},
                    {'if': {'filter_query': '{Net Exposure} contains "+"', 'column_id': 'Net Exposure'},
                     'color': THEME.get('success', '#27ae60')},
                ],
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

            # ── Portfolio detail tabs (Beta / Alpha) ──────────────────────────
            html.Hr(style={'borderColor': THEME['table_header'], 'margin': '20px 0 15px 0'}),
            html.Div([
                html.Div([
                    html.H6("Portfolio Allocations", style={
                        'color': THEME['text_main'], 'margin': '0',
                        'fontSize': '13px', 'fontWeight': 'bold',
                    }),
                    html.Span(
                        "Snapshots saved when you click RUN ANALYSIS (Beta) or RUN OPTIMIZATION (Alpha).",
                        style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '10px'},
                    ),
                ], style={'flex': '1', 'display': 'flex', 'alignItems': 'center'}),
                html.Button(
                    "↻ Refresh",
                    id='summary-refresh-btn',
                    n_clicks=0,
                    style={
                        'backgroundColor': THEME['bg_input'],
                        'color': THEME['accent'],
                        'border': f'1px solid {THEME["accent"]}',
                        'borderRadius': '4px',
                        'padding': '4px 14px',
                        'cursor': 'pointer',
                        'fontSize': '12px',
                        'fontWeight': 'bold',
                    },
                ),
                html.Span(id='summary-refresh-status', style={
                    'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '10px',
                }),
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '10px'}),
            dcc.Tabs(
                id='summary-book-tabs',
                value='beta',
                children=[
                    dcc.Tab(
                        label='Beta Book',
                        value='beta',
                        style={'backgroundColor': THEME['bg_card'], 'color': THEME['text_sub'],
                               'padding': '6px 16px', 'border': 'none', 'fontSize': '13px'},
                        selected_style={'backgroundColor': THEME['warning'], 'color': 'white',
                                        'padding': '6px 16px', 'border': 'none',
                                        'fontWeight': 'bold', 'fontSize': '13px'},
                    ),
                    dcc.Tab(
                        label='Alpha Book',
                        value='alpha',
                        style={'backgroundColor': THEME['bg_card'], 'color': THEME['text_sub'],
                               'padding': '6px 16px', 'border': 'none', 'fontSize': '13px'},
                        selected_style={'backgroundColor': THEME['danger'], 'color': 'white',
                                        'padding': '6px 16px', 'border': 'none',
                                        'fontWeight': 'bold', 'fontSize': '13px'},
                    ),
                ],
                style={'marginBottom': '0'},
            ),
            dcc.Loading(
                type='default',
                children=html.Div(
                    id='summary-book-table-container',
                    style={'minHeight': '120px', 'paddingTop': '10px'},
                ),
            ),
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
            "Strategy: At each month start, run correlation analysis to select diversified assets, then apply factor risk parity allocation.",
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
                    value=10,
                    style={'width': '80px', 'marginRight': '5px', 'padding': '5px', 'borderRadius': '4px', 'border': '1px solid #444', 'backgroundColor': '#fff', 'color': '#000'}
                ),
                dcc.Dropdown(
                    id='backtest-capital-unit',
                    options=[
                        {"label": "Million", "value": "million"},
                        {"label": "Billion", "value": "billion"},
                    ],
                    value="billion",
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
                    value='1Y',
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

        # Row 3: Allocation Mode
        html.Div([
            html.Label("Allocation Mode:", style={'fontWeight': 'bold', 'marginRight': '12px', 'color': THEME['text_main']}),
            dcc.RadioItems(
                id='backtest-alloc-mode',
                options=[
                    {'label': ' Pure Risk Parity', 'value': 'risk_parity'},
                    {'label': ' Factor Model Scaling  (not available — factor backtests pending)', 'value': 'factor_scaling', 'disabled': True},
                ],
                value='risk_parity',
                inline=True,
                inputStyle={'marginRight': '4px'},
                labelStyle={'marginRight': '20px', 'color': THEME['text_main'], 'fontSize': '13px'},
            ),
        ], style={'marginBottom': '15px', 'display': 'flex', 'alignItems': 'center'}),

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


def build_risk_factor_backtest_layout():
    """Build the layout for the Risk Factor Backtest tab (BACKTEST subtab in Beta Book).

    Maps PORTFOLIO-tab risk factors to yield/price series, runs close-only
    technical strategies (MA, Bollinger, Momentum, Z-Score), and persists PnL.
    """
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
        # Spread
        {'label': 'SPDL.IRS (IRS Level)',     'value': 'SPDL.IRS'},
        {'label': 'SPSL.IRS (IRS Slope)',     'value': 'SPSL.IRS'},
        {'label': 'SPDL.CDB (CDB Level)',     'value': 'SPDL.CDB'},
        {'label': 'SPSL.CDB (CDB Slope)',     'value': 'SPSL.CDB'},
        {'label': 'SPDL.ICP (ICP Level)',     'value': 'SPDL.ICP'},
        # FX
        {'label': 'FXDL.USDCNY',             'value': 'FXDL.USDCNY'},
        {'label': 'FXDL.EURCNY',             'value': 'FXDL.EURCNY'},
        # Commodity
        {'label': 'CMDL.AU (Gold)',           'value': 'CMDL.AU'},
        {'label': 'CMDL.CU (Copper)',         'value': 'CMDL.CU'},
        {'label': 'CMDL.AL (Aluminium)',      'value': 'CMDL.AL'},
        {'label': 'CMDL.SC (Crude Oil)',      'value': 'CMDL.SC'},
    ]

    default_factors = ['IRDL.CN', 'IRSL.CN', 'SPDL.CDB', 'FXDL.USDCNY']

    return html.Div([
        html.H4("Risk Factor Backtest",
                 style={'color': THEME['text_main'], 'marginBottom': '6px'}),
        html.P("Backtest technical strategies on risk factors from the PORTFOLIO tab. "
               "Yield factors use duration-adjusted returns; FX/Commodity use price returns.",
               style={'color': THEME['text_sub'], 'fontSize': '12px',
                      'marginBottom': '16px', 'fontStyle': 'italic'}),

        # ── Row 1: Factor selection ─────────────────────────────────────
        html.Div([
            html.Div([
                html.Label("Factors:", style={'fontWeight': 'bold', 'marginRight': '10px',
                                              'color': THEME['text_main'], 'fontSize': '13px'}),
                dcc.Dropdown(
                    id='rfbt-factor-selector',
                    options=all_factor_options,
                    value=default_factors,
                    multi=True,
                    placeholder="Select factors…",
                    style={'flex': '1', 'minWidth': '360px',
                           'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']},
                ),
            ], style={'display': 'flex', 'alignItems': 'center', 'flex': '1'}),

            # Hidden store – always FactorModel
            dcc.Store(id='rfbt-strategy-selector', data='FactorModel'),
        ], style={'display': 'flex', 'gap': '20px', 'flexWrap': 'wrap',
                  'marginBottom': '12px'}),

        # ── Row 2: Date range & strategy params ─────────────────────────
        html.Div([
            html.Div([
                html.Label("Period:", style={'fontWeight': 'bold', 'marginRight': '10px',
                                             'color': THEME['text_main'], 'fontSize': '13px'}),
                dcc.DatePickerRange(
                    id='rfbt-date-range',
                    min_date_allowed=datetime(2015, 1, 1).date(),
                    max_date_allowed=datetime.now().date(),
                    start_date=datetime(2023, 1, 1).date(),
                    end_date=datetime.now().date(),
                    display_format='YYYY-MM-DD',
                    style={'backgroundColor': THEME['bg_input']},
                ),
            ], style={'display': 'flex', 'alignItems': 'center'}),

            # Hidden placeholders (keep IDs for callback State refs)
            html.Div(id='rfbt-ma-params', children=[
                dcc.Input(id='rfbt-ma-short', type='number', value=10, style={'display': 'none'}),
                dcc.Input(id='rfbt-ma-long', type='number', value=30, style={'display': 'none'}),
            ], style={'display': 'none'}),

            html.Div(id='rfbt-boll-params', children=[
                dcc.Input(id='rfbt-boll-window', type='number', value=20, style={'display': 'none'}),
                dcc.Input(id='rfbt-boll-std', type='number', value=1.5, style={'display': 'none'}),
            ], style={'display': 'none'}),
            html.Div(id='rfbt-mom-params', children=[
                dcc.Input(id='rfbt-mom-window', type='number', value=20, style={'display': 'none'}),
            ], style={'display': 'none'}),
            html.Div(id='rfbt-zscore-params', children=[
                dcc.Input(id='rfbt-zscore-window', type='number', value=60, style={'display': 'none'}),
                dcc.Input(id='rfbt-zscore-entry', type='number', value=1.5, style={'display': 'none'}),
                dcc.Input(id='rfbt-zscore-exit', type='number', value=0.5, style={'display': 'none'}),
            ], style={'display': 'none'}),

            # Factor Model params
            html.Div(id='rfbt-fm-params', children=[
                html.Label("Train (months):", style={'fontWeight': 'bold', 'marginRight': '4px',
                                                     'color': THEME['text_main'], 'fontSize': '12px'}),
                dcc.Input(id='rfbt-fm-train', type='number', value=12, min=3,
                          style={'width': '55px', 'marginRight': '10px', 'padding': '4px',
                                 'borderRadius': '4px', 'border': '1px solid #444',
                                 'backgroundColor': '#fff', 'color': '#000'}),
                html.Label("IC thr:", style={'fontWeight': 'bold', 'marginRight': '4px',
                                             'color': THEME['text_main'], 'fontSize': '12px'}),
                dcc.Input(id='rfbt-fm-ic', type='number', value=0.05, step=0.01, min=0.01,
                          style={'width': '60px', 'marginRight': '10px', 'padding': '4px',
                                 'borderRadius': '4px', 'border': '1px solid #444',
                                 'backgroundColor': '#fff', 'color': '#000'}),
                html.Label("Top N:", style={'fontWeight': 'bold', 'marginRight': '4px',
                                            'color': THEME['text_main'], 'fontSize': '12px'}),
                dcc.Input(id='rfbt-fm-topn', type='number', value=8, min=1,
                          style={'width': '55px', 'padding': '4px',
                                 'borderRadius': '4px', 'border': '1px solid #444',
                                 'backgroundColor': '#fff', 'color': '#000'}),
            ], style={'display': 'flex', 'alignItems': 'center'}),

        ], style={'display': 'flex', 'gap': '16px', 'flexWrap': 'wrap',
                  'marginBottom': '14px', 'alignItems': 'center'}),

        # ── Row 3: Buttons ──────────────────────────────────────────────
        html.Div([
            html.Button("Generate factor-rates.pkl", id='rfbt-generate-btn', n_clicks=0,
                        style={'backgroundColor': THEME['accent'], 'color': 'white',
                               'padding': '8px 16px', 'border': 'none', 'borderRadius': '5px',
                               'cursor': 'pointer', 'fontSize': '12px', 'fontWeight': 'bold',
                               'marginRight': '12px'}),
            html.Button("Run Backtest & Save", id='rfbt-run-btn', n_clicks=0,
                        style={'backgroundColor': THEME['success'], 'color': 'white',
                               'padding': '8px 16px', 'border': 'none', 'borderRadius': '5px',
                               'cursor': 'pointer', 'fontSize': '12px', 'fontWeight': 'bold'}),
            html.Span(id='rfbt-status', style={'marginLeft': '16px',
                                               'color': THEME['text_sub'], 'fontSize': '12px'}),
        ], style={'marginBottom': '16px'}),

        # ── Results area ────────────────────────────────────────────────
        dcc.Loading(
            type='default',
            children=html.Div(id='rfbt-results-container', style={'minHeight': '200px'}),
        ),

    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px',
              'borderRadius': '5px', 'margin': '10px'})


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

        pkl_options = discover_pkl_files()
    except Exception as e:
        pkl_options = []
        print(f"Error discovering pkl files: {e}")

    # Compact style definitions for Strategy Config sidebar
    DARK_INPUT_STYLE = {
        'backgroundColor': '#132C56',
        'color': '#E2E8F0',
        'border': '1px solid #2B4C7E',
        'fontSize': '1.0rem',
        'borderRadius': '4px',
        'padding': '4px 8px'
    }

    SECTION_STYLE = {
        'marginBottom': '25px',
    }

    SECTION_TITLE_STYLE = {
        'color': '#90CDF4',
        'fontSize': '1.0rem',
        'fontWeight': '700',
        'textTransform': 'uppercase',
        'letterSpacing': '0.05em',
        'borderBottom': '1px solid #2B4C7E',
        'paddingBottom': '6px',
        'marginBottom': '12px'
    }

    LABEL_STYLE = {
        'fontSize': '0.95rem',
        'color': '#A0AEC0',
        'marginBottom': '4px',
        'fontWeight': '600',
        'display': 'block'
    }

    # Sidebar (from futures.backtest.layout.create_sidebar) - Compact optimized layout
    sidebar = html.Div([
        html.H4(
            "Strategy Config",
            style={
                'textAlign': 'left',
                'marginBottom': '22px',
                'color': 'white',
                'fontWeight': '600',
                'fontSize': '1.35rem',
                'letterSpacing': '0.03rem',
                'borderBottom': '1px solid #4A5568',
                'paddingBottom': '12px'
            }
        ),

        # Data Settings
        html.Div([
            html.Div("Data Settings", style=SECTION_TITLE_STYLE),
            dbc.Row([
                dbc.Col([
                    html.Label("Source", style=LABEL_STYLE),
                    dcc.RadioItems(
                        id='bf-data-source',
                        options=[{'label': ' Local', 'value': 'local'}, {'label': ' Wind', 'value': 'wind'}],
                        value='local',
                        labelStyle={'display': 'inline-block', 'marginRight': '12px', 'fontSize': '1.0rem', 'color': '#CBD5E0', 'cursor': 'pointer'},
                        inputStyle={"marginRight": "4px", "cursor": 'pointer'}
                    )
                ], width=6),
                dbc.Col([
                    html.Label("Mode", style=LABEL_STYLE),
                    dcc.RadioItems(
                        id='bf-trading-mode',
                        options=[{'label': ' Daily', 'value': 'daily'}, {'label': ' Intraday', 'value': 'intraday'}],
                        value='daily',
                        labelStyle={'display': 'inline-block', 'marginRight': '12px', 'fontSize': '1.0rem', 'color': '#CBD5E0', 'cursor': 'pointer'},
                        inputStyle={"marginRight": "4px", "cursor": 'pointer'}
                    )
                ], width=6),
            ], className="mb-3"),

            html.Div(id='bf-wind-inputs', children=[
                html.Label("Wind Symbol", style=LABEL_STYLE),
                dcc.Dropdown(
                    id='bf-wind-code',
                    placeholder="Select symbol",
                    style={'fontSize': '1.0rem', 'color': 'black'}
                )
            ], className="mb-2"),

            html.Div(id='bf-local-inputs', children=[
                html.Label("Local Symbol", style=LABEL_STYLE),
                dcc.Dropdown(
                    id='bf-local-symbol',
                    options=pkl_options,
                    placeholder="Select symbol",
                    style={'fontSize': '1.0rem', 'color': 'black'}
                )
            ], style={'display': 'none'}, className="mb-2"),

            html.Label("Date Range", style=LABEL_STYLE),
            html.Div([
                dcc.DatePickerRange(
                    id='bf-date-range',
                    start_date=(datetime.now() - timedelta(days=30)).date(),
                    end_date=datetime.now().date(),
                    display_format='YYYY-MM-DD',
                    style={'fontSize': '1.0rem', 'width': '100%'},
                    className="mb-2",
                    with_portal=True,
                    day_size=39
                )
            ], style={'marginBottom': '10px'}),

            html.Div(id='bf-timeframe-container', children=[
                html.Label("Timeframe", style=LABEL_STYLE),
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
                    style={'fontSize': '1.0rem', 'color': 'black'}
                ),
            ], className="mb-2"),

            dbc.Row([
                dbc.Col([
                    html.Label("OOS Split", style=LABEL_STYLE),
                    dcc.DatePickerSingle(
                        id='bf-oos-split-date',
                        date=datetime.now().date(),
                        display_format='YYYY-MM-DD',
                        style={'fontSize': '1.0rem', 'width': '100%'},
                    ),
                ], width=6),
                dbc.Col([
                    html.Label("In-sample", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id='bf-insample-lookback',
                        options=[
                            {'label': '6 Months', 'value': '6M'},
                            {'label': '1 Year', 'value': '1Y'},
                            {'label': '2 Years', 'value': '2Y'},
                        ],
                        value='1Y',
                        clearable=False,
                        style={'fontSize': '1.0rem', 'color': 'black'}
                    ),
                ], width=6)
            ], className="mb-2"),
        ], style=SECTION_STYLE),

        # Strategy Selection
        html.Div([
            html.Div("Strategies", style=SECTION_TITLE_STYLE),
            dcc.Checklist(
                id='bf-strategy-selector',
                options=[
                    {'label': ' MA', 'value': 'MA'},
                    {'label': ' DeMark', 'value': 'DeMark'},
                    {'label': ' Bollinger', 'value': 'Boll'},
                    {'label': ' VWAP', 'value': 'VWAP'},
                    {'label': ' Momentum', 'value': 'Momentum'},
                    {'label': ' ATR', 'value': 'ATR'},
                    {'label': ' SAR', 'value': 'SAR'},
                    {'label': ' Market Regime', 'value': 'MarketRegime'},
                ],
                value=['MA', 'Boll', 'SAR', 'MarketRegime'],
                # Force a compact 3-column layout inside the narrow sidebar.
                labelStyle={
                    'display': 'inline-block',
                    'width': '33%',
                    'marginBottom': '8px',
                    'fontSize': '1.0rem',
                    'color': '#E2E8F0',
                    'cursor': 'pointer',
                    'verticalAlign': 'top'
                },
                inputStyle={"marginRight": "8px", "cursor": 'pointer'},
                style={'marginTop': '6px'}
            )
        ], style=SECTION_STYLE),

        # Market Regime Configuration - 2 columns side by side (Flexbox)
        html.Div([
            html.Div("Regime Logic", style=SECTION_TITLE_STYLE),
            html.Div([
                html.Div([
                    html.Label("Trending", style={'fontSize': '0.95rem', 'color': '#A0AEC0', 'marginBottom': '2px', 'display': 'block'}),
                    dcc.Dropdown(
                        id='bf-mr-trending-strategy',
                        options=[
                            {'label': 'MA', 'value': 'MA'},
                            {'label': 'SAR', 'value': 'SAR'},
                            {'label': 'ATR', 'value': 'ATR'}
                        ],
                        value='SAR',
                        style={'fontSize': '0.95rem', 'color': 'black'},
                    ),
                ], style={'flex': 1, 'paddingRight': '4px', 'minWidth': '0'}),
                html.Div([
                    html.Label("Mean-Rev", style={'fontSize': '0.95rem', 'color': '#A0AEC0', 'marginBottom': '2px', 'display': 'block'}),
                    dcc.Dropdown(
                        id='bf-mr-meanrev-strategy',
                        options=[
                            {'label': 'Boll', 'value': 'Boll'},
                            {'label': 'VWAP', 'value': 'VWAP'},
                            {'label': 'ATR', 'value': 'ATRMeanRev'}
                        ],
                        value='Boll',
                        style={'fontSize': '0.95rem', 'color': 'black'}
                    )
                ], style={'flex': 1, 'paddingLeft': '4px', 'minWidth': '0'}),
            ], style={'display': 'flex', 'flexDirection': 'row', 'width': '100%'})
        ], style={'marginBottom': '15px'}),

        # Parameters - compact 3-column grid (Flexbox)
        html.Div([
            html.Div("Parameters", style=SECTION_TITLE_STYLE),
            # Row 1: MA | Bollinger | VWAP
            html.Div([
                # MA
                html.Div([
                    html.Div("MA", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Div([
                        html.Div([html.Label("S", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-ma-short', type='number', value=5, min=2, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginRight': '2px'}),
                        html.Div([html.Label("L", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-ma-long', type='number', value=20, min=5, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginLeft': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'row'})
                ], style={'flex': 1, 'paddingRight': '4px', 'minWidth': '0'}),
                # Boll
                html.Div([
                    html.Div("Boll", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Div([
                        html.Div([html.Label("P", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-boll-window', type='number', value=20, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginRight': '2px'}),
                        html.Div([html.Label("σ", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-boll-std', type='number', value=1.0, step=0.1, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginLeft': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'row'}),
                    dcc.Checklist(id='bf-boll-exit', options=[{'label': ' Exit@MA', 'value': 'exit'}], value=[], labelStyle={'fontSize': '0.85rem', 'color': '#CBD5E0'}, style={'marginTop': '2px'})
                ], style={'flex': 1, 'paddingLeft': '4px', 'paddingRight': '4px', 'minWidth': '0'}),
                # VWAP
                html.Div([
                    html.Div("VWAP", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Label("Win", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}),
                    dcc.Input(id='bf-vwap-window', type='number', value=20, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})
                ], style={'flex': 1, 'paddingLeft': '4px', 'minWidth': '0'}),
            ], style={'display': 'flex', 'flexDirection': 'row', 'width': '100%', 'marginBottom': '8px'}),
            
            # Row 2: Momentum | ATR | SAR
            html.Div([
                # Mom
                html.Div([
                    html.Div("Mom", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Label("LB", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}),
                    dcc.Input(id='bf-mom-window', type='number', value=14, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})
                ], style={'flex': 1, 'paddingRight': '4px', 'minWidth': '0'}),
                # ATR
                html.Div([
                    html.Div("ATR", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Div([
                        html.Div([html.Label("E", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-atr-ema-window', type='number', value=11, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'paddingRight': '2px'}),
                        html.Div([html.Label("A", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-atr-window', type='number', value=14, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'paddingLeft': '2px', 'paddingRight': '2px'}),
                        html.Div([html.Label("M", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-atr-mult', type='number', value=2.0, step=0.1, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'paddingLeft': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'row'})
                ], style={'flex': 1, 'paddingLeft': '4px', 'paddingRight': '4px', 'minWidth': '0'}),
                # SAR
                html.Div([
                    html.Div("SAR", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Div([
                        html.Div([html.Label("AF", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-sar-af', type='number', value=0.02, step=0.01, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginRight': '2px'}),
                        html.Div([html.Label("Max", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-sar-max-af', type='number', value=0.2, step=0.01, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginLeft': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'row'})
                ], style={'flex': 1, 'paddingLeft': '4px', 'minWidth': '0'}),
            ], style={'display': 'flex', 'flexDirection': 'row', 'width': '100%'})
        ], style={'marginBottom': '15px', 'padding': '10px', 'backgroundColor': '#0a1e3d', 'borderRadius': '4px', 'border': '1px solid #2B4C7E'}),

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

            if not isinstance(factor_levels.index, pd.DatetimeIndex):
                factor_levels.index = pd.to_datetime(factor_levels.index)
            factor_levels = factor_levels.sort_index()
            
            fig = go.Figure()
            x_min_all = None
            x_max_all = None
            for factor in selected_factors:
                if factor in factor_levels.columns:
                    series = factor_levels[factor].dropna()
                    if not series.empty:
                        fig.add_trace(go.Scatter(x=series.index, y=series.values, mode='lines', name=factor))
                        s_min = series.index.min()
                        s_max = series.index.max()
                        x_min_all = s_min if x_min_all is None else min(x_min_all, s_min)
                        x_max_all = s_max if x_max_all is None else max(x_max_all, s_max)

            default_xaxis = dict(
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

            yaxis_config = dict(gridcolor=THEME['table_header'], autorange=True)

            # Default to 3M rather than "All" when data exists.
            if x_max_all is not None and x_min_all is not None:
                x_min_ts = pd.Timestamp(x_min_all)
                x_max_ts = pd.Timestamp(x_max_all)
                default_start = max(x_min_ts, x_max_ts - relativedelta(months=3))
                default_xaxis['range'] = [default_start, x_max_ts]

                y_min, y_max = float('inf'), float('-inf')
                for factor in selected_factors:
                    if factor in factor_levels.columns:
                        series = factor_levels[factor].dropna()
                        mask = (series.index >= default_start) & (series.index <= x_max_ts)
                        viz_series = series[mask]
                        if not viz_series.empty:
                            y_min = min(y_min, viz_series.min())
                            y_max = max(y_max, viz_series.max())
                
                if y_min != float('inf') and y_max != float('-inf'):
                    padding = (y_max - y_min) * 0.05 if y_max != y_min else abs(y_max) * 0.05 or 0.5
                    yaxis_config['range'] = [y_min - padding, y_max + padding]
                    yaxis_config['autorange'] = False

            fig.update_layout(
                xaxis_title="Date", yaxis_title="Value", hovermode='x unified',
                template=THEME['chart_template'], height=500,
                paper_bgcolor=THEME['bg_main'], plot_bgcolor=THEME['bg_main'],
                font={'color': THEME['text_main']},
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font={'color': THEME['text_main']}),
                xaxis=default_xaxis,
                yaxis=yaxis_config,
                # Avoid freezing prior zoom/range state when factor selections change.
                uirevision='factor-history-dynamic'
            )
            return fig
        except Exception as e:
            return go.Figure().update_layout(title=f"Error plotting data: {str(e)}", template=THEME['chart_template'])

    @app.callback(
        Output('factor-history-chart', 'figure', allow_duplicate=True),
        Input('factor-history-chart', 'relayoutData'),
        State('factor-history-chart', 'figure'),
        prevent_initial_call=True
    )
    def rescale_factor_history_yaxis(relayout_data, figure):
        """Rescale y-axis to visible data when x-axis range changes via rangeselector."""
        if not relayout_data or not figure:
            raise dash.exceptions.PreventUpdate

        x_start = relayout_data.get('xaxis.range[0]')
        x_end   = relayout_data.get('xaxis.range[1]')

        # Also handle autorange reset ("All" button)
        if relayout_data.get('xaxis.autorange') is True:
            patched = Patch()
            patched['layout']['yaxis']['autorange'] = True
            return patched

        if x_start is None or x_end is None:
            raise dash.exceptions.PreventUpdate

        try:
            t_start = pd.Timestamp(x_start)
            t_end   = pd.Timestamp(x_end)
        except Exception:
            raise dash.exceptions.PreventUpdate

        y_min, y_max = float('inf'), float('-inf')
        for trace in figure.get('data', []):
            xs = trace.get('x', [])
            ys = trace.get('y', [])
            for x_val, y_val in zip(xs, ys):
                if y_val is None:
                    continue
                try:
                    t = pd.Timestamp(x_val)
                except Exception:
                    continue
                if t_start <= t <= t_end:
                    if y_val < y_min:
                        y_min = y_val
                    if y_val > y_max:
                        y_max = y_val

        if y_min == float('inf') or y_max == float('-inf'):
            raise dash.exceptions.PreventUpdate

        padding = (y_max - y_min) * 0.05 if y_max != y_min else abs(y_max) * 0.05 or 0.5
        patched = Patch()
        patched['layout']['yaxis']['autorange'] = False
        patched['layout']['yaxis']['range'] = [y_min - padding, y_max + padding]
        return patched

    # 3.4 Factor Pool Counter and Store Updater
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

            # ── Heatmap: show ALL selected factors (not just low-corr pairs) ────
            all_factors_list = list(corr_matrix.columns)

            # Mask upper triangle for the full matrix
            corr_values = corr_matrix.values.copy()
            mask_upper = np.triu(np.ones(corr_values.shape), k=1).astype(bool)
            corr_values[mask_upper] = np.nan

            n_factors = len(all_factors_list)
            # Scale height so labels are readable regardless of how many factors
            heatmap_height = max(500, min(900, 80 + n_factors * 40))

            # --- Heatmap Plot ---
            heatmap_fig = go.Figure(data=go.Heatmap(
                z=corr_values,
                x=all_factors_list,
                y=all_factors_list,
                colorscale='RdBu',
                zmin=-1, zmax=1,
                hovertemplate='%{y} / %{x}<br>Correlation: %{z:.3f}<extra></extra>',
                xgap=1, ygap=1,
                text=[[f"{v:.2f}" if not np.isnan(v) else "" for v in row] for row in corr_values],
                texttemplate="%{text}",
            ))

            heatmap_fig.update_layout(
                title=f"Rank Correlation Matrix — {n_factors} factors · {period}",
                height=heatmap_height,
                template=THEME['chart_template'],
                paper_bgcolor=THEME['bg_card'],
                plot_bgcolor=THEME['bg_card'],
                font={'color': THEME['text_main'], 'size': 11},
                margin=dict(l=160, r=50, t=70, b=120),
                xaxis={'side': 'bottom', 'tickangle': -45},
                yaxis={'autorange': 'reversed'},
            )

            # Low-corr pairs still drive diversification recommendations
            top_factors = set(bottom_pairs['Factor A']).union(set(bottom_pairs['Factor B']))
            top_factors_list = sorted(list(top_factors))

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
        [Output('add-diversified-status', 'children'),
         Output('asset-pool-store', 'data', allow_duplicate=True),
         Output('asset-pool-display', 'children', allow_duplicate=True),
         Output('pool-count', 'children', allow_duplicate=True)],
        Input('add-diversified-assets-btn', 'n_clicks'),
        prevent_initial_call=True
    )
    def add_diversified_assets_to_pool(n_clicks):
        """
        Replace the asset pool with recommended diversified assets.
        Updates asset-pool-store directly so the Portfolio tab sees the change
        immediately without requiring a page reload.
        """
        no_change = (dash.no_update, dash.no_update, dash.no_update)
        if not n_clicks or n_clicks == 0:
            return ("",) + no_change

        # Get assets from global variable (set by correlation analysis)
        recommended_assets = DIVERSIFICATION_RECOMMENDATIONS.get('assets', [])

        if not recommended_assets:
            return ("⚠ No recommended assets available. Please run correlation analysis first.",) + no_change

        # REPLACE the entire asset pool with recommended assets
        new_pool = [asset.copy() for asset in recommended_assets]

        # Save to persistent storage
        try:
            save_asset_pool(new_pool)
        except Exception as e:
            print(f"Error saving asset pool: {e}")
            return (f"✗ Error saving: {str(e)}",) + no_change

        # Build display items (same style as manage_asset_pool)
        display = []
        for asset in new_pool:
            bg_col = '#b48b32' if asset.get('type') == 'Commodities' else '#2c5e40'
            display.append(html.Div([
                html.Span(f"• {asset['name']}", style={'fontWeight': 'bold', 'color': 'white'}),
                html.Span(
                    f" ({asset.get('universe', '')} - {asset.get('sector', '')})",
                    style={'color': '#ddd', 'fontSize': '12px'},
                ),
            ], style={'padding': '5px', 'marginBottom': '5px', 'backgroundColor': bg_col, 'borderRadius': '3px'}))

        count_text = f"({len(new_pool)})"

        # Count assets by type for status message
        type_counts: dict = {}
        for asset in new_pool:
            a_type = asset.get('type', 'Other')
            type_counts[a_type] = type_counts.get(a_type, 0) + 1
        type_summary = ", ".join([f"{count} {t}" for t, count in type_counts.items()])
        status_msg = f"✓ {len(new_pool)} assets added to pool ({type_summary})."

        return status_msg, new_pool, display, count_text

    # 3.6 Risk Factor Budget Input Generator
    @app.callback(
        Output('risk-budget-container', 'children'),
        [Input('asset-pool-store', 'data'),
         Input('rp-budget-store', 'data'),
         Input('factor-signals-snapshot-store', 'data'),
         Input('allocation-mode', 'value')],
        [State('capital-input', 'value'),
         State('capital-unit', 'value')],
    )
    def update_risk_budget_inputs(asset_pool, rp_budgets, snapshot_data, allocation_mode, capital, capital_unit):
        if not asset_pool:
             return [html.Div("Add assets to see risk factors", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px', 'textAlign': 'center'})]

        active_factors = set()
        
        # Mappings based on MultiAsset logic
        rates_map = {'CN': 'CN', 'US': 'US', 'EU': 'DE', 'UK': 'UK', 'JP': 'JP'}
        comm_map = {'Gold': 'AU', 'Aluminium': 'AL', 'Copper': 'CU', 'Crude Oil': 'SC', 'Crude_Oil': 'SC'}

        for asset in asset_pool:
            a_type = asset.get('type')
            
            if a_type == 'Rates':
                asset_name = asset.get('name', '')
                prefix = asset_name[:2]
                rf_country = rates_map.get(prefix)
                if rf_country:
                    active_factors.add(f"IRDL.{rf_country}")
                    active_factors.add(f"IRSL.{rf_country}")
                    active_factors.add(f"IRCV.{rf_country}")
            
            elif a_type == 'Spread':
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
                 code = comm_map.get(asset_name)
                 if code:
                     active_factors.add(f"CMDL.{code}")

        if not active_factors:
             return [html.Div("No risk factors identified.", style={'color': THEME['text_sub'], 'fontSize': '12px'})]

        sorted_factors = sorted(list(active_factors))
        n_factors = len(sorted_factors)

        # ── Compute RP Max per factor ──────────────────────────────────────────
        # Use post-run RP budgets if available; else fall back to equal capital share
        try:
            cap_val = float(capital or 100)
            cap_mult = 1e9 if (capital_unit == 'billion') else 1e6
            total_capital_m = cap_val * cap_mult / 1e6
        except (TypeError, ValueError):
            total_capital_m = 100.0
        equal_share = round(total_capital_m / n_factors, 2) if n_factors else 1.0

        # ── Factor model signal lookup (scalar + colour) ───────────────────────
        SCALAR_META = {
            -1.5: ('Strong Short', THEME.get('danger', '#e74c3c')),
            -1.0: ('Short',        '#e74c3c'),
            -0.5: ('Mild Short',   '#e67e22'),
             0.0: ('Neutral',      THEME.get('text_sub', '#aaa')),
             0.5: ('Mild Long',    '#27ae60'),
             1.0: ('Long',         THEME.get('success', '#2ecc71')),
             1.5: ('Strong Long',  '#2ecc71'),
        }
        snapshot_by_rf = {}
        if snapshot_data:
            for rec in snapshot_data:
                rf = rec.get('risk_factor')
                if rf:
                    snapshot_by_rf[rf] = rec

        def get_coeff(factor):
            rec = snapshot_by_rf.get(factor)
            if rec is not None:
                return float(rec.get('scalar', 1.0))
            return 1.0  # default: full long — placeholder until factor model is run

        # ── Factor vol lookup (live 1Y EWMA) ─────────────────────────────────
        _vol_map = compute_factor_vol_map(sorted_factors)

        # ── Inverse-vol proportional RP Max (stable base for risk_parity / factor_scaling) ─
        _inv_vols = {}
        for _f in sorted_factors:
            _v = _vol_map.get(_f)
            if _v is not None and pd.notna(_v) and _v > 0:
                _inv_vols[_f] = 1.0 / _v
        _total_inv_vol = sum(_inv_vols.values())
        if _total_inv_vol > 0:
            _inv_vol_budgets = {
                _f: round(total_capital_m * _inv_vols.get(_f, 0.0) / _total_inv_vol, 2)
                for _f in sorted_factors
            }
        else:
            _inv_vol_budgets = {_f: equal_share for _f in sorted_factors}

        def get_rp_max(factor):
            if allocation_mode == 'user_defined':
                # User Defined: preserve what the user last stored (or equal share on first load)
                return float(rp_budgets[factor]) if (rp_budgets and factor in rp_budgets) else equal_share
            # risk_parity and factor_scaling: always deterministic inverse-vol proportional
            return _inv_vol_budgets.get(factor, equal_share)

        # ── Build rows ─────────────────────────────────────────────────────────
        rows = []
        for factor in sorted_factors:
            rp_max = get_rp_max(factor)
            coeff  = get_coeff(factor)
            # factor_scaling: scale exposure by signal coeff; other modes: exposure = RP Max
            suggested = round(rp_max * coeff, 2) if allocation_mode == 'factor_scaling' else rp_max
            label, color = SCALAR_META.get(coeff, (f'{coeff:+.1f}×', THEME.get('text_main', '#fff')))
            is_default_coeff = factor not in snapshot_by_rf

            vol_val = _vol_map.get(factor)
            vol_str = f"{vol_val:.2f}%" if vol_val is not None and pd.notna(vol_val) else "–"

            rows.append(
                html.Div([
                    html.Span(factor, style={
                        'color': THEME['text_main'], 'fontSize': '12px',
                        'width': '80px', 'fontWeight': 'bold', 'flexShrink': '0',
                    }),
                    html.Span(vol_str, style={
                        'color': THEME.get('text_sub', '#aaa'), 'fontSize': '12px',
                        'width': '62px', 'textAlign': 'right', 'flexShrink': '0',
                        'fontFamily': 'monospace',
                    }),
                    html.Span(f"{rp_max:.1f}M", style={
                        'color': THEME['text_sub'], 'fontSize': '12px',
                        'width': '54px', 'textAlign': 'right', 'flexShrink': '0',
                    }),
                    html.Span(
                        f"×{coeff:+.1f}",
                        title=f"{label}{' (default)' if is_default_coeff else ''}",
                        style={
                            'color': THEME.get('text_sub', '#aaa') if is_default_coeff else color,
                            'fontSize': '12px', 'width': '44px', 'textAlign': 'center',
                            'flexShrink': '0', 'fontWeight': 'bold',
                            'fontStyle': 'italic' if is_default_coeff else 'normal',
                        }
                    ),
                    dcc.Input(
                        id={'type': 'risk-budget-input', 'index': factor},
                        type='number',
                        value=suggested,
                        step=0.1,
                        style={
                            'width': '52px', 'fontSize': '12px', 'padding': '2px 4px',
                            'backgroundColor': '#fff', 'color': '#000',
                            'border': f'1px solid {THEME["table_header"]}',
                            'borderRadius': '2px', 'textAlign': 'right',
                        }
                    ),
                    html.Span("M", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '2px'}),
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '4px', 'gap': '4px'})
            )
        
        return rows

    # ── 3.7  Factor Model Signals – refresh & render ──────────────────
    @app.callback(
        [Output('factor-signals-table-container', 'children'),
         Output('factor-signals-status', 'children'),
         Output('factor-signals-snapshot-store', 'data')],
        [Input('refresh-factor-signals-btn', 'n_clicks')],
        prevent_initial_call=True,
    )
    def refresh_factor_signals(n_clicks):
        """Compute signal snapshot from the factor prediction engine and
        render as a colour-coded table in the Factor tab.

        Signal sources (merged, risk-factor models take priority):
        1. Contract-level ``trained_model_*.joblib`` from ``factors/``
           → decomposed to risk factors via exposure profiles.
        2. Risk-factor-level ``factor_model_*.joblib`` from ``input/models/``
           → direct risk-factor predictions (override contract-based).
        """
        try:
            from factors.processing.exposure_mapper import (
                BucketConfig, compute_signal_snapshot,
            )
            from factors.processing.risk_factor_mapper import (
                CONTRACT_RISK_PROFILES, decompose_signal_series,
            )
            import joblib, os, glob
            from settings.paths import PATH

            rf_signals: dict = {}  # risk_factor → signal Series
            source_info: list = []  # human-readable summary

            # --- Source 1: contract-level models (factors/) --------------------
            model_dir = os.path.join(str(PATH), 'factors')
            model_files = glob.glob(os.path.join(model_dir, 'trained_model_*.joblib'))

            if model_files:
                from factors.processing.loader import getDailyTS, ensure_returns_column
                from factors.generator.factory import FactorCalculatorFactory
                from factors.engine.predictor import predict_returns

                n_contracts = 0
                for mf in model_files:
                    basename = os.path.basename(mf)
                    parts = basename.replace('trained_model_', '').replace('.joblib', '').split('_')
                    contract = parts[0] if parts else None
                    if contract not in CONTRACT_RISK_PROFILES:
                        continue
                    artifact = joblib.load(mf)
                    trained_model  = artifact.get('trained_model', {})
                    selected_factors = artifact.get('selected_factors', [])
                    ticker = artifact.get('config', {}).get('ticker', contract)
                    if not trained_model or not selected_factors:
                        continue
                    try:
                        raw_data = getDailyTS(ticker)
                        raw_data = ensure_returns_column(raw_data)
                        factory  = FactorCalculatorFactory(raw_data)
                        all_factors = factory.generate_factors()
                        predictions = predict_returns(all_factors, trained_model, selected_factors)
                        predictions = predictions.dropna()
                        predictions = predictions[predictions != 0]
                    except Exception:
                        continue
                    if predictions is None or (hasattr(predictions, 'empty') and predictions.empty):
                        continue
                    decomposed = decompose_signal_series(predictions, contract)
                    for col in decomposed.columns:
                        if col in rf_signals:
                            rf_signals[col] = rf_signals[col].add(decomposed[col], fill_value=0)
                        else:
                            rf_signals[col] = decomposed[col].copy()
                    n_contracts += 1

                if n_contracts:
                    source_info.append(f"{n_contracts} contracts")

            # --- Source 2: risk-factor-level models (input/models/) -----------
            try:
                from multiasset.factor_model import predict_factor_signals
                rf_model_signals = predict_factor_signals(DIR_INPUT, DIR_MODELS)
                if rf_model_signals:
                    for rf, series in rf_model_signals.items():
                        rf_signals[rf] = series  # override contract-derived
                    source_info.append(f"{len(rf_model_signals)} risk-factor models")
            except Exception as e:
                print(f"Warning: risk-factor model signals unavailable: {e}")

            if not rf_signals:
                return (
                    html.Div("No signal series could be computed from trained models.",
                             style={'color': THEME['text_sub']}),
                    "No signals",
                    {},
                )

            # --- bucket mapping ------------------------------------------------
            cfg = BucketConfig()
            snapshot = compute_signal_snapshot(rf_signals, cfg)

            if snapshot.empty:
                return (
                    html.Div("Signal snapshot is empty.", style={'color': THEME['text_sub']}),
                    "Empty",
                    {},
                )

            # --- render table --------------------------------------------------
            def _bucket_color(label):
                label_lower = str(label).lower()
                if 'strong long' in label_lower: return THEME['success']
                if 'long' in label_lower: return '#27ae60'
                if 'strong short' in label_lower: return THEME['danger']
                if 'short' in label_lower: return '#c0392b'
                return THEME['text_sub']

            rows = [
                html.Tr([
                    html.Td(r['risk_factor'], style={'fontWeight': 'bold'}),
                    html.Td(f"{r['signal']:.4f}"),
                    html.Td(r['bucket_label'],
                             style={'color': _bucket_color(r['bucket_label']),
                                    'fontWeight': 'bold'}),
                    html.Td(f"{r['scalar']:+.1f}×"),
                    html.Td(f"{r['risk_budget']:+.2f} M"),
                    html.Td(f"{r['confidence']:.0%}"),
                ], style={'fontSize': '12px'})
                for r in snapshot.to_dict('records')
            ]

            table = html.Table(
                [html.Thead(html.Tr([
                    html.Th(c, style={'padding': '4px 8px', 'color': THEME['text_sub'],
                                      'borderBottom': f'1px solid {THEME["table_header"]}'})
                    for c in ['Risk Factor', 'Signal', 'Bucket', 'Scalar',
                              'Risk Budget', 'Confidence']
                ]))] + [html.Tbody(rows)],
                style={'width': '100%', 'color': THEME['text_main'],
                       'fontSize': '12px', 'borderCollapse': 'collapse'},
            )

            # Store snapshot as serialisable dict for Portfolio tab
            snapshot_data = snapshot.to_dict(orient='records')

            source_str = ' + '.join(source_info) if source_info else 'unknown'

            return (
                table,
                f"Updated ({len(snapshot)} factors · {source_str})",
                snapshot_data,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return (
                html.Div(f"Error: {e}", style={'color': THEME['danger']}),
                "Error",
                {},
            )

    @app.callback(
        [Output('beta-bond-signals-container', 'children'),
         Output('beta-bond-status', 'children')],
        [Input('beta-bond-refresh-btn', 'n_clicks'),
         Input('beta-bond-type-selector', 'value')],
        prevent_initial_call=False,
    )
    def refresh_beta_bond_signals(refresh_clicks, bond_type):
        selected_bond_type = bond_type or 'TBond'
        try:
            signal_cards, bond_count = _build_bond_signal_cards(selected_bond_type)
            action = 'Loaded'
            ctx = dash.callback_context
            if ctx.triggered:
                trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
                if trigger_id == 'beta-bond-refresh-btn':
                    action = 'Refreshed'
                elif trigger_id == 'beta-bond-type-selector':
                    action = 'Switched'

            label = BOND_SIGNAL_LABELS.get(selected_bond_type, selected_bond_type)
            if bond_count is None:
                status = f"{action} {label} · no live signal rows available · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            else:
                status = f"{action} {label} · {bond_count} live rows · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            return signal_cards, status
        except Exception as e:
            traceback.print_exc()
            return (
                html.Div(f"Error loading bond signals: {e}", style={'color': THEME['danger'], 'padding': '20px'}),
                f"Load failed · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            )

    # ── 3.8  Mode status hint ─────────────────────────────────────────
    @app.callback(
        Output('factor-signals-toggle-status', 'children'),
        [Input('allocation-mode', 'value')],
        [State('factor-signals-snapshot-store', 'data'),
         State('asset-pool-store', 'data')],
    )
    def autofill_risk_budgets_status(allocation_mode, snapshot_data, asset_pool):
        """Show a one-line hint for the selected allocation mode."""
        if allocation_mode == 'risk_parity':
            return "RP Max = inv-vol weights · same result on every run"
        if allocation_mode == 'user_defined':
            return "Edit Exposure inputs directly · re-runs preserve your values"
        # factor_scaling
        if not snapshot_data:
            return "⚠ No signal snapshot — click 'Refresh Signals' in the Factor tab first."
        return f"✓ {len(snapshot_data)} factor signals scale RP Max at run time."

    # 4. Run Analysis (Portfolio Tab -> Results)
    @app.callback(
        [Output('portfolio-table-container', 'children'),
         Output('status-message', 'children'),
         Output('timestamp-display', 'children'),
         Output('portfolio-data-store', 'data'),
         Output('rp-budget-store', 'data')],
        [Input('run-button', 'n_clicks')],
        [State('capital-input', 'value'),
         State('capital-unit', 'value'),
         State('asset-pool-store', 'data'),
         State({'type': 'risk-budget-input', 'index': ALL}, 'value'),
         State({'type': 'risk-budget-input', 'index': ALL}, 'id'),
         State('allocation-mode', 'value'),
         State('factor-signals-snapshot-store', 'data')]
    )
    def run_analysis(n_clicks, total_capital, capital_unit, asset_pool,
                     budget_values, budget_ids, allocation_mode, signal_snapshot):
        if n_clicks == 0:
            return (html.Div("No data available. Click 'Run Analysis' to start.", style={'color': THEME['text_sub']}),
                    "", "", {}, {})

        try:
            # Validate asset pool
            if not asset_pool or len(asset_pool) == 0:
                error_msg = html.Span("⚠ Please add assets to the pool before running analysis", 
                                    style={'color': THEME['warning'], 'fontWeight': 'bold'})
                return (html.Div("No assets in pool.", style={'color': THEME['warning']}),
                        error_msg, "", {}, {})
            
            # Convert capital to CNY
            multiplier = 1e9 if capital_unit == 'billion' else 1e6
            total_capital_cny = float(total_capital) * multiplier
            
            # Get selected assets
            selected_asset_names = [asset['name'] for asset in asset_pool]
            
            # Build risk budgets based on allocation mode
            risk_budgets = None
            rp_budgets_out = {}
            factor_names_in_pool = [id_dict['index'] for id_dict in (budget_ids or [])]
            total_capital_m = total_capital_cny / 1e6

            if allocation_mode == 'risk_parity':
                # Pure Risk Parity: optimizer runs unconstrained ERC — always deterministic.
                # rp_budgets_out will be filled from optimizer factor vols after the run.
                risk_budgets = None

            elif allocation_mode == 'factor_scaling':
                # Factor Model Scaling: inverse-vol base budgets, scaled by signal scalar.
                _vm = compute_factor_vol_map(factor_names_in_pool) if factor_names_in_pool else {}
                _iv = {f: 1.0 / _vm[f] for f in factor_names_in_pool
                       if _vm.get(f) and pd.notna(_vm[f]) and _vm[f] > 0}
                _tot = sum(_iv.values())
                n_pool = len(factor_names_in_pool) or 1
                _base = (
                    {f: round(total_capital_m * _iv.get(f, 0.0) / _tot, 2) for f in factor_names_in_pool}
                    if _tot > 0
                    else {f: round(total_capital_m / n_pool, 2) for f in factor_names_in_pool}
                )
                if signal_snapshot:
                    _snap = {rec['risk_factor']: rec for rec in signal_snapshot if rec.get('risk_factor')}
                    risk_budgets = {}
                    scaled_count = 0
                    for f, base_val in _base.items():
                        rec = _snap.get(f)
                        if rec is not None:
                            risk_budgets[f] = round(base_val * float(rec.get('scalar', 1.0)), 2)
                            scaled_count += 1
                        else:
                            risk_budgets[f] = base_val
                    print(f"📡 Factor model scaling applied to {scaled_count} risk budgets")
                else:
                    risk_budgets = _base
                # Store unscaled base budgets — same signals → same result → idempotent
                rp_budgets_out = _base

            else:  # user_defined
                # User Defined: use input-box values exactly; write them back unchanged.
                if budget_ids and budget_values:
                    risk_budgets = {}
                    for val, id_dict in zip(budget_values, budget_ids):
                        factor_name = id_dict['index']
                        try:
                            risk_budgets[factor_name] = float(val) if val is not None else 1.0
                        except (ValueError, TypeError):
                            pass
                rp_budgets_out = dict(risk_budgets) if risk_budgets else {}

            # Run optimization
            summary, returns, vols, factor_exp, factor_risk, portfolio = run_risk_parity_allocation(
                total_capital=total_capital_cny, use_cache=True, selected_assets=selected_asset_names,
                risk_budgets=risk_budgets, use_deterministic=True
            )
            
            if summary.empty:
                error_msg = html.Span("⚠ No matching assets found in optimization results", 
                                    style={'color': THEME['warning'], 'fontWeight': 'bold'})
                return (html.Div("No matching assets found.", style={'color': THEME['warning']}),
                        error_msg, "", {}, {})
            
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
                _units = np.where(
                    portfolio_df['Asset Type'].isin(('Rates', 'Spread')),
                    10_000_000.0,
                    1_000_000.0,
                )
                _rounded = np.floor(portfolio_df['Capital (CNY)'].values / _units) * _units
                total_rounded_capital = float(_rounded.sum())
                _display_df = portfolio_df.copy()
                _display_df['Capital (CNY)'] = [f"{v / 1_000_000:,.2f}" for v in _rounded]
                _display_df['Weight (%)'] = portfolio_df['Weight (%)'].map(lambda v: f"{v:.2f}%")
                portfolio_enhanced = _display_df.to_dict('records')
            
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

            # For Pure Risk Parity: derive RP Max from actual factor risk contributions
            # returned by the full-covariance optimizer (proper ERC attribution).
            if allocation_mode == 'risk_parity':
                factor_risk = ALLOCATION_RESULTS.get('factor_risk', pd.DataFrame())
                if (not factor_risk.empty
                        and 'Risk Factor' in factor_risk.columns
                        and 'Risk Contribution (%)' in factor_risk.columns):
                    _valid_rc = factor_risk[pd.notna(factor_risk['Risk Contribution (%)'])]
                    rc_map = dict(zip(_valid_rc['Risk Factor'], _valid_rc['Risk Contribution (%)']))
                    total_rc = sum(v for v in rc_map.values() if v > 0)
                    if total_rc > 1e-6:
                        rp_budgets_out = {
                            f: round(total_capital_m * v / total_rc, 2)
                            for f, v in rc_map.items() if v > 0
                        }
                    else:
                        # Fallback: inv-vol proportional
                        _fnames_erc = list(vols.index) if hasattr(vols, 'index') else []
                        _iv = {f: 1.0/float(vols[f]) for f in _fnames_erc
                               if pd.notna(vols.get(f)) and float(vols[f]) > 0}
                        _tot = sum(_iv.values()) or 1.0
                        rp_budgets_out = {f: round(total_capital_m * v / _tot, 2) for f, v in _iv.items()}
                else:
                    # Fallback: inv-vol proportional
                    _fnames_erc = list(vols.index) if hasattr(vols, 'index') else []
                    _iv = {f: 1.0/float(vols[f]) for f in _fnames_erc
                           if pd.notna(vols.get(f)) and float(vols[f]) > 0}
                    _tot = sum(_iv.values()) or 1.0
                    rp_budgets_out = {f: round(total_capital_m * v / _tot, 2) for f, v in _iv.items()}
            # factor_scaling and user_defined already have rp_budgets_out set above

            # ── Save Beta snapshot for Summary tab ────────────────────────────
            try:
                import pathlib
                pathlib.Path(_SUMMARY_BETA_PARQUET).parent.mkdir(parents=True, exist_ok=True)
                _snap = portfolio_df.copy()
                _snap['_timestamp'] = datetime.now().isoformat()
                _snap['_capital_cny'] = _snap['Capital (CNY)']
                # Ensure all factor-sensitivity columns are float (serialisable)
                for _c in _snap.columns:
                    if _c not in ('Asset Type', 'Universe', 'Sector', 'Asset Name',
                                  '_timestamp', '_capital_cny'):
                        _snap[_c] = pd.to_numeric(_snap[_c], errors='coerce')
                _snap.to_parquet(_SUMMARY_BETA_PARQUET, index=False)
                print(f"✓ Beta portfolio snapshot saved → {_SUMMARY_BETA_PARQUET}")
            except Exception as _se:
                print(f"Warning: Could not save Beta snapshot: {_se}")

            return (portfolio_table, status_msg, timestamp_msg, {'status': 'success'}, rp_budgets_out)
            
        except Exception as e:
            # Print full traceback for debugging
            print(f"\n{'='*80}")
            print("ERROR in run_analysis callback:")
            print(f"{'='*80}")
            traceback.print_exc()
            print(f"{'='*80}\n")
            
            error_msg = html.Span(f"✗ Error: {str(e)}", style={'color': THEME['danger'], 'fontWeight': 'bold'})
            return (html.Div(f"Error: {str(e)}", style={'color': THEME['danger']}),
                    error_msg, "", {}, {})

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
         State('backtest-top-pairs', 'value'),
         State('backtest-alloc-mode', 'value')]
    )
    def update_historical_allocation(n_clicks, total_capital, capital_unit, start_date, end_date, corr_lookback, top_pairs, alloc_mode):
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

        alloc_mode = alloc_mode or 'risk_parity'

        if alloc_mode == 'factor_scaling':
            unavail_fig = go.Figure()
            unavail_fig.update_layout(
                title="Factor Model Scaling — not available yet",
                annotations=[{
                    'text': 'Factor Model Scaling requires per-factor signal backtests which are still in development.<br>'
                            'Please use Pure Risk Parity.',
                    'xref': 'paper', 'yref': 'paper', 'x': 0.5, 'y': 0.5,
                    'showarrow': False, 'font': {'size': 14, 'color': THEME['warning']},
                    'align': 'center',
                }],
                template=THEME['chart_template'],
                paper_bgcolor=THEME['bg_main'],
                plot_bgcolor=THEME['bg_main'],
                font={'color': THEME['text_main']},
            )
            return unavail_fig, unavail_fig, None, html.Div(
                "Factor Model Scaling is not yet available — factor signal backtests are pending.",
                style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'},
            )

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
                
                # --- Step 3: Run factor risk parity allocation ---
                # Create portfolio for these assets
                try:
                    portfolio = create_custom_portfolio(
                        selected_asset_names,
                        use_deterministic=True,
                    )
                except Exception as e:
                    print(f"  {rebalance_date.date()}: Portfolio creation failed: {e}")
                    continue
                
                # Use shared factor risk parity optimizer with deterministic factors
                try:
                    optimizer = FactorRiskParityOptimizer(
                        portfolio=portfolio, 
                        input_dir=str(DIR_INPUT),
                        factor_model_lookback_years=1.0,
                        vol_lookback_months=RiskModelConfig.FACTOR_VOL_LOOKBACK_MONTHS,
                        ewma_lambda=RiskModelConfig.FACTOR_VOL_EWMA_LAMBDA,
                    )
                    weights_series, _ = optimizer.fit_and_calculate(pd.Timestamp(rebalance_date))
                    weights = weights_series.to_dict()
                except Exception as e:
                    print(f"  {rebalance_date.date()}: Factor risk optimization failed: {e}")
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
            if 'DeMark' in selected_strategies:
                results['DeMark'] = run_demark_strategy(df_resampled)
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

            if 'DeMark' in results:
                df_demark = results['DeMark']
                for col, color, name in [
                    ('tdst_support', '#2ecc71', 'TDST Support'),
                    ('tdst_resistance', '#e74c3c', 'TDST Resistance'),
                ]:
                    series = df_demark[col].dropna()
                    if not series.empty:
                        fig.add_trace(go.Scatter(
                            x=series.index,
                            y=series.values,
                            mode='lines',
                            name=name,
                            line=dict(color=color, width=1.2, dash='dot')
                        ), row=1, col=1)

                for flag_col, name, symbol, color, price_col in [
                    ('buy_setup_complete', 'TD Buy Setup 9', 'triangle-up', '#27ae60', 'low'),
                    ('sell_setup_complete', 'TD Sell Setup 9', 'triangle-down', '#c0392b', 'high'),
                    ('buy_countdown_complete', 'TD Buy Countdown 13', 'star', '#2ecc71', 'low'),
                    ('sell_countdown_complete', 'TD Sell Countdown 13', 'star', '#e74c3c', 'high'),
                ]:
                    mask = df_demark[flag_col].eq(1)
                    if mask.any():
                        fig.add_trace(go.Scatter(
                            x=df_demark.index[mask],
                            y=df_demark.loc[mask, price_col],
                            mode='markers',
                            name=name,
                            marker=dict(symbol=symbol, color=color, size=10)
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

    # ================================================================
    # Risk Factor Backtest callbacks (BACKTEST subtab)
    # ================================================================

    @app.callback(
        [Output('rfbt-ma-params', 'style'),
         Output('rfbt-boll-params', 'style'),
         Output('rfbt-mom-params', 'style'),
         Output('rfbt-zscore-params', 'style'),
         Output('rfbt-fm-params', 'style')],
        Input('rfbt-strategy-selector', 'data'),
    )
    def toggle_rfbt_strategy_params(strategy):
        """Show/hide strategy-specific parameter inputs."""
        flex = {'display': 'flex', 'alignItems': 'center'}
        hide = {'display': 'none', 'alignItems': 'center'}
        return (hide, hide, hide, hide, flex)

    @app.callback(
        Output('rfbt-status', 'children', allow_duplicate=True),
        Input('rfbt-generate-btn', 'n_clicks'),
        prevent_initial_call=True,
    )
    def generate_factor_rates_click(n_clicks):
        """Generate (or regenerate) factor-rates.pkl."""
        if not n_clicks:
            raise dash.exceptions.PreventUpdate
        try:
            from multiasset.factor_backtest import generate_factor_rates
            df = generate_factor_rates(DIR_INPUT, save=True)
            return f"✅ factor-rates.pkl saved ({df.shape[1]} factors, {len(df)} days)"
        except Exception as e:
            return f"❌ Error: {e}"

    @app.callback(
        [Output('rfbt-results-container', 'children'),
         Output('rfbt-status', 'children')],
        Input('rfbt-run-btn', 'n_clicks'),
        [State('rfbt-factor-selector', 'value'),
         State('rfbt-strategy-selector', 'data'),
         State('rfbt-date-range', 'start_date'),
         State('rfbt-date-range', 'end_date'),
         State('rfbt-ma-short', 'value'),
         State('rfbt-ma-long', 'value'),
         State('rfbt-boll-window', 'value'),
         State('rfbt-boll-std', 'value'),
         State('rfbt-mom-window', 'value'),
         State('rfbt-zscore-window', 'value'),
         State('rfbt-zscore-entry', 'value'),
         State('rfbt-zscore-exit', 'value'),
         State('rfbt-fm-train', 'value'),
         State('rfbt-fm-ic', 'value'),
         State('rfbt-fm-topn', 'value')],
        prevent_initial_call=True,
    )
    def run_risk_factor_backtest(
        n_clicks, factors, strategy, start_date, end_date,
        ma_short, ma_long, boll_window, boll_std,
        mom_window, zscore_window, zscore_entry, zscore_exit,
        fm_train, fm_ic, fm_topn,
    ):
        if not n_clicks or not factors:
            raise dash.exceptions.PreventUpdate

        try:
            from multiasset.factor_backtest import (
                run_factor_backtest, compute_metrics, get_factor_duration,
                _is_yield_factor,
            )

            # Build strategy-specific kwargs – always FactorModel
            strategy = 'FactorModel'
            kwargs = {'train_months': int(fm_train or 12),
                      'ic_threshold': float(fm_ic or 0.05),
                      'top_n': int(fm_topn or 8)}

            results = run_factor_backtest(
                factors=factors,
                strategy=strategy,
                start_date=start_date,
                end_date=end_date,
                input_dir=DIR_INPUT,
                save=True,
                **kwargs,
            )

            if not results:
                return (
                    html.Div("No results — check that factor-rates.pkl exists and factors have data.",
                             style={'color': THEME['warning'], 'padding': '20px'}),
                    "⚠️ No factors produced results",
                )

            # ── Build summary metrics table ─────────────────────────────
            metric_rows = []
            for factor, df in results.items():
                m = compute_metrics(df)
                dur = get_factor_duration(factor)
                is_y = _is_yield_factor(factor)
                metric_rows.append({
                    'Factor': factor,
                    'Type': 'Yield' if is_y else 'Price',
                    'Scale': f'{dur:.1f}' if dur > 0 else '—',
                    'Total Ret': f"{m.get('Total Return', 0):.2%}",
                    'Ann Ret': f"{m.get('Ann. Return', 0):.2%}",
                    'Ann Vol': f"{m.get('Ann. Vol', 0):.2%}",
                    'Sharpe': f"{m.get('Sharpe', 0):.2f}",
                    'Max DD': f"{m.get('Max Drawdown', 0):.2%}",
                    'Win': f"{m.get('Win Rate', 0):.1%}",
                    'Days': int(m.get('Days', 0)),
                })

            metrics_table = dash_table.DataTable(
                data=metric_rows,
                columns=[{'name': c, 'id': c} for c in metric_rows[0].keys()],
                style_cell={'textAlign': 'center', 'padding': '6px 8px',
                            'backgroundColor': THEME['bg_input'],
                            'color': THEME['text_main'], 'border': 'none',
                            'fontSize': '11px'},
                style_header={'backgroundColor': THEME['table_header'],
                              'fontWeight': 'bold', 'color': THEME['accent'],
                              'border': 'none'},
                style_data_conditional=[
                    {'if': {'row_index': 'odd'},
                     'backgroundColor': THEME['table_row_even']},
                ],
                style_table={'overflowX': 'auto', 'marginBottom': '16px'},
            )

            # ── Build cumulative return chart ───────────────────────────
            fig = go.Figure()
            colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12',
                      '#9b59b6', '#1abc9c', '#e67e22', '#34495e',
                      '#E91E63', '#00BCD4']
            for i, (factor, df) in enumerate(results.items()):
                cum = df['cumulative_returns'].dropna()
                fig.add_trace(go.Scatter(
                    x=cum.index, y=cum.values, mode='lines',
                    name=factor, line={'color': colors[i % len(colors)]},
                ))

            fig.update_layout(
                title=f'Cumulative Returns — {strategy} Strategy',
                xaxis_title='Date', yaxis_title='Cumulative Return',
                hovermode='x unified',
                template=THEME['chart_template'], height=420,
                paper_bgcolor=THEME['bg_main'],
                plot_bgcolor=THEME['bg_main'],
                font={'color': THEME['text_main']},
                legend=dict(orientation='h', yanchor='bottom', y=1.02,
                            xanchor='right', x=1,
                            font={'color': THEME['text_main']}),
                xaxis=dict(gridcolor=THEME['table_header']),
                yaxis=dict(gridcolor=THEME['table_header']),
            )

            # ── Build signals chart (subplots per factor) ──────────────
            n_factors = len(results)
            signal_fig = make_subplots(
                rows=n_factors, cols=1, shared_xaxes=True,
                subplot_titles=list(results.keys()),
                vertical_spacing=0.04,
            )
            for i, (factor, df) in enumerate(results.items(), start=1):
                sig = df['signal'].dropna()
                signal_fig.add_trace(
                    go.Scatter(
                        x=sig.index, y=sig.values, mode='lines',
                        name=f'{factor} sig',
                        line={'color': colors[(i - 1) % len(colors)], 'width': 1},
                    ),
                    row=i, col=1,
                )

            signal_fig.update_layout(
                title='Positions / Signals',
                height=max(200, 120 * n_factors),
                template=THEME['chart_template'],
                paper_bgcolor=THEME['bg_main'],
                plot_bgcolor=THEME['bg_main'],
                font={'color': THEME['text_main']},
                showlegend=False,
            )

            status_msg = (f"✅ Backtest complete — {strategy} on "
                          f"{len(results)} factors, saved to factor-backtest.pkl")

            return (
                html.Div([
                    metrics_table,
                    dcc.Graph(figure=fig),
                    dcc.Graph(figure=signal_fig),
                ]),
                status_msg,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return (
                html.Div(f"Error: {e}",
                         style={'color': THEME['danger'], 'padding': '20px'}),
                f"❌ {e}",
            )

    # ── IRDL Hedge Overlay callback ───────────────────────────────────────────
    @app.callback(
        Output('irdl-hedge-ticket-container', 'children'),
        [
            Input('portfolio-data-store', 'data'),
            Input('irdl-hedge-ratio', 'value'),
            Input('irdl-hedge-instrument', 'value'),
            Input('irdl-hedge-irs-maturity', 'value'),
            Input({'type': 'irdl-dv01-override', 'index': ALL}, 'value'),
        ],
        [
            State({'type': 'irdl-dv01-override', 'index': ALL}, 'id'),
            State('capital-input', 'value'),
            State('capital-unit', 'value'),
        ],
        prevent_initial_call=True,
    )
    def update_irdl_hedge_ticket(
        store_data, hedge_ratio_pct, instrument, irs_maturity,
        dv01_values, dv01_ids, capital_value, capital_unit,
    ):
        factor_risk = ALLOCATION_RESULTS.get('factor_risk')
        if factor_risk is None or factor_risk.empty:
            return html.Div(
                "Run Analysis first to compute portfolio exposures.",
                style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px'},
            )
        if 'Net Exposure' not in factor_risk.columns:
            return html.Div(
                "Net Exposure column not available — re-run Analysis.",
                style={'color': THEME['warning'], 'fontSize': '12px'},
            )

        try:
            # Build capital
            multiplier = 1e9 if capital_unit == 'billion' else 1e6
            total_capital = float(capital_value or 10) * multiplier

            # Build DV01 overrides dict
            dv01_overrides = {}
            for val, id_dict in zip(dv01_values or [], dv01_ids or []):
                cty = id_dict['index']
                if val is not None:
                    try:
                        dv01_overrides[cty] = float(val)
                    except (ValueError, TypeError):
                        pass

            hedge_ratio = (hedge_ratio_pct or 0) / 100.0

            tickets = compute_irdl_hedge(
                factor_risk_records=factor_risk.to_dict('records'),
                total_capital=total_capital,
                hedge_ratio=hedge_ratio,
                instrument=instrument or 'futures',
                dv01_overrides=dv01_overrides if dv01_overrides else None,
                irs_maturity=irs_maturity or '10Y',
            )

            if not tickets:
                return html.Div(
                    "No IRDL factors found in current allocation.",
                    style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px'},
                )

            _dir_color = {
                'SHORT':     THEME.get('danger', '#e74c3c'),
                'PAY FIXED': THEME.get('danger', '#e74c3c'),
                'LONG':      THEME.get('success', '#27ae60'),
                'RCV FIXED': THEME.get('success', '#27ae60'),
            }

            return html.Div([
                html.Div(
                    f"Hedge ratio: {hedge_ratio_pct}%  ·  Instrument: "
                    f"{'Bond Futures' if instrument == 'futures' else 'Pay-fixed IRS'}  ·  "
                    f"Capital: {float(capital_value or 10):,.0f} {capital_unit}",
                    style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '8px'},
                ),
                dash_table.DataTable(
                    data=tickets,
                    columns=[
                        {'name': 'Country',            'id': 'Country'},
                        {'name': 'Net IRDL Exp (DY)',  'id': 'Net IRDL Exp (DY)'},
                        {'name': 'Port DV01 (CNY/bp)', 'id': 'Port DV01 (CNY/bp)'},
                        {'name': 'Hedge DV01 (CNY/bp)', 'id': 'Hedge DV01 (CNY/bp)'},
                        {'name': 'Quantity',           'id': 'Quantity'},
                        {'name': 'Direction',          'id': 'Direction'},
                        {'name': 'Instrument',         'id': 'Instrument'},
                    ],
                    style_cell={
                        'textAlign': 'center', 'padding': '8px 10px',
                        'fontSize': '12px',
                        'backgroundColor': THEME['table_row_odd'],
                        'color': THEME['text_main'], 'border': 'none',
                    },
                    style_header={
                        'backgroundColor': THEME['table_header'],
                        'color': THEME['text_main'],
                        'fontWeight': 'bold', 'border': 'none',
                    },
                    style_data_conditional=[
                        {'if': {'row_index': 'even'}, 'backgroundColor': THEME['table_row_even']},
                        *[
                            {'if': {'filter_query': f'{{Direction}} = "{d}"', 'column_id': 'Direction'},
                             'color': c, 'fontWeight': 'bold'}
                            for d, c in _dir_color.items()
                        ],
                        {'if': {'filter_query': '{Net IRDL Exp (DY)} > 0', 'column_id': 'Net IRDL Exp (DY)'},
                         'color': THEME.get('success', '#27ae60')},
                        {'if': {'filter_query': '{Net IRDL Exp (DY)} < 0', 'column_id': 'Net IRDL Exp (DY)'},
                         'color': THEME.get('danger', '#e74c3c')},
                    ],
                    style_table={'overflowX': 'auto'},
                ),
            ])

        except Exception as exc:
            return html.Div(
                f"Error computing hedge: {exc}",
                style={'color': THEME['danger'], 'fontSize': '12px'},
            )

    # ── Summary tab: Beta / Alpha portfolio table callback ────────────────────
    @app.callback(
        [Output('summary-book-table-container', 'children'),
         Output('summary-refresh-status', 'children')],
        [Input('summary-book-tabs', 'value'),
         Input('summary-refresh-btn', 'n_clicks')],
    )
    def update_summary_book_table(tab_value, _n_clicks):
        """Load the saved parquet snapshot and render a styled table with
        Close Price and Market Value columns."""
        import os as _os

        def _no_data(msg: str):
            return (
                html.Div(msg, style={
                    'color': THEME['text_sub'], 'fontStyle': 'italic',
                    'padding': '30px', 'textAlign': 'center', 'fontSize': '13px',
                }),
                "",
            )

        # ── Beta tab ──────────────────────────────────────────────────────────
        if tab_value == 'beta':
            if not _os.path.exists(_SUMMARY_BETA_PARQUET):
                return _no_data(
                    "No Beta snapshot found. Click RUN ANALYSIS in the Beta Book → Portfolio tab first."
                )
            try:
                df = pd.read_parquet(_SUMMARY_BETA_PARQUET)
                ts = df['_timestamp'].iloc[0] if '_timestamp' in df.columns else "unknown"

                # Close Price: look up last factor level for each asset's primary factor
                close_prices = _get_beta_close_prices()

                def _close_price_for(asset_name: str) -> float | None:
                    """Match asset name prefix to a factor-level proxy."""
                    for prefix, price in close_prices.items():
                        if asset_name.upper().startswith(prefix.upper()):
                            return price
                    return None

                capital_col = '_capital_cny' if '_capital_cny' in df.columns else 'Capital (CNY)'
                display_rows = []
                for _, row in df.iterrows():
                    asset = str(row.get('Asset Name', ''))
                    if asset == 'TOTAL':
                        continue
                    cap_cny = float(row.get(capital_col, 0) or 0)
                    cap_mm  = round(cap_cny / 1e6, 2)
                    wt      = round(float(row.get('Weight (%)', 0) or 0), 2)
                    cp      = _close_price_for(asset)
                    mv_mm   = cap_mm   # bonds at ~par → market value ≈ notional

                    display_rows.append({
                        'Asset Type':        row.get('Asset Type', ''),
                        'Universe':          row.get('Universe', ''),
                        'Asset Name':        asset,
                        'Close Price (%)':   f"{cp:.4f}" if cp is not None else 'N/A',
                        'Capital (MM CNY)':  f"{cap_mm:,.2f}",
                        'Market Value (MM)': f"{mv_mm:,.2f}",
                        'Weight (%)':        f"{wt:.2f}%",
                    })

                if not display_rows:
                    return _no_data("Beta snapshot is empty.")

                table = dash_table.DataTable(
                    data=display_rows,
                    columns=[{'name': c, 'id': c} for c in display_rows[0].keys()],
                    style_cell={
                        'textAlign': 'center', 'padding': '8px',
                        'backgroundColor': THEME['table_row_odd'],
                        'color': THEME['text_main'], 'border': 'none',
                        'fontSize': '12px',
                    },
                    style_header={
                        'backgroundColor': THEME['table_header'],
                        'color': THEME['text_main'],
                        'fontWeight': 'bold', 'border': 'none',
                    },
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                    ],
                    style_table={'overflowX': 'auto'},
                    sort_action='native',
                    page_size=20,
                )
                status = f"Beta snapshot from {ts[:19]}"
                return table, status

            except Exception as exc:
                return _no_data(f"Error loading Beta snapshot: {exc}")

        # ── Alpha tab ─────────────────────────────────────────────────────────
        elif tab_value == 'alpha':
            if not _os.path.exists(_SUMMARY_ALPHA_PARQUET):
                return _no_data(
                    "No Alpha snapshot found. Click RUN OPTIMIZATION in the Alpha Book → Portfolio tab first."
                )
            try:
                df = pd.read_parquet(_SUMMARY_ALPHA_PARQUET)
                ts = df['_timestamp'].iloc[0] if '_timestamp' in df.columns else "unknown"

                display_rows = []
                for _, row in df.iterrows():
                    trade_id = str(row.get('ID', ''))
                    if trade_id in ('TOTAL', ''):
                        continue
                    spread_val = row.get('spread', None)
                    cp_bp      = round(float(spread_val), 4) if pd.notna(spread_val) else None
                    notional   = float(row.get('notional_mm', 0) or 0)
                    dv01_k     = float(row.get('DV01_k', 0) or 0)
                    # Mark-to-market = DV01 × current spread level
                    mv_mm = round(dv01_k * float(cp_bp) / 1000, 3) if cp_bp is not None else None

                    display_rows.append({
                        'ID':                  trade_id,
                        'Spread Type':         row.get('spread_type', ''),
                        'Style':               row.get('style', ''),
                        'Direction':           row.get('direction', ''),
                        'Z-Score':             f"{float(row.get('Zscore', 0) or 0):.2f}",
                        'Close Price (bp)':    f"{cp_bp:.4f}" if cp_bp is not None else 'N/A',
                        'Notional (MM CNY)':   f"{notional:,.1f}",
                        'DV01 (k CNY/bp)':     f"{dv01_k:.1f}",
                        'MtM Value (MM CNY)':  f"{mv_mm:,.3f}" if mv_mm is not None else 'N/A',
                        'Weight (%)':          f"{float(row.get('weight', 0) or 0) * 100:.2f}%",
                    })

                if not display_rows:
                    return _no_data("Alpha snapshot is empty.")

                dir_styles = [
                    {'if': {'filter_query': '{Direction} = "BUY"'},
                     'backgroundColor': 'rgba(0, 204, 150, 0.12)'},
                    {'if': {'filter_query': '{Direction} = "SELL"'},
                     'backgroundColor': 'rgba(239, 85, 59, 0.12)'},
                ]
                table = dash_table.DataTable(
                    data=display_rows,
                    columns=[{'name': c, 'id': c} for c in display_rows[0].keys()],
                    style_cell={
                        'textAlign': 'center', 'padding': '8px',
                        'backgroundColor': THEME['table_row_odd'],
                        'color': THEME['text_main'], 'border': 'none',
                        'fontSize': '12px',
                    },
                    style_header={
                        'backgroundColor': THEME['table_header'],
                        'color': THEME['text_main'],
                        'fontWeight': 'bold', 'border': 'none',
                    },
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                        *dir_styles,
                    ],
                    style_table={'overflowX': 'auto'},
                    sort_action='native',
                    page_size=20,
                )
                status = f"Alpha snapshot from {ts[:19]}"
                return table, status

            except Exception as exc:
                return _no_data(f"Error loading Alpha snapshot: {exc}")

        return _no_data("Select a tab above.")
