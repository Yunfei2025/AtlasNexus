# -*- coding: utf-8 -*-
"""Futures Desk > Monitor: turn the strategies' trades today into order tickets for manual trading.

Each strategy trade gives an Open ticket at its entry bar and a Close ticket at its exit (signal change,
stop / target, or the session close). A ticket is
  pending  -- still to do: an open whose position the strategy still holds, or a close of a position you
              marked opened;
  forming  -- would be pending, but its signal bar has not finished yet, so the signal can still vanish
              (a stop / target close is never forming: it has already traded);
  done     -- you ticked it (manual_log), optionally with your fill;
  missed   -- no longer worth doing: an open the strategy already closed again before you placed it (and its
              close, since you hold nothing);
  unsized  -- an open that sizes to 0 lots: one lot risks more than the per-product budget, so no position
              (Today's book says the same).
Pure logic: rows come from monitor.live_state, sizing from pool.size_position, the log from manual_log."""

from __future__ import annotations

import pandas as pd

from .contracts import app_code, day_close, order_words, price_fmt, round_tick, tick_of
from .pool import CONTRACT_MULTIPLIER

LIMIT_TICKS = 2     # suggested limit = last price this many ticks through the market (fills like a market order)
CHASE_FRAC = 0.5    # warn when price has moved this share of the stop distance since the signal bar
FLATTEN_WARN_MIN = 10   # minutes before the close the flatten reminder turns on


def tf_minutes(candidate):
    """Bar size in minutes of a candidate such as 'SAR@30min' / 'MA@1h'."""
    tf = str(candidate).split('@')[-1].lower()
    if tf.endswith('min'):
        return int(tf[:-3])
    if tf.endswith('h'):
        return int(tf[:-1]) * 60
    return 1


def action_key(product, entry_t, kind):
    return f"{product}|{pd.Timestamp(entry_t):%H:%M}|{kind}"


def _ticket(direction, opening, lots, contract, product, limit):
    side, offset, cn = order_words(direction, opening, product)
    return f"{app_code(contract)} · {side} {offset} {cn} · {lots} lot{'s' if lots != 1 else ''} · limit {price_fmt(limit, product)}"


