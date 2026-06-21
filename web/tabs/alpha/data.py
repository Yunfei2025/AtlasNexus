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
# Theme / Style constants — mirrors web/assets/colors.css design tokens.
# Alpha Book accent is amber (--accent-amber), not blue.
# ---------------------------------------------------------------------------
THEME = {
    'bg_main': '#0e1d3a',     # --navy-800 / --surface-sunken-ish working bg
    'bg_card': '#122a4c',     # --navy-700 / --surface-panel
    'bg_raised': '#102544',   # --navy-750 / --surface-raised
    'bg_input': '#17345c',    # --navy-600 / --surface-input
    'text_main': '#e9eef8',   # --text-primary
    'text_sub': '#a4b6d2',    # --text-secondary
    'border': '#2a517f',      # --border-strong
    'border_sub': '#1e3a5f',  # --border-default
    'accent': '#e0a23c',      # --accent-amber (Alpha Book accent)
    'blue': '#3d8bd4',        # --accent-blue (Run/Refresh actions)
    'cyan': '#45b6e6',        # --accent-cyan
    'purple': '#7c70d6',      # --accent-purple (checkbox/radio/slider accent)
    'success': '#2f9d6b',     # --accent-green
    'warning': '#e0a23c',     # --accent-amber
    'danger': '#d56b6b',      # --negative
    'table_header': '#17345c',
    'table_row_even': '#122a4c',
    'table_row_odd': '#0e1d3a',
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
        'label': 'Curve & Cross-Asset Spreads',
        'types': ['TenorSpread'],
        'description': 'Curve slope, cross-curve, and bond/CD-vs-repo spreads (e.g. 5s10s, CDBCGB, CGBRepo7d)',
        'style': 'Mixed',
    },
    'Bond-Futures': {
        'label': 'Bond vs Futures (IRR − Repo)',
        'types': ['NetBasis'],
        'description': 'CTD implied repo (IRR) minus FR007 funding cost',
        'style': 'Carry',
    },
    'Futures-Term': {
        'label': 'Futures Term Basis',
        'types': ['TermBasis'],
        'description': 'Near vs far futures contract spread',
        'style': 'MeanReversion',
    },
    'Futures-Swap': {
        'label': 'Futures vs Swap (FYTM − IRS)',
        'types': ['FuturesSwap'],
        'description': 'Futures implied YTM minus matched-tenor FR007 IRS rate',
        'style': 'Mixed',
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
_SWAP_SPREAD_BUTTERFLY_PATTERN = re.compile(r"^(?:Repo7d|Shi3M)-(?:\d+[my]){3,}$", re.IGNORECASE)

# Global state for diversified trade recommendations
DIVERSIFIED_TRADE_RECOMMENDATIONS = {
    'trades': [],
    'timestamp': None,
}


def _exclude_swapspread_butterflies(labels: pd.Index | pd.Series):
    """Return mask that excludes IRS butterfly IDs such as Repo7d-1y2y5y or Shi3M-3m6m9m."""
    text = labels.astype(str)
    return ~text.str.match(_SWAP_SPREAD_BUTTERFLY_PATTERN)


def _build_tenor_spread_timeseries(cnbd_data: object) -> dict[str, pd.Series]:
    """Build tenor spread time series from CNBD key-rate history."""
    if not isinstance(cnbd_data, dict) or 'CGB' not in cnbd_data or 'CDB' not in cnbd_data:
        return {}
    try:
        result = {
            'CGB-5s10s': cnbd_data['CGB']['中债国债到期收益率:10年'] - cnbd_data['CGB']['中债国债到期收益率:5年'],
            'CGB-10s30s': cnbd_data['CGB']['中债国债到期收益率:30年'] - cnbd_data['CGB']['中债国债到期收益率:10年'],
            'CDB-5s10s': cnbd_data['CDB']['中债国开债到期收益率:10年'] - cnbd_data['CDB']['中债国开债到期收益率:5年'],
            'CDB-10s30s': cnbd_data['CDB']['中债国开债到期收益率:30年'] - cnbd_data['CDB']['中债国开债到期收益率:10年'],
            'CDBCGB-5y': cnbd_data['CDB']['中债国开债到期收益率:5年'] - cnbd_data['CGB']['中债国债到期收益率:5年'],
            'CDBCGB-10y': cnbd_data['CDB']['中债国开债到期收益率:10年'] - cnbd_data['CGB']['中债国债到期收益率:10年'],
            'CDBCGB-30y': cnbd_data['CDB']['中债国开债到期收益率:30年'] - cnbd_data['CGB']['中债国债到期收益率:30年'],
        }

        swap_ts = cnbd_data.get('SwapTS')
        icp = cnbd_data.get('ICP')

        if isinstance(swap_ts, pd.DataFrame):
            cgb = cnbd_data['CGB']
            if 'FR007S1Y.IR' in swap_ts.columns and '中债国债到期收益率:1年' in cgb.columns:
                result['CGBRepo7d-1y'] = cgb['中债国债到期收益率:1年'] - swap_ts['FR007S1Y.IR']
            if 'FR007S2Y.IR' in swap_ts.columns and '中债国债到期收益率:2年' in cgb.columns:
                result['CGBRepo7d-2y'] = cgb['中债国债到期收益率:2年'] - swap_ts['FR007S2Y.IR']
            if 'FR007S5Y.IR' in swap_ts.columns and '中债国债到期收益率:5年' in cgb.columns:
                result['CGBRepo7d-5y'] = cgb['中债国债到期收益率:5年'] - swap_ts['FR007S5Y.IR']
            if 'FR007S10Y.IR' in swap_ts.columns and '中债国债到期收益率:10年' in cgb.columns:
                result['CGBRepo7d-10y'] = cgb['中债国债到期收益率:10年'] - swap_ts['FR007S10Y.IR']

            if isinstance(icp, pd.DataFrame):
                if 'FR007S3M.IR' in swap_ts.columns and '中债商业银行同业存单到期收益率(AAA):3个月' in icp.columns:
                    result['ICPRepo7d-3m'] = icp['中债商业银行同业存单到期收益率(AAA):3个月'] - swap_ts['FR007S3M.IR']
                if 'FR007S6M.IR' in swap_ts.columns and '中债商业银行同业存单到期收益率(AAA):6个月' in icp.columns:
                    result['ICPRepo7d-6m'] = icp['中债商业银行同业存单到期收益率(AAA):6个月'] - swap_ts['FR007S6M.IR']
                if 'FR007S9M.IR' in swap_ts.columns and '中债商业银行同业存单到期收益率(AAA):9个月' in icp.columns:
                    result['ICPRepo7d-9m'] = icp['中债商业银行同业存单到期收益率(AAA):9个月'] - swap_ts['FR007S9M.IR']
                if 'FR007S1Y.IR' in swap_ts.columns and '中债商业银行同业存单到期收益率(AAA):1年' in icp.columns:
                    result['ICPRepo7d-1y'] = icp['中债商业银行同业存单到期收益率(AAA):1年'] - swap_ts['FR007S1Y.IR']

        return result
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Data Loading Utilities
# ---------------------------------------------------------------------------

def _get_input_dir() -> Path:
    try:
        from settings.paths import DIR_INPUT
        return Path(DIR_INPUT)
    except ImportError:
        return Path(__file__).parent.parent.parent / 'input'


# ---------------------------------------------------------------------------
# Repo-label normalizer (applied once per file load, not per call site)
# ---------------------------------------------------------------------------

def _normalize_repo_label(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r'^Repo-', 'Repo7d-', value, flags=re.IGNORECASE)
    return value


def _normalize_repo_obj(obj: Any) -> Any:
    if isinstance(obj, pd.DataFrame):
        out = obj.copy()
        if out.index.dtype == object:
            out.index = out.index.map(_normalize_repo_label)
        if out.columns.dtype == object:
            out.columns = out.columns.map(_normalize_repo_label)
        return out
    if isinstance(obj, pd.Series):
        out = obj.copy()
        if out.index.dtype == object:
            out.index = out.index.map(_normalize_repo_label)
        out.name = _normalize_repo_label(out.name)
        return out
    if isinstance(obj, dict):
        return {_normalize_repo_label(k): _normalize_repo_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalize_repo_obj(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(_normalize_repo_obj(v) for v in obj)
    return obj


# ---------------------------------------------------------------------------
# mtime-keyed pickle cache  (module-level, shared across all callers)
# ---------------------------------------------------------------------------

_PICKLE_CACHE: dict[str, tuple[float, Any]] = {}


def _load_pickle_cached(filepath: Path) -> Optional[Any]:
    """Load a pickle file, caching the result keyed by file mtime.

    The Repo-label normalization is applied once per file load and the
    normalized object is stored in the cache, so callers never pay for it.
    """
    path_str = str(filepath)
    try:
        mtime = filepath.stat().st_mtime
    except FileNotFoundError:
        return None

    cached = _PICKLE_CACHE.get(path_str)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    try:
        with open(filepath, 'rb') as f:
            obj = pickle.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        try:
            obj = pd.read_pickle(filepath)
        except Exception as e2:
            print(f"Fallback also failed for {filepath}: {e2}")
            return None

    obj = _normalize_repo_obj(obj)
    _PICKLE_CACHE[path_str] = (mtime, obj)
    return obj


def _load_pickle_safe(filepath: Path) -> Optional[Any]:
    """Thin wrapper kept for call-site compatibility; delegates to the mtime cache."""
    return _load_pickle_cached(filepath)


def _normalize_repo_frame(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if not isinstance(df, pd.DataFrame):
        return df
    out = df.copy()
    if out.index.dtype == object:
        out.index = out.index.map(lambda x: re.sub(r'^Repo-', 'Repo7d-', str(x), flags=re.IGNORECASE))
    if out.columns.dtype == object:
        out.columns = out.columns.map(lambda x: re.sub(r'^Repo-', 'Repo7d-', str(x), flags=re.IGNORECASE))
    return out


def load_spread_data(spread_type: str) -> Optional[pd.DataFrame]:
    """Load spread data for a given type and return DataFrame with required columns."""
    dir_input = _get_input_dir()

    try:
        from curves.refreshers.alpha import get_alpha_spread_table

        snap_df = get_alpha_spread_table(spread_type, dir_input=dir_input)
        if snap_df is not None and isinstance(snap_df, pd.DataFrame) and not snap_df.empty:
            snap_df = _normalize_repo_frame(snap_df)
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

    elif spread_type == 'TenorSpread':
        try:
            from curves.utils.loader import loadCNBDTS
            tenor_ts = _build_tenor_spread_timeseries(loadCNBDTS())
            if tenor_ts:
                df = pd.DataFrame({
                    'spread': {name: pd.to_numeric(series, errors='coerce').dropna().iloc[-1]
                               for name, series in tenor_ts.items()
                               if isinstance(series, pd.Series) and not pd.to_numeric(series, errors='coerce').dropna().empty}
                })
                if not df.empty:
                    return df
        except Exception:
            pass
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

    elif spread_type == 'FuturesSwap':
        data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
        if data is None:
            return None
        fs = data.get('FuturesSwap', {})
        if not isinstance(fs, dict) or not fs:
            return None
        frames = []
        for ctype, cdata in fs.items():
            if isinstance(cdata, dict) and 'StatInfo' in cdata:
                df = cdata['StatInfo'].copy()
                df['ctype'] = ctype
                frames.append(df)
        return pd.concat(frames, axis=0) if frames else None

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


def _get_duration_mult(
    instrument: str,
    spread_type: str,
    snap: Optional[pd.DataFrame] = None,
) -> float:
    """Return the duration multiplier for a spread instrument.

    SwapSpread (Repo7d-*, Shi3M-*, Basis-*, FR007S*.IR, etc.)
        Single leg (1 tenor): duration of that tenor.
        Pair       (2 tenors): duration of the last (longer) tenor.
        Fly        (3 tenors): duration of the middle tenor.

    TBondCurve / TBondSwap / CBondCurve / CBondSwap
        Bond IDs. Look up ttm from snapshot; duration ≈ ttm × 0.92.
        Pass *snap* (pre-loaded via ``load_spread_data``) to avoid a pickle
        read per row when called inside a DataFrame.apply loop.

    All other types: 1.0.
    """
    if spread_type in ('TBondCurve', 'TBondSwap', 'CBondCurve', 'CBondSwap'):
        try:
            if snap is None:
                snap = load_spread_data(spread_type)
            if isinstance(snap, pd.DataFrame) and instrument in snap.index and 'ttm' in snap.columns:
                ttm = float(snap.loc[instrument, 'ttm'])
                if ttm > 0:
                    return round(ttm * 0.92 if ttm > 1.0 else ttm, 4)
        except Exception:
            pass
        return 1.0

    if spread_type in ('NetBasis', 'TermBasis'):
        # instrument is e.g. 'T-NQ1' or a bond code; use contract-type TTM proxy
        _CTYPE_TENOR = {'T': 10.0, 'TL': 30.0, 'TF': 5.0, 'TS': 2.0}
        ctype = instrument.split('-')[0] if '-' in instrument else instrument
        tenor = _CTYPE_TENOR.get(ctype, 5.0)
        return round(tenor * 0.92, 4)

    if spread_type == 'FuturesSwap':
        # instrument is contract type: T / TF / TS / TL
        _CTYPE_TENOR = {'T': 10.0, 'TL': 30.0, 'TF': 5.0, 'TS': 2.0}
        tenor = _CTYPE_TENOR.get(instrument, 5.0)
        return round(tenor * 0.92, 4)

    if spread_type == 'TenorSpread':
        # TenorSpread: PnL ≈ duration_first_leg × Δspread (DV01-hedged position)
        # e.g. CGB-10s30s → first leg = 10y → use duration of shorter tenor
        # The 's' suffix is used for years in tenor spread IDs (e.g. 10s = 10 years)
        dash_pos = instrument.find('-')
        tenor_part = instrument[dash_pos + 1:] if dash_pos != -1 else instrument
        # Match m/M/y/Y suffixes (SwapSpread style) or s/S suffix (TenorSpread style = years)
        tenors_my = re.findall(r'\d+(?:\.\d+)?[mMyY]', tenor_part)
        if tenors_my:
            return _tenor_to_duration(tenors_my[0].lower())
        # Fall back to 's' suffix: treat Ns as Ny (N years)
        tenors_s = re.findall(r'(\d+(?:\.\d+)?)s', tenor_part, re.IGNORECASE)
        if tenors_s:
            return _tenor_to_duration(tenors_s[0] + 'y')
        return 1.0

    if spread_type == 'SwapSpread':
        # SwapSpread: PnL ≈ duration_second_leg × Δspread (longer/paying leg drives DV01)
        # e.g. Repo7d-1y3y → second leg = 3y; Basis-1y → single tenor = 1y
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
            return _tenor_to_duration(tenors[1].lower())  # second (longer) leg
        else:
            return _tenor_to_duration(tenors[1].lower())  # middle for flies

    return 1.0


def _get_borrow_cost_annual_bp(spread_type: str, instrument: str) -> tuple[float, float]:
    """Return (long_borrow_bp, short_borrow_bp) annual repo/borrow cost in bp.

    TenorSpread (e.g. CGB-10s30s, CDB-5s10s):
        LONG  the spread = short the LONGER-tenor bond  → long_borrow_bp  = BORROW_COST[longer]
        SHORT the spread = short the SHORTER-tenor bond → short_borrow_bp = BORROW_COST[shorter]
    BondCurve / BondSwap:
        Symmetric — same cost for both directions based on the bond's ttm bucket.
    Others:
        (0.0, 0.0)
    """
    try:
        from settings.fixed_income import BondConfig
        bc = BondConfig.BORROW_COST  # {5: 10, 10: 40, 20: 100, 30: 120}
    except Exception:
        return 0.0, 0.0

    def _bucket(years: float) -> float:
        if years <= 5:
            return float(bc.get(5, 10))
        elif years <= 10:
            return float(bc.get(10, 40))
        elif years <= 20:
            return float(bc.get(20, 100))
        else:
            return float(bc.get(30, 120))

    if spread_type == 'TenorSpread':
        # 'CGB-10s30s' → shorter=10, longer=30
        m = re.search(r'(\d+)s(\d+)s?$', instrument, re.IGNORECASE)
        if m:
            shorter = float(m.group(1))
            longer  = float(m.group(2))
            return _bucket(longer), _bucket(shorter)
        # 'CDBCGB-30y' → single tenor, symmetric
        m2 = re.search(r'-(\d+)y$', instrument, re.IGNORECASE)
        if m2:
            cost = _bucket(float(m2.group(1)))
            return cost, cost
        return 0.0, 0.0

    if spread_type in ('TBondCurve', 'CBondCurve', 'TBondSwap', 'CBondSwap'):
        try:
            snap = load_spread_data(spread_type)
            if isinstance(snap, pd.DataFrame) and instrument in snap.index and 'ttm' in snap.columns:
                ttm = float(snap.loc[instrument, 'ttm'])
                if ttm > 0:
                    cost = _bucket(ttm)
                    return cost, cost
        except Exception:
            pass
        return 0.0, 0.0

    if spread_type == 'NetBasis':
        # LONG net basis = long cash bond + short futures
        # Financing cost = bond borrow cost for the long leg
        # instrument e.g. 'T-NQ1' → use T=10y bucket
        _CTYPE_TENOR = {'T': 10.0, 'TL': 30.0, 'TF': 5.0, 'TS': 2.0}
        ctype = instrument.split('-')[0] if '-' in instrument else instrument
        tenor = _CTYPE_TENOR.get(ctype, 5.0)
        cost  = _bucket(tenor)
        return cost, cost   # symmetric: borrow bond regardless of direction

    if spread_type == 'FuturesSwap':
        # LONG futures-swap = long futures + pay fixed IRS
        # No physical bond borrow; cost is in the IRS fixed rate (already in spread)
        return 0.0, 0.0

    return 0.0, 0.0


def _get_tenor_yields_for_spread(instrument: str) -> tuple[Optional[float], Optional[float]]:
    """Extract short-tenor and long-tenor yields (in %) for a TenorSpread instrument.

    Returns: (short_tenor_yield, long_tenor_yield) or (None, None) if not available.
    Example: CGB-10s30s → (y_10y, y_30y)
    """
    try:
        from curves.utils.loader import loadCNBDTS
        env = loadCNBDTS()

        # Parse tenor spread ID like "CGB-10s30s", "CDB-5s10s", "CDBCGB-10y"
        if 'CGB-' in instrument or 'CDB-' in instrument:
            bond_type = 'CGB' if 'CGB-' in instrument else 'CDB'
            tenor_data = env.get(bond_type, {})

            # Extract tenor values
            m = re.search(r'(\d+)s(\d+)s?$', instrument, re.IGNORECASE)
            if m:
                short_tenor = f"中债{'国债' if bond_type == 'CGB' else '国开'}到期收益率:{m.group(1)}年"
                long_tenor = f"中债{'国债' if bond_type == 'CGB' else '国开'}到期收益率:{m.group(2)}年"
            else:
                m2 = re.search(r'-(\d+)y$', instrument, re.IGNORECASE)
                if m2:  # CDBCGB-10y (symmetric)
                    tenor_str = m2.group(1)
                    short_tenor = f"中债国债到期收益率:{tenor_str}年"
                    long_tenor = f"中债国开债到期收益率:{tenor_str}年"
                else:
                    return None, None

            # Get the latest values
            short_val = tenor_data.get(short_tenor)
            long_val = tenor_data.get(long_tenor)
            if short_val is not None and long_val is not None:
                # Convert to latest value if Series
                if isinstance(short_val, pd.Series):
                    short_val = float(short_val.iloc[-1])
                if isinstance(long_val, pd.Series):
                    long_val = float(long_val.iloc[-1])
                return float(short_val), float(long_val)
    except Exception:
        pass

    return None, None


def _get_current_fr007_bp() -> Optional[float]:
    """Get current FR007 rate in basis points from market data.

    Loads the latest FR007.IR value from database-px.pkl['IRS'] and converts
    from percentage to basis points. Returns None if not available.
    """
    try:
        dir_input = _get_input_dir()
        db_path = dir_input / 'database-px.pkl'
        if not db_path.exists():
            return None
        data = _load_pickle_safe(db_path)
        if isinstance(data, dict) and 'IRS' in data:
            irs_df = data['IRS']
            if isinstance(irs_df, pd.DataFrame) and 'FR007.IR' in irs_df.columns:
                val = irs_df['FR007.IR'].dropna().iloc[-1] if not irs_df['FR007.IR'].dropna().empty else None
                if val is not None and pd.notna(val):
                    return float(val) * 100.0  # Convert % to bp
    except Exception:
        pass
    return None


def _get_ttm_display(spread_type: str, instrument: str) -> Optional[float]:
    """Return TTM (years) for the Candidates table TTM column.

    BondCurve / BondSwap : bond TTM from snapshot.
    TenorSpread           : first-leg tenor (e.g. 10 for CGB-10s30s, 10 for CDBCGB-10y).
    SwapSpread            : second-leg tenor for pairs and flies (e.g. 2 for Repo7d-1y2y,
                            2 for Repo7d-1y2y, 0.75 for Shi3M-6m9m).
    All other types       : None.
    """
    def _tenor_to_yr(t: str) -> Optional[float]:
        t = t.strip().lower()
        m = re.match(r'^(\d+(?:\.\d+)?)(m|y)$', t)
        if not m:
            return None
        val, unit = float(m.group(1)), m.group(2)
        return round(val / 12.0 if unit == 'm' else val, 2)

    if spread_type in ('TBondCurve', 'CBondCurve', 'TBondSwap', 'CBondSwap'):
        try:
            snap = load_spread_data(spread_type)
            if isinstance(snap, pd.DataFrame) and instrument in snap.index and 'ttm' in snap.columns:
                ttm = float(snap.loc[instrument, 'ttm'])
                if ttm > 0:
                    return round(ttm, 1)
        except Exception:
            pass
        return None

    if spread_type == 'TenorSpread':
        # CGB-10s30s → first leg = 10
        m = re.search(r'(\d+)s(\d+)s?$', instrument, re.IGNORECASE)
        if m:
            return float(m.group(1))
        # CDBCGB-10y → 10
        m2 = re.search(r'-(\d+)y$', instrument, re.IGNORECASE)
        if m2:
            return float(m2.group(1))
        return None

    if spread_type == 'SwapSpread':
        dash = instrument.find('-')
        if dash == -1:
            return None
        tenors = re.findall(r'\d+(?:\.\d+)?[mMyY]', instrument[dash + 1:])
        if len(tenors) >= 1:
            # Single tenor (Basis-1y): use it; pairs/flies (Basis-1y2y, Repo7d-1y2y5y): use second leg
            return _tenor_to_yr(tenors[1] if len(tenors) >= 2 else tenors[0])
        return None

    return None


def load_carry_roll_timeseries(spread_type: str) -> Optional[pd.DataFrame]:
    """Load daily 3m carry+roll time series for each instrument (in bp)."""
    dir_input = _get_input_dir()

    if spread_type in ('TBondSwap', 'CBondSwap'):
        prefix = 'TBond' if spread_type == 'TBondSwap' else 'CBond'
        data = _load_pickle_safe(dir_input / f'{prefix}-spds.pkl')
        if isinstance(data, dict):
            carry = data.get('BondSwap', {}).get('BondCarry')
            if isinstance(carry, pd.DataFrame) and not carry.empty:
                # BondCarry = (bond_yield - FR007S3M) * 100 = annual spread in bp.
                # Convert to 3m carry in % to match spread_ts units (also in %):
                #   bp → % : / 100
                #   annual → 3m : * (90/360)
                #   combined: / 400
                return carry.apply(pd.to_numeric, errors='coerce') / 400.0
        return None

    if spread_type in ('TBondCurve', 'CBondCurve'):
        prefix = 'TBond' if spread_type == 'TBondCurve' else 'CBond'
        data = _load_pickle_safe(dir_input / f'{prefix}-spds.pkl')
        if isinstance(data, dict):
            spd = data.get('BondCurve', {}).get('Spread')
            if isinstance(spd, pd.DataFrame) and not spd.empty:
                # Spread is annual yield difference in % (e.g. 0.01 = 1bp).
                # Convert to 3m carry in % to match price_pnl units:
                #   annual % → 3m % : * (90/360)
                return spd.apply(pd.to_numeric, errors='coerce') * (90.0 / 360.0)
        return None

    if spread_type == 'SwapSpread':
        data = _load_pickle_safe(dir_input / 'IRS-pxspds.pkl')
        if isinstance(data, dict):
            cr = data.get('CarryRoll3m')
            if isinstance(cr, pd.DataFrame) and not cr.empty:
                # CarryRoll3m is already stored as 3m carry in % (carry3m + roll3m
                # from generators/irs.py are in % after / 100 conversion).
                # No further scaling needed.
                return cr.apply(pd.to_numeric, errors='coerce')
        return None

    if spread_type == 'TenorSpread':
        # Primary: read from pre-computed Tenor-spds.pkl written by StatGenerator.
        tenor_spds = _load_pickle_safe(dir_input / 'Tenor-spds.pkl')
        if isinstance(tenor_spds, dict):
            cr = tenor_spds.get('TenorSpread', {}).get('CarryRoll3m')
            if isinstance(cr, pd.DataFrame) and not cr.empty:
                return cr.apply(pd.to_numeric, errors='coerce')

        # Fallback: compute on-the-fly from database-px.pkl.
        # Carry component in 3m %, to match spread_ts units (raw CNBD yield diff in %).
        # Convention for _carry_accrual: ts[t] = 3m carry in %, so that
        #   carry_income = position * sum(ts[t0:t1]) / 90  is in %
        # and the final *100 in run_spread_backtest converts to bp.
        #
        # Annual carry for each structure:
        #   XsYs (CGB-10s30s etc.)  BUY=steepener: carry = Y_short - Y_long = -spread_%
        #   CDBCGB cross-sector      BUY=long CDB : carry = Y_CDB - Y_CGB   = +spread_%
        # Convert annual % → 3m %: multiply by 90/360.
        # Negate XsYs (\d+s\d+) columns; CDBCGB stays positive.
        try:
            db = _load_pickle_safe(dir_input / 'database-px.pkl')
            if isinstance(db, dict) and 'CGB' in db and 'CDB' in db:
                tenor_ts = _build_tenor_spread_timeseries(db)
                if tenor_ts:
                    df = pd.DataFrame(tenor_ts).apply(pd.to_numeric, errors='coerce') * (90.0 / 360.0)
                    for col in df.columns:
                        if re.search(r'\d+s\d+', col, re.IGNORECASE):
                            df[col] = -df[col]
                    return df
        except Exception:
            pass
        return None

    return None


def display_key(spread_type: str, inst: str) -> str:
    """Return a short, human-readable column key for correlation matrices.

    Bond IDs share the same code across Curve/Swap types, so the suffix
    disambiguates.  Futures types (NetBasis / TermBasis / FuturesSwap) all use
    T/TF/TS/TL, so a suffix is mandatory there too.
    """
    if spread_type in ('TBondCurve', 'CBondCurve'):
        base = inst.replace('.IB', '')
        return f'{base}-OTR'
    if spread_type in ('TBondSwap', 'CBondSwap'):
        base = inst.replace('.IB', '')
        return f'{base}-Swp'
    if spread_type == 'NetBasis':
        return f'{inst}-Basis'
    if spread_type == 'TermBasis':
        return f'{inst}-Cal'
    if spread_type == 'FuturesSwap':
        return f'{inst}-FtSwp'
    # All other types (SwapSpread, TenorSpread, PCASpread …) have unique IDs —
    # return as-is so existing behaviour is unchanged.
    return inst


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
                result = _normalize_repo_frame(nested['Spread'])
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
                result = _normalize_repo_frame(nested['Spread'])
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
                result = _normalize_repo_frame(nested['Spread'])
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
                df_spread = _normalize_repo_frame(df_spread)
                cols = pd.Index(df_spread.columns.astype(str))
                df_spread = df_spread.loc[:, ~cols.str.endswith('.IR')].copy()
                df_spread = df_spread.loc[:, _exclude_swapspread_butterflies(pd.Index(df_spread.columns))].copy()
                return df_spread
        return None

    elif spread_type == 'TenorSpread':
        # Primary: compute from database-px.pkl via loadCNBDTS for full historical data.
        try:
            from curves.utils.loader import loadCNBDTS
            env = loadCNBDTS()
            tenor_ts = _build_tenor_spread_timeseries(env)
            if tenor_ts:
                df = pd.DataFrame(tenor_ts)
                return df.apply(pd.to_numeric, errors='coerce')
        except Exception:
            pass

        # Fallback: read from pre-computed Tenor-spds.pkl (limited to ~1 year).
        tenor_spds = _load_pickle_safe(dir_input / 'Tenor-spds.pkl')
        if isinstance(tenor_spds, dict):
            spd = tenor_spds.get('TenorSpread', {}).get('Spread')
            if isinstance(spd, pd.DataFrame) and not spd.empty:
                return spd.apply(pd.to_numeric, errors='coerce')

        return None

    elif spread_type == 'NetBasis':
        data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
        if data is None:
            return None
        nb_data = data.get('NetBasis', {})
        if not isinstance(nb_data, dict):
            return None
        frames = []
        for ctype, cdata in nb_data.items():
            if isinstance(cdata, dict) and 'Spread' in cdata:
                sp = cdata['Spread']
                if isinstance(sp, pd.DataFrame) and not sp.empty:
                    frames.append(sp)
        return pd.concat(frames, axis=1) if frames else None

    elif spread_type == 'TermBasis':
        data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
        if data is None:
            return None
        tb = data.get('TermBasis', {})
        if isinstance(tb, dict) and 'Spread' in tb:
            sp = tb['Spread']
            return sp if isinstance(sp, pd.DataFrame) and not sp.empty else None
        return None

    elif spread_type == 'FuturesSwap':
        data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
        if data is None:
            return None
        fs = data.get('FuturesSwap', {})
        if not isinstance(fs, dict):
            return None
        frames = []
        for ctype, cdata in fs.items():
            if isinstance(cdata, dict) and 'Spread' in cdata:
                sp = cdata['Spread']
                if isinstance(sp, pd.DataFrame) and not sp.empty:
                    frames.append(sp)
        return pd.concat(frames, axis=1) if frames else None

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
        return _normalize_repo_frame(data.get(key))

    elif spread_type in ['CBondCurve', 'CBondSwap']:
        data = _load_pickle_safe(dir_input / 'CBond-spdsrt.pkl')
        if data is None:
            return None
        key = 'BondCurve' if spread_type == 'CBondCurve' else 'BondSwap'
        return _normalize_repo_frame(data.get(key))

    elif spread_type == 'SwapSpread':
        return _normalize_repo_frame(_load_pickle_safe(dir_input / 'IRS-spdsrt.pkl'))

    elif spread_type in ['NetBasis', 'TermBasis']:
        return _load_pickle_safe(dir_input / 'futures-spdsrt.pkl')

    elif spread_type == 'FuturesSwap':
        data = _load_pickle_safe(dir_input / 'futures-spds.pkl')
        if data is None:
            return None
        fs = data.get('FuturesSwap', {})
        if not isinstance(fs, dict):
            return None
        frames = []
        for ctype, cdata in fs.items():
            if isinstance(cdata, dict) and 'Spread' in cdata:
                sp = cdata['Spread']
                if isinstance(sp, pd.DataFrame) and not sp.empty:
                    frames.append(sp)
        return pd.concat(frames, axis=1) if frames else None

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
