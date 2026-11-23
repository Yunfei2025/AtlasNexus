# -*- coding: utf-8 -*-
"""Futures Desk > Monitor: paper P&L of each approved strategy since its walk-forward, against the band
the walk-forward expected (pure logic, local files only)."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from futures.backtest.costs import apply_costs, trade_stats
from futures.backtest.live_bars import (
    china_now, live_meta_for, load_live, load_night, night_meta_for, night_session, with_live,
)
from futures.backtest import night as night_mod
from futures.backtest.minute_bars import export_monitor_slice, load_minute_bars
from futures.backtest.walkforward import (
    CONTINUOUS_STRATEGIES, STRATEGIES, _P, daily_pnl_of, load_walkforward, product_minute_bars, resample_bars,
)

from . import approvals
from . import daily as daily_mod

HAIRCUT = 0.5          # expected mean = this share of the walk-forward mean (selection bias)
MIN_FORWARD_DAYS = 5   # fewer forward days than this is too early for a band verdict
BAND_HORIZON = 20      # the expected cone is drawn at least this many days ahead


def is_night_day(rec):
    """True for a strategy approved on night + day bars (approvals.approve with a night + day walk-forward)."""
    return (rec or {}).get('session') == 'night+day'


def is_continuous(rec):
    """True for a night + day approval from a continuous run: the position is carried through every close."""
    return bool((rec or {}).get('continuous'))


def strategy_of(strategy, rec):
    """The approved strategy's function: its continuous form for a continuous approval, else the plain one."""
    return CONTINUOUS_STRATEGIES.get(strategy) or STRATEGIES[strategy] if is_continuous(rec) else STRATEGIES[strategy]


def forward_replay(product, rec):
    """Daily net P&L of the approved strategy on each main-contract day after rec['wf_last_day'], from the
    tick files or the shared minute-bar cache. Returns {'series', 'trades', 'win'} (empty before any
    forward day)."""
    contract = product_minute_bars(product, latest=3, night=is_night_day(rec))
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
        res = apply_costs(strategy_of(strategy, rec)(resample_bars(contract[c], timeframe)), rec['cost_bp'],
                          flat_at_close=not is_continuous(rec), exits=rec.get('exits'))
        parts.append(daily_pnl_of(res).reindex(days).fillna(0.0))
        stats.append(trade_stats(res[res.index.normalize().isin(days)], rec['cost_bp']))
    n_tr = sum(s['trades'] for s in stats)
    wins = sum(s['win'] * s['trades'] for s in stats if not math.isnan(s['win']))
    return {'series': pd.concat(parts).sort_index(), 'trades': n_tr, 'win': wins / n_tr if n_tr else float('nan')}


def with_finished_live_day(product, rec, fwd):
    """Add today's P&L to the forward series once the live session is complete.

    forward_replay reads settled bar files only, so a day that finished after the last bar-cache sync is
    missing: the losing streak, z-score and status then ignore it (e.g. "3 losing days" on a day that made
    money). A session still in progress is left out -- a partial day must not extend or break a streak."""
    try:
        live = live_state(product, rec)
    except Exception:
        return fwd
    if not live or not live.get('closed'):
        return fwd
    day = pd.Timestamp(live['day']).normalize()
    series = fwd['series']
    if day <= pd.Timestamp(rec['wf_last_day']) or day in pd.DatetimeIndex(series.index).normalize():
        return fwd
    series = pd.concat([series, pd.Series([live['day_return']], index=[day])]).sort_index()
    return dict(fwd, series=series)


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


def longest_losing_run(series):
    """Longest run of consecutive losing days anywhere in `series` (flat days neither extend nor break it)."""
    best = cur = 0
    for v in series[series != 0]:
        cur = cur + 1 if v < 0 else 0
        best = max(best, cur)
    return best


