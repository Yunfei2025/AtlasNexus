# -*- coding: utf-8 -*-
"""Top-level data loaders: snapshot, timeseries, realtime, and macro series."""

from __future__ import annotations

from typing import Optional
import re

import pandas as pd

from .constants import _build_tenor_spread_timeseries, _exclude_swapspread_butterflies, SPREAD_CATEGORIES
from .io import _get_input_dir, _load_pickle_safe, _normalize_repo_frame


def to_newissue_stage_label(ticker: str) -> str:
    """Convert NewIssue ticker to canonical compact label (e.g. NIBOTR-5Y)."""
    m = re.match(r'^([^:]+):([^:]+):([^|]+)\|(.+)$', str(ticker))
    if not m:
        return str(ticker)
    tenor, stage = m.group(1), m.group(2)
    stage_map = {
        'nib_otr': 'NIBOTR',
        'otr_ofr1': 'OTROFR1',
    }
    return f"{stage_map.get(stage, stage.upper())}-{tenor}"


def load_newissue_stage_timeseries() -> Optional[pd.DataFrame]:
    """Load canonical BondNewIssue stage series stitched across episode history.

    This reconstructs a continuous per-stage history from the backfilled
    ``TBond-newissue.pkl`` / ``CBond-newissue.pkl`` universe files so seasonal
    analytics can plot year-over-year overlays even though the dashboard-facing
    ``BondNewIssue-spds.pkl`` summary is only a compact snapshot.

    Output columns are concise stage keys such as ``NIB_OTR-5Y`` and
    ``OTR_OFR1-10Y``.
    """
    dir_input = _get_input_dir()

    def _read_history(asset_class: str) -> list[pd.DataFrame]:
        data = _load_pickle_safe(dir_input / f'{asset_class}-newissue.pkl')
        if not isinstance(data, dict):
            return []
        out: list[pd.DataFrame] = []
        for tenor_bucket, df in data.items():
            if not isinstance(df, pd.DataFrame) or df.empty:
                continue
            frame = df.copy()
            frame.index = pd.to_datetime(frame.index)

            # OTR/OFR1 has the long-lived history we want for year-over-year overlays.
            if {'ytm_otr', 'ytm_ofr1'}.issubset(frame.columns):
                tmp = frame[['ytm_otr', 'ytm_ofr1']].copy()
                tmp['spread'] = pd.to_numeric(tmp['ytm_otr'], errors='coerce') - pd.to_numeric(tmp['ytm_ofr1'], errors='coerce')
                tmp = tmp.dropna(subset=['spread'])
                if not tmp.empty:
                    tmp['label'] = f'OTROFR1-{tenor_bucket}'
                    tmp['date'] = tmp.index
                    out.append(tmp[['label', 'spread', 'date']])

            # NIB/OTR is typically sparse because the NIB is new; keep any valid points.
            if {'ytm_nib', 'ytm_otr'}.issubset(frame.columns):
                tmp = frame[['ytm_nib', 'ytm_otr', 'instrument_id_nib_otr']].copy()
                tmp['spread'] = pd.to_numeric(tmp['ytm_nib'], errors='coerce') - pd.to_numeric(tmp['ytm_otr'], errors='coerce')
                tmp = tmp.dropna(subset=['spread'])
                if not tmp.empty:
                    tmp['label'] = f'NIBOTR-{tenor_bucket}'
                    tmp['date'] = tmp.index
                    out.append(tmp[['label', 'spread', 'date']])
        return out

    frames = _read_history('TBond') + _read_history('CBond')
    if not frames:
        # Fallback to the compact summary artifact if universe history is missing.
        data = _load_pickle_safe(dir_input / 'BondNewIssue-spds.pkl')
        if not isinstance(data, dict):
            return None
        spread = data.get('BondNewIssue', {}).get('Spread') if isinstance(data.get('BondNewIssue'), dict) else None
        if not isinstance(spread, pd.DataFrame) or spread.empty:
            return None
        spread = spread.apply(pd.to_numeric, errors='coerce')
        return spread

    long_df = pd.concat(frames, axis=0, ignore_index=True)
    if long_df.empty:
        return None

    long_df['date'] = pd.to_datetime(long_df['date'])
    pivot = long_df.pivot_table(index='date', columns='label', values='spread', aggfunc='last').sort_index()
    pivot = pivot.apply(pd.to_numeric, errors='coerce')
    pivot = pivot.dropna(axis=1, how='all')
    return pivot if not pivot.empty else None


