# -*- coding: utf-8 -*-
"""Shared, non-Dash helper functions used by the Risk / Summary callback
modules (risk_books.py, risk_tickets.py, risk_dashboard.py).

These are plain functions with no `app` closure dependency, so they live at
module level and can be imported wherever needed instead of being redefined
per callback.
"""

from __future__ import annotations

import os
import pathlib
import re
import warnings

import numpy as np
import pandas as pd

from settings.paths import DIR_INPUT
from ...alpha.data import load_spread_data as _load_alpha_spread_data
from ...alpha.data.duration import _tenor_to_duration
from ._common import (
    _SUMMARY_ALPHA_PARQUET,
    _BETA_BOOK_USER_PARQUET,
    _ALPHA_POSITIONS_PARQUET,
    _load_cr_ts,
)


def _coerce_float(value) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _row_key(row: dict, default: int = -1) -> int:
    """Parse a row's `__row_key` as int, falling back on non-numeric values
    (e.g. the synthetic TOTAL row, whose `__row_key` is '')."""
    try:
        return int(row.get('__row_key', default))
    except (TypeError, ValueError):
        return default


def _compute_alpha_carry_mtm(
    spread_type: str,
    instrument_id: str,
    open_date_str: str,
    volume_mm: float | None,
) -> float | None:
    if _load_cr_ts is None or not open_date_str or not volume_mm:
        return None
    try:
        cr_ts = _load_cr_ts(spread_type)
        if cr_ts is None or instrument_id not in cr_ts.columns:
            return None
        series = cr_ts[instrument_id].dropna()
        open_dt = pd.to_datetime(open_date_str)
        today = pd.Timestamp.today().normalize()
        mask = (series.index >= open_dt) & (series.index <= today)
        carry_cum_pct = float(series[mask].sum()) / 90.0
        return round(volume_mm * carry_cum_pct / 100.0, 4)
    except Exception:
        return None


def _refresh_alpha_display_row(row: dict) -> dict:
    updated = dict(row)
    open_price_bp = _coerce_float(updated.get('Open price (bp)'))
    volume_mm = _coerce_float(updated.get('Volume (mm)'))
    duration = _coerce_float(updated.get('Duration'))
    close_price_bp = _coerce_float(updated.get('Close Price (bp)'))

    mtm_price_mm = None
    if None not in (open_price_bp, volume_mm, duration, close_price_bp):
        mtm_price_mm = round(
            volume_mm * duration * (close_price_bp - open_price_bp) / 10000.0,
            4,
        )

    mtm_carry_mm = _compute_alpha_carry_mtm(
        str(updated.get('Spread Type', '')),
        str(updated.get('ID', '')),
        str(updated.get('Open date', '')),
        volume_mm,
    )

    mtm_total_mm = None
    if mtm_price_mm is not None or mtm_carry_mm is not None:
        mtm_total_mm = round((mtm_price_mm or 0.0) + (mtm_carry_mm or 0.0), 4)

    updated['MTM spd (bp)'] = f"{open_price_bp:,.4f}" if open_price_bp is not None else ''
    updated['MtM Carry (MM CNY)'] = f"{mtm_carry_mm:,.4f}" if mtm_carry_mm is not None else ''
    updated['MtM Value (MM CNY)'] = f"{mtm_total_mm:,.4f}" if mtm_total_mm is not None else ''
    return updated


def _persist_alpha_summary_rows(rows: list[dict]) -> None:
    # Skip the synthetic TOTAL row — it is not a real position.
    records = [{
        'spread_type': str(r.get('Spread Type', '')),
        'ID': str(r.get('ID', '')),
        'style': str(r.get('Style', '')),
        'direction': str(r.get('Direction', '')),
        'open_price_bp': r.get('Open price (bp)', ''),
        'volume_mm': r.get('Volume (mm)', ''),
        'open_date': str(r.get('Open date', '')),
    } for r in rows if str(r.get('ID', '')) != 'TOTAL']
    pd.DataFrame(records).to_parquet(_ALPHA_POSITIONS_PARQUET, index=False)

    if not os.path.exists(_SUMMARY_ALPHA_PARQUET):
        return

    snapshot = pd.read_parquet(_SUMMARY_ALPHA_PARQUET)
    if snapshot.empty or 'ID' not in snapshot.columns:
        snapshot.to_parquet(_SUMMARY_ALPHA_PARQUET, index=False)
        return

    current_keys = {
        (str(r.get('Spread Type', '')), str(r.get('ID', '')))
        for r in rows
        if str(r.get('ID', '')) not in ('', 'TOTAL')
    }

    spread_type_series = snapshot['spread_type'].fillna('').astype(str) if 'spread_type' in snapshot.columns else pd.Series('', index=snapshot.index)
    id_series = snapshot['ID'].fillna('').astype(str)
    row_keys = pd.Series(list(zip(spread_type_series, id_series)), index=snapshot.index)
    keep_mask = id_series.isin(['', 'TOTAL']) | row_keys.isin(current_keys)
    snapshot.loc[keep_mask].to_parquet(_SUMMARY_ALPHA_PARQUET, index=False)


