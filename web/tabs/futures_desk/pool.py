# -*- coding: utf-8 -*-
"""Futures Desk > Today: pool screen and today's book (pure logic, no Dash)."""

from __future__ import annotations

import math
import os
import re
from datetime import datetime
from itertools import combinations

import numpy as np
import pandas as pd

from futures.backtest.costs import default_cost_bp, product_of
from futures.backtest.data_loader import load_raw_file
from futures.backtest import minute_bars
from futures.backtest.minute_bars import last_bar_time
from futures.backtest.walkforward import STRATEGIES, load_walkforward, product_minute_bars, resample_bars
from settings.futures import FuturesConfig
from settings.paths import DIR_INPUT

from . import approvals

# CNY per 1.0 move of the quoted price, per lot. Typed in from exchange contract specs, NOT read from
# any data feed: verify before sizing real orders.
CONTRACT_MULTIPLIER = {
    'IF': 300, 'IH': 300, 'IC': 200, 'IM': 200,
    'T': 10000, 'TF': 10000, 'TS': 20000, 'TL': 10000,
    'AU': 1000, 'AG': 15, 'CU': 5, 'AL': 5, 'ZN': 5, 'RB': 10,
    'LC': 1, 'SA': 20, 'SC': 1000, 'JM': 60, 'EC': 50,
}
MAX_BOOK = 5
PNL_CORR_WARN = 0.5

_panel_cache = {'mtime': None, 'data': None}


def daily_panels():
    """(close, volume) panels of the futures pool from futures-dailyK_con.pkl, cached on file mtime."""
    path = DIR_INPUT / 'futures-dailyK_con.pkl'
    mtime = path.stat().st_mtime
    if _panel_cache['mtime'] != mtime:
        raw = load_raw_file(str(path)) or {}
        pool = [s for s in FuturesConfig.SYMBOLS if s in raw]

        def panel(col):
            p = pd.DataFrame({s: pd.to_numeric(raw[s][col], errors='coerce') for s in pool})
            p.index = pd.to_datetime(p.index)
            return p.sort_index()

        _panel_cache.update(mtime=mtime, data=(panel('Close'), panel('Volume')))
    return _panel_cache['data']


def least_correlated(corr, n=MAX_BOOK):
    """The n names with the lowest mean |pairwise correlation| (exhaustive search)."""
    a = corr.abs().values
    best, best_score = None, float('inf')
    for combo in combinations(range(len(a)), n):
        idx = np.array(combo)
        score = a[np.ix_(idx, idx)].sum()  # diagonal is a constant n, so the sum ranks the same
        if score < best_score:
            best, best_score = combo, score
    return [corr.index[i] for i in best], (best_score - n) / (n * (n - 1))


def _busdays_since(ts, today):
    return int(np.busday_count(ts.date(), today.date()))


def screen_rows(today=None):
    """One row per product of the pool: data status, liquidity, volatility, cost and approval."""
    today = today or datetime.now()
    close, volume = daily_panels()
    approved = approvals.load_approved()
    tick_dir = minute_bars.TICK_DIR
    with_ticks = ({re.match(r'[A-Z]+', f).group() for f in os.listdir(tick_dir) if re.fullmatch(r'[A-Z]+\d{3,4}\.pkl', f)}
                  if os.path.isdir(tick_dir) else set())
    rows = []
    for sym in close.columns:
        prod = product_of(sym)
        c = close[sym].dropna()
        wf = load_walkforward(prod, approvals.DESK_DIR)
        a = approved.get(prod)
        rows.append({
            'product': prod, 'symbol': sym,
            'daily_last': c.index.max(), 'stale_days': _busdays_since(c.index.max(), today),
            'gaps_1y': int(close[sym].tail(252).isna().sum()),
            'volume_20d': float(volume[sym].tail(20).mean()),
            'vol_ann': float(c.pct_change().tail(20).std() * math.sqrt(252)),
            'cost_bp': wf['cost_bp'] if wf else default_cost_bp(prod),
            'cost_src': 'measured' if wf else 'default',
            'intraday_to': last_bar_time(prod), 'has_ticks': prod in with_ticks,
            'wf_run_at': wf['run_at'] if wf else None,
            'status': (a or {}).get('status', 'approved') if a else None,
            'candidate': a['candidate'] if a else None,
            'pooled_sharpe': a['pooled_sharpe'] if a else None,
        })
    return rows


def intraday_state(product, candidate):
    """Main contract (most traded on the latest day), its last price and the approved strategy's current
    signal on the latest minute bars (tick files or the shared bar cache)."""
    contracts = product_minute_bars(product, latest=2)
    if not contracts:
        raise ValueError(f"no intraday data for {product}")

    def recency(item):
        b = item[1]
        day = b.index.normalize()
        return day.max(), float(b.loc[day == day.max(), 'volume'].sum())

    name, bars = max(contracts.items(), key=recency)
    strategy, timeframe = candidate.split('@')
    sig = STRATEGIES[strategy](resample_bars(bars, timeframe))['signal'].astype(float)
    return {
        'contract': name, 'last_price': float(bars['close'].iloc[-1]), 'last_time': bars.index[-1],
        'signal': float(sig.iloc[-1]), 'since': sig.index[(sig != sig.shift()).to_numpy()][-1],
    }


