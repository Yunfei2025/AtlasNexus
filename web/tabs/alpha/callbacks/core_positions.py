# -*- coding: utf-8 -*-
"""Open Core (TenorSpread) positions as the backtest holds them today.

Single source of truth for both the Candidates tab's Open Positions (Core)
card and the correlation check's locked backdrop, so the two never disagree
on which Core names are held.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from ..data import load_spread_data, load_core_seed, has_7y_leg
from .backtest_state import latest_position, run_instrument_backtest, short_allowed
from .helpers import _load_alpha_book_positions


def get_open_core_positions() -> tuple[list[dict], int]:
    """Return ``(open_rows, n_flat)`` for the Core book.

    The universe is the full seed membership plus the saved positions file
    (saved rows win), minus any 7y-leg spread. Each name is reconciled against
    the backtest: FLAT names are dropped and counted, held names take the
    backtest's direction and regime (trend -> momentum, mr -> mean-reverting); a backtest that cannot run leaves the saved row
    as-is (and is skipped if nothing was saved). SELLs on credit-bond legs are
    dropped since they cannot be shorted.
    """
    rows_by_id: dict[str, dict] = {}
    for p in _load_alpha_book_positions():
        if str(p.get('spread_type', '') or '') == 'TenorSpread' and not has_7y_leg(p.get('instrument', '')):
            rows_by_id[str(p.get('instrument', '') or '')] = p
    try:
        snap = load_spread_data('TenorSpread')
    except Exception:
        snap = None
    for c in load_core_seed():
        cid = str(c.get('ID', '') or '')
        if not cid or cid in rows_by_id:
            continue
        z = np.nan
        if isinstance(snap, pd.DataFrame) and cid in snap.index and 'Zscore' in snap.columns:
            z = pd.to_numeric(snap.loc[cid, 'Zscore'], errors='coerce')
        rows_by_id[cid] = {
            'ID': cid, 'instrument': cid, 'spread_type': 'TenorSpread',
            'Zscore': None if pd.isna(z) else float(z), 'direction': '',
        }

    open_rows: list[dict] = []
    n_flat = 0
    for inst_id, p in rows_by_id.items():
        results = run_instrument_backtest('TenorSpread', inst_id)
        state = None if results is None else latest_position(results)
        if state == 'FLAT':
            n_flat += 1
            continue
        if state in ('BUY', 'SELL'):
            # Regime = the style of the trade the backtest actually holds.
            _style = str((results.get('open_trade') or {}).get('style', '')).lower()
            p = {**p, 'direction': state,
                 'regime': 'momentum' if _style == 'trend' else 'mean-reverting' if _style == 'mr' else p.get('regime', '')}
        elif not p.get('direction'):
            continue
        if str(p.get('direction', '')).upper() == 'SELL' and not short_allowed(inst_id):
            continue
        open_rows.append(p)
    return open_rows, n_flat



def mr_stop_target_bp(instrument_id: str) -> Optional[tuple[float, float]]:
    """(stop_bp, target_bp) distances from the current spread, from the
    instrument's saved backtest params -- mean-reverting names only.

    Mirrors the backtest's MR exits (engine_monthly): the target is hit when
    |z| falls to ``exit_z``, the stop when |z| rises to ``stop_z``, with z
    measured against the EWMA sigma the engine uses. Distances are magnitudes
    in bp, measured in the adverse (stop) / favourable (target) direction from
    today's spread, floored at 0 (0 = already at/through the level). Returns
    None when the backtest cannot run, the current style is not MR, or the
    z-score is unavailable -- callers keep their generic formula then.
    """
    from ..backtest.engine_monthly import MR_VOL_SPAN

    res = run_instrument_backtest('TenorSpread', instrument_id)
    if not isinstance(res, dict):
        return None
    style_ts = res.get('style_ts')
    if style_ts is None or len(style_ts) == 0 or str(style_ts.iloc[-1]).lower() != 'mr':
        return None
    z_ts, s = res.get('zscore_ts'), res.get('spread_ts')
    if z_ts is None or s is None or z_ts.dropna().empty:
        return None
    z = abs(float(z_ts.dropna().iloc[-1]))
    s = pd.to_numeric(s, errors='coerce').dropna()
    span = max(int(MR_VOL_SPAN), 2)
    sigma = float(s.ewm(span=span, min_periods=span).std().iloc[-1])
    if not np.isfinite(sigma) or sigma <= 0:
        return None
    exit_z, stop_z = float(res['exit_z']), float(res['stop_z'])
    scale = 100.0  # TenorSpread series are in % -> bp (same as the table's spread/vol)
    return (max(stop_z - z, 0.0) * sigma * scale, max(z - exit_z, 0.0) * sigma * scale)


_EXIT_CACHE: dict = {}
_EXIT_CACHE_TTL_S = 60.0


def backtest_exit_signal(instrument_id: str, open_date) -> Optional[tuple[str, str, pd.Timestamp]]:
    """Has the backtest (saved params) already exited a trade the book holds?

    Returns ``(exit_reason, direction, exit_date)`` when the backtest is FLAT
    today and its most recent closed trade exited on/after ``open_date`` (the
    date the book actually opened the position) -- i.e. the signal says close.
    ``exit_reason`` is the engine's reason: 'target', 'stop_loss', 'max_hold',
    'trailing', 'flip', ... Returns None when the backtest is still holding,
    cannot run, or its last exit predates the book's entry (not our trade).
    Cached for a minute since the table re-renders on every interaction.
    """
    import time

    od = pd.to_datetime(open_date, errors='coerce')
    if pd.isna(od):
        return None
    key = (instrument_id, od.normalize())
    now = time.time()
    hit = _EXIT_CACHE.get(key)
    if hit is not None and now - hit[0] < _EXIT_CACHE_TTL_S:
        return hit[1]

    out = None
    res = run_instrument_backtest('TenorSpread', instrument_id)
    if isinstance(res, dict) and latest_position(res) == 'FLAT':
        tdf = res.get('trades_df')
        if isinstance(tdf, pd.DataFrame) and not tdf.empty:
            last = tdf.iloc[-1]
            ex = pd.to_datetime(last.get('exit_date'), errors='coerce')
            if pd.notna(ex) and ex.normalize() >= od.normalize():
                out = (str(last.get('exit_reason', '') or ''), str(last.get('direction', '') or ''), ex)
    _EXIT_CACHE[key] = (now, out)
    return out
