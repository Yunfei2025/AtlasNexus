# -*- coding: utf-8 -*-
"""Leg resolution: map spread IDs to underlying instrument legs."""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


_TENOR_MAP = {
    '3m': '3M', '6m': '6M', '9m': '9M', '1y': '1Y',
    '2y': '2Y', '3y': '3Y', '5y': '5Y', '10y': '10Y'
}


def _parse_repo_spread_legs(spread_id: str) -> tuple[str, str]:
    """Parse 'Repo7d-1y2y' → ('FR007S2Y.IR', 'FR007S1Y.IR') or
    'Shi3M-1y4y' → ('SHI3MS4Y.IR', 'SHI3MS1Y.IR') or
    'Basis-5y' → ('SHI3MS5Y.IR', 'FR007S5Y.IR').

    For spreads: leg1 is the longer/paid tenor, leg2 the shorter/received tenor.
    A 3-tenor fly ID (e.g. 'Repo7d-1y2y5y') only uses the first two tenors
    here (1y, 2y) — see _parse_repo_spread_fly_legs for the belly/wings form.
    """
    # Handle Basis spreads (e.g., "Basis-5y" → (SHI3MS5Y.IR, FR007S5Y.IR))
    m = re.match(r'basis-(\d+)y$', spread_id.lower())
    if m:
        tenor = _TENOR_MAP.get(f"{m.group(1)}y", f"{m.group(1).upper()}Y")
        return (f'SHI3MS{tenor}.IR', f'FR007S{tenor}.IR')

    # Handle Repo7d and Shi3M spreads (both long the longer tenor, short the shorter)
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