def _parse_newissue_stage_label(label: str) -> Optional[tuple[str, str]]:
    """Reverse of ``to_newissue_stage_label``: 'OTROFR1-10Y' -> ('otr_ofr1', '10Y')."""
    m = re.match(r'^(NIBOTR|OTROFR1)-(.+)$', str(label))
    if not m:
        return None
    stage = 'nib_otr' if m.group(1) == 'NIBOTR' else 'otr_ofr1'
    return stage, m.group(2)


def load_newissue_episode_series(label: str) -> list[tuple[pd.Timestamp, str, pd.Series]]:
    """Per-episode BondNewIssue spread paths, indexed by days since the
    episode's identity (leg1/leg2 bond pair) was established.

    Unlike ``load_newissue_stage_timeseries`` (a single calendar-indexed
    column), this splits the history into one series per contiguous run of a
    stable (leg1_id, leg2_id) pair — i.e. one series per issuance/roll episode
    — so callers can overlay "day 0 = new pair" through to the next roll
    (typically a quarter, at most a year) instead of a full calendar year.

    Returns a list of (start_date, leg1_bond_code, series) tuples, sorted
    chronologically. ``leg1_bond_code`` is the newly-issued leg of the pair
    (NIB for nib_otr, OTR for otr_ofr1) — used as the episode legend/label
    since it identifies the bond, unlike the start date.
    """
    parsed = _parse_newissue_stage_label(label)
    if parsed is None:
        return []
    stage, tenor_bucket = parsed
    leg1_col, leg2_col, id1_col, id2_col = (
        ('ytm_otr', 'ytm_ofr1', 'otr_id', 'ofr1_id') if stage == 'otr_ofr1'
        else ('ytm_nib', 'ytm_otr', 'nib_id', 'otr_id')
    )

    dir_input = _get_input_dir()
    episodes: list[tuple[pd.Timestamp, str, pd.Series]] = []
    for asset_class in ('TBond', 'CBond'):
        data = _load_pickle_safe(dir_input / f'{asset_class}-newissue.pkl')
        if not isinstance(data, dict):
            continue
        df = data.get(tenor_bucket)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        needed = {leg1_col, leg2_col, id1_col, id2_col}
        if not needed.issubset(df.columns):
            continue

        frame = df.copy()
        frame.index = pd.to_datetime(frame.index)
        sub = frame[[leg1_col, leg2_col, id1_col, id2_col]].copy()
        sub['spread'] = pd.to_numeric(sub[leg1_col], errors='coerce') - pd.to_numeric(sub[leg2_col], errors='coerce')
        sub = sub.dropna(subset=['spread', id1_col, id2_col])
        if sub.empty:
            continue

        pair_key = sub[id1_col].astype(str) + '|' + sub[id2_col].astype(str)
        episode_id = (pair_key != pair_key.shift()).cumsum()
        for _, grp in sub.groupby(episode_id):
            if len(grp) < 2:
                continue
            start_date = grp.index[0]
            leg1_code = str(grp[id1_col].iloc[0])
            days_since_start = (grp.index - start_date).days
            rebased = grp['spread'].to_numpy() - grp['spread'].iloc[0]
            s = pd.Series(rebased, index=days_since_start)
            s = s[~s.index.duplicated(keep='last')].sort_index()
            episodes.append((start_date, leg1_code, s))

    episodes.sort(key=lambda item: item[0])
    return episodes


