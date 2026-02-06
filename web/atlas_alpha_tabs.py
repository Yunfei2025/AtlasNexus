# -*- coding: utf-8 -*-
"""Alpha Book tab layouts and callbacks for AtlasNexus Daily Console.

Implements:
- CANDIDATES subtab: Scan for alpha candidates based on spread z-scores, with correlation filtering
- PORTFOLIO subtab: Multi-factor scoring with risk parity allocation

Data sources:
- Bond-Curve spreads: TBond-spds.pkl, CBond-spds.pkl
- Bond-Swap spreads: TBond-spds.pkl, CBond-spds.pkl  
- Swap spreads: IRS-pxspds.pkl
- Futures basis: futures-spds.pkl (NetBasis, TermBasis)
- Misc spreads: Misc-spds.pkl (PCA, Binary)
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

import numpy as np
import pandas as pd
from dateutil.relativedelta import relativedelta

from dash import dcc, html, dash_table, callback_context
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go

# ---------------------------------------------------------------------------
# Theme / Style constants (mirror atlas_multiasset_tabs.py)
# ---------------------------------------------------------------------------
THEME = {
    'bg_main': '#082255',
    'bg_card': '#0c2b64',
    'bg_input': '#112e66',
    'text_main': '#ffffff',
    'text_sub': '#aab0c0',
    'accent': '#3498db',
    'success': '#00cc96',
    'warning': '#f39c12',
    'danger': '#ef553b',
    'table_header': '#1a3a7a',
    'table_row_even': '#0c2b64',
    'table_row_odd': '#082255',
}

# ---------------------------------------------------------------------------
# Spread type definitions
# ---------------------------------------------------------------------------
SPREAD_CATEGORIES = {
    'Bond-Curve': {
        'label': 'Bond vs Model Curve',
        'types': ['TBondCurve', 'CBondCurve'],
        'description': 'Treasury/Policybank bond yield vs fitted curve',
        'style': 'MeanReversion',
    },
    'Bond-Swap': {
        'label': 'Bond vs Swap',
        'types': ['TBondSwap', 'CBondSwap'],
        'description': 'Bond yield vs interpolated swap rate',
        'style': 'Mixed',  # Can be Carry or Trend
    },
    'Swap-Spread': {
        'label': 'Swap Spreads',
        'types': ['SwapSpread'],
        'description': 'IRS spread trades (box, basis)',
        'style': 'Mixed',  # Can be MR or Carry/Trend
    },
    'Tenor-Spread': {
        'label': 'Tenor Spreads',
        'types': ['TenorSpread'],
        'description': 'Curve slope / cross-curve spreads (e.g. 5s10s, 10s30s)',
        'style': 'MeanReversion',
    },
    'Bond-Futures': {
        'label': 'Bond vs Futures (Net Basis)',
        'types': ['NetBasis'],
        'description': 'CTD bond vs futures implied yield',
        'style': 'Carry',
    },
    'Futures-Term': {
        'label': 'Futures Term Basis',
        'types': ['TermBasis'],
        'description': 'Near vs far futures contract spread',
        'style': 'MeanReversion',
    },
    'PCA-Spread': {
        'label': 'Multi-Asset PCA',
        'types': ['PCASpread'],
        'description': 'Cross-asset relative value from PCA',
        'style': 'MeanReversion',
    },
    'Binary-Spread': {
        'label': 'Binary Regression',
        'types': ['BinarySpread'],
        'description': 'Pairwise bond spread regression',
        'style': 'MeanReversion',
    },
}

# Flatten for dropdown
SPREAD_TYPE_OPTIONS = []
for cat, info in SPREAD_CATEGORIES.items():
    for stype in info['types']:
        SPREAD_TYPE_OPTIONS.append({
            'label': f"{info['label']} ({stype})",
            'value': stype,
            'category': cat,
        })

# Default z-score thresholds
ZSCORE_ENTRY_THRESHOLD = 2.0
ZSCORE_EXIT_THRESHOLD = 0.5
MAX_CORRELATION_THRESHOLD = 0.6

# Instrument selector prefix for non-spread (macro) series used by bond-swap trend backtests
MACRO_PREFIX = "MACRO|"

# Global state for diversified trade recommendations
# This persists across tab switches (unlike dcc.Store which is tab-scoped)
DIVERSIFIED_TRADE_RECOMMENDATIONS = {
    'trades': [],       # List of recommended trade dictionaries
    'timestamp': None   # When the analysis was run
}

# ---------------------------------------------------------------------------
# Data Loading Utilities
# ---------------------------------------------------------------------------

def _get_input_dir() -> Path:
    """Get the input directory path."""
    try:
        from settings.paths import DIR_INPUT
        return Path(DIR_INPUT)
    except ImportError:
        # Fallback
        return Path(__file__).parent.parent / 'input'


def _load_pickle_safe(filepath: Path) -> Optional[Any]:
    """Load pickle file with error handling."""
    if not filepath.exists():
        print(f"Warning: {filepath} not found")
        return None
    try:
        with open(filepath, 'rb') as f:
            return pickle.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        try:
            return pd.read_pickle(filepath)
        except Exception as e2:
            print(f"Fallback also failed: {e2}")
            return None


def load_spread_data(spread_type: str) -> Optional[pd.DataFrame]:
    """Load spread data for a given type and return DataFrame with required columns.
    
    Returns DataFrame with columns: [spread, mean, vol, Zscore, halflife, stationary, ...]
    """
    dir_input = _get_input_dir()

    # Prefer the normalized snapshot generated in curves/refreshers/alpha.py.
    # This aligns with how realtime z-scores / stationarity / carry+roll are stored.
    try:
        from curves.refreshers.alpha import get_alpha_spread_table

        snap_df = get_alpha_spread_table(spread_type, dir_input=dir_input)
        if snap_df is not None and isinstance(snap_df, pd.DataFrame) and not snap_df.empty:
            if spread_type == 'SwapSpread':
                # Filter out .IR columns/indices if present
                snap_df = snap_df[~snap_df.index.astype(str).str.endswith('.IR')].copy()
            return snap_df
    except Exception:
        pass
    
    # Map spread type to file and key
    if spread_type in ['TBondCurve', 'TBondSwap']:
        data = _load_pickle_safe(dir_input / 'TBond-spds.pkl')
        if data is None:
            return None
        key = 'BondCurve' if spread_type == 'TBondCurve' else 'BondSwap'
        return data.get(key, {}).get('StatInfo')
        
    elif spread_type in ['CBondCurve', 'CBondSwap']:
        data = _load_pickle_safe(dir_input / 'CBond-spds.pkl')
        if data is None:
            return None
        key = 'BondCurve' if spread_type == 'CBondCurve' else 'BondSwap'
        return data.get(key, {}).get('StatInfo')
        
    elif spread_type == 'SwapSpread':
        data = _load_pickle_safe(dir_input / 'IRS-pxspds.pkl')
        if data is None:
            return None
        df = data.get('StatInfo')
        if isinstance(df, pd.DataFrame) and not df.empty:
            df = df[~df.index.astype(str).str.endswith('.IR')].copy()
            return df
        return None
        
    elif spread_type == 'NetBasis':
        data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
        if data is None:
            return None
        # NetBasis is dict by contract type
        nb_data = data.get('NetBasis', {})
        frames = []
        for contract, cdata in nb_data.items():
            if isinstance(cdata, dict) and 'StatInfo' in cdata:
                df = cdata['StatInfo'].copy()
                df['contract'] = contract
                frames.append(df)
        return pd.concat(frames, axis=0) if frames else None
        
    elif spread_type == 'TermBasis':
        data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
        if data is None:
            return None
        return data.get('TermBasis', {}).get('StatInfo')
        
    elif spread_type == 'PCASpread':
        data = _load_pickle_safe(dir_input / 'Misc-spds.pkl')
        if data is None:
            return None
        return data.get('PCASpread', {}).get('StatInfo')
        
    elif spread_type == 'BinarySpread':
        data = _load_pickle_safe(dir_input / 'Misc-spds.pkl')
        if data is None:
            return None
        return data.get('BinarySpread', {}).get('StatInfo')
    
    return None


def load_spread_timeseries(spread_type: str) -> Optional[pd.DataFrame]:
    """Load historical spread time series for correlation analysis."""
    dir_input = _get_input_dir()
    
    # First try loading from Alpha-spreadsrt.pkl which has pre-processed time series
    alpha_snapshot = _load_pickle_safe(dir_input / 'Alpha-spreadsrt.pkl')
    if alpha_snapshot and isinstance(alpha_snapshot, dict):
        timeseries_data = alpha_snapshot.get('_timeseries', {})
        if isinstance(timeseries_data, dict) and spread_type in timeseries_data:
            ts = timeseries_data[spread_type]
            if isinstance(ts, pd.DataFrame) and not ts.empty:
                # SwapSpread: exclude instruments ending with '.IR'
                if spread_type == 'SwapSpread':
                    cols = pd.Index(ts.columns.astype(str))
                    ts = ts.loc[:, ~cols.str.endswith('.IR')].copy()
                print(f"[DEBUG] Loaded {spread_type} from Alpha-spreadsrt['_timeseries'], shape={ts.shape}")
                return ts
    
    # Fallback: load directly from source pickle files
    if spread_type in ['TBondCurve', 'TBondSwap']:
        filepath = dir_input / 'TBond-spds.pkl'
        data = _load_pickle_safe(filepath)
        if data is None:
            print(f"[DEBUG] {filepath} returned None")
            return None
        key = 'BondCurve' if spread_type == 'TBondCurve' else 'BondSwap'
        print(f"[DEBUG] TBond-spds.pkl keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        if isinstance(data, dict) and key in data:
            nested = data[key]
            print(f"[DEBUG] data['{key}'] type: {type(nested)}, keys: {list(nested.keys()) if isinstance(nested, dict) else 'N/A'}")
            if isinstance(nested, dict) and 'Spread' in nested:
                result = nested['Spread']
                print(f"[DEBUG] data['{key}']['Spread'] type: {type(result)}, shape: {result.shape if isinstance(result, pd.DataFrame) else 'N/A'}")
                return result
        return None
        
    elif spread_type in ['CBondCurve', 'CBondSwap']:
        filepath = dir_input / 'CBond-spds.pkl'
        data = _load_pickle_safe(filepath)
        if data is None:
            print(f"[DEBUG] {filepath} returned None")
            return None
        key = 'BondCurve' if spread_type == 'CBondCurve' else 'BondSwap'
        print(f"[DEBUG] CBond-spds.pkl keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        if isinstance(data, dict) and key in data:
            nested = data[key]
            print(f"[DEBUG] data['{key}'] type: {type(nested)}, keys: {list(nested.keys()) if isinstance(nested, dict) else 'N/A'}")
            if isinstance(nested, dict) and 'Spread' in nested:
                result = nested['Spread']
                print(f"[DEBUG] data['{key}']['Spread'] type: {type(result)}, shape: {result.shape if isinstance(result, pd.DataFrame) else 'N/A'}")
                return result
        return None
        
    elif spread_type == 'PCASpread':
        filepath = dir_input / 'Misc-spds.pkl'
        data = _load_pickle_safe(filepath)
        if data is None:
            print(f"[DEBUG] {filepath} returned None")
            return None
        print(f"[DEBUG] Misc-spds.pkl keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")
        if isinstance(data, dict) and 'PCASpread' in data:
            nested = data['PCASpread']
            if isinstance(nested, dict) and 'Spread' in nested:
                result = nested['Spread']
                print(f"[DEBUG] data['PCASpread']['Spread'] type: {type(result)}, shape: {result.shape if isinstance(result, pd.DataFrame) else 'N/A'}")
                return result
        return None

    elif spread_type == 'SwapSpread':
        filepath = dir_input / 'IRS-pxspds.pkl'
        data = _load_pickle_safe(filepath)
        if data is None:
            print(f"[DEBUG] {filepath} returned None")
            return None
        if isinstance(data, dict) and 'Spread' in data:
            df_spread = data.get('Spread')
            if isinstance(df_spread, pd.DataFrame) and not df_spread.empty:
                cols = pd.Index(df_spread.columns.astype(str))
                df_spread = df_spread.loc[:, ~cols.str.endswith('.IR')].copy()
                print(f"[DEBUG] Loaded SwapSpread from IRS-pxspds.pkl Spread, shape={df_spread.shape}")
                return df_spread
        return None
    
    print(f"[DEBUG] Unsupported spread_type: {spread_type}")
    return None


def load_macro_series(series_name: str) -> Optional[pd.Series]:
    """Load macro (curve-level) time series used for bond-swap style trades.

    Supports:
    - TBond-FR007:1Y
    - TBond-FR007:5Y

    Data source: curves.utils.loader.loadCNBDTS (database-px.pkl).
    """
    try:
        from curves.utils.loader import loadCNBDTS
    except Exception:
        return None

    try:
        env = loadCNBDTS()
        cgb = env.get('CGB')
        swap = env.get('SwapTS')
        if cgb is None or swap is None:
            return None

        if series_name == 'TBond-FR007:1Y':
            s = cgb['中债国债到期收益率:1年'] - swap['FR007S1Y.IR']
        elif series_name == 'TBond-FR007:5Y':
            s = cgb['中债国债到期收益率:5年'] - swap['FR007S5Y.IR']
        else:
            return None

        s = pd.to_numeric(s, errors='coerce').dropna()
        s.name = series_name
        return s
    except Exception:
        return None


def load_realtime_spreads(spread_type: str) -> Optional[pd.DataFrame]:
    """Load realtime spread data (refreshed by StatRefresher)."""
    dir_input = _get_input_dir()
    
    if spread_type in ['TBondCurve', 'TBondSwap']:
        data = _load_pickle_safe(dir_input / 'TBond-spdsrt.pkl')
        if data is None:
            return None
        key = 'BondCurve' if spread_type == 'TBondCurve' else 'BondSwap'
        return data.get(key)
        
    elif spread_type in ['CBondCurve', 'CBondSwap']:
        data = _load_pickle_safe(dir_input / 'CBond-spdsrt.pkl')
        if data is None:
            return None
        key = 'BondCurve' if spread_type == 'CBondCurve' else 'BondSwap'
        return data.get(key)
        
    elif spread_type == 'SwapSpread':
        return _load_pickle_safe(dir_input / 'IRS-spdsrt.pkl')
        
    elif spread_type in ['NetBasis', 'TermBasis']:
        return _load_pickle_safe(dir_input / 'futures-spdsrt.pkl')
        
    elif spread_type in ['PCASpread', 'BinarySpread']:
        data = _load_pickle_safe(dir_input / 'Misc-spdsrt.pkl')
        if data:
            return data.get(spread_type)
    
    return None


def get_spread_style(spread_type: str) -> str:
    """Get the trading style for a spread type."""
    for cat, info in SPREAD_CATEGORIES.items():
        if spread_type in info['types']:
            return info['style']
    return 'Unknown'


# ---------------------------------------------------------------------------
# Correlation Analysis
# ---------------------------------------------------------------------------

def compute_spread_correlation(
    spread_types: List[str],
    lookback_days: int = 252,
) -> Tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """Compute correlation matrix of spread changes across selected types.
    
    Returns:
        corr_matrix: Correlation matrix
        spread_changes: DataFrame of daily spread changes
    """
    all_spreads = {}
    
    for stype in spread_types:
        ts = load_spread_timeseries(stype)
        print(f"[DEBUG] load_spread_timeseries({stype}) returned: {type(ts)}, shape: {ts.shape if isinstance(ts, pd.DataFrame) else 'N/A'}")
        if ts is not None and isinstance(ts, pd.DataFrame):
            # Use last lookback_days
            ts = ts.tail(lookback_days)
            print(f"[DEBUG] After tail({lookback_days}): shape={ts.shape}, columns={list(ts.columns)[:5]}")
            for col in ts.columns:
                all_spreads[f"{stype}|{col}"] = ts[col]
    
    print(f"[DEBUG] Total spreads collected: {len(all_spreads)}")
    if len(all_spreads) < 2:
        return None, None
    
    df_spreads = pd.DataFrame(all_spreads)
    # Use diff() for spread changes (more appropriate than pct_change for bp spreads)
    df_changes = df_spreads.diff().dropna()
    
    print(f"[DEBUG] df_changes shape: {df_changes.shape}")
    if df_changes.shape[0] < 20:
        return None, None
    
    corr_matrix = df_changes.corr()
    return corr_matrix, df_changes


def rank_low_correlation_pairs(
    corr_matrix: pd.DataFrame,
    top_n: int = 10,
) -> pd.DataFrame:
    """Rank pairs by lowest absolute correlation."""
    # Mask upper triangle
    mask = np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
    corr_stacked = corr_matrix.where(mask).stack().reset_index()
    corr_stacked.columns = ['Asset A', 'Asset B', 'Correlation']
    corr_stacked['AbsCorr'] = corr_stacked['Correlation'].abs()
    
    return corr_stacked.sort_values('AbsCorr', ascending=True).head(top_n)


# ---------------------------------------------------------------------------
# Risk Parity Sizing
# ---------------------------------------------------------------------------

def risk_parity_weights(
    cov_matrix: pd.DataFrame,
    risk_budget: Optional[Dict[str, float]] = None,
) -> pd.Series:
    """Compute risk parity weights given covariance matrix.
    
    Uses iterative optimization for equal risk contribution.
    """
    n = cov_matrix.shape[0]
    assets = cov_matrix.columns.tolist()
    
    # Default to equal risk budget
    if risk_budget is None:
        target_rc = np.ones(n) / n
    else:
        target_rc = np.array([risk_budget.get(a, 1/n) for a in assets])
        target_rc = target_rc / target_rc.sum()
    
    cov = cov_matrix.values
    
    # Simple iterative approach
    w = np.ones(n) / n
    for _ in range(100):
        port_var = w.T @ cov @ w
        if port_var < 1e-12:
            break
        marginal_risk = cov @ w
        risk_contrib = w * marginal_risk / np.sqrt(port_var)
        total_risk = np.sum(risk_contrib)
        if total_risk < 1e-12:
            break
        rc_pct = risk_contrib / total_risk
        
        # Update weights toward target
        adjustment = target_rc / (rc_pct + 1e-8)
        w = w * adjustment
        w = w / w.sum()
    
    return pd.Series(w, index=assets)


def _compute_risk_parity_weights(df_candidates: pd.DataFrame) -> Tuple[Dict[str, float], np.ndarray]:
    """Compute risk parity weights for alpha candidates using historical spread data.
    
    Args:
        df_candidates: DataFrame with candidate trades (must have 'ID', 'spread_type' columns)
    
    Returns:
        Tuple of (weights_dict, risk_contribution_array)
        - weights_dict: {trade_id: weight}
        - risk_contribution_array: risk contribution for each trade
    """
    from scipy.optimize import minimize
    
    # Load historical spread time series for each candidate
    dir_input = _get_input_dir()
    spread_series = {}
    
    for idx, row in df_candidates.iterrows():
        trade_id = row['ID']
        spread_type = row.get('spread_type', '')
        
        # Try to load spread time series
        try:
            # Load the spread data file
            if spread_type in ['TBondCurve', 'TBondSwap']:
                data = _load_pickle_safe(dir_input / 'TBond-spds.pkl')
                key = 'BondCurve' if spread_type == 'TBondCurve' else 'BondSwap'
            elif spread_type in ['CBondCurve', 'CBondSwap']:
                data = _load_pickle_safe(dir_input / 'CBond-spds.pkl')
                key = 'BondCurve' if spread_type == 'CBondCurve' else 'BondSwap'
            elif spread_type == 'SwapSpread':
                data = _load_pickle_safe(dir_input / 'IRS-pxspds.pkl')
                key = 'Spread'
            elif spread_type in ['NetBasis', 'TermBasis']:
                data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
                key = spread_type
            else:
                data = _load_pickle_safe(dir_input / 'Misc-spds.pkl')
                key = 'Spread'
            
            if data and key in data:
                spread_df = data[key].get('Spread')
                if spread_df is not None and trade_id in spread_df.columns:
                    # Use last 252 days (1 year) for covariance
                    spread_series[trade_id] = spread_df[trade_id].dropna().tail(252)
        except Exception as e:
            print(f"Warning: Could not load spread data for {trade_id}: {e}")
    
    # If we don't have enough historical data, fall back to simplified method
    if len(spread_series) < 2:
        print("⚠ Insufficient historical data for risk parity, using inverse volatility")
        n = len(df_candidates)
        weights = {row['ID']: 1/n for _, row in df_candidates.iterrows()}
        risk_contrib = np.ones(n) / n
        return weights, risk_contrib
    
    # Align all series to common dates
    spread_df = pd.DataFrame(spread_series).dropna()
    
    if len(spread_df) < 20:
        print("⚠ Too few common dates for covariance, using inverse volatility")
        n = len(df_candidates)
        weights = {row['ID']: 1/n for _, row in df_candidates.iterrows()}
        risk_contrib = np.ones(n) / n
        return weights, risk_contrib
    
    # Calculate returns (daily changes)
    returns = spread_df.diff().dropna()
    
    # Calculate covariance matrix
    cov_matrix = returns.cov()
    cov = cov_matrix.values
    n = len(cov)
    
    # Risk parity optimization
    def _risk_contribution(w, cov):
        """Calculate risk contribution for each asset."""
        port_var = w.T @ cov @ w
        if port_var < 1e-12:
            return np.ones(len(w)) / len(w)
        marginal_risk = cov @ w
        return (w * marginal_risk) / np.sqrt(port_var)
    
    def _objective(w, cov):
        """Objective: minimize variance of risk contributions."""
        rc = _risk_contribution(w, cov)
        target = 1.0 / len(w)
        return np.sum((rc - target) ** 2)
    
    # Constraints: weights sum to 1
    constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]
    
    # Bounds: no short positions, max 30% in any single trade (reduced from 50% for better diversification)
    bounds = [(0.0, 0.3) for _ in range(n)]
    
    # Initial guess: equal weight
    w0 = np.ones(n) / n
    
    # Optimize
    result = minimize(
        _objective,
        w0,
        args=(cov,),
        method='SLSQP',
        bounds=bounds,
        constraints=constraints,
        options={'maxiter': 1000, 'ftol': 1e-9}
    )
    
    if not result.success:
        print(f"⚠ Risk parity optimization did not converge: {result.message}")
        # Fall back to equal weights
        weights_array = np.ones(n) / n
    else:
        weights_array = result.x
    
    # Calculate final risk contributions
    risk_contrib = _risk_contribution(weights_array, cov)
    
    # Create weights dictionary
    weights_dict = {col: w for col, w in zip(spread_df.columns, weights_array)}
    
    print(f"✓ Risk parity optimization completed:")
    print(f"  - Weights std: {weights_array.std():.4f}")
    print(f"  - Risk contribution std: {risk_contrib.std():.4f}")
    
    return weights_dict, risk_contrib


# ---------------------------------------------------------------------------
# Scoring Functions
# ---------------------------------------------------------------------------

def compute_candidate_scores(
    df: pd.DataFrame,
    weights: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """Compute composite scores for candidates.
    
    Factors:
    - zscore_score: Signal strength (abs z-score, higher = stronger signal)
    - mr_score: Mean-reversion confidence (based on halflife, stationarity)
    - vol_score: Volatility-adjusted (lower vol = better risk/reward)
    """
    if weights is None:
        weights = {
            'zscore': 0.40,
            'mr_conf': 0.30,
            'vol_adj': 0.15,
            'liquidity': 0.15,
        }
    
    df = df.copy()
    
    # Z-score signal strength (0-100)
    if 'Zscore' in df.columns:
        abs_z = df['Zscore'].abs()
        df['zscore_score'] = (abs_z / abs_z.max() * 100).clip(0, 100)
    else:
        df['zscore_score'] = 50
    
    # Mean-reversion confidence (0-100)
    if 'halflife' in df.columns and 'stationary' in df.columns:
        # Shorter halflife = higher MR confidence (cap at 60 days)
        hl = df['halflife'].clip(1, 120)
        hl_score = (1 - hl / 120) * 100
        stat_score = (df['stationary'] == 'YES').astype(float) * 50
        df['mr_score'] = (hl_score * 0.5 + stat_score).fillna(25)
    else:
        df['mr_score'] = 50
    
    # Volatility score (lower vol = better, normalize 0-100)
    if 'vol' in df.columns:
        vol = df['vol'].abs()
        vol_norm = vol / vol.max()
        df['vol_score'] = ((1 - vol_norm) * 100).clip(0, 100)
    else:
        df['vol_score'] = 50
    
    # Liquidity placeholder (would use volume/turnover if available)
    df['liquidity_score'] = 50
    
    # Composite score
    df['composite_score'] = (
        weights['zscore'] * df['zscore_score'] +
        weights['mr_conf'] * df['mr_score'] +
        weights['vol_adj'] * df['vol_score'] +
        weights['liquidity'] * df['liquidity_score']
    )
    
    return df


def compute_scan_score(df: pd.DataFrame) -> pd.DataFrame:
    """Compute lightweight scan-time score for ranking and filtering.
    
    This is a fast preview score computed during candidate scanning without
    loading historical time series. Portfolio allocation will recompute the
    authoritative score with full parameters.
    
    Formula:
    - MeanReversion: edge/risk = |spread - mean| / halflife / vol
    - Carry/Trend: edge/risk = (carry_roll * direction_sign) / vol
    - composite_score_preview = max(0, edge/risk)
    
    Returns:
        DataFrame with added columns: edge_preview, composite_score_preview
    """
    df = df.copy()
    
    style = (
        df['style'].astype(str).str.strip().str.lower()
        if 'style' in df.columns
        else pd.Series('', index=df.index, dtype=str)
    )
    is_mr = style.eq('meanreversion')
    
    spread = (
        pd.to_numeric(df['spread'], errors='coerce')
        if 'spread' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    mean = (
        pd.to_numeric(df['mean'], errors='coerce')
        if 'mean' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    halflife = (
        pd.to_numeric(df['halflife'], errors='coerce')
        if 'halflife' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    carry = (
        pd.to_numeric(df['carry_roll'], errors='coerce')
        if 'carry_roll' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    vol = (
        pd.to_numeric(df['vol'], errors='coerce').abs()
        if 'vol' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    
    # Robust risk fallback
    risk = vol.replace(0, np.nan)
    fallback_risk = float(risk.median(skipna=True)) if not risk.dropna().empty else 1.0
    if not np.isfinite(fallback_risk) or fallback_risk <= 0:
        fallback_risk = 1.0
    risk = risk.fillna(fallback_risk)
    
    # MR: |spread - mean| / halflife
    hl = halflife.replace(0, np.nan).abs()
    expected_mr = (spread - mean).abs() / hl
    
    # Carry/Trend: carry_roll aligned to direction
    direction = (
        df['direction'].astype(str).str.strip().str.upper()
        if 'direction' in df.columns
        else pd.Series('', index=df.index, dtype=str)
    )
    dir_sign = pd.Series(1.0, index=df.index, dtype=float)
    dir_sign.loc[direction.eq('SELL')] = -1.0
    expected_tc = carry.fillna(0.0) * dir_sign
    
    # Combine
    expected_move = expected_tc.where(~is_mr, expected_mr)
    edge = expected_move.fillna(0.0)
    
    df['edge_preview'] = edge
    df['composite_score_preview'] = (edge / risk).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    
    return df


def compute_unified_edge_vol_score(
    df: pd.DataFrame,
    *,
    mom_window: int = 20,
    mom_k: float = 1.0,
) -> pd.DataFrame:
    """Compute a unified, weightless score across MR and Carry/Trend.

    The intent is to rank all candidates on a common axis without user-chosen weights.

    Uses expected daily edge (in spread bp/day) divided by risk (bp):
    - MeanReversion: expected_move_per_day ≈ |spread - mean| / halflife
    - Carry/Trend: expected_move_per_day ≈ carry_roll + k * momentum_per_day
        where momentum_per_day ≈ (s_t - s_{t-m}) / m

    Notes:
    - For Carry/Trend, expected_move_per_day is aligned to trade direction when available:
        BUY => + (carry_roll + k*mom)
        SELL => - (carry_roll + k*mom)
    - composite_score is clipped at 0 to avoid negative score-weighted allocations.
    """
    df = df.copy()

    style = (
        df['style'].astype(str).str.strip().str.lower()
        if 'style' in df.columns
        else pd.Series('', index=df.index, dtype=str)
    )
    is_mr = style.eq('meanreversion')

    spread = (
        pd.to_numeric(df['spread'], errors='coerce')
        if 'spread' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    mean = (
        pd.to_numeric(df['mean'], errors='coerce')
        if 'mean' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    halflife = (
        pd.to_numeric(df['halflife'], errors='coerce')
        if 'halflife' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    carry = (
        pd.to_numeric(df['carry_roll'], errors='coerce')
        if 'carry_roll' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )
    vol = (
        pd.to_numeric(df['vol'], errors='coerce').abs()
        if 'vol' in df.columns
        else pd.Series(np.nan, index=df.index, dtype=float)
    )

    # Robust risk fallback
    risk = vol.replace(0, np.nan)
    fallback_risk = float(risk.median(skipna=True)) if not risk.dropna().empty else 1.0
    if not np.isfinite(fallback_risk) or fallback_risk <= 0:
        fallback_risk = 1.0
    risk = risk.fillna(fallback_risk)

    # ---------------------------------------------------------------------
    # Carry per day (bp/day)
    # ---------------------------------------------------------------------
    # carry_roll is stored as a 3m carry+roll (bp) for the BUY side.
    # Convert to per-day and flip sign for SELL where we have direction.
    carry_days = 63.0  # ~3m trading days
    carry_per_day = carry / carry_days
    df['carry_per_day'] = carry_per_day

    # ---------------------------------------------------------------------
    # Momentum per day (bp/day) for carry/trend trades
    # ---------------------------------------------------------------------
    # Prefer precomputed momentum if present, else compute from historical series.
    mom_window_i = int(mom_window) if mom_window is not None else 20
    if mom_window_i < 1:
        mom_window_i = 1
    try:
        mom_k_f = float(mom_k) if mom_k is not None else 1.0
    except Exception:
        mom_k_f = 1.0

    momentum_per_day = pd.Series(np.nan, index=df.index, dtype=float)
    if 'momentum_per_day' in df.columns:
        momentum_per_day = pd.to_numeric(df['momentum_per_day'], errors='coerce')
    elif 'mom_per_day' in df.columns:
        momentum_per_day = pd.to_numeric(df['mom_per_day'], errors='coerce')
    elif {'spread_type', 'ID'}.issubset(df.columns):
        try:
            from curves.refreshers.alpha import load_historical_spread_series

            dir_input = _get_input_dir()
            # Only compute momentum for non-MR rows (keeps IO smaller).
            df_tc = df.loc[~is_mr, ['spread_type', 'ID']].copy()
            for stype, grp in df_tc.groupby('spread_type'):
                ids = grp['ID'].astype(str).tolist()
                series_map = load_historical_spread_series(
                    str(stype),
                    ids,
                    dir_input=dir_input,
                    lookback_days=max(252, mom_window_i + 5),
                )
                for row_idx, cid in grp['ID'].astype(str).items():
                    s = series_map.get(f"{stype}|{cid}")
                    if isinstance(s, pd.Series) and len(s) > mom_window_i:
                        try:
                            # Average bp/day over the window
                            mom_val = float(pd.to_numeric(s, errors='coerce').diff(mom_window_i).dropna().iloc[-1]) / float(mom_window_i)
                            momentum_per_day.at[row_idx] = mom_val  # type: ignore[index]
                        except Exception:
                            continue
        except Exception:
            pass

    df['momentum_per_day'] = momentum_per_day

    # ---------------------------------------------------------------------
    # Expected move per day
    # ---------------------------------------------------------------------
    # ---------------------------------------------------------------------
    # Direction for scoring
    # ---------------------------------------------------------------------
    # For MR, direction comes from mean-reversion (z-score sign).
    # For Carry/Trend, use momentum-implied direction when available.
    direction_in = (
        df['direction'].astype(str).str.strip().str.upper()
        if 'direction' in df.columns
        else pd.Series('', index=df.index, dtype=str)
    )

    # MR direction convention for spreads in this app:
    #   z > 0 => BUY spread
    #   z < 0 => SELL spread
    # For MR rows we always derive this from Zscore to avoid carrying forward any stale/mismatched UI direction.
    z = pd.to_numeric(df['Zscore'], errors='coerce') if 'Zscore' in df.columns else pd.Series(np.nan, index=df.index)
    mr_dir = pd.Series('SELL', index=df.index, dtype=str)
    mr_dir.loc[z.gt(0)] = 'BUY'

    # TC direction: prefer momentum sign if available, else keep provided
    tc_dir = direction_in.copy()
    mom = momentum_per_day
    tc_dir = tc_dir.where(~(tc_dir.eq('') & mom.gt(0)), 'BUY')
    tc_dir = tc_dir.where(~(tc_dir.eq('') & mom.lt(0)), 'SELL')

    direction_score = tc_dir.where(~is_mr, mr_dir)
    df['direction_score'] = direction_score

    dir_sign = pd.Series(1.0, index=df.index, dtype=float)
    dir_sign.loc[direction_score.eq('SELL')] = -1.0
    df['dir_sign_score'] = dir_sign

    # MR expected PnL per day (directional):
    # Our trading convention uses direction derived from Zscore sign:
    #   z > 0 => BUY action (buy leg1 / sell leg2)
    #   z < 0 => SELL action (sell leg1 / buy leg2)
    # In this setup the stored spread series is typically leg2-leg1, so BUY action corresponds
    # to being short the stored spread. Therefore expected PnL per day from mean reversion is:
    #   expected_pnl_mr ≈ dir_sign * (spread - mean) / halflife
    # and carry_roll is a BUY-side PnL (3m, bp), so SELL flips its sign via dir_sign.
    hl = halflife.replace(0, np.nan).abs()
    mr_reversion_pnl_per_day = ((spread - mean) / hl).replace([np.inf, -np.inf], np.nan)
    expected_mr = (dir_sign * mr_reversion_pnl_per_day).fillna(0.0) + (carry_per_day.fillna(0.0) * dir_sign)

    # Carry/Trend: carry_per_day + k * momentum_per_day, aligned to scoring direction.
    tc_raw = carry_per_day.fillna(0.0) + (mom_k_f * momentum_per_day.fillna(0.0))

    # Trend confirmation: if momentum exists, require it to agree with direction.
    # This avoids ranking trades where direction is not confirmed by recent move.
    trend_confirm = pd.Series(1.0, index=df.index, dtype=float)
    has_mom = momentum_per_day.notna() & (momentum_per_day.abs() > 0)
    trend_confirm.loc[has_mom] = (momentum_per_day.loc[has_mom] * dir_sign.loc[has_mom] > 0).astype(float)
    df['trend_confirm'] = trend_confirm

    expected_tc = tc_raw * dir_sign * trend_confirm

    expected_move_per_day = expected_tc.where(~is_mr, expected_mr)
    df['expected_move_per_day'] = expected_move_per_day

    # Edge and score
    edge = expected_move_per_day.fillna(0.0)
    df['edge'] = edge
    df['risk'] = risk
    df['composite_score'] = (edge / risk).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=0.0)
    return df


def select_diversified_trades(
    candidates: List[Dict],
    max_trades: int = 10,
) -> List[Dict]:
    """Select diversified trades using greedy low-correlation selection.
    
    Prioritizes high-quality trades (high score, good risk metrics) while
    minimizing correlation between selected trades.
    """
    if not candidates or len(candidates) == 0:
        return []
    
    # Convert to DataFrame for easier manipulation
    df = pd.DataFrame(candidates)
    
    # Filter for quality: must have valid score, vol, and zscore
    df = df[
        (df.get('composite_score', pd.Series([0] * len(df))) > 0) &
        (df.get('vol', pd.Series([np.nan] * len(df))).notna()) &
        (df.get('Zscore', pd.Series([np.nan] * len(df))).notna())
    ].copy()
    
    if len(df) == 0:
        return []
    
    # Sort by composite_score (or score if available)
    score_col = 'composite_score' if 'composite_score' in df.columns else 'score'
    if score_col in df.columns:
        df = df.sort_values(score_col, ascending=False)
    
    # Simple greedy diversification: alternate between spread types and styles
    selected = []
    seen_types = set()
    seen_styles = set()
    
    # First pass: one from each spread_type
    for _, row in df.iterrows():
        if len(selected) >= max_trades:
            break
        spread_type = row.get('spread_type', '')
        if spread_type not in seen_types:
            selected.append(row.to_dict())
            seen_types.add(spread_type)
    
    # Second pass: fill remaining slots with highest scoring
    for _, row in df.iterrows():
        if len(selected) >= max_trades:
            break
        if row.to_dict() not in selected:
            selected.append(row.to_dict())
    
    return selected[:max_trades]


def build_diversified_trades_display(trades: List[Dict]) -> html.Div:
    """Build display for diversified trade recommendations."""
    if not trades or len(trades) == 0:
        return html.Div(
            "No diversified trades available. Run scan to generate recommendations.",
            style={'color': THEME['text_sub'], 'fontSize': '12px', 'padding': '10px'}
        )
    
    # Group by spread type for summary
    type_counts = {}
    for trade in trades:
        t_type = trade.get('spread_type', 'Other')
        type_counts[t_type] = type_counts.get(t_type, 0) + 1
    
    summary_items = []
    for t_type, count in sorted(type_counts.items()):
        summary_items.append(
            html.Span(
                f"{count} {t_type}",
                style={
                    'backgroundColor': THEME['bg_input'],
                    'padding': '4px 10px',
                    'borderRadius': '3px',
                    'marginRight': '8px',
                    'fontSize': '11px',
                    'display': 'inline-block',
                    'marginBottom': '5px',
                }
            )
        )
    
    # Build trade list
    trade_items = []
    for i, trade in enumerate(trades[:10], 1):
        trade_id = trade.get('ID', 'N/A')
        spread_type = trade.get('spread_type', 'N/A')
        style = trade.get('style', 'N/A')
        direction = trade.get('direction', 'N/A')
        zscore = trade.get('Zscore', 0)
        score = trade.get('composite_score', trade.get('score', 0))
        
        dir_color = THEME['success'] if direction == 'BUY' else THEME['danger']
        
        trade_items.append(
            html.Div([
                html.Span(f"{i}. ", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginRight': '5px'}),
                html.Span(f"{trade_id}", style={'color': THEME['text_main'], 'fontWeight': 'bold', 'marginRight': '8px'}),
                html.Span(f"[{spread_type}]", style={'color': THEME['accent'], 'fontSize': '11px', 'marginRight': '8px'}),
                html.Span(f"{style}", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginRight': '8px'}),
                html.Span(f"{direction}", style={'color': dir_color, 'fontWeight': 'bold', 'fontSize': '11px', 'marginRight': '8px'}),
                html.Span(f"Z={zscore:.2f}", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginRight': '8px'}),
                html.Span(f"Score={score:.2f}", style={'color': THEME['success'] if score > 0 else THEME['text_sub'], 'fontSize': '11px'}),
            ], style={'marginBottom': '6px'})
        )
    
    return html.Div([
        html.P(
            f"Based on scan results, {len(trades)} diversified trades are recommended:",
            style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginBottom': '10px'}
        ),
        html.Div(summary_items, style={'marginBottom': '12px'}),
        html.Div(
            trade_items,
            style={
                'backgroundColor': THEME['bg_input'],
                'padding': '10px',
                'borderRadius': '4px',
                'maxHeight': '250px',
                'overflowY': 'auto'
            }
        ),
    ])


# ---------------------------------------------------------------------------
# Layout Builders
# ---------------------------------------------------------------------------

def build_candidates_layout() -> html.Div:
    """Build the CANDIDATES subtab layout."""
    
    return html.Div([
        # Header
        html.H6("Alpha Candidates Scanner", style={'color': THEME['text_main'], 'marginBottom': '15px'}),
        html.P(
            "Scan for relative value opportunities across spread types. "
            "Filter by z-score deviation and check correlations before sizing.",
            style={'color': THEME['text_sub'], 'fontSize': '13px', 'marginBottom': '20px'}
        ),
        
        # Controls Row 1: Spread Selection
        html.Div([
            html.Div([
                html.Label("Spread Categories:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginBottom': '8px', 'display': 'block'}),
                dcc.Checklist(
                    id='alpha-spread-categories',
                    options=[
                        {'label': ' Bond-Curve (MR)', 'value': 'Bond-Curve'},
                        {'label': ' Bond-Swap (Carry/Trend)', 'value': 'Bond-Swap'},
                        {'label': ' Swap Spreads (MR/Carry)', 'value': 'Swap-Spread'},
                        {'label': ' Tenor Spreads (MR)', 'value': 'Tenor-Spread'},
                        {'label': ' Net Basis (Carry)', 'value': 'Bond-Futures'},
                        {'label': ' Term Basis (MR)', 'value': 'Futures-Term'},
                    ],
                    value=['Bond-Curve', 'Bond-Swap', 'Tenor-Spread'],
                    inline=True,
                    labelStyle={'color': THEME['text_main'], 'marginRight': '15px', 'fontSize': '12px'},
                    inputStyle={'marginRight': '5px'},
                ),
            ], style={'flex': '1'}),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}),
        
        # Controls Row 2: Filters
        html.Div([
            # Z-score threshold
            html.Div([
                html.Label("Z-Score Entry Threshold:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                dcc.Slider(
                    id='alpha-zscore-threshold',
                    min=1.0,
                    max=3.5,
                    step=0.25,
                    value=2.0,
                    marks={i: f'{i:.1f}σ' for i in [1.0, 1.5, 2.0, 2.5, 3.0, 3.5]},
                    tooltip={'placement': 'bottom', 'always_visible': False},
                ),
            ], style={'flex': '1', 'marginRight': '30px'}),
            
            # Direction filter
            html.Div([
                html.Label("Direction:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                dcc.RadioItems(
                    id='alpha-direction-filter',
                    options=[
                        {'label': ' All', 'value': 'all'},
                        {'label': ' BUY (z < -thd)', 'value': 'buy'},
                        {'label': ' SELL (z > +thd)', 'value': 'sell'},
                    ],
                    value='all',
                    inline=True,
                    labelStyle={'color': THEME['text_main'], 'marginRight': '15px', 'fontSize': '12px'},
                ),
            ], style={'flex': '1'}),
        ], style={'display': 'flex', 'alignItems': 'center', 'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}),
        
        # Scan Button
        html.Div([
            html.Button(
                "🔍 Scan Candidates",
                id='alpha-scan-btn',
                n_clicks=0,
                style={
                    'backgroundColor': THEME['accent'],
                    'color': 'white',
                    'padding': '10px 25px',
                    'border': 'none',
                    'borderRadius': '4px',
                    'cursor': 'pointer',
                    'fontWeight': 'bold',
                    'fontSize': '14px',
                    'marginRight': '15px',
                }
            ),
            html.Span(id='alpha-scan-status', style={'color': THEME['text_sub'], 'fontSize': '12px'}),
        ], style={'marginBottom': '20px'}),
        
        # Results Table
        html.Div([
            html.H6("Candidates", style={'color': THEME['text_main'], 'marginBottom': '10px'}),
            dcc.Loading(
                id='loading-candidates',
                type='default',
                children=html.Div(id='alpha-candidates-table-container'),
            ),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '20px'}),
        
        # Correlation Analysis Section
        html.Div([
            html.H6("Correlation Check", style={'color': THEME['text_main'], 'marginBottom': '10px'}),
            html.P(
                "Verify selected candidates have low correlation before adding to basket.",
                style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginBottom': '15px'}
            ),
            
            html.Div([
                html.Label("Lookback:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                dcc.Dropdown(
                    id='alpha-corr-lookback',
                    options=[
                        {'label': '3 Months', 'value': 63},
                        {'label': '6 Months', 'value': 126},
                        {'label': '1 Year', 'value': 252},
                        {'label': '2 Years', 'value': 504},
                    ],
                    value=252,
                    clearable=False,
                    style={'width': '140px', 'marginRight': '20px'},
                ),
                html.Label("Max |Corr|:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                dcc.Dropdown(
                    id='alpha-max-corr',
                    options=[
                        {'label': '0.3', 'value': 0.3},
                        {'label': '0.4', 'value': 0.4},
                        {'label': '0.5', 'value': 0.5},
                        {'label': '0.6', 'value': 0.6},
                        {'label': '0.7', 'value': 0.7},
                    ],
                    value=0.5,
                    clearable=False,
                    style={'width': '100px', 'marginRight': '20px'},
                ),
                html.Button(
                    "📊 Check Correlation",
                    id='alpha-corr-btn',
                    n_clicks=0,
                    style={
                        'backgroundColor': THEME['warning'],
                        'color': 'white',
                        'padding': '8px 15px',
                        'border': 'none',
                        'borderRadius': '4px',
                        'cursor': 'pointer',
                        'fontWeight': 'bold',
                    }
                ),
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '15px'}),
            
            dcc.Loading(
                id='loading-corr',
                type='default',
                children=html.Div(id='alpha-corr-results'),
            ),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px'}),
        
        # Diversified Trade Recommendation Panel
        html.Div([
            html.Hr(style={'borderColor': THEME['text_sub'], 'margin': '20px 0'}),
            html.H6("📊 Diversified Trade Recommendation", style={'color': THEME['success'], 'marginBottom': '10px'}),
            html.P(
                "Select top N trades from the Lowest Correlation Pairs (from Correlation Check above).",
                style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '10px'}
            ),
            html.Div([
                html.Label("Number of trades (N):", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                dcc.Input(
                    id='alpha-diversified-n',
                    type='number',
                    value=10,
                    min=1,
                    max=50,
                    step=1,
                    style={'width': '80px', 'marginRight': '20px', 'padding': '5px', 'borderRadius': '4px'}
                ),
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '10px'}),
            html.Div(id='alpha-diversified-trades-display'),
            html.Div([
                html.Button(
                    "🔄 Replace Strategy Pool with Selected Trades",
                    id='alpha-replace-pool-btn',
                    n_clicks=0,
                    style={
                        'backgroundColor': THEME['success'],
                        'color': 'white',
                        'padding': '10px 25px',
                        'border': 'none',
                        'borderRadius': '5px',
                        'cursor': 'pointer',
                        'fontWeight': 'bold',
                        'fontSize': '14px',
                        'marginTop': '10px',
                    }
                ),
                html.Span(
                    id='alpha-replace-pool-status',
                    style={'marginLeft': '15px', 'color': THEME['text_sub'], 'fontSize': '12px'}
                ),
            ]),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginTop': '15px'}),
        
        # Hidden stores for correlation data
        dcc.Store(id='alpha-corr-pairs-store', data=[]),
        
    ], style={'padding': '10px'})


def build_portfolio_layout() -> html.Div:
    """Build the PORTFOLIO subtab layout."""
    
    return html.Div([
        # Configuration Panel
        html.Div([
            html.Div([
                html.H5("Configuration", style={'margin': '0', 'color': THEME['text_main'], 'fontSize': '16px'}),
            ], style={'flex': '1'}),
            
            html.Div([
                html.Label("Total Capital:", style={'fontWeight': 'bold', 'marginRight': '10px', 'fontSize': '14px', 'color': THEME['text_main']}),
                dcc.Input(
                    id='alpha-total-capital',
                    type='number',
                    value=10,
                    min=1,
                    style={'width': '100px', 'marginRight': '5px', 'padding': '5px', 'borderRadius': '4px', 'border': '1px solid #444', 'backgroundColor': '#fff', 'color': '#000'}
                ),
                html.Span("Billion CNY", style={'color': THEME['text_sub'], 'fontSize': '14px', 'marginRight': '20px'}),
                
                html.Label("Max DV01 per Trade:", style={'fontWeight': 'bold', 'marginRight': '10px', 'fontSize': '14px', 'color': THEME['text_main']}),
                dcc.Input(
                    id='alpha-max-dv01',
                    type='number',
                    value=5,
                    min=1,
                    step=1,
                    style={'width': '120px', 'marginRight': '5px', 'padding': '5px', 'borderRadius': '4px', 'border': '1px solid #444', 'backgroundColor': '#fff', 'color': '#000'}
                ),
                html.Span("Million CNY", style={'color': THEME['text_sub'], 'fontSize': '14px', 'marginRight': '20px'}),
                
                html.Label("Method:", style={'fontWeight': 'bold', 'marginRight': '10px', 'fontSize': '14px', 'color': THEME['text_main']}),
                html.Span("Risk Parity", style={'color': THEME['accent'], 'fontSize': '14px', 'fontWeight': 'bold'}),
            ], style={'display': 'flex', 'alignItems': 'center'}),
        ], style={'display': 'flex', 'alignItems': 'center', 'padding': '15px 20px', 'backgroundColor': THEME['bg_input'], 'borderBottom': f'1px solid {THEME["table_header"]}', 'borderRadius': '8px 8px 0 0', 'marginBottom': '20px'}),
        
        # Hidden inputs for removed features (keep for callback compatibility)
        html.Div([
            dcc.Input(id='alpha-mom-k', type='number', value=1.0, style={'display': 'none'}),
            dcc.Input(id='alpha-mom-window', type='number', value=20, style={'display': 'none'}),
            dcc.Input(id='alpha-alloc-method', type='text', value='risk_parity', style={'display': 'none'}),
            dcc.Checklist(id='alpha-enforce-corr', options=[], value=[], style={'display': 'none'}),
        ], style={'display': 'none'}),
        
        # Portfolio Allocation Results
        html.Div([
            html.Div([
                html.H4("Portfolio Allocation Results", style={'color': THEME['text_main'], 'marginBottom': '15px', 'flex': '1'}),
                html.Div([
                    html.Button(
                        'RUN OPTIMIZATION',
                        id='alpha-score-btn',
                        n_clicks=0,
                        style={'backgroundColor': THEME['accent'], 'color': 'white', 'padding': '8px 20px', 'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer', 'fontSize': '14px', 'fontWeight': 'bold'}
                    ),
                ], style={'marginLeft': '20px'})
            ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between'}),
            
            # Current Strategy Pool Display
            html.Div([
                html.Div(id='alpha-pool-status', style={'fontSize': '13px', 'color': THEME['text_sub'], 'marginBottom': '10px'}),
                html.Div(id='alpha-pool-preview', style={'fontSize': '11px', 'color': THEME['text_main']}),
            ], style={'marginBottom': '15px', 'padding': '10px', 'backgroundColor': THEME['bg_input'], 'borderRadius': '4px'}),
            
            html.Div([
                html.Div(id='alpha-score-status', style={'fontSize': '13px', 'color': THEME['text_main'], 'marginRight': '20px'}),
                html.Div(id='alpha-portfolio-summary', style={'color': THEME['text_sub'], 'fontSize': '11px'})
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '15px', 'justifyContent': 'flex-end'}),

            dcc.Loading(
                id='loading-portfolio',
                type='default',
                children=[
                    html.Div(id='alpha-scored-table-container'),
                    html.Div(id='alpha-risk-chart-container', style={'marginTop': '20px'}),
                ]
            )
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'marginBottom': '20px', 'borderRadius': '5px'}),
        
    ], style={'padding': '10px'})


# ---------------------------------------------------------------------------
# Callback Registration
# ---------------------------------------------------------------------------

def register_alpha_callbacks(app) -> None:
    """Register all callbacks for the Alpha Book tabs."""
    
    # -------------------------------------------------------------------------
    # CANDIDATES: Scan Button
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('alpha-candidates-table-container', 'children'),
         Output('alpha-scan-status', 'children'),
         Output('alpha-selected-candidates', 'data'),
         Output('alpha-diversified-trades-display', 'children')],
        Input('alpha-scan-btn', 'n_clicks'),
        [State('alpha-spread-categories', 'value'),
         State('alpha-zscore-threshold', 'value'),
         State('alpha-direction-filter', 'value')],
        prevent_initial_call=True
    )
    def scan_candidates(n_clicks, categories, zscore_thd, direction):
        if not n_clicks or not categories:
            return html.Div("Select spread categories and click Scan.", style={'color': THEME['text_sub']}), "", [], html.Div()

        try:
            z_thd = float(zscore_thd) if zscore_thd is not None else float(ZSCORE_ENTRY_THRESHOLD)
        except Exception:
            z_thd = float(ZSCORE_ENTRY_THRESHOLD)

        # Use generator-side filtering so we cap to 20 MR + 20 Carry/Trend,
        # enforce stationary==YES for MeanReversion, and compute correlations.
        try:
            from curves.refreshers.alpha import load_alpha_candidates

            obj = load_alpha_candidates(
                dir_input=_get_input_dir(),
                refresh=True,
                allowed_categories=categories,
                zscore_threshold=z_thd,
                max_per_style=20,
                lookback_days=252,
                max_abs_corr=0.6,
                top_n_low_corr=10,
            )
            df_all = obj.get('candidates')
            df_low = obj.get('selected_lowcorr')
            if isinstance(df_all, pd.DataFrame) and not df_all.empty:
                pass
            else:
                df_all = pd.DataFrame()
            if not isinstance(df_low, pd.DataFrame):
                df_low = pd.DataFrame()
        except Exception:
            df_all = pd.DataFrame()
            df_low = pd.DataFrame()

        scanned_time = datetime.now().strftime('%H:%M:%S')

        if df_all.empty:
            return (
                html.Div(
                    f"No candidates found (MR requires stationary=YES, zscore≥{z_thd:g}).",
                    style={'color': THEME['warning']},
                ),
                f"Scanned at {scanned_time}",
                [],
                html.Div()
            )

        # Direction filter (applied after generator selection)
        # Mean-reversion convention for this app:
        #   z > +thd => BUY spread
        #   z < -thd => SELL spread
        # Apply this filter only to MR rows (carry/trend direction is not derived from z-score).
        if 'Zscore' in df_all.columns and 'style' in df_all.columns:
            style_s = df_all['style'].astype(str).str.strip().str.lower()
            is_mr_row = style_s.eq('meanreversion')
            if direction == 'buy':
                df_all = df_all[(~is_mr_row) | (df_all['Zscore'] >= z_thd)].copy()
            elif direction == 'sell':
                df_all = df_all[(~is_mr_row) | (df_all['Zscore'] <= -z_thd)].copy()

        if df_all.empty:
            return (
                html.Div(
                    f"Candidates exist, but none match direction filter at zscore≥{z_thd:g}.",
                    style={'color': THEME['warning']},
                ),
                f"Scanned at {scanned_time}",
                [],
                html.Div()
            )

        # Add direction label (only if not provided by generator)
        # MR convention here: z>0 => BUY, z<0 => SELL.
        if 'direction' not in df_all.columns and 'Zscore' in df_all.columns:
            df_all = df_all.copy()
            df_all['direction'] = df_all['Zscore'].apply(lambda z: 'BUY' if float(z) > 0 else 'SELL')

        # Ensure a single canonical ranking column.
        # Prefer generator-provided unified `score`; fall back to UI preview if needed.
        if 'score' not in df_all.columns:
            df_all = compute_scan_score(df_all)
            if 'composite_score_preview' in df_all.columns:
                df_all = df_all.copy()
                df_all['score'] = pd.to_numeric(df_all['composite_score_preview'], errors='coerce')

        # Sort by score if present (generator score takes priority, else use preview)
        if 'score' in df_all.columns:
            df_all = df_all.sort_values('score', ascending=False)
        elif 'abs_zscore' in df_all.columns:
            df_all = df_all.sort_values('abs_zscore', ascending=False)

        # Display columns
        display_cols = [
            'ID', 'spread_type', 'category', 'style', 'direction',
            'Zscore', 'spread', 'mean', 'vol', 'carry_roll', 'halflife', 'stationary',
            'score', 'selected_lowcorr'
        ]
        df_display = df_all.copy()
        if 'ID' not in df_display.columns and df_display.index.name == 'ID':
            df_display = df_display.reset_index()
        available_cols = [c for c in display_cols if c in df_display.columns]
        df_display = df_display[available_cols].copy()

        for col in ['Zscore', 'spread', 'mean', 'vol', 'carry_roll', 'halflife', 'score']:
            if col in df_display.columns:
                df_display[col] = pd.to_numeric(df_display[col], errors='coerce').round(3)

        # Split candidates into MR and Trend/Carry
        df_mr = pd.DataFrame()
        df_trend = pd.DataFrame()

        style_summary_div = html.Div()
        if 'style' in df_display.columns:
            style_counts = df_display['style'].astype(str).str.strip().value_counts(dropna=False)
            style_summary = ', '.join([f"{k}: {int(v)}" for k, v in style_counts.items()])
            style_summary_div = html.Div(
                f"Styles found: {style_summary}",
                style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '8px'},
            )

            df_mr = df_display[df_display['style'].astype(str).str.lower().eq('meanreversion')].copy()
            df_trend = df_display[df_display['style'].astype(str).str.lower().isin(['carry', 'trend', 'trendfollowing'])].copy()

        # Shared table styling
        _table_style_table = {'overflowX': 'auto', 'maxHeight': '300px', 'overflowY': 'auto'}
        _table_style_header = {
            'backgroundColor': THEME['table_header'],
            'color': THEME['text_main'],
            'fontWeight': 'bold',
            'textAlign': 'left',
        }
        _table_style_cell = {
            'backgroundColor': THEME['bg_card'],
            'color': THEME['text_main'],
            'textAlign': 'left',
            'padding': '8px',
            'fontSize': '12px',
        }
        _table_style_data_conditional = [  # type: ignore[arg-type]
            {'if': {'filter_query': '{direction} = "BUY"'}, 'backgroundColor': 'rgba(0, 204, 150, 0.15)'},
            {'if': {'filter_query': '{direction} = "SELL"'}, 'backgroundColor': 'rgba(239, 85, 59, 0.15)'},
            {'if': {'filter_query': '{selected_lowcorr} = True'}, 'backgroundColor': 'rgba(52, 152, 219, 0.18)'},
            {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['table_row_odd']},
        ]

        # MR candidates table (always render; show empty-state when none)
        mr_body = html.Div(
            "No mean-reversion candidates under current filters.",
            style={'color': THEME['text_sub'], 'fontSize': '12px', 'padding': '8px'},
        )
        if not df_mr.empty:
            mr_body = dash_table.DataTable(
                id='alpha-candidates-table-mr',
                columns=[{'name': c, 'id': c} for c in df_mr.columns],
                data=df_mr.head(20).to_dict('records'),  # type: ignore[arg-type]
                row_selectable='multi',
                selected_rows=[],
                style_table=_table_style_table,
                style_header=_table_style_header,
                style_cell=_table_style_cell,
                style_data_conditional=_table_style_data_conditional,  # type: ignore[arg-type]
                page_size=20,
                sort_action='native',
                filter_action='native',
            )

        table_mr = html.Div(
            [
                html.H6(
                    f"Mean-Reversion Candidates (max 20) - {len(df_mr)} found",
                    style={'color': THEME['text_main'], 'marginBottom': '8px'},
                ),
                style_summary_div,
                mr_body,
            ],
            style={'marginBottom': '20px'},
        )

        # Trend/Carry candidates table (always render; show empty-state when none)
        trend_body = html.Div(
            "No carry/trend candidates under current filters.",
            style={'color': THEME['text_sub'], 'fontSize': '12px', 'padding': '8px'},
        )
        if not df_trend.empty:
            trend_body = dash_table.DataTable(
                id='alpha-candidates-table-trend',
                columns=[{'name': c, 'id': c} for c in df_trend.columns],
                data=df_trend.head(20).to_dict('records'),  # type: ignore[arg-type]
                row_selectable='multi',
                selected_rows=[],
                style_table=_table_style_table,
                style_header=_table_style_header,
                style_cell=_table_style_cell,
                style_data_conditional=_table_style_data_conditional,  # type: ignore[arg-type]
                page_size=20,
                sort_action='native',
                filter_action='native',
            )

        table_trend = html.Div(
            [
                html.H6(
                    f"Carry/Trend Candidates (max 20) - {len(df_trend)} found",
                    style={'color': THEME['text_main'], 'marginBottom': '8px'},
                ),
                style_summary_div,
                trend_body,
            ],
            style={'marginBottom': '20px'},
        )

        # Low-correlation top-10 table (if available)
        low_corr_div = html.Div()
        if isinstance(df_low, pd.DataFrame) and not df_low.empty:
            df_low_disp = df_low.copy()
            if 'ID' not in df_low_disp.columns and df_low_disp.index.name == 'ID':
                df_low_disp = df_low_disp.reset_index()
            low_cols = [c for c in ['basket_rank', 'ID', 'spread_type', 'category', 'style', 'Zscore', 'carry_roll', 'score'] if c in df_low_disp.columns]
            df_low_disp = df_low_disp[low_cols].copy()
            for col in ['Zscore', 'carry_roll', 'score']:
                if col in df_low_disp.columns:
                    df_low_disp[col] = pd.to_numeric(df_low_disp[col], errors='coerce').round(3)

            low_table = dash_table.DataTable(
                id='alpha-lowcorr-table',
                columns=[{'name': c, 'id': c} for c in df_low_disp.columns],
                data=df_low_disp.to_dict('records'),  # type: ignore[arg-type]
                style_table={'overflowX': 'auto', 'maxHeight': '220px', 'overflowY': 'auto'},
                style_header={
                    'backgroundColor': THEME['table_header'],
                    'color': THEME['text_main'],
                    'fontWeight': 'bold',
                },
                style_cell={
                    'backgroundColor': THEME['bg_card'],
                    'color': THEME['text_main'],
                    'fontSize': '11px',
                    'padding': '6px',
                },
                page_size=10,
            )
            low_corr_div = html.Div([
                html.H6('Recommended Low-Correlation Top 10', style={'color': THEME['text_main'], 'marginBottom': '8px'}),
                html.Div('Greedy selection using spread-change correlations (lookback 252d).', style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '8px'}),
                low_table,
            ], style={'marginBottom': '15px'})

        table_out = html.Div([
            low_corr_div,
            table_mr,
            table_trend,
        ])

        status = f"Found {len(df_all)} candidates at {scanned_time}"

        candidate_data = df_display.to_dict('records')
        
        # Build diversified trades display (shows recommended low-correlation trades)
        diversified_display = html.Div()
        if isinstance(df_low, pd.DataFrame) and not df_low.empty:
            # Add direction column to df_low if not present
            df_low_enriched = df_low.copy()
            if 'direction' not in df_low_enriched.columns and 'Zscore' in df_low_enriched.columns:
                df_low_enriched['direction'] = df_low_enriched['Zscore'].apply(lambda z: 'BUY' if float(z) < 0 else 'SELL')
            
            # Store recommended trades in global variable for "Replace Pool" button
            DIVERSIFIED_TRADE_RECOMMENDATIONS['trades'] = df_low_enriched.to_dict('records')
            DIVERSIFIED_TRADE_RECOMMENDATIONS['timestamp'] = datetime.now()
            
            trade_items = []
            for idx, row in df_low_enriched.iterrows():
                trade_id = row.get('ID', idx)
                spread_type = row.get('spread_type', 'N/A')
                style = row.get('style', 'N/A')
                zscore = row.get('Zscore', 0)
                direction = row.get('direction', 'N/A')
                dir_color = THEME['success'] if direction == 'BUY' else THEME['danger']
                trade_items.append(
                    html.Div([
                        html.Span(f"• {trade_id} ({spread_type} - {style}) ", style={'color': THEME['text_main']}),
                        html.Span(f"{direction}", style={'color': dir_color, 'fontWeight': 'bold'}),
                        html.Span(f" | Z={zscore:.2f}", style={'color': THEME['text_main']}),
                    ], style={'fontSize': '11px', 'padding': '2px 0'})
                )
            
            diversified_display = html.Div([
                html.Div(
                    f"✓ {len(df_low_enriched)} low-correlation trades recommended for diversification",
                    style={'color': THEME['success'], 'fontWeight': 'bold', 'marginBottom': '8px', 'fontSize': '12px'}
                ),
                html.Div(trade_items, style={'maxHeight': '150px', 'overflowY': 'auto', 'backgroundColor': THEME['bg_input'], 'padding': '8px', 'borderRadius': '4px'})
            ])
        else:
            # No low-correlation trades available
            DIVERSIFIED_TRADE_RECOMMENDATIONS['trades'] = []
            DIVERSIFIED_TRADE_RECOMMENDATIONS['timestamp'] = None
            diversified_display = html.Div(
                "Run scan to generate diversified trade recommendations",
                style={'color': THEME['text_sub'], 'fontSize': '11px', 'fontStyle': 'italic'}
            )
        
        return table_out, status, candidate_data, diversified_display
    
    # -------------------------------------------------------------------------
    # CANDIDATES: Replace Strategy Pool with Diversified Trades
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('alpha-replace-pool-status', 'children'),
         Output('alpha-selected-candidates', 'data', allow_duplicate=True),
         Output('alpha-diversified-trades-display', 'children', allow_duplicate=True)],
        Input('alpha-replace-pool-btn', 'n_clicks'),
        [State('alpha-corr-pairs-store', 'data'),
         State('alpha-diversified-n', 'value'),
         State('alpha-selected-candidates', 'data')],
        prevent_initial_call=True
    )
    def replace_strategy_pool(n_clicks, corr_pairs_data, n_trades, all_candidates):
        """Replace the strategy pool with top N trades from lowest correlation pairs."""
        if not n_clicks or n_clicks == 0:
            return "", [], html.Div()
        
        # Validate inputs
        if not corr_pairs_data or len(corr_pairs_data) == 0:
            return "⚠ No correlation pairs available. Please run 'Check Correlation' first.", [], html.Div(
                "Run 'Check Correlation' to generate low-correlation pairs.",
                style={'color': THEME['text_sub'], 'fontSize': '11px', 'fontStyle': 'italic'}
            )
        
        if not all_candidates or len(all_candidates) == 0:
            return "⚠ No candidates available. Please run scan first.", [], html.Div(
                "Run scan to generate candidates.",
                style={'color': THEME['text_sub'], 'fontSize': '11px', 'fontStyle': 'italic'}
            )
        
        try:
            # Get top N pairs
            n = int(n_trades) if n_trades else 10
            top_pairs = corr_pairs_data[:n]
            
            # Extract asset names from pairs
            selected_asset_names = set()
            for pair in top_pairs:
                selected_asset_names.add(pair.get('Asset A', ''))
                selected_asset_names.add(pair.get('Asset B', ''))
            
            # Debug output
            print(f"[DEBUG] Top {n} correlation pairs:")
            print(f"[DEBUG] Selected asset names from pairs: {selected_asset_names}")
            
            # Match with candidates using ID
            df_candidates = pd.DataFrame(all_candidates)
            if 'ID' not in df_candidates.columns:
                return "⚠ Candidate data missing ID column.", [], html.Div()
            
            # Debug output
            print(f"[DEBUG] Candidate IDs available: {set(df_candidates['ID'].tolist())}")
            
            # Filter candidates that are in the selected low-correlation pairs
            selected_trades = []
            for _, row in df_candidates.iterrows():
                trade_id = row.get('ID', '')
                if trade_id in selected_asset_names:
                    trade_dict = row.to_dict()
                    # Ensure direction column exists
                    if 'direction' not in trade_dict and 'Zscore' in trade_dict:
                        zscore = float(trade_dict['Zscore'])
                        trade_dict['direction'] = 'BUY' if zscore < 0 else 'SELL'
                    selected_trades.append(trade_dict)
            
            print(f"[DEBUG] Matched {len(selected_trades)} trades")
            
            if len(selected_trades) == 0:
                return "⚠ No matching trades found in candidates.", [], html.Div(
                    "Could not match correlation pairs to scanned candidates.",
                    style={'color': THEME['warning'], 'fontSize': '11px'}
                )
            
            # Count trades by type for status message
            type_counts = {}
            for trade in selected_trades:
                t_type = trade.get('spread_type', 'Other')
                type_counts[t_type] = type_counts.get(t_type, 0) + 1
            
            type_summary = ", ".join([f"{count} {t}" for t, count in type_counts.items()])
            status_msg = f"✓ Replaced strategy pool with {len(selected_trades)} trades ({type_summary}). Switch to Portfolio tab to allocate capital."
            
            # Build display
            trade_items = []
            for trade in selected_trades:
                trade_id = trade.get('ID', 'N/A')
                spread_type = trade.get('spread_type', 'N/A')
                style = trade.get('style', 'N/A')
                zscore = trade.get('Zscore', 0)
                direction = trade.get('direction', 'N/A')
                dir_color = THEME['success'] if direction == 'BUY' else THEME['danger']
                trade_items.append(
                    html.Div([
                        html.Span(f"• {trade_id} ({spread_type} - {style}) ", style={'color': THEME['text_main']}),
                        html.Span(f"{direction}", style={'color': dir_color, 'fontWeight': 'bold'}),
                        html.Span(f" | Z={zscore:.2f}", style={'color': THEME['text_main']}),
                    ], style={'fontSize': '11px', 'padding': '2px 0'})
                )
            
            diversified_display = html.Div([
                html.Div(
                    f"✓ {len(selected_trades)} low-correlation trades selected from correlation analysis",
                    style={'color': THEME['success'], 'fontWeight': 'bold', 'marginBottom': '8px', 'fontSize': '12px'}
                ),
                html.Div(trade_items, style={'maxHeight': '150px', 'overflowY': 'auto', 'backgroundColor': THEME['bg_input'], 'padding': '8px', 'borderRadius': '4px'})
            ])
            
            return status_msg, selected_trades, diversified_display
            
        except Exception as e:
            print(f"Error replacing strategy pool: {e}")
            import traceback
            traceback.print_exc()
            return f"❌ Error: {str(e)[:50]}", [], html.Div()
    
    # -------------------------------------------------------------------------
    # CANDIDATES: Correlation Check
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('alpha-corr-results', 'children'),
         Output('alpha-corr-pairs-store', 'data')],
        Input('alpha-corr-btn', 'n_clicks'),
        [State('alpha-spread-categories', 'value'),
         State('alpha-corr-lookback', 'value'),
         State('alpha-max-corr', 'value'),
         State('alpha-selected-candidates', 'data')],
        prevent_initial_call=True
    )
    def check_correlation(n_clicks, categories, lookback, max_corr, all_candidates):
        if not n_clicks or not categories:
            return html.Div("Select categories and click Check Correlation.", style={'color': THEME['text_sub']}), []
        
        # If we have scanned candidates, use those for correlation analysis
        if all_candidates and len(all_candidates) > 0:
            df_candidates = pd.DataFrame(all_candidates)
            if 'ID' in df_candidates.columns and 'spread_type' in df_candidates.columns:
                print(f"[DEBUG] Using {len(df_candidates)} scanned candidates for correlation analysis")
                
                # Load time series for each candidate
                all_spreads = {}
                for _, row in df_candidates.iterrows():
                    trade_id = row.get('ID', '')
                    spread_type = row.get('spread_type', '')
                    if not trade_id or not spread_type:
                        continue
                    
                    ts = load_spread_timeseries(spread_type)
                    if ts is not None and isinstance(ts, pd.DataFrame) and trade_id in ts.columns:
                        all_spreads[trade_id] = ts[trade_id]
                
                print(f"[DEBUG] Loaded time series for {len(all_spreads)} candidates")
                
                if len(all_spreads) >= 2:
                    df_spreads = pd.DataFrame(all_spreads).tail(lookback)
                    df_changes = df_spreads.diff().dropna()
                    
                    if len(df_changes) >= 20:
                        corr_matrix = df_changes.corr()
                    else:
                        corr_matrix = None
                else:
                    corr_matrix = None
                
                if corr_matrix is not None and not corr_matrix.empty:
                    # Use candidate-based correlation
                    print(f"[DEBUG] Built correlation matrix from candidates: {corr_matrix.shape}")
                else:
                    # Fall back to category-based
                    print(f"[DEBUG] Insufficient candidate data, falling back to category analysis")
                    corr_matrix = None
            else:
                corr_matrix = None
        else:
            corr_matrix = None
        
        # Fall back to category-based correlation if no candidates available
        if corr_matrix is None:
            # Gather spread types
            spread_types = []
            for cat in categories:
                if cat in SPREAD_CATEGORIES:
                    spread_types.extend(SPREAD_CATEGORIES[cat]['types'])
            
            if len(spread_types) == 0:
                return html.Div("No spread types selected.", style={'color': THEME['warning']}), []
            
            # First try to load pre-computed correlation from Alpha-candidates.pkl
            dir_input = _get_input_dir()
            candidates_data = _load_pickle_safe(dir_input / 'Alpha-candidates.pkl')
            
            if candidates_data and isinstance(candidates_data, dict):
                corr_matrix = candidates_data.get('corr')
                print(f"[DEBUG] Loaded correlation from Alpha-candidates.pkl: {type(corr_matrix)}, shape: {corr_matrix.shape if isinstance(corr_matrix, pd.DataFrame) else 'N/A'}")
            
            # Fall back to computing correlation if not available
            if corr_matrix is None or not isinstance(corr_matrix, pd.DataFrame) or corr_matrix.empty:
                print(f"[DEBUG] Computing correlation for spread_types: {spread_types}")
                corr_matrix, _ = compute_spread_correlation(spread_types, lookback_days=lookback)
        
        if corr_matrix is None or corr_matrix.empty:
            return html.Div("Insufficient data for correlation analysis. Need at least 2 instruments with historical data.", style={'color': THEME['warning']}), []
        
        # Rank low correlation pairs
        low_corr_pairs = rank_low_correlation_pairs(corr_matrix, top_n=15)
        
        # Find high correlation pairs (potential duplicates)
        high_corr = low_corr_pairs[low_corr_pairs['AbsCorr'] > max_corr]
        
        # Build heatmap
        # Limit to top assets from low-corr pairs
        top_assets = set(low_corr_pairs['Asset A'].head(10)).union(set(low_corr_pairs['Asset B'].head(10)))
        top_assets = sorted(list(top_assets))[:12]  # Limit for readability
        
        if len(top_assets) >= 2:
            sub_corr = corr_matrix.loc[top_assets, top_assets]
            
            # Mask upper triangle
            corr_vals = sub_corr.values.copy()
            mask_upper = np.triu(np.ones(corr_vals.shape), k=1).astype(bool)
            corr_vals[mask_upper] = np.nan
            
            heatmap = go.Figure(data=go.Heatmap(
                z=corr_vals,
                x=sub_corr.columns,
                y=sub_corr.index,
                colorscale='RdBu',
                zmin=-1, zmax=1,
                hovertemplate='%{y} vs %{x}<br>Corr: %{z:.3f}<extra></extra>',
            ))
            heatmap.update_layout(
                title='Spread Correlation Matrix (Lower Triangle)',
                height=350,
                margin=dict(l=100, r=20, t=40, b=80),
                plot_bgcolor=THEME['bg_main'],
                paper_bgcolor=THEME['bg_main'],
                font=dict(color=THEME['text_main'], size=10),
                xaxis=dict(tickangle=45),
            )
            
            heatmap_div = dcc.Graph(figure=heatmap, style={'height': '350px'})
        else:
            heatmap_div = html.Div("Not enough assets for heatmap.", style={'color': THEME['text_sub']})
        
        # Low correlation pairs table
        low_corr_pairs['Correlation'] = low_corr_pairs['Correlation'].round(3)
        low_corr_pairs['AbsCorr'] = low_corr_pairs['AbsCorr'].round(3)
        
        pairs_table = dash_table.DataTable(
            columns=[{'name': c, 'id': c} for c in ['Asset A', 'Asset B', 'Correlation', 'AbsCorr']],
            data=low_corr_pairs[['Asset A', 'Asset B', 'Correlation', 'AbsCorr']].to_dict('records'),
            style_table={'overflowX': 'auto', 'maxHeight': '200px'},
            style_header={
                'backgroundColor': THEME['table_header'],
                'color': THEME['text_main'],
                'fontWeight': 'bold',
            },
            style_cell={
                'backgroundColor': THEME['bg_card'],
                'color': THEME['text_main'],
                'fontSize': '11px',
                'padding': '5px',
            },
            style_data_conditional=[
                {
                    'if': {'filter_query': f'{{AbsCorr}} > {max_corr}'},
                    'backgroundColor': 'rgba(239, 85, 59, 0.2)',
                },
            ],
            page_size=10,
        )
        
        # Warning for high correlations
        warning_div = html.Div()
        if len(high_corr) > 0:
            warning_div = html.Div([
                html.P(
                    f"⚠️ {len(high_corr)} pairs exceed max correlation threshold ({max_corr}). "
                    "Consider removing correlated candidates before sizing.",
                    style={'color': THEME['warning'], 'fontSize': '12px', 'marginTop': '10px'}
                )
            ])
        
        # Store pairs data for later use
        pairs_data = low_corr_pairs.to_dict('records') if isinstance(low_corr_pairs, pd.DataFrame) else []
        
        return html.Div([
            heatmap_div,
            html.H6("Lowest Correlation Pairs", style={'color': THEME['text_main'], 'marginTop': '15px', 'marginBottom': '10px'}),
            pairs_table,
            warning_div,
        ]), pairs_data
    
    # -------------------------------------------------------------------------
    # PORTFOLIO: Display Current Strategy Pool
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('alpha-pool-status', 'children'),
         Output('alpha-pool-preview', 'children')],
        [Input('alpha-selected-candidates', 'data'),
         Input('alpha-score-btn', 'n_clicks')], # Trigger on button click too
    )
    def display_strategy_pool(candidates, _): # Ignore button clicks argument
        """Display the current strategy pool content."""
        if not candidates or len(candidates) == 0:
            return (
                "📭 Strategy Pool is empty. Go to CANDIDATES tab and click 'Replace Strategy Pool' button.",
                html.Div()
            )
        
        # Count by type
        df = pd.DataFrame(candidates)
        type_counts = df['spread_type'].value_counts().to_dict() if 'spread_type' in df.columns else {}
        type_summary = ", ".join([f"{count} {t}" for t, count in type_counts.items()])
        
        # Create preview list
        preview_items = []
        for i, row in enumerate(df.head(10).itertuples(), 1):
            trade_id = getattr(row, 'ID', f'Trade {i}')
            spread_type = getattr(row, 'spread_type', 'N/A')
            direction = getattr(row, 'direction', 'N/A')
            zscore = getattr(row, 'Zscore', 0)
            
            dir_color = THEME['success'] if direction == 'BUY' else THEME['danger']
            
            preview_items.append(
                html.Span([
                    html.Span(f"{trade_id}", style={'fontWeight': 'bold', 'marginRight': '5px'}),
                    html.Span(f"({spread_type})", style={'color': THEME['accent'], 'marginRight': '5px'}),
                    html.Span(direction, style={'color': dir_color, 'marginRight': '5px'}),
                    html.Span(f"Z={zscore:.2f}", style={'color': THEME['text_sub']}),
                ], style={'marginRight': '15px', 'display': 'inline-block', 'marginBottom': '5px'})
            )
        
        if len(df) > 10:
            preview_items.append(
                html.Span(f"... +{len(df) - 10} more", style={'color': THEME['text_sub'], 'fontStyle': 'italic'})
            )
        
        status = f"✓ Strategy Pool contains {len(candidates)} trades ({type_summary})"
        
        return status, html.Div(preview_items)
    
    # -------------------------------------------------------------------------
    # PORTFOLIO: Run Scoring & Allocation
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('alpha-scored-table-container', 'children'),
         Output('alpha-risk-chart-container', 'children'),
         Output('alpha-score-status', 'children'),
         Output('alpha-portfolio-summary', 'children')],
        Input('alpha-score-btn', 'n_clicks'),
        [State('alpha-selected-candidates', 'data'),
         State('alpha-mom-k', 'value'),
         State('alpha-mom-window', 'value'),
         State('alpha-total-capital', 'value'),
         State('alpha-max-dv01', 'value'),
         State('alpha-alloc-method', 'value'),
         State('alpha-enforce-corr', 'value')],
        prevent_initial_call=True
    )
    def run_scoring(n_clicks, candidates, mom_k, mom_window, total_capital, max_dv01, alloc_method, enforce_corr):
        
        if not n_clicks:
            return html.Div(), html.Div(), "", html.Div()
        
        if not candidates:
            return (
                html.Div("No candidates. Run scan in Candidates tab first.", style={'color': THEME['warning']}),
                html.Div(),
                "",
                html.Div()
            )
        
        try:
            print(f"[DEBUG] run_scoring: received {len(candidates)} candidates")
            print(f"[DEBUG] total_capital={total_capital}, max_dv01={max_dv01}, alloc_method={alloc_method}")
            
            df = pd.DataFrame(candidates)
            print(f"[DEBUG] df columns: {df.columns.tolist()}")
            
            # Handle None values with defaults
            mom_window = int(mom_window) if mom_window is not None else 20
            mom_k = float(mom_k) if mom_k is not None else 1.0
            total_capital = float(total_capital) if total_capital is not None else 10000.0  # Default 10B
            max_dv01 = float(max_dv01) if max_dv01 is not None else 5000000.0  # Default 5M
            
            # Compute unified weightless scores
            df_scored = compute_unified_edge_vol_score(
                df, 
                mom_window=mom_window, 
                mom_k=mom_k
            )

            df_scored = df_scored.sort_values('composite_score', ascending=False)
            
            # Filter out zero or near-zero score trades (negative expected edge)
            min_score_threshold = 0.001
            df_scored = df_scored[df_scored['composite_score'] > min_score_threshold].copy()
            
            print(f"[DEBUG] After filtering zero-score trades: {len(df_scored)} remaining (threshold={min_score_threshold})")
            
            # Allocation
            n_trades = len(df_scored)
            if n_trades == 0:
                return (
                    html.Div("No candidates with positive expected edge. All trades filtered out (score ≤ 0).", style={'color': THEME['warning']}),
                    html.Div(),
                    "",
                    html.Div()
                )
            
            # Determine allocation method
            alloc_method = alloc_method or 'risk_parity'
            print(f"[DEBUG] Using allocation method: {alloc_method}")
            
            if alloc_method == 'equal':
                df_scored['weight'] = 1 / n_trades
            elif alloc_method == 'score':
                score_sum = df_scored['composite_score'].sum()
                df_scored['weight'] = df_scored['composite_score'] / score_sum if score_sum > 0 else 1 / n_trades
            elif alloc_method == 'inv_vol':
                if 'vol' in df_scored.columns:
                    inv_vol = 1 / df_scored['vol'].replace(0, np.nan).fillna(df_scored['vol'].mean())
                    df_scored['weight'] = inv_vol / inv_vol.sum()
                else:
                    df_scored['weight'] = 1 / n_trades
            else:  # risk_parity (default)
                try:
                    weights_dict, risk_contrib = _compute_risk_parity_weights(df_scored)
                    df_scored['weight'] = df_scored['ID'].map(weights_dict).fillna(0)
                    df_scored['risk_contribution'] = df_scored['ID'].map(dict(zip(df_scored['ID'], risk_contrib))).fillna(0)
                except Exception as e:
                    print(f"⚠ Risk parity optimization failed: {e}, falling back to equal weights")
                    df_scored['weight'] = 1 / n_trades
                    df_scored['risk_contribution'] = 1 / n_trades
            
            # Normalize weights to sum to 1
            weight_sum = df_scored['weight'].sum()
            if weight_sum > 0 and weight_sum != 1.0:
                df_scored['weight'] = df_scored['weight'] / weight_sum
            
            # Calculate notional
            df_scored['notional_mm'] = df_scored['weight'] * total_capital
            
            # Calculate suggested DV01 based on notional and typical bond duration
            # Assume average duration ~ 5 years for bond spreads
            avg_duration = 5.0
            df_scored['suggested_dv01'] = (df_scored['notional_mm'] * 1e6 * avg_duration * 0.0001).clip(upper=max_dv01)
            
            # Select display columns
            display_cols = [
                'ID', 'spread_type', 'style', 'direction',
                'Zscore', 'carry_roll', 'vol',
                'momentum_per_day', 'expected_move_per_day',
                'edge', 'risk', 'composite_score',
                'zscore_score', 'mr_score',
                'weight', 'risk_contribution', 'notional_mm', 'suggested_dv01',
            ]
            available_cols = [c for c in display_cols if c in df_scored.columns]
            
            df_display = df_scored[available_cols].copy()
            
            # Round numeric columns
            for col in df_display.columns:
                if df_display[col].dtype in ['float64', 'float32']:
                    df_display[col] = df_display[col].round(2)
            
            # Build scored table
            # Conditional styling only if direction column exists
            conditional_style = []
            if 'direction' in df_display.columns:
                conditional_style = [
                    {
                        'if': {'filter_query': '{direction} = "BUY"'},
                        'backgroundColor': 'rgba(0, 204, 150, 0.15)',
                    },
                    {
                        'if': {'filter_query': '{direction} = "SELL"'},
                        'backgroundColor': 'rgba(239, 85, 59, 0.15)',
                    },
                ]
            
            table = dash_table.DataTable(
                id='alpha-scored-table',
                columns=[{'name': c, 'id': c} for c in df_display.columns],
                data=df_display.head(30).to_dict('records'),  # type: ignore[arg-type]
                style_table={'overflowX': 'auto', 'maxHeight': '350px', 'overflowY': 'auto'},
                style_header={
                    'backgroundColor': THEME['table_header'],
                    'color': THEME['text_main'],
                    'fontWeight': 'bold',
                    'textAlign': 'left',
                },
                style_cell={
                    'backgroundColor': THEME['bg_card'],
                    'color': THEME['text_main'],
                    'textAlign': 'left',
                    'padding': '8px',
                    'fontSize': '12px',
                },
                style_data_conditional=conditional_style,  # type: ignore[arg-type]
                sort_action='native',
                page_size=15,
            )
            
            status = f"Scored {len(df_scored)} trades at {datetime.now().strftime('%H:%M:%S')}"
            
            # Portfolio summary
            summary = html.Div([
                html.Div([
                    html.Div([
                        html.Strong("Total Trades: ", style={'color': THEME['text_sub']}),
                        html.Span(f"{len(df_scored)}", style={'color': THEME['text_main']}),
                    ], style={'marginRight': '30px'}),
                    html.Div([
                        html.Strong("Capital Allocated: ", style={'color': THEME['text_sub']}),
                        html.Span(f"{total_capital:.1f} MM", style={'color': THEME['text_main']}),
                    ], style={'marginRight': '30px'}),
                    html.Div([
                        html.Strong("Avg Score: ", style={'color': THEME['text_sub']}),
                        html.Span(f"{df_scored['composite_score'].mean():.1f}", style={'color': THEME['text_main']}),
                    ], style={'marginRight': '30px'}),
                    html.Div([
                        html.Strong("Risk Parity: ", style={'color': THEME['text_sub']}),
                        html.Span(
                            f"σ(RC)={df_scored['risk_contribution'].std():.3f}" if 'risk_contribution' in df_scored.columns else "N/A",
                            style={'color': THEME['text_main']}
                        ),
                    ], style={'marginRight': '30px'}),
                    html.Div([
                        html.Strong("BUY/SELL: ", style={'color': THEME['text_sub']}),
                        html.Span(
                            f"{(df_scored['direction'] == 'BUY').sum()} / {(df_scored['direction'] == 'SELL').sum()}" if 'direction' in df_scored.columns else "N/A",
                            style={'color': THEME['text_main']}
                        ),
                    ]),
                ], style={'display': 'flex', 'flexWrap': 'wrap', 'marginBottom': '15px'}),
                
                # Style breakdown
                html.Div([
                    html.Strong("By Style: ", style={'color': THEME['text_sub']}),
                    html.Span(
                        " | ".join([f"{style}: {count}" for style, count in df_scored.groupby('style').size().items()]),
                        style={'color': THEME['text_main'], 'fontSize': '12px'}
                    ) if 'style' in df_scored.columns else "",
                ]),
            ])
            
            # Create risk contribution chart if available
            risk_chart = html.Div()
            if 'risk_contribution' in df_scored.columns and 'weight' in df_scored.columns:
                # Create side-by-side bar charts: Weights vs Risk Contributions
                fig = go.Figure()
                
                # Sort by weight for better visualization
                df_chart = df_scored.nlargest(15, 'weight')[['ID', 'weight', 'risk_contribution']].copy()
                
                fig.add_trace(go.Bar(
                    x=df_chart['ID'],
                    y=df_chart['weight'] * 100,
                    name='Weight (%)',
                    marker_color=THEME['accent'],
                    yaxis='y',
                ))
                
                fig.add_trace(go.Bar(
                    x=df_chart['ID'],
                    y=df_chart['risk_contribution'] * 100,
                    name='Risk Contribution (%)',
                    marker_color=THEME['success'],
                    yaxis='y',
                ))
                
                fig.update_layout(
                    title={
                        'text': 'Portfolio Allocation: Weights vs Risk Contributions',
                        'font': {'size': 14, 'color': THEME['text_main']},
                    },
                    xaxis={'title': 'Trade ID', 'tickangle': -45, 'color': THEME['text_main']},
                    yaxis={'title': 'Percentage (%)', 'color': THEME['text_main']},
                    barmode='group',
                    template='plotly_dark',
                    paper_bgcolor=THEME['bg_card'],
                    plot_bgcolor=THEME['bg_card'],
                    height=400,
                    margin={'l': 60, 'r': 20, 't': 50, 'b': 100},
                    legend={'orientation': 'h', 'y': 1.1, 'x': 0.5, 'xanchor': 'center'},
                )
                
                risk_chart = dcc.Graph(figure=fig, config={'displayModeBar': False})
            
            return table, risk_chart, status, summary
        
        except Exception as e:
            import traceback
            error_msg = f"Error in portfolio optimization: {str(e)}"
            print(f"[ERROR] {error_msg}")
            print(traceback.format_exc())
            return (
                html.Div(error_msg, style={'color': THEME['warning'], 'padding': '10px'}),
                html.Div(),
                f"Error at {datetime.now().strftime('%H:%M:%S')}",
                html.Div(f"Details: {str(e)[:100]}", style={'color': THEME['warning'], 'fontSize': '11px'})
            )

    # -------------------------------------------------------------------------
    # BACKTEST: Mode Tab Selector
    # -------------------------------------------------------------------------
    @app.callback(
        Output('backtest-mode-content', 'children'),
        Input('backtest-mode-tabs', 'value'),
    )
    def render_backtest_mode(mode):
        if mode == 'individual':
            return build_individual_backtest_panel()
        elif mode == 'portfolio':
            return build_portfolio_backtest_panel()
        return html.Div("Select a backtest mode.")

    # -------------------------------------------------------------------------
    # BACKTEST: Populate Instrument Dropdown
    # -------------------------------------------------------------------------
    @app.callback(
        Output('bt-instrument', 'options'),
        Input('bt-spread-type', 'value'),
    )
    def update_instrument_options(spread_type):
        if not spread_type:
            return []

        macro_options = []
        if spread_type == 'TBondSwap':
            macro_options = [
                {'label': 'Macro: TBond-FR007:1Y', 'value': f"{MACRO_PREFIX}TBond-FR007:1Y"},
                {'label': 'Macro: TBond-FR007:5Y', 'value': f"{MACRO_PREFIX}TBond-FR007:5Y"},
            ]
        
        df = load_spread_data(spread_type)
        if df is None or df.empty:
            return macro_options
        
        options = [{'label': str(idx), 'value': str(idx)} for idx in df.index[:50]]
        return macro_options + options

    # -------------------------------------------------------------------------
    # BACKTEST: Run Individual Backtest
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('bt-individual-results', 'children'),
         Output('bt-individual-status', 'children')],
        Input('bt-run-individual-btn', 'n_clicks'),
        [State('bt-spread-type', 'value'),
         State('bt-instrument', 'value'),
         State('bt-entry-z', 'value'),
         State('bt-exit-z', 'value'),
         State('bt-stop-z', 'value'),
         State('bt-max-hold', 'value'),
         State('bt-period', 'value'),
         State('bt-trade-style', 'value'),
         State('bt-theta', 'value'),
         State('bt-mom-window', 'value'),
         State('bt-vol-window', 'value'),
         State('bt-trailing-mult', 'value'),
         State('bt-carry-buffer', 'value'),
         State('bt-allow-short', 'value')],
        prevent_initial_call=True
    )
    def run_individual_backtest(
        n_clicks, spread_type, instrument, entry_z, exit_z, stop_z, max_hold, period, style,
        theta, mom_window, vol_window, trailing_mult, carry_buffer, allow_short
    ):
        if not n_clicks:
            return html.Div(), ""
        
        if not spread_type or not instrument:
            return html.Div("Please select spread type and instrument.", style={'color': THEME['warning']}), ""

        ts = None
        display_instrument = instrument
        if isinstance(instrument, str) and instrument.startswith(MACRO_PREFIX):
            macro_name = instrument[len(MACRO_PREFIX):]
            display_instrument = macro_name
            ts = load_macro_series(macro_name)
            if ts is not None:
                ts = ts.tail(period)
        else:
            spread_ts = load_spread_timeseries(spread_type)
            if spread_ts is None:
                return html.Div(f"No time series data available for {spread_type}.", style={'color': THEME['warning']}), ""
            if instrument in spread_ts.columns:
                ts = spread_ts[instrument].tail(period)
            else:
                return html.Div(f"Instrument {instrument} not found in data.", style={'color': THEME['warning']}), ""

        if ts is None or len(ts.dropna()) < 60:
            return html.Div("Insufficient data for backtest.", style={'color': THEME['warning']}), ""

        style = style or 'mr'
        if style == 'trend':
            results = run_trend_backtest_dc(
                spread_ts=ts,
                theta=float(theta) if theta is not None else 0.02,
                mom_window=int(mom_window) if mom_window is not None else 20,
                vol_window=int(vol_window) if vol_window is not None else 60,
                trailing_mult=float(trailing_mult) if trailing_mult is not None else 1.5,
                carry_buffer=float(carry_buffer) if carry_buffer is not None else 0.0,
                max_hold=int(max_hold) if max_hold is not None else 60,
                allow_short=bool(allow_short and 'allow' in allow_short),
            )
        else:
            results = run_spread_backtest(
                spread_ts=ts,
                entry_z=entry_z or 2.0,
                exit_z=exit_z or 0.5,
                stop_z=stop_z or 4.0,
                max_hold=max_hold or 60,
                trade_style=style,
            )
        
        status = f"Backtest completed at {datetime.now().strftime('%H:%M:%S')}"
        display = build_backtest_results_display(results, title=f"Backtest: {display_instrument} ({spread_type})")
        
        return display, status

    # -------------------------------------------------------------------------
    # BACKTEST: Run Portfolio Backtest
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('bt-portfolio-results', 'children'),
         Output('bt-portfolio-status', 'children')],
        Input('bt-run-portfolio-btn', 'n_clicks'),
        [State('bt-portfolio-categories', 'value'),
         State('bt-max-positions', 'value'),
         State('bt-port-entry-z', 'value'),
         State('bt-port-exit-z', 'value'),
         State('bt-rebalance-freq', 'value'),
         State('bt-alloc-method', 'value'),
         State('bt-corr-constraint', 'value'),
         State('bt-bondswap-style', 'value'),
         State('bt-port-include-macro', 'value'),
         State('bt-port-theta', 'value'),
         State('bt-port-mom-window', 'value'),
         State('bt-port-vol-window', 'value'),
         State('bt-port-trailing-mult', 'value'),
         State('bt-port-carry-buffer', 'value'),
         State('bt-port-allow-short', 'value'),
         State('bt-port-period', 'value'),
         State('bt-initial-capital', 'value'),
         State('bt-txn-cost', 'value')],
        prevent_initial_call=True
    )
    def run_portfolio_backtest(n_clicks, categories, max_pos, entry_z, exit_z, 
                                rebal_freq, alloc_method, corr_constraint,
                                bondswap_style, include_macro,
                                theta, mom_window, vol_window, trailing_mult, carry_buffer, allow_short,
                                period, capital, txn_cost):
        if not n_clicks or not categories:
            return html.Div(), ""
        
        # Collect all spread time series
        all_results = []
        all_spreads = {}
        
        bondswap_style = bondswap_style or 'carry'
        include_macro = bool(include_macro and 'include' in include_macro)

        trend_params = {
            'theta': float(theta) if theta is not None else 0.02,
            'mom_window': int(mom_window) if mom_window is not None else 20,
            'vol_window': int(vol_window) if vol_window is not None else 60,
            'trailing_mult': float(trailing_mult) if trailing_mult is not None else 1.5,
            'carry_buffer': float(carry_buffer) if carry_buffer is not None else 0.0,
            'max_hold': 60,
            'allow_short': bool(allow_short and 'allow' in allow_short),
        }

        for cat in categories:
            if cat not in SPREAD_CATEGORIES:
                continue
            
            for stype in SPREAD_CATEGORIES[cat]['types']:
                spread_ts = load_spread_timeseries(stype)
                if spread_ts is None:
                    continue
                
                spread_ts = spread_ts.tail(period)
                
                # Run backtest on each spread
                for col in spread_ts.columns[:10]:  # Limit for performance
                    ts = spread_ts[col]
                    if len(ts.dropna()) < 60:
                        continue

                    use_trend = (cat == 'Bond-Swap' and bondswap_style == 'trend')
                    if use_trend:
                        result = run_trend_backtest_dc(spread_ts=ts, **trend_params)
                    else:
                        result = run_spread_backtest(
                            spread_ts=ts,
                            entry_z=entry_z or 2.0,
                            exit_z=exit_z or 0.5,
                            stop_z=4.0,
                            max_hold=60,
                            trade_style='mr' if SPREAD_CATEGORIES[cat]['style'] == 'MeanReversion' else 'carry',
                        )
                    
                    if result.get('n_trades', 0) > 0:
                        result['spread_type'] = stype
                        result['instrument'] = col
                        result['category'] = cat
                        all_results.append(result)
                        all_spreads[f"{stype}|{col}"] = ts

                # Optional: include macro series for Treasury bond-swap category
                if include_macro and cat == 'Bond-Swap' and stype == 'TBondSwap':
                    for macro_name in ['TBond-FR007:1Y', 'TBond-FR007:5Y']:
                        mts = load_macro_series(macro_name)
                        if mts is None:
                            continue
                        mts = mts.tail(period)
                        if len(mts.dropna()) < 60:
                            continue

                        if bondswap_style == 'trend':
                            mres = run_trend_backtest_dc(spread_ts=mts, **trend_params)
                        else:
                            mres = run_spread_backtest(
                                spread_ts=mts,
                                entry_z=entry_z or 2.0,
                                exit_z=exit_z or 0.5,
                                stop_z=4.0,
                                max_hold=60,
                                trade_style='carry',
                            )

                        if mres.get('n_trades', 0) > 0:
                            mres['spread_type'] = stype
                            mres['instrument'] = macro_name
                            mres['category'] = cat
                            all_results.append(mres)
                            all_spreads[f"{stype}|{macro_name}"] = mts
        
        if not all_results:
            return html.Div("No valid backtest results. Check data availability.", style={'color': THEME['warning']}), ""
        
        # Aggregate results
        results_df = pd.DataFrame([
            {
                'spread_type': r['spread_type'],
                'instrument': r['instrument'],
                'category': r['category'],
                'style': (
                    bondswap_style
                    if r.get('category') == 'Bond-Swap'
                    else ('mr' if SPREAD_CATEGORIES.get(r.get('category'), {}).get('style') == 'MeanReversion' else 'carry')
                ),
                'n_trades': r['n_trades'],
                'total_pnl': r['total_pnl'],
                'win_rate': r['win_rate'],
                'sharpe': r['sharpe'],
                'max_dd': r['max_drawdown'],
            }
            for r in all_results
        ])
        
        # Select top spreads by Sharpe
        results_df = results_df.sort_values('sharpe', ascending=False)
        top_spreads = results_df.head(max_pos or 10)
        
        # Portfolio-level metrics
        portfolio_pnl = top_spreads['total_pnl'].sum()
        portfolio_trades = top_spreads['n_trades'].sum()
        avg_sharpe = top_spreads['sharpe'].mean()
        avg_winrate = top_spreads['win_rate'].mean()
        
        # Build display
        metrics_div = html.Div([
            html.H6("Portfolio Backtest Results", style={'color': THEME['text_main'], 'marginBottom': '15px'}),
            html.Div([
                html.Div([
                    html.Strong("Spreads Tested: ", style={'color': THEME['text_sub']}),
                    html.Span(f"{len(results_df)}", style={'color': THEME['text_main']}),
                ], style={'marginRight': '25px'}),
                html.Div([
                    html.Strong("Top Spreads: ", style={'color': THEME['text_sub']}),
                    html.Span(f"{len(top_spreads)}", style={'color': THEME['text_main']}),
                ], style={'marginRight': '25px'}),
                html.Div([
                    html.Strong("Total Trades: ", style={'color': THEME['text_sub']}),
                    html.Span(f"{portfolio_trades:.0f}", style={'color': THEME['text_main']}),
                ], style={'marginRight': '25px'}),
                html.Div([
                    html.Strong("Portfolio PnL: ", style={'color': THEME['text_sub']}),
                    html.Span(f"{portfolio_pnl:.1f} bp", style={'color': THEME['success'] if portfolio_pnl > 0 else THEME['danger']}),
                ], style={'marginRight': '25px'}),
                html.Div([
                    html.Strong("Avg Sharpe: ", style={'color': THEME['text_sub']}),
                    html.Span(f"{avg_sharpe:.2f}", style={'color': THEME['success'] if avg_sharpe > 1 else THEME['text_main']}),
                ], style={'marginRight': '25px'}),
                html.Div([
                    html.Strong("Avg Win Rate: ", style={'color': THEME['text_sub']}),
                    html.Span(f"{avg_winrate:.1f}%", style={'color': THEME['text_main']}),
                ]),
            ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '10px', 'marginBottom': '20px'}),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'})
        
        # Top spreads table
        top_spreads_display = top_spreads.copy()
        for col in ['total_pnl', 'win_rate', 'sharpe', 'max_dd']:
            if col in top_spreads_display.columns:
                top_spreads_display[col] = top_spreads_display[col].round(2)
        
        spreads_table = html.Div([
            html.H6("Top Performing Spreads", style={'color': THEME['text_main'], 'marginBottom': '10px'}),
            dash_table.DataTable(
                columns=[{'name': c, 'id': c} for c in top_spreads_display.columns],
                data=top_spreads_display.to_dict('records'),
                style_table={'overflowX': 'auto', 'maxHeight': '300px', 'overflowY': 'auto'},
                style_header={
                    'backgroundColor': THEME['table_header'],
                    'color': THEME['text_main'],
                    'fontWeight': 'bold',
                },
                style_cell={
                    'backgroundColor': THEME['bg_card'],
                    'color': THEME['text_main'],
                    'fontSize': '11px',
                    'padding': '6px',
                },
                style_data_conditional=[
                    {'if': {'filter_query': '{sharpe} > 1'}, 'backgroundColor': 'rgba(0, 204, 150, 0.1)'},
                    {'if': {'filter_query': '{sharpe} < 0'}, 'backgroundColor': 'rgba(239, 85, 59, 0.1)'},
                ],
                sort_action='native',
                page_size=15,
            ),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px'})
        
        status = f"Portfolio backtest completed at {datetime.now().strftime('%H:%M:%S')}"
        
        return html.Div([metrics_div, spreads_table]), status


def build_basket_layout() -> html.Div:
    """Build the BASKET subtab layout - final trade basket management."""
    
    return html.Div([
        html.H6("Alpha Basket", style={'color': THEME['text_main'], 'marginBottom': '15px'}),
        html.P(
            "Final selected trades ready for execution. Review positions, adjust sizes, and export tickets.",
            style={'color': THEME['text_sub'], 'fontSize': '13px', 'marginBottom': '20px'}
        ),
        
        # Basket table (populated from portfolio)
        html.Div([
            html.H6("Current Basket", style={'color': THEME['accent'], 'marginBottom': '10px'}),
            html.Div(id='alpha-basket-table-container', children=[
                html.P("No trades in basket. Optimize portfolio in the Portfolio tab and add to basket.", 
                       style={'color': THEME['text_sub'], 'padding': '20px'})
            ]),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}),
        
        # Actions
        html.Div([
            html.Button(
                "📋 Export to Clipboard",
                id='alpha-export-btn',
                n_clicks=0,
                style={
                    'backgroundColor': THEME['accent'],
                    'color': 'white',
                    'padding': '10px 20px',
                    'border': 'none',
                    'borderRadius': '4px',
                    'cursor': 'pointer',
                    'marginRight': '10px',
                }
            ),
            html.Button(
                "🗑️ Clear Basket",
                id='alpha-clear-basket-btn',
                n_clicks=0,
                style={
                    'backgroundColor': THEME['danger'],
                    'color': 'white',
                    'padding': '10px 20px',
                    'border': 'none',
                    'borderRadius': '4px',
                    'cursor': 'pointer',
                }
            ),
        ], style={'marginBottom': '15px'}),
        
        # Basket store
        dcc.Store(id='alpha-basket-store', data=[]),
        
    ], style={'padding': '10px'})


def build_backtest_layout() -> html.Div:
    """Build the BACKTEST subtab layout - backtest individual spreads and portfolio."""
    
    return html.Div([
        # Header
        html.H6("Alpha Backtest", style={'color': THEME['text_main'], 'marginBottom': '15px'}),
        html.P(
            "Backtest individual spread trades or the full portfolio using historical data. "
            "Evaluate strategy performance with z-score (MR/Carry) or directional-change trend rules.",
            style={'color': THEME['text_sub'], 'fontSize': '13px', 'marginBottom': '20px'}
        ),
        
        # Tab selector: Individual vs Portfolio
        dcc.Tabs(
            id='backtest-mode-tabs',
            value='individual',
            children=[
                dcc.Tab(label='Individual Spread', value='individual', 
                        style={'backgroundColor': THEME['bg_card'], 'color': THEME['text_main'], 'padding': '8px'},
                        selected_style={'backgroundColor': THEME['accent'], 'color': 'white', 'padding': '8px'}),
                dcc.Tab(label='Portfolio', value='portfolio',
                        style={'backgroundColor': THEME['bg_card'], 'color': THEME['text_main'], 'padding': '8px'},
                        selected_style={'backgroundColor': THEME['accent'], 'color': 'white', 'padding': '8px'}),
            ],
            style={'marginBottom': '20px'}
        ),
        
        html.Div(id='backtest-mode-content'),
        
    ], style={'padding': '10px'})


def build_individual_backtest_panel() -> html.Div:
    """Build the individual spread backtest panel."""
    
    return html.Div([
        # Spread Selection
        html.Div([
            html.H6("Spread Selection", style={'color': THEME['accent'], 'marginBottom': '15px'}),
            
            html.Div([
                html.Div([
                    html.Label("Spread Type:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginBottom': '5px', 'display': 'block'}),
                    dcc.Dropdown(
                        id='bt-spread-type',
                        options=[
                            {'label': 'Bond-Curve (Treasury)', 'value': 'TBondCurve'},
                            {'label': 'Bond-Curve (Policybank)', 'value': 'CBondCurve'},
                            {'label': 'Bond-Swap (Treasury)', 'value': 'TBondSwap'},
                            {'label': 'Bond-Swap (Policybank)', 'value': 'CBondSwap'},
                            {'label': 'Swap Spread', 'value': 'SwapSpread'},
                            {'label': 'Net Basis (Futures)', 'value': 'NetBasis'},
                            {'label': 'Term Basis (Futures)', 'value': 'TermBasis'},
                            {'label': 'PCA Spread', 'value': 'PCASpread'},
                        ],
                        value='TBondCurve',
                        clearable=False,
                        style={'width': '250px'},
                    ),
                ], style={'marginRight': '20px'}),
                
                html.Div([
                    html.Label("Instrument:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginBottom': '5px', 'display': 'block'}),
                    dcc.Dropdown(
                        id='bt-instrument',
                        options=[],  # Populated by callback
                        placeholder="Select instrument...",
                        style={'width': '250px'},
                    ),
                ], style={'marginRight': '20px'}),
            ], style={'display': 'flex', 'marginBottom': '15px'}),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}),
        
        # Strategy Parameters
        html.Div([
            html.H6("Strategy Parameters", style={'color': THEME['accent'], 'marginBottom': '15px'}),
            
            html.Div([
                # Entry/Exit thresholds
                html.Div([
                    html.Label("Entry Z-Score:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Input(id='bt-entry-z', type='number', value=2.0, min=0.5, max=4.0, step=0.25,
                              style={'width': '80px', 'marginRight': '30px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),
                
                html.Div([
                    html.Label("Exit Z-Score:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Input(id='bt-exit-z', type='number', value=0.5, min=0, max=2.0, step=0.25,
                              style={'width': '80px', 'marginRight': '30px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),
                
                html.Div([
                    html.Label("Stop Loss (σ):", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Input(id='bt-stop-z', type='number', value=4.0, min=2.0, max=6.0, step=0.5,
                              style={'width': '80px', 'marginRight': '30px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),
                
                html.Div([
                    html.Label("Max Holding (days):", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Input(id='bt-max-hold', type='number', value=60, min=5, max=252, step=5,
                              style={'width': '80px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),
            ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '15px', 'marginBottom': '15px'}),
            
            # Lookback period
            html.Div([
                html.Label("Backtest Period:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                dcc.Dropdown(
                    id='bt-period',
                    options=[
                        {'label': '1 Year', 'value': 252},
                        {'label': '2 Years', 'value': 504},
                        {'label': '3 Years', 'value': 756},
                        {'label': '5 Years', 'value': 1260},
                    ],
                    value=504,
                    clearable=False,
                    style={'width': '150px', 'marginRight': '30px'},
                ),
                
                html.Label("Trade Style:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                dcc.RadioItems(
                    id='bt-trade-style',
                    options=[
                        {'label': ' Mean-Reversion', 'value': 'mr'},
                        {'label': ' Carry', 'value': 'carry'},
                        {'label': ' Trend (Directional-Change)', 'value': 'trend'},
                    ],
                    value='mr',
                    inline=True,
                    labelStyle={'color': THEME['text_main'], 'marginRight': '15px'},
                ),
            ], style={'display': 'flex', 'alignItems': 'center'}),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}),

        # Trend Parameters (used when Trade Style = Trend)
        html.Div([
            html.H6("Trend Parameters (Directional-Change)", style={'color': THEME['accent'], 'marginBottom': '15px'}),

            html.Div([
                html.Div([
                    html.Label("Theta:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Input(id='bt-theta', type='number', value=0.02, min=0.001, max=0.2, step=0.001,
                              style={'width': '90px', 'marginRight': '30px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),

                html.Div([
                    html.Label("Mom window:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Input(id='bt-mom-window', type='number', value=20, min=5, max=120, step=1,
                              style={'width': '80px', 'marginRight': '30px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),

                html.Div([
                    html.Label("Vol window:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Input(id='bt-vol-window', type='number', value=60, min=20, max=252, step=1,
                              style={'width': '80px', 'marginRight': '30px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),

                html.Div([
                    html.Label("Trail mult:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Input(id='bt-trailing-mult', type='number', value=1.5, min=0.5, max=5.0, step=0.1,
                              style={'width': '80px', 'marginRight': '30px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),

                html.Div([
                    html.Label("Carry buffer:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Input(id='bt-carry-buffer', type='number', value=0.0, step=0.0001,
                              style={'width': '90px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),
            ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '15px'}),

            html.Div([
                dcc.Checklist(
                    id='bt-allow-short',
                    options=[{'label': ' Allow short-spread trades', 'value': 'allow'}],
                    value=['allow'],
                    labelStyle={'color': THEME['text_main'], 'fontSize': '13px'},
                ),
            ], style={'marginTop': '10px'}),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}),
        
        # Run Button
        html.Div([
            html.Button(
                "▶️ Run Individual Backtest",
                id='bt-run-individual-btn',
                n_clicks=0,
                style={
                    'backgroundColor': THEME['success'],
                    'color': 'white',
                    'padding': '12px 25px',
                    'border': 'none',
                    'borderRadius': '4px',
                    'cursor': 'pointer',
                    'fontWeight': 'bold',
                    'fontSize': '14px',
                }
            ),
            html.Span(id='bt-individual-status', style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginLeft': '15px'}),
        ], style={'marginBottom': '20px'}),
        
        # Results
        dcc.Loading(
            id='loading-bt-individual',
            type='default',
            children=html.Div(id='bt-individual-results'),
        ),
    ])


def build_portfolio_backtest_panel() -> html.Div:
    """Build the portfolio backtest panel."""
    
    return html.Div([
        # Portfolio Configuration
        html.Div([
            html.H6("Portfolio Configuration", style={'color': THEME['accent'], 'marginBottom': '15px'}),
            
            # Spread categories to include
            html.Div([
                html.Label("Include Spread Categories:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginBottom': '8px', 'display': 'block'}),
                dcc.Checklist(
                    id='bt-portfolio-categories',
                    options=[
                        {'label': ' Bond-Curve', 'value': 'Bond-Curve'},
                        {'label': ' Bond-Swap', 'value': 'Bond-Swap'},
                        {'label': ' Swap Spreads', 'value': 'Swap-Spread'},
                        {'label': ' Net Basis', 'value': 'Bond-Futures'},
                        {'label': ' Term Basis', 'value': 'Futures-Term'},
                    ],
                    value=['Bond-Curve', 'Bond-Swap'],
                    inline=True,
                    labelStyle={'color': THEME['text_main'], 'marginRight': '15px', 'fontSize': '12px'},
                ),
            ], style={'marginBottom': '15px'}),

            # Bond-Swap specific style override
            html.Div([
                html.H6("Bond-Swap Settings", style={'color': THEME['accent'], 'marginBottom': '10px'}),
                html.Div([
                    html.Label("Bond-Swap Style:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.RadioItems(
                        id='bt-bondswap-style',
                        options=[
                            {'label': ' Carry', 'value': 'carry'},
                            {'label': ' Trend (Directional-Change)', 'value': 'trend'},
                        ],
                        value='carry',
                        inline=True,
                        labelStyle={'color': THEME['text_main'], 'marginRight': '15px'},
                    ),
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '8px'}),

                html.Div([
                    dcc.Checklist(
                        id='bt-port-include-macro',
                        options=[{'label': ' Include macro series (TBond-FR007 1Y/5Y) when Bond-Swap selected', 'value': 'include'}],
                        value=['include'],
                        labelStyle={'color': THEME['text_main'], 'fontSize': '13px'},
                    ),
                ]),
            ], style={'backgroundColor': THEME['bg_input'], 'padding': '12px', 'borderRadius': '5px', 'marginBottom': '15px'}),

            # Trend parameters for portfolio Bond-Swap (used when Bond-Swap Style = Trend)
            html.Div([
                html.H6("Bond-Swap Trend Parameters (Directional-Change)", style={'color': THEME['accent'], 'marginBottom': '10px'}),
                html.Div([
                    html.Div([
                        html.Label("Theta:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                        dcc.Input(id='bt-port-theta', type='number', value=0.02, min=0.001, max=0.2, step=0.001,
                                  style={'width': '90px', 'marginRight': '30px'}),
                    ], style={'display': 'flex', 'alignItems': 'center'}),

                    html.Div([
                        html.Label("Mom window:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                        dcc.Input(id='bt-port-mom-window', type='number', value=20, min=5, max=120, step=1,
                                  style={'width': '80px', 'marginRight': '30px'}),
                    ], style={'display': 'flex', 'alignItems': 'center'}),

                    html.Div([
                        html.Label("Vol window:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                        dcc.Input(id='bt-port-vol-window', type='number', value=60, min=20, max=252, step=1,
                                  style={'width': '80px', 'marginRight': '30px'}),
                    ], style={'display': 'flex', 'alignItems': 'center'}),

                    html.Div([
                        html.Label("Trail mult:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                        dcc.Input(id='bt-port-trailing-mult', type='number', value=1.5, min=0.5, max=5.0, step=0.1,
                                  style={'width': '80px', 'marginRight': '30px'}),
                    ], style={'display': 'flex', 'alignItems': 'center'}),

                    html.Div([
                        html.Label("Carry buffer:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                        dcc.Input(id='bt-port-carry-buffer', type='number', value=0.0, step=0.0001,
                                  style={'width': '90px'}),
                    ], style={'display': 'flex', 'alignItems': 'center'}),
                ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '15px', 'marginBottom': '8px'}),

                html.Div([
                    dcc.Checklist(
                        id='bt-port-allow-short',
                        options=[{'label': ' Allow short-spread trades (trend mode)', 'value': 'allow'}],
                        value=['allow'],
                        labelStyle={'color': THEME['text_main'], 'fontSize': '13px'},
                    ),
                ]),
            ], style={'backgroundColor': THEME['bg_input'], 'padding': '12px', 'borderRadius': '5px', 'marginBottom': '15px'}),
            
            html.Div([
                html.Div([
                    html.Label("Max Positions:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Input(id='bt-max-positions', type='number', value=10, min=3, max=30, step=1,
                              style={'width': '80px', 'marginRight': '30px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),
                
                html.Div([
                    html.Label("Entry Z-Score:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Input(id='bt-port-entry-z', type='number', value=2.0, min=0.5, max=4.0, step=0.25,
                              style={'width': '80px', 'marginRight': '30px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),
                
                html.Div([
                    html.Label("Exit Z-Score:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Input(id='bt-port-exit-z', type='number', value=0.5, min=0, max=2.0, step=0.25,
                              style={'width': '80px', 'marginRight': '30px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),
                
                html.Div([
                    html.Label("Rebalance:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Dropdown(
                        id='bt-rebalance-freq',
                        options=[
                            {'label': 'Daily', 'value': 'D'},
                            {'label': 'Weekly', 'value': 'W'},
                            {'label': 'Monthly', 'value': 'M'},
                        ],
                        value='W',
                        clearable=False,
                        style={'width': '120px'},
                    ),
                ], style={'display': 'flex', 'alignItems': 'center'}),
            ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '15px', 'marginBottom': '15px'}),
            
            # Allocation method
            html.Div([
                html.Label("Allocation Method:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                dcc.RadioItems(
                    id='bt-alloc-method',
                    options=[
                        {'label': ' Risk Parity', 'value': 'risk_parity'},
                        {'label': ' Equal Weight', 'value': 'equal'},
                        {'label': ' Inverse Vol', 'value': 'inv_vol'},
                        {'label': ' Score-Weighted', 'value': 'score'},
                    ],
                    value='risk_parity',
                    inline=True,
                    labelStyle={'color': THEME['text_main'], 'marginRight': '15px'},
                ),
            ], style={'marginBottom': '15px'}),
            
            # Correlation constraint
            html.Div([
                dcc.Checklist(
                    id='bt-corr-constraint',
                    options=[{'label': ' Enforce max correlation constraint (0.5)', 'value': 'enforce'}],
                    value=['enforce'],
                    labelStyle={'color': THEME['text_main'], 'fontSize': '13px'},
                ),
            ]),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}),
        
        # Backtest Settings
        html.Div([
            html.H6("Backtest Settings", style={'color': THEME['accent'], 'marginBottom': '15px'}),
            
            html.Div([
                html.Div([
                    html.Label("Backtest Period:", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Dropdown(
                        id='bt-port-period',
                        options=[
                            {'label': '1 Year', 'value': 252},
                            {'label': '2 Years', 'value': 504},
                            {'label': '3 Years', 'value': 756},
                            {'label': '5 Years', 'value': 1260},
                        ],
                        value=504,
                        clearable=False,
                        style={'width': '150px', 'marginRight': '30px'},
                    ),
                ], style={'display': 'flex', 'alignItems': 'center'}),
                
                html.Div([
                    html.Label("Initial Capital (MM):", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Input(id='bt-initial-capital', type='number', value=100, min=10, max=1000, step=10,
                              style={'width': '100px', 'marginRight': '30px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),
                
                html.Div([
                    html.Label("Transaction Cost (bp):", style={'fontWeight': 'bold', 'color': THEME['text_main'], 'marginRight': '10px'}),
                    dcc.Input(id='bt-txn-cost', type='number', value=0.5, min=0, max=5, step=0.1,
                              style={'width': '80px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),
            ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '15px'}),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}),
        
        # Run Button
        html.Div([
            html.Button(
                "▶️ Run Portfolio Backtest",
                id='bt-run-portfolio-btn',
                n_clicks=0,
                style={
                    'backgroundColor': THEME['success'],
                    'color': 'white',
                    'padding': '12px 25px',
                    'border': 'none',
                    'borderRadius': '4px',
                    'cursor': 'pointer',
                    'fontWeight': 'bold',
                    'fontSize': '14px',
                }
            ),
            html.Span(id='bt-portfolio-status', style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginLeft': '15px'}),
        ], style={'marginBottom': '20px'}),
        
        # Results
        dcc.Loading(
            id='loading-bt-portfolio',
            type='default',
            children=html.Div(id='bt-portfolio-results'),
        ),
    ])


# ---------------------------------------------------------------------------
# Backtest Engine Functions
# ---------------------------------------------------------------------------

def run_spread_backtest(
    spread_ts: pd.Series,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 4.0,
    max_hold: int = 60,
    trade_style: str = 'mr',
) -> Dict[str, Any]:
    """Run backtest on a single spread time series.
    
    Args:
        spread_ts: Time series of spread values (in bp or %)
        entry_z: Z-score threshold for entry
        exit_z: Z-score threshold for exit (mean-reversion to mean)
        stop_z: Z-score threshold for stop-loss
        max_hold: Maximum holding period in days
        trade_style: 'mr' for mean-reversion, 'carry' for carry trades
    
    Returns:
        Dictionary with backtest results and metrics
    """
    if spread_ts is None or len(spread_ts) < 60:
        return {'error': 'Insufficient data'}
    
    spread_ts = spread_ts.dropna()
    
    # Calculate rolling statistics (60-day lookback)
    lookback = 60
    rolling_mean = spread_ts.rolling(lookback).mean()
    rolling_std = spread_ts.rolling(lookback).std()
    zscore = (spread_ts - rolling_mean) / rolling_std
    
    # Initialize tracking
    trades = []
    position = 0  # 0 = flat, 1 = long spread, -1 = short spread
    entry_date = None
    entry_price = None
    entry_zscore = None
    
    # Iterate through time series
    for i in range(lookback, len(spread_ts)):
        date = spread_ts.index[i]
        price = spread_ts.iloc[i]
        z = zscore.iloc[i]
        
        if np.isnan(z):
            continue
        
        # Check for exit conditions first
        if position != 0:
            days_held = (date - entry_date).days if entry_date else 0
            
            # Exit conditions
            exit_signal = False
            exit_reason = None
            
            if trade_style == 'mr':
                # Mean-reversion: exit when z-score reverts toward 0
                if position == 1 and z >= -exit_z:  # Long position, z was negative
                    exit_signal = True
                    exit_reason = 'target'
                elif position == -1 and z <= exit_z:  # Short position, z was positive
                    exit_signal = True
                    exit_reason = 'target'
            else:
                # Carry: exit on reversal or time
                if position == 1 and z > entry_zscore + 1:
                    exit_signal = True
                    exit_reason = 'reversal'
                elif position == -1 and z < entry_zscore - 1:
                    exit_signal = True
                    exit_reason = 'reversal'
            
            # Stop loss
            if position == 1 and z < -stop_z:
                exit_signal = True
                exit_reason = 'stop_loss'
            elif position == -1 and z > stop_z:
                exit_signal = True
                exit_reason = 'stop_loss'
            
            # Max holding period
            if days_held >= max_hold:
                exit_signal = True
                exit_reason = 'max_hold'
            
            if exit_signal:
                pnl = (price - entry_price) * position  # In spread units (bp)
                trades.append({
                    'entry_date': entry_date,
                    'exit_date': date,
                    'direction': 'LONG' if position == 1 else 'SHORT',
                    'entry_price': entry_price,
                    'exit_price': price,
                    'entry_z': entry_zscore,
                    'exit_z': z,
                    'pnl_bp': pnl,
                    'days_held': days_held,
                    'exit_reason': exit_reason,
                })
                position = 0
                entry_date = None
                entry_price = None
                entry_zscore = None
        
        # Check for entry conditions
        if position == 0:
            if trade_style == 'mr':
                # Mean-reversion: enter when z-score is extreme
                if z <= -entry_z:
                    position = 1  # Long spread (expect it to rise)
                    entry_date = date
                    entry_price = price
                    entry_zscore = z
                elif z >= entry_z:
                    position = -1  # Short spread (expect it to fall)
                    entry_date = date
                    entry_price = price
                    entry_zscore = z
            else:
                # Carry: same entry logic but different exit
                if z <= -entry_z:
                    position = 1
                    entry_date = date
                    entry_price = price
                    entry_zscore = z
                elif z >= entry_z:
                    position = -1
                    entry_date = date
                    entry_price = price
                    entry_zscore = z
    
    # Calculate metrics
    if not trades:
        return {
            'trades': [],
            'n_trades': 0,
            'total_pnl': 0,
            'win_rate': 0,
            'avg_pnl': 0,
            'avg_hold': 0,
            'sharpe': 0,
            'max_drawdown': 0,
            'spread_ts': spread_ts,
            'zscore_ts': zscore,
        }
    
    trades_df = pd.DataFrame(trades)
    pnls = trades_df['pnl_bp'].values
    
    n_trades = len(trades)
    total_pnl = pnls.sum()
    win_rate = (pnls > 0).sum() / n_trades * 100
    avg_pnl = pnls.mean()
    avg_hold = trades_df['days_held'].mean()
    
    # Sharpe (annualized, assuming ~20 trades/year avg)
    if pnls.std() > 0:
        sharpe = (pnls.mean() / pnls.std()) * np.sqrt(min(n_trades, 20))
    else:
        sharpe = 0
    
    # Max drawdown (cumulative PnL)
    cum_pnl = np.cumsum(pnls)
    running_max = np.maximum.accumulate(cum_pnl)
    drawdowns = running_max - cum_pnl
    max_drawdown = drawdowns.max() if len(drawdowns) > 0 else 0
    
    return {
        'trades': trades,
        'trades_df': trades_df,
        'n_trades': n_trades,
        'total_pnl': total_pnl,
        'win_rate': win_rate,
        'avg_pnl': avg_pnl,
        'avg_hold': avg_hold,
        'sharpe': sharpe,
        'max_drawdown': max_drawdown,
        'spread_ts': spread_ts,
        'zscore_ts': zscore,
        'cum_pnl': cum_pnl,
    }


def _dc_trend_state(series: pd.Series, theta: float) -> pd.Series:
    """Compute trend state (+1/-1) from directional-change events."""
    try:
        from curves.calibration.trend import generate as dc_generate
    except Exception:
        dc_generate = None

    s = pd.to_numeric(series, errors='coerce').dropna().copy()
    if s.empty:
        return pd.Series(dtype=float)

    if dc_generate is None:
        st = np.sign(s.diff()).replace(0, np.nan).ffill().fillna(0.0)
        st.name = 'trend_state'
        return st

    events = dc_generate(s, float(theta))
    state = pd.Series(index=s.index, dtype=float)
    cur = 0.0
    for dt, ev in events.items():
        if ev == 'Upward Trend Confirmed':
            cur = 1.0
        elif ev == 'Downward Trend Confirmed':
            cur = -1.0
        state.loc[dt] = cur
    state = state.ffill().fillna(0.0)
    state.name = 'trend_state'
    return state


def run_trend_backtest_dc(
    spread_ts: pd.Series,
    theta: float = 0.02,
    mom_window: int = 20,
    vol_window: int = 60,
    trailing_mult: float = 1.5,
    carry_buffer: float = 0.0,
    max_hold: int = 60,
    allow_short: bool = True,
) -> Dict[str, Any]:
    """Trend/carry backtest using directional-change trend confirmation."""
    if spread_ts is None or len(spread_ts) < 60:
        return {'error': 'Insufficient data'}

    s = pd.to_numeric(spread_ts, errors='coerce').dropna().copy()
    if len(s) < max(60, vol_window + 5, mom_window + 5):
        return {'error': 'Insufficient data'}

    trend_state = _dc_trend_state(s, theta=float(theta)).reindex(s.index).ffill().fillna(0.0)
    mom = s.diff(mom_window)
    sigma = s.diff().rolling(vol_window).std()
    norm_mom = mom / sigma.replace(0, np.nan)

    trades: List[Dict[str, Any]] = []
    position = 0
    entry_date = None
    entry_price = None
    best_fav = None

    start_i = max(vol_window, mom_window) + 1
    for i in range(start_i, len(s)):
        date = s.index[i]
        px = float(s.iloc[i])
        st = float(trend_state.iloc[i])
        m = float(norm_mom.iloc[i]) if not np.isnan(norm_mom.iloc[i]) else 0.0
        vol = float(sigma.iloc[i]) if not np.isnan(sigma.iloc[i]) else np.nan

        if position != 0:
            days_held = (date - entry_date).days if entry_date is not None else 0

            if best_fav is None:
                best_fav = px
            if position == 1:
                best_fav = max(best_fav, px)
            else:
                best_fav = min(best_fav, px)

            trailing_stop = False
            if not np.isnan(vol) and vol > 0 and trailing_mult > 0:
                if position == 1:
                    trailing_stop = (best_fav - px) >= trailing_mult * vol
                else:
                    trailing_stop = (px - best_fav) >= trailing_mult * vol

            carry_bad = False
            if position == 1:
                carry_bad = px < carry_buffer
            else:
                carry_bad = px > -carry_buffer

            flip = (position == 1 and st < 0) or (position == -1 and st > 0)
            time_stop = days_held >= max_hold

            if trailing_stop or carry_bad or flip or time_stop:
                pnl = (px - entry_price) * position
                trades.append({
                    'entry_date': entry_date,
                    'exit_date': date,
                    'direction': 'LONG' if position == 1 else 'SHORT',
                    'entry_price': entry_price,
                    'exit_price': px,
                    'pnl_bp': pnl,
                    'days_held': days_held,
                    'exit_reason': 'trailing' if trailing_stop else ('carry' if carry_bad else ('flip' if flip else 'max_hold')),
                })
                position = 0
                entry_date = None
                entry_price = None
                best_fav = None

        if position == 0:
            mom_ok = (st > 0 and m >= 0.5) or (st < 0 and m <= -0.5)
            if st > 0 and mom_ok and px >= carry_buffer:
                position = 1
                entry_date = date
                entry_price = px
                best_fav = px
            elif allow_short and st < 0 and mom_ok and px <= -carry_buffer:
                position = -1
                entry_date = date
                entry_price = px
                best_fav = px

    if not trades:
        return {
            'trades': [],
            'trades_df': pd.DataFrame(),
            'n_trades': 0,
            'total_pnl': 0.0,
            'win_rate': 0.0,
            'avg_pnl': 0.0,
            'avg_hold': 0.0,
            'sharpe': 0.0,
            'max_drawdown': 0.0,
            'spread_ts': s,
            'trend_state_ts': trend_state,
            'norm_mom_ts': norm_mom,
            'cum_pnl': np.array([]),
        }

    trades_df = pd.DataFrame(trades)
    pnls = trades_df['pnl_bp'].values
    n_trades = int(len(trades_df))
    total_pnl = float(np.nansum(pnls))
    win_rate = float((pnls > 0).sum() / n_trades * 100.0)
    avg_pnl = float(np.nanmean(pnls))
    avg_hold = float(trades_df['days_held'].mean())
    sharpe = float((np.nanmean(pnls) / np.nanstd(pnls)) * np.sqrt(min(n_trades, 20))) if np.nanstd(pnls) > 0 else 0.0

    cum_pnl = np.nancumsum(pnls)
    running_max = np.maximum.accumulate(cum_pnl)
    drawdowns = running_max - cum_pnl
    max_drawdown = float(drawdowns.max()) if len(drawdowns) > 0 else 0.0

    return {
        'trades': trades,
        'trades_df': trades_df,
        'n_trades': n_trades,
        'total_pnl': total_pnl,
        'win_rate': win_rate,
        'avg_pnl': avg_pnl,
        'avg_hold': avg_hold,
        'sharpe': sharpe,
        'max_drawdown': max_drawdown,
        'spread_ts': s,
        'trend_state_ts': trend_state,
        'norm_mom_ts': norm_mom,
        'cum_pnl': cum_pnl,
    }


def build_backtest_results_display(results: Dict[str, Any], title: str = "Backtest Results") -> html.Div:
    """Build the display for backtest results."""
    
    if 'error' in results:
        return html.Div(f"Error: {results['error']}", style={'color': THEME['warning'], 'padding': '20px'})
    
    if results['n_trades'] == 0:
        return html.Div("No trades generated with current parameters.", style={'color': THEME['warning'], 'padding': '20px'})
    
    # Metrics summary
    metrics_div = html.Div([
        html.H6(title, style={'color': THEME['text_main'], 'marginBottom': '15px'}),
        html.Div([
            html.Div([
                html.Strong("Total Trades: ", style={'color': THEME['text_sub']}),
                html.Span(f"{results['n_trades']}", style={'color': THEME['text_main']}),
            ], style={'marginRight': '25px'}),
            html.Div([
                html.Strong("Win Rate: ", style={'color': THEME['text_sub']}),
                html.Span(f"{results['win_rate']:.1f}%", style={'color': THEME['success'] if results['win_rate'] > 50 else THEME['danger']}),
            ], style={'marginRight': '25px'}),
            html.Div([
                html.Strong("Total PnL: ", style={'color': THEME['text_sub']}),
                html.Span(f"{results['total_pnl']:.1f} bp", style={'color': THEME['success'] if results['total_pnl'] > 0 else THEME['danger']}),
            ], style={'marginRight': '25px'}),
            html.Div([
                html.Strong("Avg PnL: ", style={'color': THEME['text_sub']}),
                html.Span(f"{results['avg_pnl']:.2f} bp", style={'color': THEME['text_main']}),
            ], style={'marginRight': '25px'}),
            html.Div([
                html.Strong("Avg Hold: ", style={'color': THEME['text_sub']}),
                html.Span(f"{results['avg_hold']:.0f} days", style={'color': THEME['text_main']}),
            ], style={'marginRight': '25px'}),
            html.Div([
                html.Strong("Sharpe: ", style={'color': THEME['text_sub']}),
                html.Span(f"{results['sharpe']:.2f}", style={'color': THEME['success'] if results['sharpe'] > 1 else THEME['text_main']}),
            ], style={'marginRight': '25px'}),
            html.Div([
                html.Strong("Max DD: ", style={'color': THEME['text_sub']}),
                html.Span(f"{results['max_drawdown']:.1f} bp", style={'color': THEME['danger']}),
            ]),
        ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '10px', 'marginBottom': '20px'}),
    ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'})
    
    # Equity curve chart
    equity_fig = go.Figure()
    
    if 'cum_pnl' in results and len(results['cum_pnl']) > 0:
        trades_df = results.get('trades_df')
        if trades_df is not None and len(trades_df) > 0:
            equity_fig.add_trace(go.Scatter(
                x=list(range(len(results['cum_pnl']))),
                y=results['cum_pnl'],
                mode='lines',
                name='Cumulative PnL',
                line=dict(color=THEME['success'], width=2),
            ))
    
    equity_fig.update_layout(
        title='Cumulative PnL (bp)',
        height=250,
        margin=dict(l=50, r=20, t=40, b=40),
        plot_bgcolor=THEME['bg_main'],
        paper_bgcolor=THEME['bg_main'],
        font=dict(color=THEME['text_main']),
        xaxis=dict(title='Trade #', gridcolor=THEME['bg_card']),
        yaxis=dict(title='Cumulative PnL (bp)', gridcolor=THEME['bg_card']),
    )
    
    equity_div = html.Div([
        dcc.Graph(figure=equity_fig, style={'height': '250px'}),
    ], style={'marginBottom': '15px'})
    
    # Signal chart: Z-score (MR/Carry) or Trend State (Trend)
    signal_fig = go.Figure()
    signal_title = 'Signal'

    if 'zscore_ts' in results and results['zscore_ts'] is not None:
        zscore_ts = results['zscore_ts'].dropna()
        if len(zscore_ts) > 0:
            signal_title = 'Z-Score History'
            signal_fig.add_trace(go.Scatter(
                x=zscore_ts.index,
                y=zscore_ts.values,
                mode='lines',
                name='Z-Score',
                line=dict(color=THEME['accent'], width=1),
            ))
            signal_fig.add_hline(y=2, line_dash='dash', line_color=THEME['danger'], annotation_text='+2σ')
            signal_fig.add_hline(y=-2, line_dash='dash', line_color=THEME['success'], annotation_text='-2σ')
            signal_fig.add_hline(y=0, line_dash='dot', line_color=THEME['text_sub'])
    elif 'trend_state_ts' in results and results['trend_state_ts'] is not None:
        st = results['trend_state_ts'].dropna()
        if len(st) > 0:
            signal_title = 'Trend State (Directional-Change)'
            signal_fig.add_trace(go.Scatter(
                x=st.index,
                y=st.values,
                mode='lines',
                name='TrendState',
                line=dict(color=THEME['accent'], width=2),
            ))
            signal_fig.add_hline(y=1, line_dash='dash', line_color=THEME['success'], annotation_text='Up')
            signal_fig.add_hline(y=-1, line_dash='dash', line_color=THEME['danger'], annotation_text='Down')
            signal_fig.add_hline(y=0, line_dash='dot', line_color=THEME['text_sub'])

    signal_fig.update_layout(
        title=signal_title,
        height=200,
        margin=dict(l=50, r=20, t=40, b=40),
        plot_bgcolor=THEME['bg_main'],
        paper_bgcolor=THEME['bg_main'],
        font=dict(color=THEME['text_main']),
        xaxis=dict(gridcolor=THEME['bg_card']),
        yaxis=dict(title='Signal', gridcolor=THEME['bg_card']),
        showlegend=False,
    )

    signal_div = html.Div([
        dcc.Graph(figure=signal_fig, style={'height': '200px'}),
    ], style={'marginBottom': '15px'})
    
    # Trades table
    trades_table = html.Div()
    if 'trades_df' in results and results['trades_df'] is not None and len(results['trades_df']) > 0:
        df = results['trades_df'].copy()
        df['entry_date'] = pd.to_datetime(df['entry_date']).dt.strftime('%Y-%m-%d')
        df['exit_date'] = pd.to_datetime(df['exit_date']).dt.strftime('%Y-%m-%d')
        for col in ['entry_price', 'exit_price', 'pnl_bp', 'entry_z', 'exit_z']:
            if col in df.columns:
                df[col] = df[col].round(2)
        
        trades_table = html.Div([
            html.H6("Trade History", style={'color': THEME['text_main'], 'marginBottom': '10px'}),
            dash_table.DataTable(
                columns=[{'name': c, 'id': c} for c in df.columns],
                data=df.to_dict('records'),
                style_table={'overflowX': 'auto', 'maxHeight': '250px', 'overflowY': 'auto'},
                style_header={
                    'backgroundColor': THEME['table_header'],
                    'color': THEME['text_main'],
                    'fontWeight': 'bold',
                },
                style_cell={
                    'backgroundColor': THEME['bg_card'],
                    'color': THEME['text_main'],
                    'fontSize': '11px',
                    'padding': '5px',
                },
                style_data_conditional=[
                    {'if': {'filter_query': '{pnl_bp} > 0'}, 'backgroundColor': 'rgba(0, 204, 150, 0.1)'},
                    {'if': {'filter_query': '{pnl_bp} < 0'}, 'backgroundColor': 'rgba(239, 85, 59, 0.1)'},
                ],
                page_size=10,
                sort_action='native',
            ),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px'})
    
    return html.Div([
        metrics_div,
        equity_div,
        signal_div,
        trades_table,
    ])
