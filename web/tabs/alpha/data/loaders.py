# -*- coding: utf-8 -*-
"""Top-level data loaders: snapshot, timeseries, realtime, and macro series."""

from __future__ import annotations

from typing import Optional

import pandas as pd

from .constants import _build_tenor_spread_timeseries, _exclude_swapspread_butterflies, SPREAD_CATEGORIES
from .io import _get_input_dir, _load_pickle_safe, _normalize_repo_frame


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
            import re
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
