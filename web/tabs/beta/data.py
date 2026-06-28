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

# --- Theme Constants (AtlasNexus Dark Blue — mirrors --an-* tokens in design.css) ---
THEME = {
    'bg_main': '#0a1428',       # --an-navy-900
    'bg_card': '#122a4c',       # --an-navy-700 / --surface-panel
    'bg_input': '#17345c',      # --an-navy-600 / --surface-input
    'text_main': '#e9eef8',     # --an-text / --text-primary
    'text_sub': '#a4b6d2',      # --an-muted / --text-secondary
    'accent': '#3d8bd4',        # --an-blue / --accent-blue
    'success': '#2f9d6b',       # --an-green / --accent-green
    'warning': '#e0a23c',       # --an-amber / --accent-amber
    'danger': '#d56b6b',        # --an-red / --negative
    'table_header': '#0e1d3a',  # --an-navy-800
    'table_row_odd': '#122a4c', # --an-navy-700
    'table_row_even': '#0a1428',# --an-navy-900
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
    'cr_factors': [],  # Credit: CRDL/CRSL/CRCV x LGB/MTN/ICP
    'fx_factors': ['FXDL.USDCNY'],
    'cmd_factors': ['CMDL.AU', 'CMDL.AL'],  # Gold + Aluminium
    'eq_factors': [],
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

    # Anchor to the last day of the previous month — same cut-off the factor
    # model uses for training — so we never overfit to current-month/today data.
    _today = pd.Timestamp.today().normalize()
    end_date = _today.replace(day=1) - relativedelta(days=1)
    end_date = min(end_date, factor_levels.index.max())
    start_date = end_date - relativedelta(years=lookback_years)
    window = factor_levels.loc[
        (factor_levels.index >= start_date) & (factor_levels.index <= end_date), available_factors
    ]
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

    # ==================== Credit Spreads (own yield - CGB, by tenor) ==========
    # China Development Bond — legacy SPDL.CDB/SPSL.CDB (outright CDB level/slope,
    # not a spread vs CGB) are kept for backward compatibility; CRDL/CRSL/CRCV.CDB
    # below are the correct CDB-vs-CGB credit spread factors (see CREDIT_CONFIG).
    'SPDL.CDB': [
        {'name': 'CDB1Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '1Y'},
        {'name': 'CDB2Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '2Y'},
        {'name': 'CDB5Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '5Y'},
        {'name': 'CDB10Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '10Y'},
    ],
    'SPSL.CDB': [
        {'name': 'CDB2Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '2Y'},
        {'name': 'CDB10Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '10Y'},
    ],
    'CRDL.CDB': [
        {'name': 'CDB1Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '1Y'},
        {'name': 'CDB2Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '2Y'},
        {'name': 'CDB5Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '5Y'},
        {'name': 'CDB10Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '10Y'},
    ],
    'CRSL.CDB': [
        {'name': 'CDB1Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '1Y'},
        {'name': 'CDB2Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '2Y'},
        {'name': 'CDB5Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '5Y'},
        {'name': 'CDB10Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '10Y'},
    ],
    'CRCV.CDB': [
        {'name': 'CDB1Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '1Y'},
        {'name': 'CDB2Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '2Y'},
        {'name': 'CDB5Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '5Y'},
        {'name': 'CDB10Y', 'type': 'Credit', 'universe': 'China Development Bond', 'sector': '10Y'},
    ],

    # Local Government Bond
    'CRDL.LGB': [
        {'name': 'LGB1Y', 'type': 'Credit', 'universe': 'Local Government Bond', 'sector': '1Y'},
        {'name': 'LGB3Y', 'type': 'Credit', 'universe': 'Local Government Bond', 'sector': '3Y'},
        {'name': 'LGB5Y', 'type': 'Credit', 'universe': 'Local Government Bond', 'sector': '5Y'},
        {'name': 'LGB10Y', 'type': 'Credit', 'universe': 'Local Government Bond', 'sector': '10Y'},
        {'name': 'LGB30Y', 'type': 'Credit', 'universe': 'Local Government Bond', 'sector': '30Y'},
    ],
    'CRSL.LGB': [
        {'name': 'LGB1Y', 'type': 'Credit', 'universe': 'Local Government Bond', 'sector': '1Y'},
        {'name': 'LGB3Y', 'type': 'Credit', 'universe': 'Local Government Bond', 'sector': '3Y'},
        {'name': 'LGB5Y', 'type': 'Credit', 'universe': 'Local Government Bond', 'sector': '5Y'},
        {'name': 'LGB10Y', 'type': 'Credit', 'universe': 'Local Government Bond', 'sector': '10Y'},
        {'name': 'LGB30Y', 'type': 'Credit', 'universe': 'Local Government Bond', 'sector': '30Y'},
    ],
    'CRCV.LGB': [
        {'name': 'LGB1Y', 'type': 'Credit', 'universe': 'Local Government Bond', 'sector': '1Y'},
        {'name': 'LGB3Y', 'type': 'Credit', 'universe': 'Local Government Bond', 'sector': '3Y'},
        {'name': 'LGB5Y', 'type': 'Credit', 'universe': 'Local Government Bond', 'sector': '5Y'},
        {'name': 'LGB10Y', 'type': 'Credit', 'universe': 'Local Government Bond', 'sector': '10Y'},
        {'name': 'LGB30Y', 'type': 'Credit', 'universe': 'Local Government Bond', 'sector': '30Y'},
    ],

    # Medium Term Note
    'CRDL.MTN': [
        {'name': 'MTN1Y', 'type': 'Credit', 'universe': 'Medium Term Note', 'sector': '1Y'},
        {'name': 'MTN2Y', 'type': 'Credit', 'universe': 'Medium Term Note', 'sector': '2Y'},
        {'name': 'MTN3Y', 'type': 'Credit', 'universe': 'Medium Term Note', 'sector': '3Y'},
        {'name': 'MTN4Y', 'type': 'Credit', 'universe': 'Medium Term Note', 'sector': '4Y'},
        {'name': 'MTN5Y', 'type': 'Credit', 'universe': 'Medium Term Note', 'sector': '5Y'},
    ],
    'CRSL.MTN': [
        {'name': 'MTN1Y', 'type': 'Credit', 'universe': 'Medium Term Note', 'sector': '1Y'},
        {'name': 'MTN2Y', 'type': 'Credit', 'universe': 'Medium Term Note', 'sector': '2Y'},
        {'name': 'MTN3Y', 'type': 'Credit', 'universe': 'Medium Term Note', 'sector': '3Y'},
        {'name': 'MTN4Y', 'type': 'Credit', 'universe': 'Medium Term Note', 'sector': '4Y'},
        {'name': 'MTN5Y', 'type': 'Credit', 'universe': 'Medium Term Note', 'sector': '5Y'},
    ],
    'CRCV.MTN': [
        {'name': 'MTN1Y', 'type': 'Credit', 'universe': 'Medium Term Note', 'sector': '1Y'},
        {'name': 'MTN2Y', 'type': 'Credit', 'universe': 'Medium Term Note', 'sector': '2Y'},
        {'name': 'MTN3Y', 'type': 'Credit', 'universe': 'Medium Term Note', 'sector': '3Y'},
        {'name': 'MTN4Y', 'type': 'Credit', 'universe': 'Medium Term Note', 'sector': '4Y'},
        {'name': 'MTN5Y', 'type': 'Credit', 'universe': 'Medium Term Note', 'sector': '5Y'},
    ],

    # Interbank Commercial Paper (Level + Slope only — too few tenors for curvature)
    'SPDL.ICP': [
        {'name': 'ICP3M', 'type': 'Credit', 'universe': 'Interbank Commercial Paper', 'sector': '3M'},
        {'name': 'ICP6M', 'type': 'Credit', 'universe': 'Interbank Commercial Paper', 'sector': '6M'},
        {'name': 'ICP1Y', 'type': 'Credit', 'universe': 'Interbank Commercial Paper', 'sector': '1Y'},
    ],
    'CRDL.ICP': [
        {'name': 'ICP3M', 'type': 'Credit', 'universe': 'Interbank Commercial Paper', 'sector': '3M'},
        {'name': 'ICP6M', 'type': 'Credit', 'universe': 'Interbank Commercial Paper', 'sector': '6M'},
        {'name': 'ICP9M', 'type': 'Credit', 'universe': 'Interbank Commercial Paper', 'sector': '9M'},
        {'name': 'ICP1Y', 'type': 'Credit', 'universe': 'Interbank Commercial Paper', 'sector': '1Y'},
    ],
    'CRSL.ICP': [
        {'name': 'ICP3M', 'type': 'Credit', 'universe': 'Interbank Commercial Paper', 'sector': '3M'},
        {'name': 'ICP6M', 'type': 'Credit', 'universe': 'Interbank Commercial Paper', 'sector': '6M'},
        {'name': 'ICP9M', 'type': 'Credit', 'universe': 'Interbank Commercial Paper', 'sector': '9M'},
        {'name': 'ICP1Y', 'type': 'Credit', 'universe': 'Interbank Commercial Paper', 'sector': '1Y'},
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

    # ==================== Commodities (CM) ====================
    'CMDL.AU': [
        {'name': 'Gold', 'type': 'Commodities', 'universe': 'Precious Metals', 'sector': 'N/A'},
    ],
    'CMDL.AG': [
        {'name': 'Silver', 'type': 'Commodities', 'universe': 'Precious Metals', 'sector': 'N/A'},
    ],
    'CMDL.AL': [
        {'name': 'Aluminium', 'type': 'Commodities', 'universe': 'Base Metals', 'sector': 'N/A'},
    ],
    'CMDL.CU': [
        {'name': 'Copper', 'type': 'Commodities', 'universe': 'Base Metals', 'sector': 'N/A'},
    ],
    'CMDL.ZN': [
        {'name': 'Zinc', 'type': 'Commodities', 'universe': 'Base Metals', 'sector': 'N/A'},
    ],
    'CMDL.SC': [
        {'name': 'Crude_Oil', 'type': 'Commodities', 'universe': 'Energy', 'sector': 'N/A'},
    ],
    'CMDL.RB': [
        {'name': 'Rebar', 'type': 'Commodities', 'universe': 'Ferrous Metals', 'sector': 'N/A'},
    ],
    'CMDL.LC': [
        {'name': 'Live_Hog', 'type': 'Commodities', 'universe': 'Livestock', 'sector': 'N/A'},
    ],
    'CMDL.SA': [
        {'name': 'Soda_Ash', 'type': 'Commodities', 'universe': 'Chemicals', 'sector': 'N/A'},
    ],
    'CMDL.JM': [
        {'name': 'Coking_Coal', 'type': 'Commodities', 'universe': 'Ferrous Metals', 'sector': 'N/A'},
    ],
    'CMDL.EC': [
        {'name': 'European_Gas', 'type': 'Commodities', 'universe': 'Energy', 'sector': 'N/A'},
    ],

    # ==================== Equities (EQ) ====================
    'EQDL.IF': [
        {'name': 'IF', 'type': 'Equities', 'universe': 'CSI 300', 'sector': 'N/A'},
    ],
    'EQDL.IC': [
        {'name': 'IC', 'type': 'Equities', 'universe': 'CSI 500', 'sector': 'N/A'},
    ],
    'EQDL.IH': [
        {'name': 'IH', 'type': 'Equities', 'universe': 'SSE 50', 'sector': 'N/A'},
    ],
    'EQDL.IM': [
        {'name': 'IM', 'type': 'Equities', 'universe': 'CSI 1000', 'sector': 'N/A'},
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