def _beta_user_row_key(row: dict) -> tuple[str, str]:
    return (str(row.get('Asset Name', '')), str(row.get('Instrument', '')))


def _is_truthy_flag(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'y'}
    return bool(value)


def _load_beta_user_overrides() -> tuple[dict[tuple[str, str], dict], set[tuple[str, str]]]:
    user_data: dict[tuple[str, str], dict] = {}
    deleted_keys: set[tuple[str, str]] = set()
    if not os.path.exists(_BETA_BOOK_USER_PARQUET):
        return user_data, deleted_keys
    try:
        udf = pd.read_parquet(_BETA_BOOK_USER_PARQUET)
    except Exception:
        return user_data, deleted_keys

    for _, record in udf.iterrows():
        key = (str(record.get('asset_name', '')), str(record.get('instrument', '')))
        if not any(key):
            continue
        is_deleted = _is_truthy_flag(record.get('deleted', False))
        if is_deleted:
            deleted_keys.add(key)
            continue
        user_data[key] = {
            'open_price': str(record.get('open_price', record.get('open_yld', ''))),
            'open_date': str(record.get('open_date', '')),
            'volume': str(record.get('volume', '')),
        }
    return user_data, deleted_keys


def _persist_beta_user_rows(
    rows: list[dict],
    deleted_keys: set[tuple[str, str]] | None = None,
) -> None:
    """Persist user-editable fields and hidden-row tombstones to parquet."""
    if deleted_keys is None:
        _, deleted_keys = _load_beta_user_overrides()

    visible_rows = [
        r for r in rows
        if str(r.get('Asset Type', '')) not in ('', 'TOTAL')
    ]
    visible_keys = {_beta_user_row_key(r) for r in visible_rows}
    deleted_keys = set(deleted_keys) - visible_keys

    records = [
        {
            'asset_name': str(r.get('Asset Name', '')),
            'instrument': str(r.get('Instrument', '')),
            'open_price': str(r.get('Open Price', '')),
            'open_date': str(r.get('Open Date', '')),
            'volume': str(r.get('Volume (MM)', '')),
            'deleted': False,
        }
        for r in visible_rows
    ]
    records.extend({
        'asset_name': asset_name,
        'instrument': instrument,
        'open_price': '',
        'open_date': '',
        'volume': '',
        'deleted': True,
    } for asset_name, instrument in sorted(deleted_keys))

    try:
        pathlib.Path(_BETA_BOOK_USER_PARQUET).parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(records).to_parquet(_BETA_BOOK_USER_PARQUET, index=False)
    except Exception:
        pass


# ── Duration/tenor + leg resolution helpers (used by Alpha table + Risk dashboard) ──

def _dur_to_tenor_label(dur: float) -> str:
    """Map duration (years) to nearest tenor label."""
    _TENOR_BOUNDS = [(0.0, 1.5, '1Y'), (1.5, 3.5, '2Y'), (3.5, 7.0, '5Y'),
                     (7.0, 12.0, '10Y'), (12.0, 17.0, '20Y'), (17.0, 9999.0, '30Y')]
    for lo, hi, label in _TENOR_BOUNDS:
        if lo <= dur < hi:
            return label
    return '30Y'


