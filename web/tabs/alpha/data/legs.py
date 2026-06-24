# -*- coding: utf-8 -*-
"""Leg resolution: map spread IDs to underlying instrument legs."""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


def _parse_repo_spread_legs(spread_id: str) -> tuple[str, str]:
    """Parse 'Repo7d-6m1y' or 'Basis-5y' → ('FR007S6M.IR', 'FR007S1Y.IR') or other legs."""
    _TENOR_MAP = {
        '3m': '3M', '6m': '6M', '9m': '9M', '1y': '1Y',
        '2y': '2Y', '3y': '3Y', '5y': '5Y', '10y': '10Y'
    }

    # Handle Basis spreads (e.g., "Basis-5y" → SHI3MS5Y.IR vs FR007S5Y.IR)
    m = re.match(r'basis-(\d+)y$', spread_id.lower())
    if m:
        tenor = _TENOR_MAP.get(f"{m.group(1)}y", f"FR007S{m.group(1).upper()}Y.IR")
        return (f'SHI3MS{tenor}.IR', f'FR007S{tenor}.IR')

    # Handle Repo7d spreads (e.g., "Repo7d-6m1y" → FR007S6M.IR vs FR007S1Y.IR)
    m = re.match(r'repo7d-(.+)', spread_id.lower())
    if not m:
        return ('', '')
    remainder = m.group(1)
    pairs = re.findall(r'(\d+[a-z])', remainder)
    if len(pairs) < 2:
        return ('', '')
    t1 = _TENOR_MAP.get(pairs[0], pairs[0].upper())
    t2 = _TENOR_MAP.get(pairs[1], pairs[1].upper())
    return (f'FR007S{t1}.IR', f'FR007S{t2}.IR')


def _tenor_str_to_years(tenor: str) -> float:
    """Convert tenor string like '1Y', '6M', '10Y' to fractional years."""
    m = re.match(r'(\d+)([MY])', tenor.upper())
    if not m:
        return 0.0
    n, unit = float(m.group(1)), m.group(2)
    return n / 12.0 if unit == 'M' else n


def _load_leg_data() -> dict:
    """Load instrument data needed for spread position leg resolution."""
    from settings.paths import DIR_INPUT

    ld: dict = {
        'otr_cgb': {}, 'otr_cdb': {},
        'ref_cgb': pd.Series(dtype=object), 'ref_cdb': pd.Series(dtype=object),
        'nb': {}, 'tb_stat': None, 'futs_def': pd.DataFrame(),
        'fs_irs': {
            'TS': 'FR007S2Y.IR',
            'TF': 'FR007S5Y.IR',
            'T': 'FR007S10Y.IR',
            'TL': 'FR007S10Y.IR'
        },
    }

    _OTR_BANDS = {
        '1Y': (0.9, 1.2), '2Y': (1.6, 2.5), '5Y': (4.0, 6.0),
        '10Y': (8.5, 10.0), '20Y': (15.0, 25.0), '30Y': (25.0, 30.0),
    }

    def _pick_otr(btype: str) -> dict:
        """Pick on-the-run bond by highest turnover within each tenor band."""
        try:
            bi = pd.read_pickle(str(Path(DIR_INPUT) / f'{btype}-InstrumentInfo.pkl'))
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
        tr = (vol / bal / 1e4).replace([np.inf, -np.inf], 0).fillna(0)
        mat = pd.to_datetime(bi['到期日期'], errors='coerce')
        sdt = pd.to_datetime(bi['起息日期'], errors='coerce')
        ttm = (mat - today).dt.days / 365.0
        kw = '国债' if btype == 'TBond' else '国家开发银行'
        nm = bi['证券全称'].astype(str).str.contains(kw, na=False)

        res = {}
        for tenor, (lo, hi) in _OTR_BANDS.items():
            mask = (ttm.notna() & sdt.notna() & (sdt < today) & (mat > today)
                    & (ttm > lo) & (ttm <= hi) & nm & (bal > 0) & (vol > 0))
            bkt = tr[mask]
            res[tenor] = bkt.idxmax() if not bkt.empty and (bkt > 0).any() else ''
        return res

    ld['otr_cgb'] = _pick_otr('TBond')
    ld['otr_cdb'] = _pick_otr('CBond')

    for key, fname in [('ref_cgb', 'TBond-cvref.pkl'), ('ref_cdb', 'CBond-cvref.pkl')]:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                cv = pd.read_pickle(str(Path(DIR_INPUT) / fname))
            rb = cv.get('RefBond', pd.DataFrame()) if isinstance(cv, dict) else pd.DataFrame()
            ld[key] = rb.iloc[-1] if not rb.empty else pd.Series(dtype=object)
        except Exception:
            pass

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fspds = pd.read_pickle(str(Path(DIR_INPUT) / 'futures-spds.pkl'))
        ld['nb'] = fspds.get('NetBasis', {})
        ld['tb_stat'] = fspds.get('TermBasis', {}).get('StatInfo')
    except Exception:
        pass

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fi = pd.read_pickle(str(Path(DIR_INPUT) / 'futures-InstrumentInfo.pkl'))
        ld['futs_def'] = fi.get('Def', pd.DataFrame())
    except Exception:
        pass

    return ld