def _parse_repo_spread_fly_legs(spread_id: str) -> tuple[str, str, str]:
    """Parse a 3-tenor IRS fly like 'Repo7d-1y2y5y' → (leg1=belly, leg2=short
    wing, leg3=long wing), e.g. ('FR007S2Y.IR', 'FR007S1Y.IR', 'FR007S5Y.IR').

    Sign convention (see resolve_legs3): BUY = long belly (leg1, receive fixed)
    / short both wings (leg2, leg3, pay fixed); SELL = opposite. Returns
    ('', '', '') if spread_id is not a 3-tenor Repo7d/Shi3M fly.
    """
    for prefix, ir_prefix in [('repo7d', 'FR007S'), ('shi3m', 'SHI3MS')]:
        m = re.match(rf'{prefix}-(.+)', spread_id.lower())
        if m:
            remainder = m.group(1)
            tenors = re.findall(r'(\d+[a-z])', remainder)
            if len(tenors) >= 3:
                short_wing, belly, long_wing = tenors[0], tenors[1], tenors[2]
                t_short = _TENOR_MAP.get(short_wing, short_wing.upper())
                t_belly = _TENOR_MAP.get(belly, belly.upper())
                t_long = _TENOR_MAP.get(long_wing, long_wing.upper())
                return (f'{ir_prefix}{t_belly}.IR', f'{ir_prefix}{t_short}.IR', f'{ir_prefix}{t_long}.IR')
    return ('', '', '')


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
        '7Y': (6.0, 8.5), '10Y': (8.5, 10.0), '20Y': (15.0, 25.0), '30Y': (25.0, 30.0),
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
        tid: Trade ID / instrument name (e.g., 'CGB-5s10s', 'Repo7d-6m1y', 'T')
        duration: Duration in years (used for bond trades to determine reference tenor)
        ld: Leg data dictionary from _load_leg_data() (lazy-loaded if None)

    Returns:
        Tuple of (leg1_code, leg2_code) or ('', '') if cannot resolve
    """
    if ld is None:
        ld = _load_leg_data()

    otr_cgb = ld.get('otr_cgb', {})
    otr_cdb = ld.get('otr_cdb', {})
    nb = ld.get('nb', {})
    futs_def = ld.get('futs_def', pd.DataFrame())
    fs_irs = ld.get('fs_irs', {})

    # Integer tenor → OTR tenor label
    _T_MAP = {1: '1Y', 2: '2Y', 5: '5Y', 7: '7Y', 10: '10Y', 20: '20Y', 30: '30Y'}
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

    # TenorSpread: CGB-5s10s, CDB-5s10s, CDBCGB-10y
    if stype == 'TenorSpread':
        upper = tid.upper()
        if upper.startswith('CDBCGB-'):
            m = re.match(r'CDBCGB-(\d+)Y$', upper)
            if m:
                t = _t_label(float(m.group(1)))
                return (otr_cdb.get(t, ''), otr_cgb.get(t, ''))
        elif upper.startswith('CGB-'):
            m3 = re.search(r'(\d+)S(\d+)S(\d+)S', upper)
            if m3:
                # Fly (NsMsLs): lossy 2-leg proxy — long belly, short long wing.
                belly = _t_label(float(m3.group(2)))
                long_wing = _t_label(float(m3.group(3)))
                return (otr_cgb.get(belly, ''), otr_cgb.get(long_wing, ''))
            m = re.search(r'(\d+)S(\d+)S', upper)
            if m:
                t1 = _t_label(float(m.group(1)))
                t2 = _t_label(float(m.group(2)))
                return (otr_cgb.get(t2, ''), otr_cgb.get(t1, ''))
        elif upper.startswith('CDB-'):
            m3 = re.search(r'(\d+)S(\d+)S(\d+)S', upper)
            if m3:
                belly = _t_label(float(m3.group(2)))
                long_wing = _t_label(float(m3.group(3)))
                return (otr_cdb.get(belly, ''), otr_cdb.get(long_wing, ''))
            m = re.search(r'(\d+)S(\d+)S', upper)
            if m:
                t1 = _t_label(float(m.group(1)))
                t2 = _t_label(float(m.group(2)))
                return (otr_cdb.get(t2, ''), otr_cdb.get(t1, ''))
        elif upper.startswith('LGBCGB-'):
            # LGBCGB is a curve-level yield spread (中债 AAA local-gov-bond yield
            # vs CGB yield). Use the live on-the-run CGB bond for the CGB leg.
            m = re.match(r'LGBCGB-(\d+)Y$', upper)
            if m:
                t = m.group(1) + 'Y'
                return (f'LGB-{t}', otr_cgb.get(t, f'CGB-{t}'))
        elif upper.startswith('MTNCGB-'):
            # Same idea as LGBCGB: use the live on-the-run CGB bond for the CGB leg.
            m = re.match(r'MTNCGB-(\d+)Y$', upper)
            if m:
                t = m.group(1) + 'Y'
                return (f'MTN-{t}', otr_cgb.get(t, f'CGB-{t}'))
        elif upper.startswith('CGBREPO7D-'):
            # CGBRepo7d-5y: long OTR CGB at that tenor vs short matched FR007 IRS tenor.
            # Example: CGBRepo7d-5y -> (260008.IB, FR007S5Y.IR)
            m = re.match(r'CGBREPO7D-(\d+[MY])$', upper)
            if m:
                tenor_token, tenor_years = _parse_tenor_token(m.group(1))
                if tenor_token:
                    otr = otr_cgb.get(_t_label(tenor_years), '')
                    return (otr, f'FR007S{tenor_token}.IR')
        elif upper.startswith(('REPO7D-', 'SHI3M-', 'BASIS-')):
            # IRS curve-slope/basis instruments carried over from SwapSpread
            # into this category (see curves.generators.stat.compute_tenor_spreads);
            # same leg semantics as stype == 'SwapSpread' below.
            return _parse_repo_spread_legs(tid)
        return ('', '')

    # Mature OFRk-vs-OTR relative value (signal_variant=otr_ofr_rv), merged
    # into TBondCurve/CBondCurve as pair-format IDs "<ofrk_id>|<otr_id>" (see
    # curves/refreshers/otr_ofr_rv.py). Leg2 is OTR, not OFR1: OTR carries the
    # liquidity premium and is a beta-book holding, so the short leg is
    # financed by selling an existing position rather than borrowing OFR1.
    if stype in ('TBondCurve', 'CBondCurve') and '|' in str(tid):
        ofrk_id, _, otr_id = str(tid).partition('|')
        return (ofrk_id, otr_id)

    # Bond-Curve: leg1 is the bond, leg2 is the current OTR for the nearest
    # supported tenor category.  The OTR categories intentionally jump from
    # 5Y to 10Y; do not use the legacy 7Y cvref column here.
    if stype == 'TBondCurve':
        return (tid, otr_cgb.get(_t_label(duration), ''))

    elif stype == 'CBondCurve':
        return (tid, otr_cdb.get(_t_label(duration), ''))

    # Bond-Swap: leg1 is the bond, leg2 is FR007 IRS with matching tenor
    elif stype == 'TBondSwap':
        return (tid, _duration_to_fr007_tenor(duration))

    elif stype == 'CBondSwap':
        return (tid, _duration_to_fr007_tenor(duration))

    # NetBasis (Bond-Futures): leg1 = CTD (long cash), leg2 = Futures (short contract)
    # Economic trade: long CTD bond, short futures contract (receive carry/repo benefit)
    elif stype == 'NetBasis':
        ctype = tid.split('-')[0]
        si = nb.get(ctype, {}).get('StatInfo')
        if si is not None and not si.empty:
            ctd = str(si['ctd_code'].iloc[0]) if 'ctd_code' in si.columns else ''
            fut = str(si['futures'].iloc[0]).replace('.CFE', '') if 'futures' in si.columns else ''
            return (ctd, fut)
        return ('', '')

    # TermBasis (Calendar Spreads): leg1 = Front contract, leg2 = Next contract
    # Economic trade: long near contract, short far contract (capture roll-down)
    elif stype == 'TermBasis':
        return _futs_front_next(tid)

    # FuturesSwap: leg1 = Futures contract, leg2 = IRS (matched tenor)
    # Economic trade: long futures (physical), pay fixed IRS (hedge rate risk)
    elif stype == 'FuturesSwap':
        front, _ = _futs_front_next(tid)
        return (front, fs_irs.get(tid, ''))

    # SwapSpread: Repo7d-XyYy or Basis-5y
    elif stype == 'SwapSpread':
        return _parse_repo_spread_legs(tid)

    # Generic IRS spreads
    elif stype == 'IRS':
        return _parse_repo_spread_legs(tid)

    # BondNewIssue: tid = "<tenor_bucket>:<stage>:<leg1_id>|<leg2_id>" (see
    # docs/dev/tbondcurve-30y-otr-ofr-plan.md). stage=nib_otr -> leg1=NIB,
    # leg2=OTR; stage=otr_ofr1 -> leg1=OTR, leg2=OFR1.
    elif stype == 'BondNewIssue':
        m = re.match(r'^[^:]+:[^:]+:([^|]+)\|(.+)$', str(tid))
        if m:
            return (m.group(1), m.group(2))
        return ('', '')

    return ('', '')


def resolve_legs3(
    stype: str, tid: str, duration: float = 0.0, ld: Optional[dict] = None
) -> tuple[str, str, Optional[str]]:
    """Resolve (leg1, leg2, leg3) for a spread, exposing the third leg of a
    3-tenor butterfly instead of resolve_legs()'s lossy 2-leg proxy.

    leg3 is None for every non-fly spread type (leg1/leg2 match resolve_legs()
    exactly in that case). For a fly:
        leg1 = belly (middle tenor)
        leg2 = short wing
        leg3 = long wing

    Sign convention (2026-09-07): BUY = long belly / short both wings;
    SELL = short belly / long both wings. OTR carries the liquidity premium
    on this desk (see curves/refreshers/otr_ofr_rv.py), so pairing the belly
    against two wings rather than a single reference leg is unrelated to that
    convention -- this is a distinct 3-leg butterfly structure.

    Args:
        stype: Spread type (e.g., 'TenorSpread', 'SwapSpread').
        tid: Trade ID / instrument name (e.g., 'CGB-5s7s10s', 'Repo7d-1y2y5y').
        duration: Duration in years (passed through to resolve_legs() for
            non-fly types).
        ld: Leg data dictionary from _load_leg_data() (lazy-loaded if None).

    Returns:
        (leg1_code, leg2_code, leg3_code_or_None).
    """
    if ld is None:
        ld = _load_leg_data()

    otr_cgb = ld.get('otr_cgb', {})
    otr_cdb = ld.get('otr_cdb', {})

    _T_MAP = {1: '1Y', 2: '2Y', 5: '5Y', 7: '7Y', 10: '10Y', 20: '20Y', 30: '30Y'}
    def _t_label(n: float) -> str:
        ni = int(round(n))
        if ni in _T_MAP:
            return _T_MAP[ni]
        return min(_T_MAP.values(), key=lambda v: abs(int(v[:-1]) - n))

    if stype == 'TenorSpread':
        upper = tid.upper()
        if upper.startswith('CGB-'):
            m3 = re.search(r'(\d+)S(\d+)S(\d+)S', upper)
            if m3:
                short_wing = _t_label(float(m3.group(1)))
                belly = _t_label(float(m3.group(2)))
                long_wing = _t_label(float(m3.group(3)))
                return (otr_cgb.get(belly, ''), otr_cgb.get(short_wing, ''), otr_cgb.get(long_wing, ''))
        elif upper.startswith('CDB-'):
            m3 = re.search(r'(\d+)S(\d+)S(\d+)S', upper)
            if m3:
                short_wing = _t_label(float(m3.group(1)))
                belly = _t_label(float(m3.group(2)))
                long_wing = _t_label(float(m3.group(3)))
                return (otr_cdb.get(belly, ''), otr_cdb.get(short_wing, ''), otr_cdb.get(long_wing, ''))

    if stype == 'SwapSpread':
        leg1, leg2, leg3 = _parse_repo_spread_fly_legs(tid)
        if leg1:
            return (leg1, leg2, leg3)

    leg1, leg2 = resolve_legs(stype, tid, duration, ld)
    return (leg1, leg2, None)


def fly_leg_tenor_years(stype: str, tid: str) -> Optional[tuple[float, float, float]]:
    """Return (belly_years, short_wing_years, long_wing_years) parsed directly
    from a 3-tenor fly ID, or None if tid is not a fly of a type resolve_legs3
    supports.

    Kept separate from resolve_legs3's bond/IRS-code lookups: a fly's leg
    durations are fully determined by its own tenor structure (unlike a
    single bond, which needs an OTR-snapshot TTM lookup), so this avoids
    threading a third leg through the snapshot-based duration fallback in
    web/tabs/risk/helpers.py::_leg_duration_years, which only knows about the
    old 2-leg (belly, long_wing) proxy.
    """
    upper = str(tid).upper()
    if stype == 'TenorSpread' and (upper.startswith('CGB-') or upper.startswith('CDB-')):
        m3 = re.search(r'(\d+)S(\d+)S(\d+)S', upper)
        if m3:
            short_wing, belly, long_wing = float(m3.group(1)), float(m3.group(2)), float(m3.group(3))
            return (belly, short_wing, long_wing)
        return None

    if stype == 'SwapSpread':
        for prefix in ('repo7d', 'shi3m'):
            m = re.match(rf'{prefix}-(.+)', str(tid).lower())
            if m:
                tenors = re.findall(r'(\d+[a-z])', m.group(1))
                if len(tenors) >= 3:
                    short_wing = _tenor_str_to_years(tenors[0].upper())
                    belly = _tenor_str_to_years(tenors[1].upper())
                    long_wing = _tenor_str_to_years(tenors[2].upper())
                    return (belly, short_wing, long_wing)
        return None

    return None


def fly_leg_dv01_ratios(stype: str, tid: str) -> Optional[tuple[float, float]]:
    """DV01-neutral wing/belly notional ratios for a 3-leg fly:
    (short_wing_ratio, long_wing_ratio), where each wing's notional =
    belly_notional * ratio, split so DV01(short_wing) + DV01(long_wing) ==
    DV01(belly), equally between the two wings (standard duration-neutral
    butterfly construction).

    Duration proxy matches how the rest of the codebase treats each family:
    bond legs (TenorSpread CGB-/CDB-) use ttm * 0.92, the same proxy
    _get_duration_mult / _leg_duration_years apply to '.IB' legs; IRS legs
    (SwapSpread Repo7d-/Shi3M-) use the swap-annuity formula
    _tenor_to_duration, matching _get_duration_mult's SwapSpread branch.
    Returns None if tid is not a fly resolve_legs3 supports, or if any leg's
    duration comes out non-positive (degenerate tenor).
    """
    tenors = fly_leg_tenor_years(stype, tid)
    if tenors is None:
        return None
    belly_y, short_y, long_y = tenors

    if stype == 'SwapSpread':
        from .duration import _tenor_to_duration
        dur_belly = _tenor_to_duration(f'{belly_y}y')
        dur_short = _tenor_to_duration(f'{short_y}y')
        dur_long = _tenor_to_duration(f'{long_y}y')
    else:
        dur_belly = belly_y * 0.92
        dur_short = short_y * 0.92
        dur_long = long_y * 0.92

    if dur_belly <= 0 or dur_short <= 0 or dur_long <= 0:
        return None
    # Each wing absorbs half the belly's DV01: notional_wing * dur_wing = 0.5 * (notional_belly * dur_belly)
    short_ratio = 0.5 * dur_belly / dur_short
    long_ratio = 0.5 * dur_belly / dur_long
    return (round(short_ratio, 4), round(long_ratio, 4))
