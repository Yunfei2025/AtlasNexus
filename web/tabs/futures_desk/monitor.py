# -*- coding: utf-8 -*-
"""Futures Desk > Monitor: paper P&L of each approved strategy since its walk-forward, against the band
the walk-forward expected (pure logic, local files only)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from futures.backtest.costs import apply_costs, trade_stats
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
                          flat_at_close=True)
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