def _parse_repo_spread_legs(spread_id: str) -> tuple[str, str]:
    """Parse 'Repo7d-1y2y' → ('FR007S2Y.IR', 'FR007S1Y.IR') or
    'Shi3M-1y4y' → ('SHI3MS4Y.IR', 'SHI3MS1Y.IR').

    Leg1 is the longer (second) tenor, leg2 the shorter (first) tenor —
    matches the +1/-1 quote weights in irs._irs_quote_spread_weights.
    """
    import re
    _TENOR_MAP = {'3m': '3M', '6m': '6M', '9m': '9M', '1y': '1Y',
                  '2y': '2Y', '3y': '3Y', '5y': '5Y', '10y': '10Y'}

    for prefix, ir_prefix in [('repo7d', 'FR007S'), ('shi3m', 'SHI3MS')]:
        m = re.match(rf'{prefix}-(.+)', spread_id.lower())
        if m:
            remainder = m.group(1)
            pairs = re.findall(r'(\d+[a-z])', remainder)
            if len(pairs) >= 2:
                t1 = _TENOR_MAP.get(pairs[0], pairs[0].upper())
                t2 = _TENOR_MAP.get(pairs[1], pairs[1].upper())
                return (f'{ir_prefix}{t2}.IR', f'{ir_prefix}{t1}.IR')

    return ('', '')


def _load_alpha_duration_snapshot(spread_type: str, snap_cache: dict) -> pd.DataFrame | None:
    """Load (and cache within the given dict) the Alpha spread snapshot used
    to look up bond `ttm` for leg-duration resolution."""
    if spread_type not in snap_cache:
        try:
            snap = _load_alpha_spread_data(spread_type)
        except Exception:
            snap = None
        snap_cache[spread_type] = snap if isinstance(snap, pd.DataFrame) else None
    return snap_cache[spread_type]


def _leg_duration_years(
    leg: str,
    spread_type: str,
    trade_id: str,
    trade_duration: float,
    snap_cache: dict | None = None,
) -> float | None:
    """Return the (positive) duration in years for a resolved Alpha leg code.

    Used both to display the Leg2/Leg1 hedge ratio and to derive accurate
    leg-specific volumes/DV01 for Net Position and the DV01 Duration Ladder.
    Returns None when the leg's duration cannot be resolved.
    """
    leg_str = str(leg or '').strip()
    if not leg_str:
        return None
    if snap_cache is None:
        snap_cache = {}

    irs_match = re.search(r'(?:FR007S|SHI3MS)(\d+[MY])\.IR$', leg_str.upper())
    if irs_match:
        return float(_tenor_to_duration(irs_match.group(1).lower()))

    curve_label_match = re.match(r'^(?:CGB|CDB|LGB|MTN)-(\d+(?:\.\d+)?)Y$', leg_str.upper())
    if curve_label_match:
        return round(float(curve_label_match.group(1)) * 0.92, 4)

    if leg_str.endswith('.IB'):
        snap_types = []
        if spread_type in {'TBondCurve', 'TBondSwap'}:
            snap_types.append('TBondCurve')
        elif spread_type in {'CBondCurve', 'CBondSwap'}:
            snap_types.append('CBondCurve')
        elif spread_type == 'TenorSpread':
            upper_tid = str(trade_id or '').upper()
            if upper_tid.startswith(('CGB-', 'LGBCGB-', 'MTNCGB-', 'CGBREPO7D-')):
                snap_types.append('TBondCurve')
            if upper_tid.startswith(('CDB-', 'CDBCGB-')):
                snap_types.append('CBondCurve')
            if upper_tid.startswith('CDBCGB-'):
                snap_types.append('TBondCurve')
        elif spread_type == 'SwapSpread':
            snap_types.append('TBondCurve')

        for snap_type in snap_types:
            snap = _load_alpha_duration_snapshot(snap_type, snap_cache)
            if isinstance(snap, pd.DataFrame) and leg_str in snap.index and 'ttm' in snap.columns:
                try:
                    ttm = float(snap.loc[leg_str, 'ttm'])
                except (TypeError, ValueError):
                    continue
                if ttm > 0:
                    return round(ttm * 0.92 if ttm > 1.0 else ttm, 4)

    # Fallback for tenor spreads when bond snapshots do not contain one of the
    # resolved OTR legs (e.g. 30Y OTR): infer leg durations directly from the
    # trade-id tenor structure and leg ordering used by _resolve_legs.
    if spread_type == 'TenorSpread':
        upper_tid = str(trade_id or '').upper()

        # CGB-10s30s / CDB-5s10s style pairs: leg1 = longer tenor, leg2 = shorter tenor
        m_pair = re.search(r'(\d+(?:\.\d+)?)S(\d+(?:\.\d+)?)S', upper_tid)
        if m_pair:
            short_t = float(m_pair.group(1))
            long_t = float(m_pair.group(2))
            try:
                ld = snap_cache.get('__leg_data')
                if ld is None:
                    ld = _load_leg_data()
                    snap_cache['__leg_data'] = ld
                resolved_leg1, resolved_leg2 = _resolve_legs(spread_type, trade_id, trade_duration or 0.0, ld)
                if leg_str == resolved_leg1:
                    return float(_tenor_to_duration(f"{long_t}y"))
                if leg_str == resolved_leg2:
                    return float(_tenor_to_duration(f"{short_t}y"))
            except Exception:
                pass

        # CDBCGB-30Y style pairs: both legs share the same tenor bucket
        m_same = re.match(r'^CDBCGB-(\d+(?:\.\d+)?)Y$', upper_tid)
        if m_same:
            return float(_tenor_to_duration(f"{m_same.group(1)}y"))

        # CGBRepo7d-5Y style bond-vs-swap pairs: bond leg uses explicit tenor token
        m_repo = re.match(r'^CGBREPO7D-(\d+[MY])$', upper_tid)
        if m_repo and leg_str.endswith('.IB'):
            return float(_tenor_to_duration(m_repo.group(1).lower()))

    if trade_duration and leg_str == str(trade_id or '').strip():
        return float(trade_duration)

    return None