def resolve_legs(stype: str, tid: str, duration: float = 0.0, ld: Optional[dict] = None) -> tuple[str, str]:
    """
    Resolve (leg1, leg2) instrument codes for a given spread type and trade ID.

    Args:
        stype: Spread type (e.g., 'TenorSpread', 'SwapSpread', 'NetBasis', etc.)
        tid: Trade ID / instrument name (e.g., 'CGB-10s30s', 'Repo7d-6m1y', 'T')
        duration: Duration in years (used for bond trades to determine reference tenor)
        ld: Leg data dictionary from _load_leg_data() (lazy-loaded if None)

    Returns:
        Tuple of (leg1_code, leg2_code) or ('', '') if cannot resolve
    """
    if ld is None:
        ld = _load_leg_data()

    otr_cgb = ld.get('otr_cgb', {})
    otr_cdb = ld.get('otr_cdb', {})
    ref_cgb = ld.get('ref_cgb', pd.Series(dtype=object))
    ref_cdb = ld.get('ref_cdb', pd.Series(dtype=object))
    nb = ld.get('nb', {})
    futs_def = ld.get('futs_def', pd.DataFrame())
    fs_irs = ld.get('fs_irs', {})

    # Integer tenor → OTR tenor label
    _T_MAP = {1: '1Y', 2: '2Y', 5: '5Y', 10: '10Y', 20: '20Y', 30: '30Y'}
    def _t_label(n: float) -> str:
        ni = int(round(n))
        if ni in _T_MAP:
            return _T_MAP[ni]
        return min(_T_MAP.values(), key=lambda v: abs(int(v[:-1]) - n))

    # Duration → FR007 IRS tenor code (for Bond-Swap trades)
    def _duration_to_fr007_tenor(dur: float) -> str:
        """Convert bond duration to matching FR007 IRS tenor (1Y, 2Y, or 5Y)."""
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

    # Duration → nearest reference bond from cvref series
    _REF_TENORS = [
        (0.3, '0.3Y'), (0.5, '0.5Y'), (0.7, '0.7Y'), (1.0, '1Y'), (1.5, '1.5Y'),
        (2.0, '2Y'), (3.0, '3Y'), (5.0, '5Y'), (7.0, '7Y'), (10.0, '10Y'),
        (20.0, '20Y'), (30.0, '30Y')
    ]
    def _nearest_ref(dur: float, ref_s: pd.Series) -> str:
        best = min(_REF_TENORS, key=lambda x: abs(x[0] - dur))
        v = ref_s.get(f'Term near {best[1]}', '')
        return str(v) if v and str(v) not in ('nan', 'None', '—') else ''

    # Front and next futures contract codes for a given contract type
    def _futs_front_next(ctype: str) -> tuple[str, str]:
        if futs_def.empty:
            return ('', '')
        parsed = []
        for idx in futs_def.index:
            m = re.match(r'^([A-Z]+)\d', str(idx).replace('.CFE', ''))
            parsed.append(m.group(1) if m else '')
        sub = futs_def[[t == ctype for t in parsed]]
        if sub.empty:
            return ('', '')
        sub_s = sub.sort_values('LASTTRADE_DATE')
        front = str(sub_s.index[0]).replace('.CFE', '') if len(sub_s) >= 1 else ''
        nxt = str(sub_s.index[1]).replace('.CFE', '') if len(sub_s) >= 2 else ''
        return (front, nxt)

    # TenorSpread: CGB-10s30s, CDB-5s10s, CDBCGB-10y
    if stype == 'TenorSpread':
        upper = tid.upper()
        if upper.startswith('CDBCGB-'):
            m = re.match(r'CDBCGB-(\d+)Y$', upper)
            if m:
                t = _t_label(float(m.group(1)))
                return (otr_cdb.get(t, ''), otr_cgb.get(t, ''))
        elif upper.startswith('CGB-'):
            m = re.search(r'(\d+)S(\d+)S', upper)
            if m:
                return (otr_cgb.get(_t_label(float(m.group(1))), ''),
                        otr_cgb.get(_t_label(float(m.group(2))), ''))
        elif upper.startswith('CDB-'):
            m = re.search(r'(\d+)S(\d+)S', upper)
            if m:
                return (otr_cdb.get(_t_label(float(m.group(1))), ''),
                        otr_cdb.get(_t_label(float(m.group(2))), ''))
        return ('', '')

    # Bond-Curve: leg1 is the bond, leg2 is nearest duration reference bond
    if stype == 'TBondCurve':
        return (tid, _nearest_ref(duration, ref_cgb))

    elif stype == 'CBondCurve':
        return (tid, _nearest_ref(duration, ref_cdb))

    # Bond-Swap: leg1 is the bond, leg2 is FR007 IRS with matching tenor
    elif stype == 'TBondSwap':
        return (tid, _duration_to_fr007_tenor(duration))

    elif stype == 'CBondSwap':
        return (tid, _duration_to_fr007_tenor(duration))

    # NetBasis (Bond-Futures): CTD vs Futures contract
    elif stype == 'NetBasis':
        ctype = tid.split('-')[0]
        si = nb.get(ctype, {}).get('StatInfo')
        if si is not None and not si.empty:
            ctd = str(si['ctd_code'].iloc[0]) if 'ctd_code' in si.columns else ''
            fut = str(si['futures'].iloc[0]).replace('.CFE', '') if 'futures' in si.columns else ''
            return (ctd, fut)
        return ('', '')

    # TermBasis (Calendar Spreads): Front vs Next futures contract
    elif stype == 'TermBasis':
        return _futs_front_next(tid)

    # FuturesSwap: Futures contract vs IRS
    elif stype == 'FuturesSwap':
        front, _ = _futs_front_next(tid)
        return (front, fs_irs.get(tid, ''))

    # SwapSpread: Repo7d-XyYy or Basis-5y
    elif stype == 'SwapSpread':
        return _parse_repo_spread_legs(tid)

    # Generic IRS spreads
    elif stype == 'IRS':
        return _parse_repo_spread_legs(tid)
