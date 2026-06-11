# -*- coding: utf-8 -*-
"""
Constants, global state, imports, and pure-data helpers for the Multi-Asset Dashboard.
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
from settings.paths import DIR_INPUT, DIR_MODELS

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

# Global state for selected factor pool (shared between Factor tab and Backtest tab)
SELECTED_FACTOR_POOL = {
    'ir_factors': ['IRDL.CN', 'IRSL.CN', 'IRCV.CN'],  # Default: CN Level/Slope/Curvature
    'sp_factors': [],
    'fx_factors': ['FXDL.USDCNY'],
    'cmd_factors': ['CMDL.AU', 'CMDL.AL'],  # Gold + Aluminium
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
        {'name': 'CN20Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '20Y'},
        {'name': 'CN30Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '30Y'},
    ],
    'IRSL.CN': [
        {'name': 'CN2Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '2Y'},
        {'name': 'CN10Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '10Y'},
        {'name': 'CN20Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '20Y'},
    ],
    'IRCV.CN': [
        {'name': 'CN2Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '2Y'},
        {'name': 'CN5Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '5Y'},
        {'name': 'CN10Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '10Y'},
        {'name': 'CN20Y', 'type': 'Rates', 'universe': 'China Gov Bond', 'sector': '20Y'},
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
    'CMDL.AG': [
        {'name': 'Silver', 'type': 'Commodities', 'universe': 'Silver', 'sector': 'N/A'},
    ],
    'CMDL.AL': [
        {'name': 'Aluminium', 'type': 'Commodities', 'universe': 'Aluminium', 'sector': 'N/A'},
    ],
    'CMDL.CU': [
        {'name': 'Copper', 'type': 'Commodities', 'universe': 'Copper', 'sector': 'N/A'},
    ],
    'CMDL.ZN': [
        {'name': 'Zinc', 'type': 'Commodities', 'universe': 'Zinc', 'sector': 'N/A'},
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