def _leg_volume_ratio(
    leg1: str,
    leg2: str,
    spread_type: str,
    trade_id: str,
    trade_duration: float,
    snap_cache: dict | None = None,
) -> float | None:
    """Duration-matched hedge ratio Volume(leg2)/Volume(leg1) = Duration(leg1)/Duration(leg2).

    Returns None when either leg's duration cannot be resolved.
    """
    if snap_cache is None:
        snap_cache = {}
    dur1 = _leg_duration_years(leg1, spread_type, trade_id, trade_duration, snap_cache)
    dur2 = _leg_duration_years(leg2, spread_type, trade_id, trade_duration, snap_cache)
    if dur1 is None or not dur2:
        return None
    return dur1 / dur2


def _parse_tenor_token(token: str) -> tuple[str, float]:
    """Parse tenor token like '5y'/'6m' into ('5Y', 5.0) or ('6M', 0.5)."""
    m = re.match(r'^(\d+)([my])$', str(token).strip().lower())
    if not m:
        return ('', 0.0)
    n = float(m.group(1))
    unit = m.group(2)
    if unit == 'm':
        return (f"{int(n)}M", n / 12.0)
    return (f"{int(n)}Y", n)


def _parse_cgb_repo_swap_legs(spread_id: str, otr_cgb: dict) -> tuple[str, str]:
    """Parse CGBRepo7d tenor trades to (OTR CGB, matched FR007 IRS tenor).

    Examples:
    - CGBRepo7d-5y  -> (most liquid OTR CGB 5Y, FR007S5Y.IR)
    - CGBRepo7d-18m -> (nearest-tenor OTR CGB, FR007S18M.IR)
    """
    import re
    m = re.match(r'^CGBREPO7D-(\d+[MY])$', str(spread_id).strip().upper())
    if not m:
        return ('', '')
    tenor_token, tenor_years = _parse_tenor_token(m.group(1))
    if not tenor_token:
        return ('', '')
    tenor_choices = ['1Y', '2Y', '5Y', '10Y', '20Y', '30Y']
    nearest = min(tenor_choices, key=lambda lbl: abs(int(lbl[:-1]) - tenor_years))
    return (otr_cgb.get(nearest, ''), f'FR007S{tenor_token}.IR')


def _tenor_str_to_years(tenor: str) -> float:
    """Convert tenor string like '1Y', '6M', '10Y' to fractional years."""
    import re as _re
    m = _re.match(r'(\d+)([MY])', tenor.upper())
    if not m:
        return 0.0
    n, unit = float(m.group(1)), m.group(2)
    return n / 12.0 if unit == 'M' else n