def pnl_panel(candidates):
    """Daily strategy P&L per product from the stored walk-forward runs. `candidates` maps
    product -> candidate name."""
    series = {}
    for prod, cand in candidates.items():
        wf = load_walkforward(prod, approvals.DESK_DIR)
        s = ((wf or {}).get('daily_pnl') or {}).get(cand)
        if s:
            ser = pd.Series(s)
            ser.index = pd.to_datetime(ser.index)
            series[prod] = ser
    return pd.DataFrame(series).sort_index()


def select_book(max_n=MAX_BOOK):
    """Who is in today's book: approved products that are not halted (Watch still trades), at most max_n,
    the least correlated by strategy P&L. Returns the approvals, the chosen / excluded / halted products and
    the strategy-P&L correlation matrix among the chosen (None with fewer than 2 products with P&L)."""
    stored = approvals.load_approved()
    approved = {p: a for p, a in stored.items() if a.get('status', 'approved') != 'halted'}
    sel = {'approved': approved, 'chosen': list(approved), 'excluded': [], 'corr': None,
           'halted': [p for p, a in stored.items() if a.get('status') == 'halted'], 'candidates': {}}
    if not approved:
        return sel
    sel['candidates'] = {p: a['candidate'] for p, a in approved.items()}
    panel = pnl_panel(sel['candidates'])
    corr = panel.corr(min_periods=20) if panel.shape[1] > 1 else None
    if len(sel['chosen']) > max_n:
        sub = corr.reindex(index=sel['chosen'], columns=sel['chosen']).fillna(1.0) if corr is not None else None
        sel['chosen'] = least_correlated(sub, max_n)[0] if sub is not None else sel['chosen'][:max_n]
        sel['excluded'] = [p for p in approved if p not in sel['chosen']]
    if corr is not None:
        sel['corr'] = corr.reindex(index=sel['chosen'], columns=sel['chosen'])
    return sel


def build_book(capital, risk_pct, stop_mult, loss_limit_pct, today=None, max_n=MAX_BOOK):
    """Today's book: up to max_n approved products, least correlated by strategy P&L, each sized so a
    stop-out costs risk_pct of capital."""
    today = today or datetime.now()
    sel = select_book(max_n)
    approved, chosen = sel['approved'], sel['chosen']
    book = {'rows': [], 'excluded': sel['excluded'], 'warnings': [], 'corr': sel['corr'],
            'approved_n': len(approved), 'halted': sel['halted']}
    if not approved:
        return book
    if sel['corr'] is not None:
        for i, a in enumerate(chosen):
            for b in chosen[i + 1:]:
                v = sel['corr'].loc[a, b]
                if pd.notna(v) and abs(v) > PNL_CORR_WARN:
                    book['warnings'].append(f"{a} and {b} strategy P&L correlation {v:+.2f}")

    close, _ = daily_panels()
    sym_of = {product_of(s): s for s in close.columns}
    risk_budget = capital * risk_pct / 100
    last_bday = np.busday_offset(np.datetime64(today.date()), -1, roll='backward')
    for prod in chosen:
        a = approved[prod]
        row = {'product': prod, 'candidate': a['candidate'], 'multiplier': CONTRACT_MULTIPLIER.get(prod)}
        if a.get('status') == 'watch':
            book['warnings'].append(f"{prod} is on Watch: {a.get('status_reason', '')}")
        try:
            st = intraday_state(prod, a['candidate'])
            sigma = float(close[sym_of[prod]].dropna().pct_change().tail(20).std())
            stop_pts = stop_mult * sigma * st['last_price']
            mult = row['multiplier']
            if mult is None:
                raise ValueError("no contract multiplier on file")
            lots = int(risk_budget // (stop_pts * mult)) if stop_pts > 0 else 0
            direction = int(st['signal'])
            row.update(
                contract=st['contract'], last_price=st['last_price'], last_time=st['last_time'],
                signal=direction, since=st['since'], daily_sigma=sigma, stop_pts=stop_pts, lots=lots,
                stop_price=st['last_price'] - direction * stop_pts if direction else None,
                risk_cny=lots * stop_pts * mult, notional=lots * st['last_price'] * mult,
                stale=np.datetime64(st['last_time'].date()) < last_bday,
            )
            if lots == 0:
                book['warnings'].append(f"{prod}: one lot risks {stop_pts * mult / capital * 100:.2f}% of capital "
                                        f"at this stop, above the {risk_pct:g}% budget: no position")
            if row['stale']:
                book['warnings'].append(f"{prod}: latest intraday data is {st['last_time']:%Y-%m-%d %H:%M}, "
                                        f"older than the last trading day")
        except Exception as e:
            row['error'] = str(e)
        book['rows'].append(row)

    live = [r for r in book['rows'] if 'error' not in r]
    book['risk_cny'] = sum(r['risk_cny'] for r in live)
    book['notional'] = sum(r['notional'] for r in live)
    book['leverage'] = book['notional'] / capital if capital else float('nan')
    book['loss_limit_cny'] = capital * loss_limit_pct / 100
    if book['risk_cny'] > book['loss_limit_cny']:
        book['warnings'].append(f"all stops hit would lose {book['risk_cny'] / capital * 100:.2f}% of capital, "
                                f"above the {loss_limit_pct:g}% daily loss limit")
    return book
