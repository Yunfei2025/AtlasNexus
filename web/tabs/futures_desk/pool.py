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

from futures.backtest.costs import apply_exits, default_cost_bp, product_of
from futures.backtest.data_loader import load_raw_file
from futures.backtest import minute_bars
from futures.backtest.minute_bars import last_bar_time
from futures.backtest.walkforward import STRATEGIES, load_walkforward, product_minute_bars, resample_bars, CONTINUOUS_STRATEGIES
from settings.futures import FuturesConfig
from settings.paths import DIR_INPUT

from . import approvals, daily
from .monitor import exit_levels

from futures.backtest.costs import CONTRACT_MULTIPLIER   # noqa: E402  (re-exported: live_ui / actions import it from here)
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
    members = set(portfolio_members())
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
            'in_portfolio': prod in members,
        })
    return rows


def intraday_state(product, candidate, exits=None, night=False, continuous=False):
    """Main contract (most traded on the latest day), its last price and the approved strategy's current
    position on the latest minute bars (tick files or the shared bar cache): flat at every earlier close,
    and after its stop / target if one is set (stays flat until the signal changes)."""
    contracts = product_minute_bars(product, latest=2, night=night)
    if not contracts:
        raise ValueError(f"no intraday data for {product}")

    def recency(item):
        b = item[1]
        day = b.index.normalize()
        return day.max(), float(b.loc[day == day.max(), 'volume'].sum())

    name, bars = max(contracts.items(), key=recency)
    strategy, timeframe = candidate.split('@')
    res = ((CONTINUOUS_STRATEGIES.get(strategy) if continuous else None) or STRATEGIES[strategy])(resample_bars(bars, timeframe))
    sig = res['signal'].astype(float)
    day = sig.index.normalize()
    if not continuous:
        sig[np.r_[day[:-1] != day[1:], False]] = 0.0   # every close but the latest day's (still open)
    if exits:
        sig, _ = apply_exits(res, sig, exits)
    since = sig.index[(sig != sig.shift()).to_numpy()][-1]
    if night:
        from futures.backtest import night as night_mod
        since = night_mod.unshift(since, pd.DatetimeIndex(sorted(set(bars.index[(bars.index - bars.index.normalize()) >= night_mod.DAY_OPEN].normalize()))))
    # entry = close of the bar where the current position was taken (the walk-forward's entry price)
    entry_px = float(res['close'].loc[since]) if sig.iloc[-1] != 0 and 'close' in res else None
    return {
        'contract': name, 'last_price': float(bars['close'].iloc[-1]), 'last_time': bars.index[-1],
        'signal': float(sig.iloc[-1]), 'since': since, 'entry_price': entry_px,
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
    """Who is in the portfolio book. With a saved portfolio (approvals.load_portfolio): exactly its members that
    are still approved and not halted (Watch still trades), in the order added; members that lost their
    approval are reported in 'missing'. Without one: every approved, non-halted product, at most max_n, the
    least correlated by strategy P&L. Returns the approvals, the chosen / excluded / halted / missing products
    and the strategy-P&L correlation matrix among the chosen (None with fewer than 2 products with P&L)."""
    stored = approvals.load_approved()
    approved = {p: a for p, a in stored.items() if a.get('status', 'approved') != 'halted'}
    members = approvals.load_portfolio()
    explicit = members is not None
    stored_d = approvals.load_approved_daily()
    approved_d = {p: a for p, a in stored_d.items() if a.get('status', 'approved') != 'halted'}
    intraday_keys = [k for k in (members or []) if not is_daily_key(k)]
    daily_keys = [k for k in (members or []) if is_daily_key(k)]
    chosen = [p for p in intraday_keys if p in approved] if explicit else list(approved)
    sel = {'approved': approved, 'chosen': chosen, 'excluded': [], 'corr': None, 'explicit': explicit,
           'halted': [p for p, a in stored.items() if a.get('status') == 'halted'], 'candidates': {},
           'missing': [p for p in intraday_keys if p not in approved] + [k for k in daily_keys if k[:-3] not in approved_d],
           'daily': [k[:-3] for k in daily_keys if k[:-3] in approved_d] if explicit else list(approved_d),
           'approved_daily': approved_d,
           'halted_daily': [p for p, a in stored_d.items() if a.get('status') == 'halted']}
    if not approved:
        return sel
    sel['candidates'] = {p: a['candidate'] for p, a in approved.items()}
    panel = pnl_panel(sel['candidates'])
    corr = panel.corr(min_periods=20) if panel.shape[1] > 1 else None
    if not explicit and len(sel['chosen']) > max_n:
        sub = corr.reindex(index=sel['chosen'], columns=sel['chosen']).fillna(1.0) if corr is not None else None
        sel['chosen'] = least_correlated(sub, max_n)[0] if sub is not None else sel['chosen'][:max_n]
        sel['excluded'] = [p for p in approved if p not in sel['chosen']]
    if corr is not None:
        sel['corr'] = corr.reindex(index=sel['chosen'], columns=sel['chosen'])
    return sel


DAILY_SUFFIX = '|1D'


def is_daily_key(key):
    return str(key).endswith(DAILY_SUFFIX)


def daily_key(product):
    return f'{product}{DAILY_SUFFIX}'


def portfolio_members():
    """The saved portfolio, or (none saved yet) what the book would trade today."""
    members = approvals.load_portfolio()
    return members if members is not None else select_book()['chosen']


def add_to_portfolio(product, max_n=MAX_BOOK, daily=False):
    """Put an approved product's strategy (its intraday one, or with daily=True its daily one) into the
    portfolio. Returns the new member list. Refuses a strategy that is not approved, is halted, or would take the
    portfolio past max_n distinct products (live data is fetched for at most that many)."""
    stored = approvals.load_approved_daily() if daily else approvals.load_approved()
    kind = 'daily strategy' if daily else 'strategy'
    if product not in stored:
        raise ValueError(f"{product} has no approved {kind}: approve a candidate in Research first")
    if stored[product].get('status') == 'halted':
        raise ValueError(f"{product} is halted: re-approve it in Research first")
    members = portfolio_members()
    key = daily_key(product) if daily else product
    if key in members:
        raise ValueError(f"{key} is already in the portfolio")
    products = {k[:-len(DAILY_SUFFIX)] if is_daily_key(k) else k for k in members}
    if product not in products and len(products) >= max_n:
        raise ValueError(f"the portfolio holds at most {max_n} products: remove one first")
    approvals.save_portfolio(members + [key])
    return members + [key]


def remove_from_portfolio(product):
    """Drop a strategy (a product, or a daily key 'IM|1D'): it leaves the portfolio and its approval record is
    deleted, so the Monitor stops tracking it too. It only comes back through approve() in Research. Returns the
    new member list."""
    members = portfolio_members()
    if product not in members:
        raise ValueError(f"{product} is not in the portfolio")
    members = [p for p in members if p != product]
    approvals.save_portfolio(members)
    try:
        approvals.remove_daily(product[:-len(DAILY_SUFFIX)]) if is_daily_key(product) else approvals.remove(product)
    except ValueError:   # already gone
        pass
    return members


def size_position(product, exits, last_price, capital, risk_pct, stop_mult, close=None):
    """Lots so that a stop-out costs risk_pct of capital. The stop distance is the approved strategy's own
    stop when it has one, else stop_mult x the 20-day daily sigma. Shared by Today's book and the Monitor's
    order tickets so both size the same position."""
    exits = exits or {}
    mult = CONTRACT_MULTIPLIER.get(product)
    if mult is None:
        raise ValueError("no contract multiplier on file")
    if close is None:
        close, _ = daily_panels()
    sym = {product_of(s): s for s in close.columns}.get(product)
    sigma = float(close[sym].dropna().pct_change().tail(20).std()) if sym else float('nan')
    if exits.get('stop'):
        stop_pts = exits['stop'] * last_price / 100 if exits['unit'] == 'pct' else exits['stop']
    else:
        stop_pts = stop_mult * sigma * last_price
    ok = stop_pts > 0 and math.isfinite(stop_pts)
    lots = int(capital * risk_pct / 100 // (stop_pts * mult)) if ok else 0
    return {'stop_pts': stop_pts, 'stop_src': 'strategy' if exits.get('stop') else 'σ', 'lots': lots,
            'daily_sigma': sigma, 'multiplier': mult}


def build_book(capital, risk_pct, stop_mult, loss_limit_pct, today=None, max_n=MAX_BOOK):
    """Today's book: up to max_n approved products, least correlated by strategy P&L, each sized so a
    stop-out costs risk_pct of capital."""
    today = today or datetime.now()
    sel = select_book(max_n)
    approved, chosen = sel['approved'], sel['chosen']
    book = {'rows': [], 'excluded': sel['excluded'], 'warnings': [], 'corr': sel['corr'],
            'approved_n': len(approved) + len(sel['approved_daily']), 'halted': sel['halted'] + [daily_key(p) for p in sel['halted_daily']],
            'missing': sel['missing'], 'explicit': sel['explicit']}
    if not approved and not sel['daily']:
        return book
    if sel['corr'] is not None:
        for i, a in enumerate(chosen):
            for b in chosen[i + 1:]:
                v = sel['corr'].loc[a, b]
                if pd.notna(v) and abs(v) > PNL_CORR_WARN:
                    book['warnings'].append(f"{a} and {b} strategy P&L correlation {v:+.2f}")

    close, _ = daily_panels()
    last_bday = np.busday_offset(np.datetime64(today.date()), -1, roll='backward')
    for prod in chosen:
        a = approved[prod]
        row = {'product': prod, 'candidate': a['candidate'], 'multiplier': CONTRACT_MULTIPLIER.get(prod)}
        if a.get('status') == 'watch':
            book['warnings'].append(f"{prod} is on Watch: {a.get('status_reason', '')}")
        try:
            exits = a.get('exits') or {}
            st = intraday_state(prod, a['candidate'], exits or None, night=a.get('session') == 'night+day', continuous=bool(a.get('continuous')))
            sz = size_position(prod, exits, st['last_price'], capital, risk_pct, stop_mult, close=close)
            sigma, stop_pts, lots, mult = sz['daily_sigma'], sz['stop_pts'], sz['lots'], sz['multiplier']
            row['stop_src'] = sz['stop_src']
            direction = int(st['signal'])
            entry_px = st['entry_price']
            lv = exit_levels(entry_px, direction, exits)
            stop_price = lv['stop']
            if direction and stop_price is None and entry_px is not None:   # no strategy stop: σ stop from the entry
                stop_price = entry_px - direction * stop_pts
            row.update(
                contract=st['contract'], last_price=st['last_price'], last_time=st['last_time'],
                signal=direction, since=st['since'], daily_sigma=sigma, stop_pts=stop_pts, lots=lots,
                entry_price=entry_px if direction else None, stop_price=stop_price if direction else None,
                target_price=lv['target'] if direction else None,
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

    for prod in sel['daily']:   # daily strategies: signal on today's forming bar, own risk budget, held overnight
        a = sel['approved_daily'][prod]
        row = {'product': prod, 'key': daily_key(prod), 'daily': True, 'candidate': a['candidate'],
               'multiplier': CONTRACT_MULTIPLIER.get(prod)}
        if a.get('status') == 'watch':
            book['warnings'].append(f"{prod} daily is on Watch: {a.get('status_reason', '')}")
        try:
            st = daily.daily_state(prod, a)
            sz = size_position(prod, {}, st['last_px'], capital, risk_pct, stop_mult, close=close)
            stop_pts, lots, mult = sz['stop_pts'], sz['lots'], sz['multiplier']
            direction, entry_px = st['position'], st['entry_px']
            row.update(
                contract=st['contract'], last_price=st['last_px'], last_time=st['as_of'], signal=direction,
                held=st['held'], since=st['since'], daily_sigma=sz['daily_sigma'], stop_pts=stop_pts, lots=lots,
                stop_src='σ', entry_price=entry_px if direction else None,
                stop_price=entry_px - direction * stop_pts if direction and entry_px is not None else None,
                target_price=None, risk_cny=lots * stop_pts * mult, notional=lots * st['last_px'] * mult,
                stale=not st['fresh'])
            if lots == 0:
                book['warnings'].append(f"{prod} daily: one lot risks {stop_pts * mult / capital * 100:.2f}% of capital "
                                        f"at this stop, above the {risk_pct:g}% budget: no position")
            if not st['fresh']:
                book['warnings'].append(f"{prod} daily: the series ends {st['day']:%Y-%m-%d}: start the Live monitor (or wait for "
                                        f"your data app) to bring in the latest days; no tickets until then")
            intra = next((r for r in book['rows'] if r['product'] == prod and not r.get('daily') and 'error' not in r), None)
            if intra and intra['signal'] and direction and intra['signal'] != direction:
                book['warnings'].append(f"{prod}: intraday is {'long' if intra['signal'] > 0 else 'short'} but daily is "
                                        f"{'long' if direction > 0 else 'short'}: they net out on the same contract at your broker")
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