def evidence_streak(product, rec):
    """The approved strategy's own longest losing run in its walk-forward, up to the approval's last day (None
    when the run is not on file). A stop-heavy strategy with a low win rate has long losing runs by design, so
    the Monitor judges its forward streak against this, not against one number for every strategy."""
    if rec.get('max_streak') is not None:
        return int(rec['max_streak'])
    wf = load_walkforward(product, approvals.DESK_DIR, night=is_night_day(rec)) or {}
    s = pd.Series(((wf.get('daily_pnl') or {}).get(rec['candidate'])) or {}, dtype=float)
    s = s[s.index <= rec['wf_last_day']]
    return longest_losing_run(s) if len(s) else None


def assess(series, mean, std, watch_sig=1.0, halt_sig=2.0, halt_losses=5, max_streak=None):
    """Compare forward P&L with the expected path (haircut mean, walk-forward std).
    Returns status 'early' | 'ok' | 'watch' | 'halted' with the reasons and the z-score.

    A losing streak halts at `halt_losses` days, or, when the strategy's own walk-forward lost more days in a row
    than that (max_streak), only once it beats that run; it watches two days earlier (at least 2)."""
    n = len(series)
    streak = losing_streak(series)
    halt_at = max(halt_losses, (max_streak or 0) + 1)
    watch_at = max(halt_at - 2, 2)
    own = f" (its walk-forward's longest run was {max_streak})" if max_streak and halt_at > halt_losses else ""
    z = None
    if n and mean is not None and std:
        z = float((series.sum() - HAIRCUT * mean * n) / (std * math.sqrt(n)))
    reasons = []
    if z is not None and z <= -halt_sig:
        reasons.append(f"P&L {z:+.1f}σ below the expected path")
    if streak >= halt_at:
        reasons.append(f"{streak} losing days in a row{own}")
    if reasons:
        return {'status': 'halted', 'z': z, 'streak': streak, 'reasons': reasons, 'halt_at': halt_at}
    if z is not None and z <= -watch_sig:
        reasons.append(f"P&L {z:+.1f}σ below the expected path")
    if streak >= watch_at:
        reasons.append(f"{streak} losing days in a row{own}")
    if reasons:
        return {'status': 'watch', 'z': z, 'streak': streak, 'reasons': reasons, 'halt_at': halt_at}
    return {'status': 'early' if n < MIN_FORWARD_DAYS else 'ok', 'z': z, 'streak': streak, 'reasons': [],
            'halt_at': halt_at}


def band(mean, std, n_days, k):
    """Expected cumulative P&L after 1..n_days with a ±k·σ·√n band."""
    n = np.arange(1, n_days + 1)
    mid = HAIRCUT * mean * n
    return n, mid, mid - k * std * np.sqrt(n), mid + k * std * np.sqrt(n)


