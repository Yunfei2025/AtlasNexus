# -*- coding: utf-8 -*-
"""Constants, data loaders, and duration helpers for the Alpha Book tabs."""

from __future__ import annotations

import pickle
import re
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Theme / Style constants
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
        'style': 'Mixed',
    },
    'Swap-Spread': {
        'label': 'Swap Spreads',
        'types': ['SwapSpread'],
        'description': 'IRS spread trades (box, basis)',
        'style': 'Mixed',
    },
    'Tenor-Spread': {
        'label': 'Tenor Spreads',
        'types': ['TenorSpread'],
        'description': 'Curve slope / cross-curve spreads (e.g. 5s10s, 10s30s)',
        'style': 'Mixed',
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
for _cat, _info in SPREAD_CATEGORIES.items():
    for _stype in _info['types']:
        SPREAD_TYPE_OPTIONS.append({
            'label': f"{_info['label']} ({_stype})",
            'value': _stype,
            'category': _cat,
        })

# Default z-score thresholds
ZSCORE_ENTRY_THRESHOLD = 2.0
ZSCORE_EXIT_THRESHOLD = 0.5
MAX_CORRELATION_THRESHOLD = 0.6

# Instrument selector prefix for non-spread (macro) series
MACRO_PREFIX = "MACRO|"
_SWAP_SPREAD_BUTTERFLY_PATTERN = re.compile(r"^(?:Repo|Shi3M)-(?:\d+[my]){3,}$", re.IGNORECASE)

# Global state for diversified trade recommendations
DIVERSIFIED_TRADE_RECOMMENDATIONS = {
    'trades': [],
    'timestamp': None,
}


def _exclude_swapspread_butterflies(labels: pd.Index | pd.Series):
    """Return mask that excludes IRS butterfly IDs such as Repo-1y2y5y or Shi3M-3m6m9m."""
    text = labels.astype(str)
    return ~text.str.match(_SWAP_SPREAD_BUTTERFLY_PATTERN)


# ---------------------------------------------------------------------------
# Data Loading Utilities
# ---------------------------------------------------------------------------

def _get_input_dir() -> Path:
    try:
        from settings.paths import DIR_INPUT
        return Path(DIR_INPUT)
    except ImportError:
        return Path(__file__).parent.parent.parent / 'input'


def _load_pickle_safe(filepath: Path) -> Optional[Any]:
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
    """Load spread data for a given type and return DataFrame with required columns."""
    dir_input = _get_input_dir()

    try:
        from curves.refreshers.alpha import get_alpha_spread_table

        snap_df = get_alpha_spread_table(spread_type, dir_input=dir_input)
        if snap_df is not None and isinstance(snap_df, pd.DataFrame) and not snap_df.empty:
            if spread_type == 'SwapSpread':
                snap_df = snap_df[~snap_df.index.astype(str).str.endswith('.IR')].copy()
                snap_df = snap_df[_exclude_swapspread_butterflies(snap_df.index)].copy()
            return snap_df
    except Exception:
        pass

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
            df = df[_exclude_swapspread_butterflies(df.index)].copy()
            return df
        return None

    elif spread_type == 'NetBasis':
        data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
        if data is None:
            return None
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


# ---------------------------------------------------------------------------
# Duration multiplier helpers
# ---------------------------------------------------------------------------

def _tenor_to_duration(tenor: str) -> float:
    """Convert a tenor string to IRS modified duration.

    Year tenors: swap annuity formula (rate=1.5%, quarterly) matching
    curves/generators/pairs.py swap_dv01 — cannot import directly because
    that module runs main() at module level.
    Month tenors: 0.9 × months/12 short-end proxy, matching _compute_mdur_irs.
    """
    tenor = tenor.strip().lower()
    m = re.match(r'^(\d+(?:\.\d+)?)(m|y)$', tenor)
    if m is None:
        return 1.0
    val, unit = float(m.group(1)), m.group(2)
    if unit == 'm':
        return round(0.9 * val / 12.0, 4)
    # Annuity formula: rate=1.5%, quarterly compounding
    rate, freq = 0.015, 4
    n = int(round(val * freq))
    if n == 0:
        return 0.0
    alpha = 1.0 / freq
    v = 1.0 / (1.0 + rate / freq)
    return round(alpha * v * (1.0 - v ** n) / (1.0 - v), 4)


def _get_duration_mult(instrument: str, spread_type: str) -> float:
    """Return the duration multiplier for a spread instrument.

    SwapSpread (Repo-*, Shi3M-*, Basis-*, FR007S*.IR, etc.)
        Single leg (1 tenor): duration of that tenor.
        Pair       (2 tenors): duration of the last (longer) tenor.
        Fly        (3 tenors): duration of the middle tenor.

    TBondCurve / TBondSwap / CBondCurve / CBondSwap
        Bond IDs. Look up ttm from snapshot; duration ≈ ttm × 0.92.

    All other types: 1.0.
    """
    if spread_type in ('TBondCurve', 'TBondSwap', 'CBondCurve', 'CBondSwap'):
        try:
            snap = load_spread_data(spread_type)
            if isinstance(snap, pd.DataFrame) and instrument in snap.index and 'ttm' in snap.columns:
                ttm = float(snap.loc[instrument, 'ttm'])
                if ttm > 0:
                    return round(ttm * 0.92 if ttm > 1.0 else ttm, 4)
        except Exception:
            pass
        return 1.0

    if spread_type in ('SwapSpread', 'TenorSpread'):
        dash_pos = instrument.find('-')
        if dash_pos == -1:
            m = re.search(r'(\d+[MY])', instrument, re.IGNORECASE)
            if m:
                return _tenor_to_duration(m.group(1).lower())
            return 1.0

        tenor_part = instrument[dash_pos + 1:]
        tenors = re.findall(r'\d+(?:\.\d+)?[mMyY]', tenor_part)
        if len(tenors) == 0:
            return 1.0
        elif len(tenors) == 1:
            return _tenor_to_duration(tenors[0].lower())
        elif len(tenors) == 2:
            return _tenor_to_duration(tenors[1].lower())
        else:
            return _tenor_to_duration(tenors[1].lower())

    return 1.0


def load_carry_roll_timeseries(spread_type: str) -> Optional[pd.DataFrame]:
    """Load daily 3m carry+roll time series for each instrument (in bp)."""
    dir_input = _get_input_dir()

    if spread_type in ('TBondSwap', 'CBondSwap'):
        prefix = 'TBond' if spread_type == 'TBondSwap' else 'CBond'
        data = _load_pickle_safe(dir_input / f'{prefix}-spds.pkl')
        if isinstance(data, dict):
            carry = data.get('BondSwap', {}).get('BondCarry')
            if isinstance(carry, pd.DataFrame) and not carry.empty:
                return carry.apply(pd.to_numeric, errors='coerce')
        return None

    if spread_type in ('TBondCurve', 'CBondCurve'):
        prefix = 'TBond' if spread_type == 'TBondCurve' else 'CBond'
        data = _load_pickle_safe(dir_input / f'{prefix}-spds.pkl')
        if isinstance(data, dict):
            spd = data.get('BondCurve', {}).get('Spread')
            if isinstance(spd, pd.DataFrame) and not spd.empty:
                return spd.apply(pd.to_numeric, errors='coerce') * 100.0
        return None

    if spread_type == 'SwapSpread':
        data = _load_pickle_safe(dir_input / 'IRS-pxspds.pkl')
        if isinstance(data, dict):
            cr = data.get('CarryRoll3m')
            if isinstance(cr, pd.DataFrame) and not cr.empty:
                return cr.apply(pd.to_numeric, errors='coerce')
        return None

    return None


def load_spread_timeseries(spread_type: str) -> Optional[pd.DataFrame]:
    """Load historical spread time series for correlation analysis."""
    dir_input = _get_input_dir()

    alpha_snapshot = _load_pickle_safe(dir_input / 'Alpha-spreadsrt.pkl')
    if alpha_snapshot and isinstance(alpha_snapshot, dict):
        timeseries_data = alpha_snapshot.get('_timeseries', {})
        if isinstance(timeseries_data, dict) and spread_type in timeseries_data:
            ts = timeseries_data[spread_type]
            if isinstance(ts, pd.DataFrame) and not ts.empty:
                if spread_type == 'SwapSpread':
                    cols = pd.Index(ts.columns.astype(str))
                    ts = ts.loc[:, ~cols.str.endswith('.IR')].copy()
                    ts = ts.loc[:, _exclude_swapspread_butterflies(pd.Index(ts.columns))].copy()
                return ts

    if spread_type in ['TBondCurve', 'TBondSwap']:
        filepath = dir_input / 'TBond-spds.pkl'
        data = _load_pickle_safe(filepath)
        if data is None:
            return None
        key = 'BondCurve' if spread_type == 'TBondCurve' else 'BondSwap'
        if isinstance(data, dict) and key in data:
            nested = data[key]
            if isinstance(nested, dict) and 'Spread' in nested:
                result = nested['Spread']
                return result
        return None

    elif spread_type in ['CBondCurve', 'CBondSwap']:
        filepath = dir_input / 'CBond-spds.pkl'
        data = _load_pickle_safe(filepath)
        if data is None:
            return None
        key = 'BondCurve' if spread_type == 'CBondCurve' else 'BondSwap'
        if isinstance(data, dict) and key in data:
            nested = data[key]
            if isinstance(nested, dict) and 'Spread' in nested:
                result = nested['Spread']
                return result
        return None

    elif spread_type == 'PCASpread':
        filepath = dir_input / 'Misc-spds.pkl'
        data = _load_pickle_safe(filepath)
        if data is None:
            return None
        if isinstance(data, dict) and 'PCASpread' in data:
            nested = data['PCASpread']
            if isinstance(nested, dict) and 'Spread' in nested:
                result = nested['Spread']
                return result
        return None

    elif spread_type == 'SwapSpread':
        filepath = dir_input / 'IRS-pxspds.pkl'
        data = _load_pickle_safe(filepath)
        if data is None:
            return None
        if isinstance(data, dict) and 'Spread' in data:
            df_spread = data.get('Spread')
            if isinstance(df_spread, pd.DataFrame) and not df_spread.empty:
                cols = pd.Index(df_spread.columns.astype(str))
                df_spread = df_spread.loc[:, ~cols.str.endswith('.IR')].copy()
                df_spread = df_spread.loc[:, _exclude_swapspread_butterflies(pd.Index(df_spread.columns))].copy()
                return df_spread
        return None

    return None


def load_macro_series(series_name: str) -> Optional[pd.Series]:
    """Load macro time series used for bond-swap style trades."""
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
