# -*- coding: utf-8 -*-
"""Duration multiplier, borrow cost, and tenor/TTM display helpers."""

from __future__ import annotations

import re
from typing import Optional

import pandas as pd

from .io import _get_input_dir, _load_pickle_safe
from .loaders import load_spread_data


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

        # Parse tenor spread ID like "CGB-10s30s", "CDB-5s10s", "CDBCGB-10y", "LGBCGB-10y"
        if instrument.upper().startswith('LGBCGB-'):
            m3 = re.search(r'-(\d+)y$', instrument, re.IGNORECASE)
            if not m3:
                return None, None
            tenor_str = m3.group(1)
            cgb = env.get('CGB', {})
            lgb = env.get('LGB', {})
            short_val = cgb.get(f"中债国债到期收益率:{tenor_str}年")
            long_val = lgb.get(f"中国:地方政府债到期收益率(AAA):{tenor_str}年") if isinstance(lgb, pd.DataFrame) else None
            if short_val is not None and long_val is not None:
                if isinstance(short_val, pd.Series):
                    short_val = float(short_val.iloc[-1])
                if isinstance(long_val, pd.Series):
                    long_val = float(long_val.iloc[-1])
                return float(short_val), float(long_val)
            return None, None

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
