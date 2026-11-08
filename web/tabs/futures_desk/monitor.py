# -*- coding: utf-8 -*-
"""Futures Desk > Monitor: paper P&L of each approved strategy since its walk-forward, against the band
the walk-forward expected (pure logic, local files only)."""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd

from futures.backtest.costs import apply_costs, trade_stats
from futures.backtest.live_bars import live_meta_for, load_live, with_live
from futures.backtest.minute_bars import load_minute_bars
from futures.backtest.walkforward import (
    STRATEGIES, daily_pnl_of, load_walkforward, product_minute_bars, resample_bars,
)

from . import approvals

HAIRCUT = 0.5          # expected mean = this share of the walk-forward mean (selection bias)
MIN_FORWARD_DAYS = 5   # fewer forward days than this is too early for a band verdict
BAND_HORIZON = 20      # the expected cone is drawn at least this many days ahead


def forward_replay(product, rec):
    """Daily net P&L of the approved strategy on each main-contract day after rec['wf_last_day'], from the
    tick files or the shared minute-bar cache. Returns {'series', 'trades', 'win'} (empty before any
    forward day)."""
    contract = product_minute_bars(product, latest=3)
    empty = {'series': pd.Series(dtype=float), 'trades': 0, 'win': float('nan')}
    if not contract:
        return empty
    dvol = pd.DataFrame({c: b['volume'].groupby(b.index.normalize()).sum() for c, b in contract.items()})
    main_of = dvol.idxmax(axis=1)
    main_of = main_of[main_of.index > pd.Timestamp(rec['wf_last_day'])]
    if main_of.empty:
        return empty
    strategy, timeframe = rec['candidate'].split('@')
    parts, stats = [], []
    for c in main_of.unique():
        days = main_of.index[main_of == c]
        res = apply_costs(STRATEGIES[strategy](resample_bars(contract[c], timeframe)), rec['cost_bp'],
                          flat_at_close=True, exits=rec.get('exits'))
        parts.append(daily_pnl_of(res).reindex(days).fillna(0.0))
        stats.append(trade_stats(res[res.index.normalize().isin(days)], rec['cost_bp']))
    n_tr = sum(s['trades'] for s in stats)
    wins = sum(s['win'] * s['trades'] for s in stats if not math.isnan(s['win']))
    return {'series': pd.concat(parts).sort_index(), 'trades': n_tr, 'win': wins / n_tr if n_tr else float('nan')}


def evidence_moments(product, rec):
    """Daily mean and std of the approved candidate's walk-forward P&L at approval time."""
    if rec.get('daily_mean') is not None and rec.get('daily_std'):
        return rec['daily_mean'], rec['daily_std']
    wf = load_walkforward(product, approvals.DESK_DIR) or {}
    s = pd.Series(((wf.get('daily_pnl') or {}).get(rec['candidate'])) or {}, dtype=float)
    s = s[s.index <= rec['wf_last_day']]
    return (float(s.mean()), float(s.std())) if len(s) > 1 else (None, None)


def losing_streak(series):
    """Trailing run of losing days; flat (zero) days neither extend nor break it."""
    n = 0
    for v in series[series != 0].iloc[::-1]:
        if v < 0:
            n += 1
        else:
            break
    return n


def assess(series, mean, std, watch_sig=1.0, halt_sig=2.0, halt_losses=5):
    """Compare forward P&L with the expected path (haircut mean, walk-forward std).
    Returns status 'early' | 'ok' | 'watch' | 'halted' with the reasons and the z-score."""
    n = len(series)
    streak = losing_streak(series)
    z = None
    if n and mean is not None and std:
        z = float((series.sum() - HAIRCUT * mean * n) / (std * math.sqrt(n)))
    reasons = []
    if z is not None and z <= -halt_sig:
        reasons.append(f"P&L {z:+.1f}σ below the expected path")
    if streak >= halt_losses:
        reasons.append(f"{streak} losing days in a row")
    if reasons:
        return {'status': 'halted', 'z': z, 'streak': streak, 'reasons': reasons}
    if z is not None and z <= -watch_sig:
        reasons.append(f"P&L {z:+.1f}σ below the expected path")
    if streak >= max(halt_losses - 2, 2):
        reasons.append(f"{streak} losing days in a row")
    if reasons:
        return {'status': 'watch', 'z': z, 'streak': streak, 'reasons': reasons}
    return {'status': 'early' if n < MIN_FORWARD_DAYS else 'ok', 'z': z, 'streak': streak, 'reasons': []}


def band(mean, std, n_days, k):
    """Expected cumulative P&L after 1..n_days with a ±k·σ·√n band."""
    n = np.arange(1, n_days + 1)
    mid = HAIRCUT * mean * n
    return n, mid, mid - k * std * np.sqrt(n), mid + k * std * np.sqrt(n)


