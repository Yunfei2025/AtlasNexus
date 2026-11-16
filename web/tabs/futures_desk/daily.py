# -*- coding: utf-8 -*-
"""Futures Desk: daily-bar strategies (e.g. 'ATR@1D'), approved next to a product's intraday strategy.

A daily strategy lives on the continuous daily series of the product (e.g. TL.CFE), never on a specific contract
(TL2612.CFE): its evidence, its signal and its forward P&L all come from that series. A daily strategy is held
overnight: the position held from one close to the next is the signal of the first close's bar, and the backtest
trades at that close. So the desk acts near the close: today's bar is built from the continuous code's own minute
bars while it forms, the signal on it is provisional until about five minutes before the close, and the ticket is
to trade the change in position at the close.

The series file is updated by other apps and lags the market by a day or more. The days it lacks, and today's
forming bar, are fetched from Wind for the same continuous code (`fetch_tail`) and saved next to the live files, so
Portfolio and Monitor read them without calling Wind. Only the ticket's contract name comes from the main-contract
list: the order has to name a real contract.
"""

from __future__ import annotations

import os
import threading

import numpy as np
import pandas as pd

from futures.backtest.costs import apply_costs, trade_stats
from futures.backtest.live_bars import FIELDS, LIVE_DIR, china_now, main_contract_codes
from futures.backtest.walkforward import (
    DAILY_FILE, STRATEGIES, daily_pnl_of, load_daily_df, max_units,
)

from .contracts import day_close

FINAL_MIN_BEFORE_CLOSE = 5   # the daily signal is final this many minutes before the session close
_tail_lock = threading.Lock()


def daily_symbol(product, path=None):
    """The continuous code of a product in the daily series file (e.g. 'TL.CFE'), or None."""
    from futures.backtest.costs import product_of
    from futures.backtest.data_loader import load_raw_file
    try:
        raw = load_raw_file(str(path or DAILY_FILE)) or {}
    except Exception:
        return None
    return next((k for k in raw if product_of(k) == product), None)


def _tail_path(symbol, live_dir=None):
    return os.path.join(str(live_dir or LIVE_DIR), f"daily_tail_{symbol.replace('.', '_')}.parquet")


def load_tail(symbol, live_dir=None):
    """The saved bars the series file does not have yet (one row per trade date, 'asof' = last minute), or None."""
    path = _tail_path(symbol, live_dir)
    return pd.read_parquet(path) if os.path.exists(path) else None


def bars_to_daily(minute):
    """Day-session minute bars -> one daily bar per trade date, with the time of its last minute in 'asof'."""
    g = minute.groupby(minute.index.normalize())
    out = pd.DataFrame({'open': g['open'].first(), 'high': g['high'].max(), 'low': g['low'].min(),
                        'close': g['close'].last(), 'volume': g['volume'].sum()})
    out['asof'] = pd.Series({d: x.index.max() for d, x in g})
    return out.dropna(subset=['close'])


def fetch_tail(product, now=None, wsi=None, live_dir=None, closed_only=False, wind_off=None, path=None):
    """Fetch the continuous code's minute bars from the day after the series file's last date to now, make them
    daily bars and save them. closed_only skips the call while the session is open (the Live monitor's rule: Wind
    is only asked when it is running); a finished day that is already saved is not asked again. Returns
    {'skipped', 'rows', 'symbol'} or {'error'}."""
    now = now or china_now()
    df = load_daily_df(product, path)
    symbol = daily_symbol(product, path)
    if df is None or symbol is None:
        return {'error': f'no daily series for {product}'}
    t = now.strftime('%H:%M:%S')
    in_session = now.weekday() < 5 and '08:55:00' <= t < '15:15:00'
    if in_session and closed_only:
        return {'skipped': 'session open: press Start live for the daily bar', 'symbol': symbol}
    old = load_tail(symbol, live_dir)
    since = df.index.max() + pd.Timedelta(days=1)
    if old is not None and len(old) and not in_session and t >= '15:15:00' and old['asof'].iloc[-1] >= pd.Timestamp(now.date()) + pd.Timedelta(hours=14, minutes=59):
        return {'skipped': None, 'rows': int(len(old)), 'symbol': symbol}   # the finished day is saved already
    if wsi is None:
        from data.providers.retrieve import _wind_disabled, _wsi
        if closed_only and (wind_off or _wind_disabled)():
            return {'skipped': 'Wind disabled', 'symbol': symbol}

        def wsi(*args):
            return _wsi(*args, on_demand=not closed_only)
    with _tail_lock:
        try:
            frame = wsi(symbol, FIELDS, since.strftime('%Y-%m-%d 08:55:00'), now.strftime('%Y-%m-%d %H:%M:%S'))
        except Exception as e:
            return {'error': str(e), 'symbol': symbol}
        if frame is None or not isinstance(frame, pd.DataFrame) or frame.empty:
            return {'error': f'Wind returned no bars for {symbol} (not connected, or a holiday)', 'symbol': symbol}
        f = frame.copy()
        f.columns = [str(c).lower() for c in f.columns]
        f.index = pd.to_datetime(f.index, errors='coerce')
        f = f[f.index.notna()].sort_index()
        for c in ('open', 'high', 'low', 'close', 'volume'):
            f[c] = pd.to_numeric(f.get(c), errors='coerce')
        f = f.dropna(subset=['close'])
        f = f[(f['close'] > 0) & (f.index.strftime('%H:%M') >= '08:55') & (f.index.strftime('%H:%M') <= '15:15')]
        if f.empty:
            return {'error': f'no day-session bars for {symbol}', 'symbol': symbol}
        tail = bars_to_daily(f)
        path_ = _tail_path(symbol, live_dir)
        os.makedirs(os.path.dirname(path_), exist_ok=True)
        tail.to_parquet(path_ + '.tmp', compression='zstd')
        os.replace(path_ + '.tmp', path_)
    return {'skipped': None, 'rows': int(len(tail)), 'symbol': symbol}