def monitor_rows(watch_sig=1.0, halt_sig=2.0, halt_losses=5):
    """One entry per approved/watch/halted product with its forward replay and assessment."""
    out = []
    approved = approvals.load_approved()
    members = approvals.load_portfolio()   # the Monitor follows the portfolio; no saved portfolio = every approval
    if members is not None:
        approved = {p: r for p, r in approved.items() if p in members}
    try:   # keep the small bar slice (what a computer without the full cache shows) current
        export_monitor_slice({p: r for p, r in approved.items() if r.get('wf_last_day')})
    except Exception:
        pass
    for prod, rec in approved.items():
        row = {'product': prod, 'key': prod, 'rec': rec, 'current': rec.get('status', 'approved')}
        try:
            mean, std = evidence_moments(prod, rec)
            fwd = with_finished_live_day(prod, rec, forward_replay(prod, rec))
            row.update(fwd=fwd, mean=mean, std=std,
                       **{'assessment': assess(fwd['series'], mean, std, watch_sig, halt_sig, halt_losses,
                                               max_streak=evidence_streak(prod, rec))})
        except Exception as e:
            row['error'] = str(e)
        out.append(row)
    keys = None if members is None else {k[:-3] for k in members if k.endswith('|1D')}
    for prod, rec in approvals.load_approved_daily().items():   # daily strategies: their own series, held overnight
        if keys is not None and prod not in keys:
            continue
        row = {'product': prod, 'key': f'{prod}|1D', 'daily': True, 'rec': rec, 'current': rec.get('status', 'approved')}
        try:
            fwd = daily_mod.forward_replay_daily(prod, rec)
            row.update(fwd=fwd, mean=rec.get('daily_mean'), std=rec.get('daily_std'),
                       **{'assessment': assess(fwd['series'], rec.get('daily_mean'), rec.get('daily_std'), watch_sig,
                                               halt_sig, halt_losses, max_streak=rec.get('max_streak'))})
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
    now = now or china_now()   # Beijing: the live files are stamped in exchange time
    contract, meta = live_meta_for(product, live_dir)
    if contract is None or not (meta.get('complete') or meta.get('date') == now.strftime('%Y-%m-%d')):
        return None
    day = pd.Timestamp(meta['date'])
    closed = bool(meta.get('complete'))
    live, _ = load_live(contract, live_dir)
    if is_night_day(rec):
        bars = with_live(load_minute_bars(contract, night=True, live_dir=live_dir), live)
        bars = night_mod.with_night(bars, night_mod.load_night_history(contract, live_dir))   # tonight's night joins today
        return _unshifted(_session_state(product, contract, rec, bars, day, closed, meta['fetched_at']), bars)
    bars = with_live(load_minute_bars(contract, live_dir=live_dir), live)
    return _session_state(product, contract, rec, bars, day, closed, meta['fetched_at'])


def _unshifted(st, bars, extra_days=()):
    """A session state computed on a night + day frame with its night stamps put back to real exchange time."""
    if st is None:
        return None
    days = pd.DatetimeIndex(sorted(set(bars.index[(bars.index - bars.index.normalize()) >= night_mod.DAY_OPEN].normalize())
                                   | {pd.Timestamp(d) for d in extra_days}))
    un = lambda t: night_mod.unshift(t, days)
    st['bars'] = st['bars'].set_axis([un(t) for t in st['bars'].index])
    st['trades'] = [dict(t, entry_t=un(t['entry_t']), exit_t=un(t['exit_t'])) for t in st['trades']]
    st.update(as_of=un(st['as_of']), since=un(st['since']), exited_at=un(st['exited_at']), session='night+day')
    return st


def night_led_state(product, rec, now=None, live_dir=None):
    """The next trade day's session while only its night part has traded (20:55 to 08:55): a night + day
    strategy is already working then, so its position, signals and tickets belong to that coming day. Built on
    the cached night + day bars plus the live night file stamped onto the coming trade date. None outside that
    window, for a product without a night session, or without a night file for tonight."""
    now = now or china_now()
    win = night_session(product, now)
    t = now.strftime('%H:%M:%S')
    if win is None or not (t >= '20:55:00' or t < '08:55:00'):
        return None
    contract, meta = night_meta_for(product, live_dir)
    if contract is None or meta.get('date') != win[0]:
        return None
    live_night, _ = load_night(contract, live_dir)
    if live_night is None or live_night.empty:
        return None
    from curves.utils.cn_calendar import is_cn_workday
    day = pd.Timestamp(win[0]) + pd.Timedelta(days=1)
    while not is_cn_workday(day.date()):
        day += pd.Timedelta(days=1)
    hist = load_minute_bars(contract, night=True, live_dir=live_dir)
    live_day, live_meta = load_live(contract, live_dir)
    if live_day is not None and live_meta and pd.Timestamp(live_meta['date']) < day:   # today's day session, not cached yet
        hist = night_mod.with_night(with_live(hist, live_day), night_mod.load_night_history(contract, live_dir))
    bars = pd.concat([hist, night_mod.restamp_onto(live_night, day).reindex(columns=hist.columns)])
    bars = bars[~bars.index.duplicated(keep='last')].sort_index()
    st = _session_state(product, contract, rec, bars, day, False, meta['fetched_at'])
    return _unshifted(st, bars, extra_days=[win[0]])