def monitor_rows(watch_sig=1.0, halt_sig=2.0, halt_losses=5):
    """One entry per approved/watch/halted product with its forward replay and assessment."""
    out = []
    for prod, rec in approvals.load_approved().items():
        row = {'product': prod, 'rec': rec, 'current': rec.get('status', 'approved')}
        try:
            mean, std = evidence_moments(prod, rec)
            fwd = forward_replay(prod, rec)
            row.update(fwd=fwd, mean=mean, std=std,
                       **{'assessment': assess(fwd['series'], mean, std, watch_sig, halt_sig, halt_losses)})
        except Exception as e:
            row['error'] = str(e)
        out.append(row)
    return out


def computed_to_applied(current, computed):
    """Status to store: computed watch/halted downgrade; ok/early mean 'approved'; halted never auto-resumes."""
    if current == 'halted':
        return 'halted'
    return 'approved' if computed in ('ok', 'early') else computed


def exit_levels(entry_px, direction, exits):
    """Stop / target prices of a position entered at entry_px (None where that exit is off)."""
    out = {'stop': None, 'target': None}
    for k in ('stop', 'target'):
        if entry_px is not None and direction and (exits or {}).get(k):
            dist = entry_px * exits[k] / 100 if exits['unit'] == 'pct' else exits[k]
            out[k] = entry_px - direction * dist if k == 'stop' else entry_px + direction * dist
    return out


def day_trades(today, exits):
    """One dict per position taken today from a result frame (after apply_costs): direction, entry time / price
    (bar close of the signal bar), its stop / target levels, and the exit time / price (the fill, so a stop or
    target shows at its level; None while the position is still open)."""
    sig, idx = today['signal'].to_numpy(), today.index
    close, fill = today['close'].to_numpy(), today['fill'].to_numpy()
    trades, cur = [], None
    for k in range(len(today)):
        if cur is not None and sig[k] != cur['direction']:
            trades.append(dict(cur, exit_t=idx[k], exit_px=float(fill[k])))
            cur = None
        if cur is None and sig[k] != 0 and (k == 0 or sig[k - 1] != sig[k]):
            cur = {'direction': int(sig[k]), 'entry_t': idx[k], 'entry_px': float(close[k])}
            cur.update(exit_levels(cur['entry_px'], cur['direction'], exits))
    if cur is not None:
        trades.append(dict(cur, exit_t=None, exit_px=None))
    return trades


def live_state(product, rec, now=None, live_dir=None):
    """Where an approved strategy stands right now, from settled history plus today's live minute bars.

    Same rules as the walk-forward (default parameters, its cost, flat at every close, its stop / target), with
    today's last bar left open. After the close it is the finished last session (file marked complete).
    None when no live bars have been fetched for today (and no finished session is on file)."""
    now = now or datetime.now()
    contract, meta = live_meta_for(product, live_dir)
    if contract is None or not (meta.get('complete') or meta.get('date') == now.strftime('%Y-%m-%d')):
        return None
    day = pd.Timestamp(meta['date'])
    closed = bool(meta.get('complete'))
    live, _ = load_live(contract, live_dir)
    bars = with_live(load_minute_bars(contract), live)
    strategy, timeframe = rec['candidate'].split('@')
    raw = STRATEGIES[strategy](resample_bars(bars, timeframe))
    res = apply_costs(raw, rec['cost_bp'], flat_at_close=True, exits=rec.get('exits'), final_bar_is_close=closed)
    today = res[res.index.normalize() == day]
    if today.empty:
        return None
    pos = float(today['signal'].iloc[-1])
    sig = res['signal']
    changed = today.index[(sig != sig.shift()).loc[today.index].to_numpy()]
    entries = [t for t in changed if sig.loc[t] != 0]
    entry_t = entries[-1] if pos != 0 and entries else None
    entry_px = float(res.loc[entry_t, 'close']) if entry_t is not None else None
    ex = rec.get('exits') or {}
    levels = exit_levels(entry_px, pos, ex)
    exited = None   # the strategy still wants a position, but the stop / target took it out
    if pos == 0 and raw['signal'].iloc[-1] != 0 and ex and 'fill' in res:
        hit = today.index[(today['fill'] != today['close']).to_numpy()]
        exited = hit[-1] if len(hit) else None
    since = entry_t if entry_t is not None else (exited if exited is not None else (changed[-1] if len(changed) else None))
    return {
        'product': product, 'contract': contract, 'candidate': rec['candidate'],
        'as_of': today.index.max(), 'fetched_at': pd.Timestamp(meta['fetched_at']),
        'position': int(pos), 'since': since, 'day': day, 'closed': closed,
        'entry_px': entry_px, 'last_px': float(today['close'].iloc[-1]),
        'day_return': float(today['strategy_returns'].sum()), 'round_trips': trade_stats(today, rec['cost_bp'])['trades'],
        'stop_px': levels['stop'], 'target_px': levels['target'], 'exited_at': exited,
        'bars': today[['open', 'high', 'low', 'close']], 'trades': day_trades(today, ex),
    }