def extended_daily(product, live_dir=None, path=None):
    """The continuous daily series plus its saved tail (dates after the file's last), or None without the series."""
    df = load_daily_df(product, path)
    if df is None:
        return None
    symbol = daily_symbol(product, path)
    tail = load_tail(symbol, live_dir) if symbol else None
    if tail is not None and len(tail):
        extra = tail[tail.index > df.index.max()][['open', 'high', 'low', 'close', 'volume']]
        if len(extra):
            df = pd.concat([df, extra])
    return df


def daily_replay(product, rec, live_dir=None):
    """The daily strategy over the extended series: (bars, result frame of apply_costs)."""
    df = extended_daily(product, live_dir)
    if df is None:
        raise ValueError(f"no daily series for {product}")
    strategy = rec['candidate'].split('@')[0]
    res = apply_costs(STRATEGIES[strategy](df), rec['cost_bp'], flat_at_close=False, exits=rec.get('exits'))
    return df, res


def forward_replay_daily(product, rec, live_dir=None):
    """Daily net P&L of the approved daily strategy on each trade date after rec['wf_last_day'] (the Monitor's
    forward series, as a return on the full position): {'series', 'trades', 'win'}, empty before any forward day."""
    df, res = daily_replay(product, rec, live_dir)
    after = pd.Timestamp(rec['wf_last_day'])
    series = daily_pnl_of(res) / rec.get('max_units', max_units(rec['candidate']))
    series = series[series.index > after]
    fwd = res[res.index > after]
    st = trade_stats(fwd, rec['cost_bp']) if len(fwd) else {'trades': 0, 'win': float('nan')}
    return {'series': series, 'trades': st['trades'], 'win': st['win']}


def _contract_name(product, symbol):
    """The real contract an order must name (the series itself is the continuous code)."""
    try:
        code = main_contract_codes().get(product)
        return code.split('.')[0] if code else symbol
    except Exception:
        return symbol


def daily_state(product, rec, now=None, live_dir=None):
    """Where the approved daily strategy stands on the latest bar of the continuous series: the position held now
    (decided at the previous bar's close), the position the strategy wants at this bar's close (provisional until
    `final_at`), and what changed. 'fresh' is False when the series (plus its saved tail) does not reach the
    current trading day, in which case no ticket should be shown. Same shape as the intraday rows where the Live
    monitor and Portfolio need it ('daily': True)."""
    now = now or china_now()
    df, res = daily_replay(product, rec, live_dir)
    symbol = daily_symbol(product)
    day = pd.Timestamp(df.index.max()).normalize()
    sig = res['signal'].astype(float)   # units: a layered strategy (ATR) holds up to max_units of them
    units = rec.get('max_units', max_units(rec['candidate']))
    k = sig.index.get_loc(day)
    target = float(sig.iloc[k])
    held = float(sig.iloc[k - 1]) if k > 0 else 0.0
    changed = sig.index[(sig != sig.shift()).to_numpy()]
    since = changed[-1] if len(changed) else None
    entry_px = float(res['close'].loc[since]) if target != 0 and since is not None else None
    close_hm = day_close(product)
    close_t = day + pd.Timedelta(hours=int(close_hm[:2]), minutes=int(close_hm[3:]))
    tail = load_tail(symbol, live_dir) if symbol else None
    from_tail = tail is not None and day in tail.index
    as_of = pd.Timestamp(tail.loc[day, 'asof']) if from_tail else close_t
    today = pd.Timestamp(now).normalize() if now.strftime('%H:%M') >= '08:55' else pd.Timestamp(now).normalize() - pd.Timedelta(days=1)
    while today.weekday() >= 5:
        today -= pd.Timedelta(days=1)
    fresh = bool(day >= today)
    closed = bool(day < today or now >= close_t.to_pydatetime() or (from_tail and as_of >= close_t - pd.Timedelta(minutes=1)))
    return {
        'product': product, 'key': f'{product}|1D', 'daily': True, 'symbol': symbol, 'contract': _contract_name(product, symbol),
        'candidate': rec['candidate'], 'day': day, 'closed': closed, 'fresh': fresh,
        'held': int(np.sign(held)), 'position': int(np.sign(target)), 'units': target, 'held_units': held, 'max_units': units,
        'since': since, 'entry_px': entry_px, 'last_px': float(df['close'].iloc[-1]),
        'as_of': as_of, 'fetched_at': pd.Timestamp(now),
        'day_return': float(res['strategy_returns'].iloc[-1]) / units, 'round_trips': int(held != target),
        'stop_px': None, 'target_px': None, 'exited_at': None, 'trades': [],
        'final_at': close_t - pd.Timedelta(minutes=FINAL_MIN_BEFORE_CLOSE), 'close_at': close_t,
        'bars': df.tail(40)[['open', 'high', 'low', 'close']],
    }