def _load_leg_data() -> dict:
    """Load instrument data needed for alpha position leg resolution (called once per refresh)."""
    ld: dict = {
        'otr_cgb': {}, 'otr_cdb': {},
        'nb': {}, 'tb_stat': None, 'futs_def': pd.DataFrame(),
        'fs_irs': {'TS': 'FR007S2Y.IR', 'TF': 'FR007S5Y.IR',
                   'T': 'FR007S10Y.IR', 'TL': 'FR007S10Y.IR'},
    }
    _OTR_BANDS = {
        '1Y': (0.9, 1.2), '2Y': (1.6, 2.5), '5Y': (4.0, 6.0),
        '10Y': (8.5, 10.0), '20Y': (15.0, 25.0), '30Y': (25.0, 30.0),
    }

    def _pick_otr(btype: str) -> dict:
        try:
            bi = pd.read_pickle(str(DIR_INPUT / f'{btype}-InstrumentInfo.pkl'))
        except Exception:
            return {}
        if not isinstance(bi, pd.DataFrame) or bi.empty:
            return {}
        need = ['起息日期', '到期日期', '证券全称', '成交量', '债券余额:亿']
        if not all(c in bi.columns for c in need):
            return {}
        today = pd.Timestamp.today().normalize()
        vol = pd.to_numeric(bi['成交量'], errors='coerce')
        bal = pd.to_numeric(bi['债券余额:亿'], errors='coerce')
        tr  = (vol / bal / 1e4).replace([np.inf, -np.inf], 0).fillna(0)
        mat = pd.to_datetime(bi['到期日期'], errors='coerce')
        sdt = pd.to_datetime(bi['起息日期'], errors='coerce')
        ttm = (mat - today).dt.days / 365.0
        kw  = '国债' if btype == 'TBond' else '国家开发银行'
        nm  = bi['证券全称'].astype(str).str.contains(kw, na=False)
        res = {}
        for tenor, (lo, hi) in _OTR_BANDS.items():
            mask = (ttm.notna() & sdt.notna() & (sdt < today) & (mat > today)
                    & (ttm > lo) & (ttm <= hi) & nm & (bal > 0) & (vol > 0))
            bkt = tr[mask]
            res[tenor] = bkt.idxmax() if not bkt.empty and (bkt > 0).any() else ''
        return res

    ld['otr_cgb'] = _pick_otr('TBond')
    ld['otr_cdb'] = _pick_otr('CBond')

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fspds = pd.read_pickle(str(DIR_INPUT / 'futures-spds.pkl'))
        ld['nb']      = fspds.get('NetBasis', {})
        ld['tb_stat'] = fspds.get('TermBasis', {}).get('StatInfo')
    except Exception:
        pass

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fi = pd.read_pickle(str(DIR_INPUT / 'futures-InstrumentInfo.pkl'))
        ld['futs_def'] = fi.get('Def', pd.DataFrame())
    except Exception:
        pass

    return ld


