# -*- coding: utf-8 -*-
"""Futures Desk > Monitor: live minute bars for the products you choose to watch (start / stop, timed refresh)."""

from __future__ import annotations

from datetime import datetime

from dash import ctx, html, no_update
from dash.dependencies import Input, Output, State

from futures.backtest.live_bars import fetch_live_bars, fetch_lock
from . import approvals
from .monitor import live_state
from .pool import MAX_BOOK
from .today import _AMBER, _GREEN, _RED, _TH, _note, _row, _table, _td, signal_cell

INTERVAL_CHOICES_MIN = (5, 10, 15)


def start_state(products, minutes):
    """The live-monitor state for a Start click, or (None, message) when the request is not valid."""
    products = [p for p in (products or []) if p]
    if not products:
        return None, "Pick at least one product to monitor live."
    if len(products) > MAX_BOOK:
        return None, f"Pick at most {MAX_BOOK} products (live data is fetched for these only)."
    if minutes not in INTERVAL_CHOICES_MIN:
        return None, "Refresh every 5, 10 or 15 minutes."
    return {'running': True, 'products': list(products), 'minutes': int(minutes),
            'started': datetime.now().strftime('%H:%M:%S')}, ''


def live_view(rows, fetch, state, now=None):
    """Table of the live positions plus the fetch outcome."""
    now = now or datetime.now()
    running = bool(state and state.get('running'))
    out = []
    if not rows:
        out.append(_note("No live bars fetched yet today for the chosen products." if running else
                         "Choose products and click ▶ Start live."))
    else:
        body = []
        for r in rows:
            age = (now - r['fetched_at']).total_seconds() / 60
            late = running and age > 2 * state['minutes']
            pnl = r['day_return'] * 100
            body.append(_row([
                _td(r['product'], left=True, bold=True), _td(r['candidate']), _td(r['contract']),
                _td(f"{r['last_px']:,.2f}"),
                signal_cell(r['position'], r['since']) if r['since'] is not None else _td('—'),
                _td('—' if r['entry_px'] is None else f"{r['entry_px']:,.2f}"),
                _td('—' if r['stop_px'] is None else f"{r['stop_px']:,.2f}"),
                _td('—' if r['target_px'] is None else f"{r['target_px']:,.2f}"),
                _td(f"{pnl:+.2f}%", _GREEN if pnl > 0 else (_RED if pnl < 0 else 'var(--text-secondary)'), bold=True),
                _td(str(r['round_trips'])),
                _td(f"{r['as_of']:%H:%M} · {age:.0f} min ago", _AMBER if late else 'var(--text-muted)'),
            ]))
        head = ["Product", "Strategy", "Contract", "Last", "Position", "Entry", "Stop at", "Target at",
                "Today (net)", "Round trips", "Bars to · fetched"]
        out.append(_table(head, body, left=(0, 4)))
        for r in rows:
            if r['exited_at'] is not None:
                out.append(_note(f"{r['product']}: stop / target hit at {r['exited_at']:%H:%M}; flat until the "
                                 f"strategy's signal changes.", _AMBER))
    if fetch and fetch.get('skipped'):
        out.append(_note(f"Not fetched: {fetch['skipped']}.", _AMBER))
    for p, v in ((fetch or {}).get('products') or {}).items():
        if 'error' in v:
            out.append(_note(f"{p}: {v['error']}", _RED))
    out.append(_note("Strategy replayed at default parameters on settled history plus today's live minute bars, "
                     "net of its cost and with its stop / target; the latest bar is still forming. Paper P&L as a "
                     "return on notional, not your fills. Wind is called only for the products listed, only while "
                     "running and inside trading hours, and only for the minutes since the last fetch."))
    return html.Div(out)


def register_live_callbacks(app):
    @app.callback(
        Output('fd-live-products', 'options'),
        [Input('fd-data-stamp', 'data'), Input('fd-subtabs', 'value')],
    )
    def fd_live_options(_stamp, _tab):
        return [{'label': f"{p} · {a['candidate']}", 'value': p}
                for p, a in approvals.load_approved().items() if a.get('status', 'approved') != 'halted']

    @app.callback(
        [Output('fd-live-state', 'data'), Output('fd-live-interval', 'disabled'),
         Output('fd-live-interval', 'interval'), Output('fd-live-note', 'children')],
        [Input('fd-live-start', 'n_clicks'), Input('fd-live-stop', 'n_clicks')],
        [State('fd-live-products', 'value'), State('fd-live-minutes', 'value')],
        prevent_initial_call=True,
    )
    def fd_live_toggle(_start, _stop, products, minutes):
        if ctx.triggered_id == 'fd-live-stop':
            return {'running': False, 'products': products or []}, True, no_update, "Stopped. No more Wind requests."
        state, msg = start_state(products, minutes)
        if state is None:
            return no_update, True, no_update, msg
        return state, False, state['minutes'] * 60_000, (
            f"Running: {', '.join(state['products'])} every {state['minutes']} min.")

    @app.callback(
        Output('fd-live-container', 'children'),
        [Input('fd-live-interval', 'n_intervals'), Input('fd-live-state', 'data')],
    )
    def fd_live_refresh(_n, state):
        if not state or not state.get('products'):
            return live_view([], None, state)
        running = bool(state.get('running'))
        fetch = None
        if running:
            if not fetch_lock.acquire(blocking=False):   # a previous fetch is still going: skip this tick
                return no_update
            fetch_lock.release()
            fetch = fetch_live_bars(state['products'])
        approved = approvals.load_approved()
        rows = []
        for p in state['products']:
            try:
                r = live_state(p, approved[p]) if p in approved else None
            except Exception as e:
                (fetch or {}).setdefault('products', {})[p] = {'error': f'live position failed: {e}'}
                r = None
            if r:
                rows.append(r)
        return live_view(rows, fetch, state)
