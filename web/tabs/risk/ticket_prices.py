# -*- coding: utf-8 -*-
"""Latest close (yield, %) and modified duration per instrument for Summary > Tickets.

Cash bonds come from the {TBond,CBond}-InstrumentInfo files (close yield and
modified duration per code), swaps from the freshest FR007 daily closes, and
the Beta book's generic curve labels (CGB-10Y, LGB3Y, ...) from the index
yields in database-px.pkl. An instrument with no source gets no mark.
"""

from __future__ import annotations

import re
import warnings

import pandas as pd

from settings.paths import DIR_INPUT
from web.tabs.alpha.data.duration import _tenor_to_duration
from .books.swap_close import freshest_daily_closes

# curve label prefix -> database-px.pkl frame
_LABEL_FRAME = {'CGB': 'CGB', 'LGB': 'LGB', 'CDB': 'CDB', 'MTN': 'MTN', 'NCD': 'ICP', 'ICP': 'ICP'}
_LABEL = re.compile(r'^(CGB|LGB|CDB|MTN|NCD|ICP)-?(\d+)Y$', re.IGNORECASE)
_SWAP = re.compile(r'^(?:FR007S|SHI3MS)(\d+[MY])\.IR$', re.IGNORECASE)


def _bond_marks() -> dict[str, tuple[float, float]]:
    """code -> (close yield %, modified duration) from the bond InstrumentInfo files."""
    out: dict[str, tuple[float, float]] = {}
    for btype in ('TBond', 'CBond', 'LBond', 'MNote'):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                bi = pd.read_pickle(str(DIR_INPUT / f'{btype}-InstrumentInfo.pkl'))
            y = pd.to_numeric(bi['收盘收益率(%)'], errors='coerce')
            d = pd.to_numeric(bi['修正久期'], errors='coerce')
        except Exception:
            continue
        for code in bi.index:
            if pd.notna(y.get(code)) and pd.notna(d.get(code)):
                out[str(code)] = (float(y[code]), float(d[code]))
    return out


def _latest(frame: pd.DataFrame, col: str):
    s = pd.to_numeric(frame[col], errors='coerce').dropna() if col in frame.columns else None
    return float(s.iloc[-1]) if s is not None and len(s) else None


def latest_marks(dv01_per_mm: dict[str, float | None]) -> dict[str, dict]:
    """{code: {'close': yield %, 'dur': years}} for the given instruments.

    ``dv01_per_mm`` maps code -> |DV01 MM/bp| / |position MM| (None when the
    position is flat); it backs the duration of an instrument with no
    duration source of its own (generic curve labels).
    """
    bonds = _bond_marks()
    try:
        px = pd.read_pickle(str(DIR_INPUT / 'database-px.pkl'))
        px = px if isinstance(px, dict) else {}
    except Exception:
        px = {}
    try:
        irs_px = pd.read_pickle(str(DIR_INPUT / 'IRS-pxspds.pkl'))
        irs_eod = irs_px.get('CloseYield') if isinstance(irs_px, dict) else None
    except Exception:
        irs_eod = None
    irs = freshest_daily_closes(px.get('IRS'), irs_eod)

    out: dict[str, dict] = {}
    for code, ratio in dv01_per_mm.items():
        code = str(code)
        close = dur = None
        m_swap, m_label = _SWAP.match(code), _LABEL.match(code)
        if code in bonds:
            close, dur = bonds[code]
        elif m_swap:
            close = _latest(irs, code)
            dur = float(_tenor_to_duration(m_swap.group(1)))
        elif m_label:
            n = int(m_label.group(2))
            frame = px.get(_LABEL_FRAME[m_label.group(1).upper()])
            if isinstance(frame, pd.DataFrame):
                col = next((c for c in frame.columns if str(c).endswith(f':{n}年')), None)
                close = _latest(frame, col) if col else None
            dur = ratio * 1e4 if ratio else n * 0.92
        if dur is None and ratio:
            dur = ratio * 1e4
        out[code] = {'close': close, 'dur': dur}
    return out