def night_lookback(strategy, bars, day):
    """(nights present, nights needed) among the trade dates before `day` that a night + day strategy looks back
    over, or None when its lookback is not a plain run of dates. Momentum averages each time slot's offset over
    the previous bf-mom-window dates and is undefined (flat) if any of those dates has no night bars."""
    if strategy != 'Mom':
        return None
    need = int(_P['bf-mom-window'])
    dates = bars.index.normalize()
    prior = sorted(d for d in dates.unique() if d < day)[-need:]
    night = set(dates[(bars.index - dates) < pd.Timedelta(hours=8)])   # night bars are stamped 00:00-05:30
    return sum(d in night for d in prior), need


def _session_state(product, contract, rec, bars, day, closed, fetched_at):
    """live_state's replay of the strategy over `bars`, reporting the session on calendar `day` of that frame."""
    strategy, timeframe = rec['candidate'].split('@')
    raw = strategy_of(strategy, rec)(resample_bars(bars, timeframe))
    res = apply_costs(raw, rec['cost_bp'], flat_at_close=not is_continuous(rec), exits=rec.get('exits'),
                      final_bar_is_close=closed)
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
        'as_of': today.index.max(), 'fetched_at': pd.Timestamp(fetched_at),
        'position': int(pos), 'since': since, 'day': day, 'closed': closed,
        'entry_px': entry_px, 'last_px': float(today['close'].iloc[-1]),
        'day_return': float(today['strategy_returns'].sum()), 'round_trips': trade_stats(today, rec['cost_bp'])['trades'],
        'stop_px': levels['stop'], 'target_px': levels['target'], 'exited_at': exited,
        'bars': today[['open', 'high', 'low', 'close']], 'trades': day_trades(today, ex),
        'lookback': night_lookback(strategy, bars, day) if rec.get('session') == 'night+day' else None,
    }


NIGHT_SHIFT = pd.Timedelta(hours=6)   # moves 21:00-02:30 into one calendar day (15:00-20:30) so the replay treats it as one session


def night_state(product, rec, now=None, live_dir=None):
    """Display-only replay of the approved strategy over a product's night session (the open one, else the last
    finished one), in the same shape as live_state plus 'night': True.

    The desk has no night history: the walk-forward and the minute-bar cache hold day sessions only, so this
    strategy was never tested on night bars. It runs on the night bars alone (no warm-up from the day
    session), at its default parameters, flat at the session end. It must never feed the Monitor statuses,
    streaks or the book. None when the product has no night session or no night bars are on file."""
    now = now or china_now()
    win = night_session(product, now)
    if win is None:
        return None
    contract, meta = night_meta_for(product, live_dir)
    if contract is None or meta.get('date') != win[0]:
        return None
    bars, _ = load_night(contract, live_dir)
    if bars is None or bars.empty:
        return None
    shifted = bars.copy()
    shifted.index = shifted.index - NIGHT_SHIFT
    day = pd.Timestamp(shifted.index.min()).normalize()
    st = _session_state(product, contract, rec, shifted, day, bool(meta.get('complete')), meta['fetched_at'])
    if st is None:
        return None
    back = lambda t: None if t is None else t + NIGHT_SHIFT
    st['bars'] = st['bars'].set_axis(st['bars'].index + NIGHT_SHIFT)
    st['trades'] = [dict(t, entry_t=back(t['entry_t']), exit_t=back(t['exit_t'])) for t in st['trades']]
    st.update(as_of=back(st['as_of']), since=back(st['since']), exited_at=back(st['exited_at']),
              day=pd.Timestamp(win[0]), night=True)
    return st