def product_actions(row, sizing, log, now=None):
    """Tickets for one product's live row (day session only). `sizing` is pool.size_position's dict for the
    current price (or None when it could not be sized); `log` is the day's manual_log dict; `now` (Beijing,
    naive) decides whether a signal bar has finished -- bars are labelled by their start, so a bar labelled
    10:30 on a 30min strategy is final at 11:00. A pending ticket on a bar still forming is 'forming': the
    signal can still disappear before the bar closes."""
    prod, contract, last = row['product'], row['contract'], row['last_px']
    tick = tick_of(prod)
    bar = pd.Timedelta(minutes=tf_minutes(row.get('candidate', '')))

    close_t = day_close(prod)

    def final_at(t):
        """When the bar labelled t is complete: the minute bars are end-labelled, so a 30min bar labelled 10:30
        holds 10:30-10:59 and is final at 10:59; it never runs past the lunch break or the session close."""
        t = pd.Timestamp(t)
        end = t + bar - pd.Timedelta(minutes=1) if bar > pd.Timedelta(minutes=1) else t
        for cap in ('11:30', close_t):
            c = t.normalize() + pd.Timedelta(hours=int(cap[:2]), minutes=int(cap[3:]))
            if t <= c:
                return min(end, c)
        return end

    def forming(t):
        return (not row.get('closed')) and now is not None and pd.Timestamp(now) < final_at(t)
    lots_now = sizing['lots'] if sizing else 0
    out = []
    for t in row['trades']:
        d, sig_px = t['direction'], t['entry_px']
        k_open, k_close = action_key(prod, t['entry_t'], 'open'), action_key(prod, t['entry_t'], 'close')
        lo, lc = log.get(k_open, {}), log.get(k_close, {})
        opened = bool(lo.get('done'))
        stop = t.get('stop')
        if stop is None and sizing and sizing.get('stop_pts'):
            stop = sig_px - d * sizing['stop_pts']   # σ stop, measured from the signal bar like the strategy's
        stop_dist = abs(sig_px - stop) if stop is not None else None
        lots = int(lo.get('lots', lots_now)) if opened else lots_now
        state = 'done' if opened else ('pending' if t['exit_t'] is None else 'missed')
        if state == 'pending' and lots == 0:
            state = 'unsized'   # one lot risks more than the per-product budget (as in Today's book)
        if state == 'pending' and forming(t['entry_t']):
            state = 'forming'
        a = {'key': k_open, 'product': prod, 'contract': contract, 'kind': 'open', 'time': t['entry_t'],
             'direction': d, 'lots': lots, 'signal_px': sig_px, 'state': state,
             'stop': round_tick(stop, prod), 'target': round_tick(t.get('target'), prod),
             'fill': lo.get('fill'), 'done_at': lo.get('at'), 'final_at': final_at(t['entry_t'])}
        ref = last if state in ('pending', 'forming') else sig_px
        a['limit'] = round_tick(ref + d * LIMIT_TICKS * (tick or 0), prod)
        a['ticket'] = _ticket(d, True, lots, contract, prod, a['limit'])
        if state in ('pending', 'forming') and stop_dist:
            move = d * (last - sig_px)
            a['drift_ticks'] = move / tick if tick else None
            a['drift_frac'] = move / stop_dist
            a['warn'] = ('chasing: price already ran ' if a['drift_frac'] >= CHASE_FRAC else
                         'near the stop: price fell back ' if a['drift_frac'] <= -CHASE_FRAC else None)
            if a['warn']:
                a['warn'] += f"{abs(a['drift_frac']) * 100:.0f}% of the stop distance since the signal"
        a['slip_ticks'] = d * (a['fill'] - sig_px) / tick if (a['fill'] is not None and tick) else None
        out.append(a)
        if t['exit_t'] is None:
            continue
        c_state = 'done' if lc.get('done') else ('pending' if opened else 'missed')
        # a stop / target hit is final the moment it trades; a signal flip on a bar still forming is not
        level_hit = any(t.get(k) is not None and t['exit_px'] is not None and abs(t['exit_px'] - t[k]) < 1e-9
                        for k in ('stop', 'target'))
        if c_state == 'pending' and not level_hit and forming(t['exit_t']):
            c_state = 'forming'
        c_lots = int(lc.get('lots', lots))
        c = {'key': k_close, 'product': prod, 'contract': contract, 'kind': 'close', 'time': t['exit_t'],
             'direction': -d, 'lots': c_lots, 'signal_px': t['exit_px'], 'state': c_state,
             'stop': None, 'target': None, 'fill': lc.get('fill'), 'done_at': lc.get('at'),
             'final_at': final_at(t['exit_t'])}
        c_ref = last if c_state in ('pending', 'forming') else t['exit_px']
        c['limit'] = round_tick(c_ref - d * LIMIT_TICKS * (tick or 0), prod)
        c['ticket'] = _ticket(-d, False, c_lots, contract, prod, c['limit'])
        c['slip_ticks'] = -d * (c['fill'] - t['exit_px']) / tick if (c['fill'] is not None and tick) else None
        out.append(c)
    return out


def held_positions(actions):
    """Positions you hold by your own log: an open marked done whose close is not marked done.
    {product: {'direction', 'lots', 'entry' (your fill, else the signal price), 'contract'}}"""
    closes_done = {a['key'] for a in actions if a['kind'] == 'close' and a['state'] == 'done'}
    held = {}
    for a in actions:
        if a['kind'] == 'open' and a['state'] == 'done' and a['key'].replace('|open', '|close') not in closes_done:
            held[a['product']] = {'direction': a['direction'], 'lots': a['lots'], 'contract': a['contract'],
                                  'entry': a['fill'] if a['fill'] is not None else a['signal_px']}
    return held


def your_pnl_cny(actions, last_px):
    """Today's P&L in CNY of what you logged: closed round trips at your fills (signal prices where no fill was
    typed) plus open positions marked at the last price. `last_px` = {product: last price}."""
    by_key = {a['key']: a for a in actions}
    total = 0.0
    for a in actions:
        if a['kind'] != 'open' or a['state'] != 'done':
            continue
        mult = CONTRACT_MULTIPLIER.get(a['product'], 0)
        entry = a['fill'] if a['fill'] is not None else a['signal_px']
        c = by_key.get(a['key'].replace('|open', '|close'))
        if c is not None and c['state'] == 'done':
            exit_px = c['fill'] if c['fill'] is not None else c['signal_px']
        else:
            exit_px = last_px.get(a['product'])
        if exit_px is not None:
            total += a['direction'] * (exit_px - entry) * a['lots'] * mult
    return total


def flatten_items(held):
    """What the close reminder needs: one entry per held position with its close time and closing ticket."""
    out = []
    for prod, h in held.items():
        side, offset, cn = order_words(-h['direction'], False, prod)
        out.append({'product': prod, 'close': day_close(prod),
                    'text': f"{app_code(h['contract'])} · {side} {offset} {cn} · {h['lots']} lots"})
    return out
