# -*- coding: utf-8 -*-
"""Futures Desk > Monitor: live minute bars for the products you choose to watch (start / stop, timed refresh)."""

from __future__ import annotations

from datetime import datetime

from dash import ctx, dcc, html, no_update
from dash.dependencies import Input, Output, State

import plotly.graph_objects as go

from futures.backtest.live_bars import fetch_live_bars, fetch_lock
from web.tabs.beta.data import THEME
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


def live_chart(r):
    """Today's bars of the strategy's bar size with each position's entry / exit and its stop and target."""
    b = r['bars']
    lab = lambda t: f"{t:%H:%M}"
    fig = go.Figure(go.Candlestick(
        x=[lab(t) for t in b.index], open=b['open'], high=b['high'], low=b['low'], close=b['close'],
        increasing_line_color=_GREEN, decreasing_line_color=_RED, showlegend=False))
    for t in r['trades']:
        x0, x1 = lab(t['entry_t']), lab(t['exit_t'] if t['exit_t'] is not None else b.index[-1])
        for key, color, name in (('stop', _RED, 'stop'), ('target', _GREEN, 'target')):
            if t.get(key) is not None:
                fig.add_trace(go.Scatter(x=[x0, x1], y=[t[key]] * 2, mode='lines', showlegend=False,
                                         line={'color': color, 'width': 1.6, 'dash': 'dash'},
                                         hovertemplate=f'{name} %{{y:,.2f}}<extra></extra>'))
                fig.add_annotation(x=x1, y=t[key], text=f"{name} {t[key]:,.2f}", showarrow=False, xanchor='right',
                                   yanchor='bottom' if key == 'target' else 'top', font={'size': 9, 'color': color})
        fig.add_trace(go.Scatter(
            x=[x0], y=[t['entry_px']], mode='markers', showlegend=False,
            marker={'symbol': 'triangle-up' if t['direction'] > 0 else 'triangle-down', 'size': 12,
                    'color': '#e9eef8', 'line': {'color': '#0b1328', 'width': 1}},
            hovertemplate=f"{'long' if t['direction'] > 0 else 'short'} %{{y:,.2f}}<extra>entry</extra>"))
        if t['exit_t'] is not None:
            won = t['direction'] * (t['exit_px'] - t['entry_px']) > 0
            fig.add_trace(go.Scatter(x=[lab(t['exit_t'])], y=[t['exit_px']], mode='markers', showlegend=False,
                                     marker={'symbol': 'x', 'size': 10, 'color': _GREEN if won else _RED,
                                             'line': {'width': 2}},
                                     hovertemplate='%{y:,.2f}<extra>exit</extra>'))
    fig.update_layout(
        height=280, template=THEME['chart_template'], paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font={'color': '#e9eef8', 'size': 10}, margin=dict(l=52, r=12, t=26, b=30), xaxis_rangeslider_visible=False,
        title={'text': f"{r['product']} · {r['candidate']} · {r['contract']}", 'font': {'size': 11}, 'x': 0.01, 'y': 0.96},
        xaxis={'type': 'category', 'nticks': 8, 'gridcolor': 'rgba(100,140,200,0.12)', 'tickfont': {'size': 9}},
        yaxis={'gridcolor': 'rgba(100,140,200,0.12)', 'tickformat': ',.2f'})
    return fig


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
    if rows:
        out.append(html.Div([dcc.Graph(figure=live_chart(r), config={'displayModeBar': False}) for r in rows],
                            style={'display': 'grid', 'gridTemplateColumns': 'repeat(auto-fit, minmax(380px, 1fr))',
                                   'gap': '8px', 'marginTop': '8px'}))
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