def load_spread_data(spread_type: str) -> Optional[pd.DataFrame]:
    """Load spread data for a given type and return DataFrame with required columns."""
    dir_input = _get_input_dir()
    loaded_snap_df = None

    try:
        from curves.refreshers.alpha import get_alpha_spread_table

        snap_df = get_alpha_spread_table(spread_type, dir_input=dir_input)
        if snap_df is not None and isinstance(snap_df, pd.DataFrame) and not snap_df.empty:
            snap_df = _normalize_repo_frame(snap_df)
            if spread_type == 'SwapSpread':
                snap_df = snap_df[~snap_df.index.astype(str).str.endswith('.IR')].copy()
                snap_df = snap_df[_exclude_swapspread_butterflies(snap_df.index)].copy()
            if spread_type != 'TenorSpread':
                return snap_df
            loaded_snap_df = snap_df
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
        loaded_df = loaded_snap_df
        try:
            from curves.utils.loader import loadCNBDTS
            tenor_ts = _build_tenor_spread_timeseries(loadCNBDTS())
            if tenor_ts:
                fallback_df = pd.DataFrame({
                    'spread': {name: pd.to_numeric(series, errors='coerce').dropna().iloc[-1]
                               for name, series in tenor_ts.items()
                               if isinstance(series, pd.Series) and not pd.to_numeric(series, errors='coerce').dropna().empty}
                })
                if loaded_df is not None and not loaded_df.empty:
                    return loaded_df.reindex(columns=loaded_df.columns.union(fallback_df.columns)).combine_first(fallback_df)
                loaded_df = fallback_df
        except Exception:
            pass
        if loaded_df is not None and not loaded_df.empty:
            return loaded_df
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

    elif spread_type == 'BondNewIssue':
        data = _load_pickle_safe(dir_input / 'BondNewIssue-spds.pkl')
        if data is None:
            return None
        return data.get('BondNewIssue', {}).get('StatInfo')

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
        #   XsYs (CGB-5s10s, CDB-5s10s)  BUY=steepener: carry = Y_short - Y_long = -spread_%
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
        return f'{inst}-OTR'
    if spread_type in ('TBondSwap', 'CBondSwap'):
        return f'{inst}-Swp'
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
        # Primary: pre-computed Tenor-spds.pkl is the canonical source of truth
        # (same source as the Spread sub-tab / dropdown via load_spread_data).
        loaded_df = None
        tenor_spds = _load_pickle_safe(dir_input / 'Tenor-spds.pkl')
        if isinstance(tenor_spds, dict):
            spd = tenor_spds.get('TenorSpread', {}).get('Spread')
            if isinstance(spd, pd.DataFrame) and not spd.empty:
                loaded_df = spd.apply(pd.to_numeric, errors='coerce')

        # Fallback: rebuild from database-px.pkl via loadCNBDTS if the pkl is unavailable.
        try:
            from curves.utils.loader import loadCNBDTS
            env = loadCNBDTS()
            tenor_ts = _build_tenor_spread_timeseries(env)
            if tenor_ts:
                df = pd.DataFrame(tenor_ts)
                df = df.apply(pd.to_numeric, errors='coerce')
                if loaded_df is not None and not loaded_df.empty:
                    return loaded_df.reindex(columns=loaded_df.columns.union(df.columns)).combine_first(df)
                return df
        except Exception:
            pass

        if loaded_df is not None and not loaded_df.empty:
            return loaded_df

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

    elif spread_type == 'BondNewIssue':
        return load_newissue_stage_timeseries()

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
        data = _load_pickle_safe(dir_input / 'IRS-spdsrt.pkl')
        if not isinstance(data, dict):
            return None
        return _normalize_repo_frame(data.get('spreads'))

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


def get_realtime_spread_bp(spread_type: str, instrument: str) -> Optional[float]:
    """Return the latest quote spread in basis points.

    Prefer bid/ofr-derived mid quotes. For close-yield spread products such as
    TenorSpread, use the latest close-yield spread when no realtime mid-quote
    artifact exists. Keep this separate from ``load_spread_data`` so UI labels
    do not accidentally use a statistical/model spread.
    """
    try:
        realtime = load_realtime_spreads(spread_type)
        if isinstance(realtime, pd.DataFrame) and instrument in realtime.index:
            row = realtime.loc[instrument]
            # IRS-spdsrt keeps both the statistical spread and the current quote
            # spread. Always use the latter for live labels.
            value_column = 'QtPx' if spread_type == 'SwapSpread' else 'spread'
            value = pd.to_numeric(row.get(value_column), errors='coerce')
            if pd.notna(value):
                return float(value) * 100.0

        if spread_type == 'TenorSpread':
            from curves.utils.loader import loadCNBDTS

            tenor_ts = _build_tenor_spread_timeseries(loadCNBDTS())
            series = tenor_ts.get(instrument)
            if isinstance(series, pd.Series):
                close_value = pd.to_numeric(series, errors='coerce').dropna()
                if not close_value.empty:
                    return float(close_value.iloc[-1]) * 100.0
        return None
    except Exception:
        return None


def get_spread_style(spread_type: str) -> str:
    """Get the trading style for a spread type."""
    for cat, info in SPREAD_CATEGORIES.items():
        if spread_type in info['types']:
            return info['style']
    return 'Unknown'