def _resolve_legs(stype: str, tid: str, duration: float, ld: dict) -> tuple:
    """Return (leg1, leg2) bond/contract codes for a given spread type and position ID."""
    import re as _re

    otr_cgb  = ld.get('otr_cgb', {})
    otr_cdb  = ld.get('otr_cdb', {})
    nb       = ld.get('nb', {})
    futs_def = ld.get('futs_def', pd.DataFrame())
    fs_irs   = ld.get('fs_irs', {})

    # Integer tenor → OTR tenor label
    _T_MAP = {1: '1Y', 2: '2Y', 5: '5Y', 10: '10Y', 20: '20Y', 30: '30Y'}
    def _t_label(n: float) -> str:
        ni = int(round(n))
        if ni in _T_MAP:
            return _T_MAP[ni]
        return min(_T_MAP.values(), key=lambda v: abs(int(v[:-1]) - n))

    # Duration → nearest on-the-run bond (same selection as the Market
    # Monitor "ON-THE-RUN BONDS" card: highest-turnover bond per tenor band).
    def _nearest_otr(dur: float, otr: dict) -> str:
        return otr.get(_t_label(dur), '')

    # Duration → FR007 IRS tenor code (for Bond-Swap trades)
    def _duration_to_fr007_tenor(dur: float) -> str:
        if dur <= 1.5:
            return 'FR007S1Y.IR'
        elif dur <= 2.0:
            return 'FR007S2Y.IR'
        elif dur <= 3.0:
            return 'FR007S3Y.IR'
        elif dur <= 4.0:
            return 'FR007S4Y.IR'
        else:
            return 'FR007S5Y.IR'

    # Front and next futures contract codes for a given contract type
    def _futs_front_next(ctype: str) -> tuple:
        if futs_def.empty:
            return ('', '')
        parsed = []
        for idx in futs_def.index:
            m = _re.match(r'^([A-Z]+)\d', str(idx).replace('.CFE', ''))
            parsed.append(m.group(1) if m else '')
        sub = futs_def[[t == ctype for t in parsed]]
        if sub.empty:
            return ('', '')
        sub_s = sub.sort_values('LASTTRADE_DATE')
        front = str(sub_s.index[0]).replace('.CFE', '') if len(sub_s) >= 1 else ''
        nxt   = str(sub_s.index[1]).replace('.CFE', '') if len(sub_s) >= 2 else ''
        return (front, nxt)

    if stype == 'TenorSpread':
        upper = tid.upper()
        if upper.startswith('CDBCGB-'):
            m = _re.match(r'CDBCGB-(\d+)Y$', upper)
            if m:
                t = _t_label(float(m.group(1)))
                return (otr_cdb.get(t, ''), otr_cgb.get(t, ''))
        elif upper.startswith('CGB-'):
            m = _re.search(r'(\d+)S(\d+)S', upper)
            if m:
                return (otr_cgb.get(_t_label(float(m.group(2))), ''),
                        otr_cgb.get(_t_label(float(m.group(1))), ''))
        elif upper.startswith('CDB-'):
            m = _re.search(r'(\d+)S(\d+)S', upper)
            if m:
                return (otr_cdb.get(_t_label(float(m.group(2))), ''),
                        otr_cdb.get(_t_label(float(m.group(1))), ''))
        elif upper.startswith('LGBCGB-'):
            # Curve-level yield spread (中债 AAA local-gov-bond yield vs CGB
            # yield) — no tradable bond pair, so legs are curve/tenor labels.
            m = _re.match(r'LGBCGB-(\d+)Y$', upper)
            if m:
                t = m.group(1) + 'Y'
                return (f'LGB-{t}', f'CGB-{t}')
        elif upper.startswith('MTNCGB-'):
            m = _re.match(r'MTNCGB-(\d+)Y$', upper)
            if m:
                t = m.group(1) + 'Y'
                return (f'MTN-{t}', f'CGB-{t}')
        elif upper.startswith('CGBREPO7D-'):
            cgb_leg, irs_leg = _parse_cgb_repo_swap_legs(upper, otr_cgb)
            if cgb_leg or irs_leg:
                return (cgb_leg, irs_leg)
        return ('', '')

    elif stype == 'TBondCurve':
        return (tid, _nearest_otr(duration, otr_cgb))

    elif stype == 'CBondCurve':
        return (tid, _nearest_otr(duration, otr_cdb))

    elif stype == 'TBondSwap':
        return (tid, _duration_to_fr007_tenor(duration))

    elif stype == 'CBondSwap':
        return (tid, _duration_to_fr007_tenor(duration))

    elif stype == 'NetBasis':
        ctype = tid.split('-')[0]
        si = nb.get(ctype, {}).get('StatInfo')
        if si is not None and not si.empty:
            ctd = str(si['ctd_code'].iloc[0]) if 'ctd_code' in si.columns else ''
            fut = str(si['futures'].iloc[0]).replace('.CFE', '') if 'futures' in si.columns else ''
            return (ctd, fut)
        return ('', '')

    elif stype == 'TermBasis':
        return _futs_front_next(tid)

    elif stype == 'FuturesSwap':
        front, _ = _futs_front_next(tid)
        return (front, fs_irs.get(tid, ''))

    elif stype == 'SwapSpread':
        cgb_leg, irs_leg = _parse_cgb_repo_swap_legs(tid, otr_cgb)
        if cgb_leg or irs_leg:
            return (cgb_leg, irs_leg)
        return _parse_repo_spread_legs(tid)

    elif stype == 'IRS':
        return _parse_repo_spread_legs(tid)

    return ('', '')
