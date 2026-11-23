# -*- coding: utf-8 -*-
"""Futures Desk > Monitor: live minute bars for the products you choose to watch (start / stop, timed refresh)."""

from __future__ import annotations


import time

from dash import ALL, ctx, dcc, html, no_update
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate

import plotly.graph_objects as go

from futures.backtest.live_bars import (
    CLOSE_TIME, NIGHT_END, NIGHT_START, SESSION_START, china_now, fetch_live_bars, fetch_lock, fetch_night_bars,
)
from web.tabs.beta.data import THEME
from . import approvals, manual_log
from .actions import (
    FLATTEN_WARN_MIN, LIMIT_TICKS, daily_actions, flatten_items, held_positions, product_actions, tf_minutes, your_pnl_cny,
)
from .contracts import app_code, price_fmt
from .daily import daily_state, fetch_tail
from .monitor import is_night_day, live_state, night_led_state, night_state
from .pool import CONTRACT_MULTIPLIER, MAX_BOOK, select_book, size_position
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
            'started': china_now().strftime('%H:%M:%S')}, ''


def live_chart(r):
    """Today's bars of the strategy's bar size with each position's entry / exit and its stop and target."""
    b = r['bars']
    lab = (lambda t: f"{t:%m-%d}") if r.get('daily') else (lambda t: f"{t:%H:%M}")
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
        title={'text': f"{r['product']} · {r['candidate']} · {r['contract']} · {r['day']:%m-%d}"
                       + (" · night, display only" if r.get('night') else "")
                       + (" · night + day" if r.get('session') == 'night+day' else "")
                       + (" · daily" if r.get('daily') else "")
                       + (" · closed" if r.get('closed') else ""), 'font': {'size': 11}, 'x': 0.01, 'y': 0.96},
        xaxis={'type': 'category', 'nticks': 8, 'gridcolor': 'rgba(100,140,200,0.12)', 'tickfont': {'size': 9}},
        yaxis={'gridcolor': 'rgba(100,140,200,0.12)', 'tickformat': ',.2f'})
    return fig


_HEALTH = {'halted': ('HALT SIGNAL', _RED), 'watch': ('WATCH', _AMBER)}


def health_badge(product, health, stored):
    """Badge for a product whose forward P&L is off track: the Monitor's computed status, else the stored one."""
    st = (health or {}).get(product)
    if st not in _HEALTH:
        st = stored if stored in _HEALTH else None
    if st is None:
        return None
    txt, col = _HEALTH[st]
    return html.Span(txt, title="Forward paper P&L is off the walk-forward's expected path: see the strategy "
                                "health section below before trading it.",
                     style={'marginLeft': '6px', 'fontSize': '8px', 'fontWeight': '700', 'color': col,
                            'border': f'1px solid {col}', 'borderRadius': '3px', 'padding': '1px 4px'})


def _tile(label, value, color='var(--text-primary)', sub=None):
    return html.Div([
        html.Div(label, style={'fontSize': '8px', 'textTransform': 'uppercase', 'letterSpacing': '0.06em',
                               'color': 'var(--text-muted)'}),
        html.Div(value, style={'fontSize': '16px', 'fontWeight': '700', 'color': color}),
        html.Div(sub or '', style={'fontSize': '9px', 'color': 'var(--text-muted)'}),
    ], style={'padding': '6px 12px', 'border': '1px solid var(--border-default)', 'borderRadius': '6px',
              'minWidth': '120px'})


def _ticket_card(a, day, muted=False):
    prod = a['product']
    d_col = _GREEN if a['direction'] > 0 else _RED
    kind = 'OPEN' if a['kind'] == 'open' else 'CLOSE'
    head = [html.Span(f"{kind} · signal bar {a['time']:%H:%M}, final {a['final_at']:%H:%M}",
                      style={'fontSize': '9px', 'color': 'var(--text-muted)'})]
    if a['state'] == 'forming':
        head.append(html.Span(f"PROVISIONAL until {a['final_at']:%H:%M}: the bar is still forming and the signal "
                              f"can vanish", style={'marginLeft': '8px', 'fontSize': '9px', 'fontWeight': '700',
                                                    'color': _AMBER}))
    if a['state'] == 'unsized':
        head.append(html.Span("no position: one lot risks more than your risk budget per product (see Today)",
                              style={'marginLeft': '8px', 'fontSize': '9px', 'color': _AMBER}))
    if a['state'] == 'missed':
        head.append(html.Span("not needed: the strategy closed it again before you opened",
                              style={'marginLeft': '8px', 'fontSize': '9px', 'color': 'var(--text-muted)'}))
    detail = [f"signal {price_fmt(a['signal_px'], prod)}"]
    if a['stop'] is not None:
        detail.append(f"stop {price_fmt(a['stop'], prod)}")
    if a['target'] is not None:
        detail.append(f"target {price_fmt(a['target'], prod)}")
    if a.get('drift_ticks') is not None:
        detail.append(f"price since signal {a['drift_ticks']:+.0f} ticks ({a['drift_frac'] * 100:+.0f}% of stop)")
    if a.get('slip_ticks') is not None:
        detail.append(f"your fill {price_fmt(a['fill'], prod)}, slippage {a['slip_ticks']:+.0f} ticks")
    body = [html.Div(head),
            html.Div(a['ticket'], style={'fontSize': '13px' if muted else '15px', 'fontWeight': '700',
                                         'fontFamily': 'var(--font-mono, monospace)', 'letterSpacing': '0.02em',
                                         'color': 'var(--text-muted)' if muted else d_col, 'margin': '2px 0'}),
            html.Div(' · '.join(detail), style={'fontSize': '10px', 'color': 'var(--text-secondary)'})]
    if a.get('warn') and not muted:
        body.append(html.Div(f"⚠ {a['warn']}", style={'fontSize': '10px', 'color': _AMBER, 'fontWeight': '600'}))
    controls = html.Div([
        dcc.Checklist(id={'type': 'fd-done', 'key': a['key'], 'day': day, 'lots': int(a['lots'])},
                      options=[{'label': ' Done', 'value': 'done'}],
                      value=['done'] if a['state'] == 'done' else [],
                      style={'fontSize': '11px', 'color': 'var(--text-primary)'}),
        dcc.Input(id={'type': 'fd-fill', 'key': a['key'], 'day': day}, type='number', debounce=True,
                  value=a.get('fill'), placeholder='fill price',
                  style={'width': '90px', 'fontSize': '10px', 'padding': '3px 6px', 'borderRadius': '4px',
                         'background': 'var(--surface-input)', 'color': 'var(--text-primary)',
                         'border': '1px solid var(--border-default)'}),
    ], style={'display': 'flex', 'gap': '8px', 'alignItems': 'center', 'flexShrink': '0'})
    border = (_AMBER if a['state'] == 'forming' else d_col) if not muted else 'var(--border-default)'
    return html.Div([html.Div(body, style={'minWidth': '0'}), controls], style={
        'display': 'flex', 'justifyContent': 'space-between', 'gap': '12px', 'alignItems': 'center',
        'padding': '8px 12px', 'borderLeft': f'3px solid {border}', 'borderRadius': '4px',
        'background': 'var(--surface-panel)', 'marginTop': '6px', 'opacity': '0.6' if muted else '1'})


def orders_view(actions_by_day, held, pnl_cny, loss_limit_cny, running):
    """The trading card: P&L / limit strip, tickets to do now, and the day's log."""
    acts = [(day, a) for day, lst in actions_by_day.items() for a in lst]
    todo = sorted([x for x in acts if x[1]['state'] in ('pending', 'forming')], key=lambda x: x[1]['time'])
    rest = sorted([x for x in acts if x[1]['state'] in ('done', 'missed', 'unsized')], key=lambda x: x[1]['time'],
                  reverse=True)
    used = -pnl_cny / loss_limit_cny if loss_limit_cny and pnl_cny < 0 else 0.0
    strip = html.Div([
        _tile("Your P&L today", f"{pnl_cny:+,.0f}", _GREEN if pnl_cny > 0 else (_RED if pnl_cny < 0 else
              'var(--text-primary)'), "CNY, from tickets marked done"),
        _tile("Daily loss limit", f"{loss_limit_cny:,.0f}", _RED if used >= 1 else (_AMBER if used >= 0.5 else
              'var(--text-primary)'), f"{used * 100:.0f}% used" if used else "CNY"),
        _tile("You hold", str(len(held)), sub=', '.join(f"{p} {'L' if h['direction'] > 0 else 'S'}{h['lots']}"
                                                        for p, h in held.items()) or 'flat'),
        _tile("To do", str(sum(1 for _, a in todo if a['state'] == 'pending')),
              _AMBER if todo else 'var(--text-primary)',
              f"+{sum(1 for _, a in todo if a['state'] == 'forming')} provisional" if any(
                  a['state'] == 'forming' for _, a in todo) else "tickets"),
    ], style={'display': 'flex', 'gap': '8px', 'flexWrap': 'wrap'})
    out = [strip]
    if used >= 1:
        out.append(_note("⚠ Daily loss limit reached by your logged trades: stop opening new positions today.", _RED))
    if todo:
        out += [_ticket_card(a, day) for day, a in todo]
    else:
        out.append(_note("Nothing to do now." + ("" if running else " Live data is not running: ▶ Start live "
                                                 "during the session to get new tickets."),
                         'var(--text-secondary)'))
    if rest:
        out.append(html.Details([
            html.Summary(f"Today's log ({len(rest)})", style={'fontSize': '10px', 'color': 'var(--text-muted)',
                                                              'cursor': 'pointer', 'marginTop': '8px'}),
            *[_ticket_card(a, day, muted=True) for day, a in rest]]))
    out.append(_note(f"Tickets follow the approved strategy on live bars, sized like Today's book (capital and "
                     f"risk from Today). Limit = last price {LIMIT_TICKS} ticks through the market; prices are on the "
                     f"contract's tick. Stop / target are the strategy's levels from the signal bar: set them as "
                     f"conditional orders in your app. Tick Done once the order is in, and type your fill to track "
                     f"slippage and your P&L. Close-today (平今) is shown for SHFE / INE products. Tick sizes and "
                     f"multipliers are typed in from exchange specs: verify before trading."))
    return html.Div(out)


def live_view(rows, fetch, state, now=None, sizing=None, health=None, stored=None):
    """Table of the live positions plus the fetch outcome."""
    now = now or china_now()   # fetched_at is Beijing time
    running = bool(state and state.get('running'))
    out = []
    if not rows:
        out.append(_note("No live bars fetched yet today for the chosen products." if running else
                         "No saved session for the book's products yet. While the market is open, choose products "
                         "and click ▶ Start live."))
    else:
        body = []
        for r in rows:
            age = (now - r['fetched_at']).total_seconds() / 60
            late = running and not r['closed'] and age > 2 * state['minutes']
            pnl = r['day_return'] * 100
            sz = (sizing or {}).get(r.get('key', r['product']))
            lots = sz['lots'] if sz else None
            pnl_cny = (r['day_return'] * lots * r['last_px'] * CONTRACT_MULTIPLIER.get(r['product'], 0)
                       if lots else None)
            badge = None if r.get('night') else health_badge(r.get('key', r['product']), health, (stored or {}).get(r.get('key', r['product'])))
            body.append(_row([
                html.Td([r['product'], badge] if badge else r['product'],
                        style={'padding': '5px 8px', 'fontSize': '10px', 'fontWeight': '600',
                               'color': 'var(--text-secondary)', 'whiteSpace': 'nowrap', 'textAlign': 'left'}),
                _td(r['candidate'] + (' · night' if r.get('night') else '') + (' · night+day' if r.get('session') == 'night+day' else '')
                    + (f" · daily (holding {r['held']:+d})" if r.get('daily') else ''),
                    _AMBER if r.get('night') else 'var(--text-secondary)'),
                _td(r['contract']),
                _td(price_fmt(r['last_px'], r['product'])),
                signal_cell(r['position'], r['since']) if r['since'] is not None else _td('—'),
                _td(price_fmt(r['entry_px'], r['product'])),
                _td(price_fmt(r['stop_px'], r['product'])),
                _td(price_fmt(r['target_px'], r['product'])),
                _td('—' if lots is None or r.get('night') else str(lots)),
                _td(f"{pnl:+.2f}%", _GREEN if pnl > 0 else (_RED if pnl < 0 else 'var(--text-secondary)'), bold=True),
                _td('—' if pnl_cny is None or r.get('night') else f"{pnl_cny:+,.0f}"),
                _td(str(r['round_trips'])),
                _td(f"{r['day']:%m-%d} {'night ' if r.get('night') else ''}closed · to {r['as_of']:%H:%M}" if r['closed'] else
                    f"{r['as_of']:%H:%M} · {age:.0f} min ago", _AMBER if late else 'var(--text-muted)'),
            ]))
        head = ["Product", "Strategy", "Contract", "Last", "Position", "Entry", "Stop at", "Target at", "Lots",
                "Today (net)", "Paper CNY", "Round trips", "Bars to · fetched"]
        out.append(_table(head, body, left=(0, 4)))
        for r in rows:
            if r['exited_at'] is not None:
                out.append(_note(f"{r['product']}: stop / target hit at {r['exited_at']:%H:%M}; flat until the "
                                 f"strategy's signal changes.", _AMBER))
    if rows:
        out.append(html.Div([dcc.Graph(figure=live_chart(r), config={'displayModeBar': False}) for r in rows],
                            style={'display': 'grid', 'gridTemplateColumns': 'repeat(auto-fit, minmax(380px, 1fr))',
                                   'gap': '8px', 'marginTop': '8px'}))
    if fetch and fetch.get('skipped') and running:
        out.append(_note(f"Not fetched: {fetch['skipped']}.", _AMBER))
    if fetch and running and fetch.get('session') == 'closed':
        bj = fetch.get('now')
        out.append(_note(f"Day session closed ({SESSION_START[:5]}-{CLOSE_TIME[:5]} Beijing"
                         + (f"; now {bj:%a %H:%M} Beijing" if bj is not None else "")
                         + "): showing the last finished day session.", _AMBER))
    for r in rows:
        lb = r.get('lookback')
        if lb and lb[0] < lb[1] and r['position'] == 0:
            out.append(_note(f"{r['product']}: night history incomplete ({lb[0]} of the last {lb[1]} trade days have night "
                             "bars), so the strategy cannot compute its bands and stays flat through the night. "
                             "Press Backfill nights.", _AMBER))
    if any(r.get('night') for r in rows):
        out.append(_note(f"Night rows ({NIGHT_START[:5]} onward; AU/AG to 02:30, AL/CU to 01:00, JM to 23:00) are "
                         "display only: the strategies were walk-forward tested on day-session bars only, so a night "
                         "replay runs on the night bars alone with no warm-up and is not evidence. It does not enter "
                         "the Monitor statuses, losing streaks, z-scores or Today's book.", _AMBER))
    for p, v in ((fetch or {}).get('products') or {}).items():
        if 'error' in v:
            out.append(_note(f"{p}: {v['error']}", _RED))
    out.append(_note("Strategy replayed at default parameters on settled history plus today's live minute bars, "
                     "net of its cost and with its stop / target; while the market is open the latest bar is still "
                     "forming. Paper P&L as a return on notional, not your fills. Open market: Wind is called only "
                     "for the products listed, only while running, and only for the minutes since the last fetch. "
                     "After the close the finished session is fetched once and saved in database/futures_desk/live; "
                     "later views read that file."))
    return html.Div(out)


def register_live_callbacks(app):
    @app.callback(
        [Output('fd-live-products', 'options'), Output('fd-live-products', 'value')],
        [Input('fd-data-stamp', 'data'), Input('fd-subtabs', 'value')],
        State('fd-live-products', 'value'),
    )
    def fd_live_options(_stamp, _tab, current):
        """Approved products; an empty pick is filled with today's book so ▶ Start live is one click."""
        opts = [{'label': f"{p} · {a['candidate']}", 'value': p}
                for p, a in approvals.load_approved().items() if a.get('status', 'approved') != 'halted']
        seen = {o['value'] for o in opts}
        opts += [{'label': f"{p} · {a['candidate']} (daily)", 'value': p}
                 for p, a in approvals.load_approved_daily().items()
                 if a.get('status', 'approved') != 'halted' and p not in seen]
        valid = {o['value'] for o in opts}
        keep = [p for p in (current or []) if p in valid]
        if keep:
            return opts, (keep if keep != current else no_update)
        try:
            chosen = [p for p in select_book()['chosen'] if p in valid][:MAX_BOOK]
        except Exception:
            chosen = []
        return opts, chosen

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

    @app.callback(Output('fd-backfill-note', 'children'), Input('fd-night-backfill', 'n_clicks'),
                  prevent_initial_call=True)
    def fd_night_backfill(_n):
        from futures.backtest.live_bars import backfill_night
        try:
            r = backfill_night(days=10)
        except Exception as e:
            return f"Backfill failed: {e}"
        errs = r['errors']
        return (f"{r['fetched']} night(s) fetched, {r['skipped']} already on file"
                + (f", {len(errs)} problem(s): {'; '.join(f'{k}: {v}' for k, v in list(errs.items())[:2])}" if errs else "") + ".")

    @app.callback(
        [Output('fd-live-container', 'children'), Output('fd-orders-container', 'children'),
         Output('fd-desk-clock', 'data')],
        [Input('fd-live-interval', 'n_intervals'), Input('fd-live-state', 'data'), Input('fd-subtabs', 'value'),
         Input('fd-data-stamp', 'data'), Input('fd-done-stamp', 'data'), Input('fd-mon-health', 'data')],
        [State('fd-capital', 'value'), State('fd-risk-pct', 'value'), State('fd-stop-mult', 'value'),
         State('fd-loss-limit', 'value')],
    )
    def fd_live_refresh(_n, state, subtab, _stamp, _done, health, capital, risk_pct, stop_mult, loss_limit):
        """Running: incremental fetch of the chosen products. Otherwise the book's products, from the saved
        session; the finished day is fetched from Wind once when it is not on file yet. A Done / fill entry or
        a health update only re-renders from the files on disk (no Wind call)."""
        if subtab != 'monitor':
            raise PreventUpdate
        refetch = ctx.triggered_id not in ('fd-done-stamp', 'fd-mon-health')
        running = bool(state and state.get('running'))
        daily_members = []
        try:
            sel = select_book()
            daily_members = sel['daily']
        except Exception:
            sel = None
        if state and state.get('products'):
            products = state['products']
        else:
            products = ((sel['chosen'] if sel else []) + [p for p in daily_members if sel and p not in sel['chosen']])
        if not products:
            return live_view([], None, state), orders_view({}, {}, 0.0, 0.0, running), {}
        night_products = [p for p in products if p in NIGHT_END]
        if refetch:
            if not fetch_lock.acquire(blocking=False):   # a previous fetch is still going: skip this tick
                return no_update, no_update, no_update
            fetch_lock.release()
            fetch = fetch_live_bars(products, closed_only=not running)
            night_fetch = fetch_night_bars(night_products, closed_only=not running) if night_products else None
            for p in daily_members:   # the continuous series' tail (days the file lacks + today's forming bar)
                if p in approvals.load_approved_daily():
                    tl = fetch_tail(p, closed_only=not running)
                    if 'error' in tl:
                        fetch.setdefault('products', {})[f'{p} daily'] = {'error': tl['error']}
                    elif tl.get('skipped') and running:
                        fetch['skipped'] = fetch.get('skipped') or f"{p} daily: {tl['skipped']}"
        else:
            fetch, night_fetch = {}, None
        if night_fetch:
            for p, v in (night_fetch.get('products') or {}).items():
                if 'error' in v:
                    fetch.setdefault('products', {})[f'{p} night'] = v
            if night_fetch.get('skipped') and running:
                fetch['skipped'] = fetch.get('skipped') or f"night: {night_fetch['skipped']}"
        approved = approvals.load_approved()
        approved_daily = approvals.load_approved_daily()
        rows = []
        for p in products:
            if p in daily_members and p in approved_daily:
                try:
                    rows.append(daily_state(p, approved_daily[p]))
                except Exception as e:
                    fetch.setdefault('products', {})[f'{p} daily'] = {'error': f'daily position failed: {e}'}
            try:
                r = ((night_led_state(p, approved[p]) if is_night_day(approved[p]) else None)
                     or live_state(p, approved[p])) if p in approved else None
            except Exception as e:
                fetch.setdefault('products', {})[p] = {'error': f'live position failed: {e}'}
                r = None
            if r:
                rows.append(r)
            if p in night_products and p in approved and not is_night_day(approved[p]):   # integrated ones trade the night
                try:
                    n = night_state(p, approved[p])
                except Exception as e:
                    fetch.setdefault('products', {})[f'{p} night'] = {'error': f'night position failed: {e}'}
                    n = None
                if n:
                    rows.append(n)
        return desk_views(rows, fetch, state, approved, health, capital, risk_pct, stop_mult, loss_limit)

    @app.callback(
        Output('fd-done-stamp', 'data'),
        Input({'type': 'fd-done', 'key': ALL, 'day': ALL, 'lots': ALL}, 'value'),
        prevent_initial_call=True,
    )
    def fd_done(_values):
        """Tick / untick a ticket. Only a real change is written (re-rendered checkboxes also fire this)."""
        tid = ctx.triggered_id
        if not isinstance(tid, dict) or not ctx.triggered:
            raise PreventUpdate
        done = bool(ctx.triggered[0].get('value'))
        if bool(manual_log.load_log(tid['day']).get(tid['key'], {}).get('done')) == done:
            raise PreventUpdate
        manual_log.set_done(tid['day'], tid['key'], done, lots=tid.get('lots'))
        return {'t': time.time()}

    @app.callback(
        Output('fd-done-stamp', 'data', allow_duplicate=True),
        Input({'type': 'fd-fill', 'key': ALL, 'day': ALL}, 'value'),
        prevent_initial_call=True,
    )
    def fd_fill(_values):
        """Record the fill price typed for a ticket (empty clears it)."""
        tid = ctx.triggered_id
        if not isinstance(tid, dict) or not ctx.triggered:
            raise PreventUpdate
        val = ctx.triggered[0].get('value')
        fill = float(val) if isinstance(val, (int, float)) and val > 0 else None
        if manual_log.load_log(tid['day']).get(tid['key'], {}).get('fill') == fill:
            raise PreventUpdate
        manual_log.set_fill(tid['day'], tid['key'], fill)
        return {'t': time.time()}

    # Clock, bar / close countdowns, flatten banner, tab title and browser notifications: in the browser, every
    # 15 s, from the last server render (no server or Wind call).
    app.clientside_callback(
        CLOCK_JS,
        [Output('fd-clock', 'children'), Output('fd-flatten-banner', 'children'),
         Output('fd-flatten-banner', 'style')],
        [Input('fd-clock-tick', 'n_intervals'), Input('fd-desk-clock', 'data')],
    )
    app.clientside_callback(
        ALERTS_JS, Output('fd-alerts-enable', 'children'), Input('fd-alerts-enable', 'n_clicks'),
        prevent_initial_call=True,
    )


def _valid_number(v):
    return isinstance(v, (int, float)) and v == v and v > 0


def desk_views(rows, fetch, state, approved, health, capital, risk_pct, stop_mult, loss_limit, now=None):
    """(live table, orders card, clock data) for the rendered rows."""
    now = now or china_now()
    running = bool(state and state.get('running'))
    sized = all(_valid_number(v) for v in (capital, risk_pct, stop_mult, loss_limit))
    sizing, actions_by_day, last_px, bars = {}, {}, {}, set()
    for r in rows:
        if r.get('night'):
            continue
        p = r['product']
        key = r.get('key', p)   # a product can have an intraday and a daily row: they are sized separately
        rec = {} if r.get('daily') else approved.get(p, {})
        if sized:
            try:
                sizing[key] = size_position(p, rec.get('exits'), r['last_px'], capital, risk_pct, stop_mult)
            except Exception:
                sizing[key] = None
        day = f"{r['day']:%Y-%m-%d}"
        log = manual_log.load_log(day)
        naive_now = now.replace(tzinfo=None) if hasattr(now, 'tzinfo') else now
        actions_by_day.setdefault(day, []).extend(
            (daily_actions(r, sizing.get(key), log, now=naive_now) if r.get('fresh', True) else []) if r.get('daily')
            else product_actions(r, sizing.get(key), log, now=naive_now))
        if not r.get('daily'):
            last_px[p] = r['last_px']
            if not r.get('closed'):
                bars.add(tf_minutes(r['candidate']))
    all_acts = [a for lst in actions_by_day.values() for a in lst]
    intraday = [a for a in all_acts if not a.get('daily')]   # daily positions are held overnight: no flatten, no day P&L
    held = held_positions(intraday)
    pnl = your_pnl_cny(intraday, last_px)
    limit_cny = capital * loss_limit / 100 if sized else 0.0
    stored = {p: a.get('status') for p, a in approved.items()}
    stored.update({f'{p}|1D': a.get('status') for p, a in approvals.load_approved_daily().items()})
    table = live_view(rows, fetch, state, now=now, sizing=sizing, health=health, stored=stored)
    if not sized:
        table = html.Div([_note("Set capital, risk, stop and loss limit in Today to size the tickets.", _RED), table])
    orders = orders_view(actions_by_day, held, pnl, limit_cny, running)
    clock = {
        'flatten': flatten_items(held), 'warn_min': FLATTEN_WARN_MIN, 'bars': sorted(bars),
        'night_ends': sorted({NIGHT_END[r['product']] for r in rows if r.get('session') == 'night+day' and r['product'] in NIGHT_END}),
        'pending': [{'key': a['key'], 'text': a['ticket']} for a in all_acts if a['state'] == 'pending'],
    }
    return table, orders, clock


CLOCK_JS = """
function(n, data) {
    data = data || {};
    const bj = new Date(Date.now() + 8 * 3600e3);
    const h = bj.getUTCHours(), m = bj.getUTCMinutes(), wd = bj.getUTCDay();
    const now = h * 60 + m + bj.getUTCSeconds() / 60;
    const pad = x => String(x).padStart(2, '0');
    const hm = x => pad(Math.floor(x / 60)) + ':' + pad(Math.round(x % 60));
    const left = x => { x = Math.max(0, Math.ceil(x)); return x >= 60 ? Math.floor(x / 60) + 'h ' + pad(x % 60) + 'm' : x + 'm'; };
    const parse = s => { const p = s.split(':'); return +p[0] * 60 + +p[1]; };
    const open = wd >= 1 && wd <= 5 && now >= 9 * 60 && now < 15 * 60 + 15 && !(now >= 11 * 60 + 30 && now < 13 * 60);
    // night + day strategies are working from 21:00 until their night session ends (Friday's runs into Saturday)
    const nEnds = (data.night_ends || []).map(parse);
    const nEnd = nEnds.length ? Math.max.apply(null, nEnds) : null;
    const nightOpen = nEnd !== null && ((wd >= 1 && wd <= 5 && now >= 21 * 60) || (wd >= 2 && wd <= 6 && now < nEnd));
    const parts = ['Beijing ' + pad(h) + ':' + pad(m)];
    if (nightOpen) {
        const cap = 24 * 60 + nEnd;   // the same scale as t: minutes since the evening's midnight
        const t = now >= 21 * 60 ? now : now + 24 * 60;
        (data.bars || []).forEach(b => {
            const nxt = Math.min(Math.ceil((t + 1 + 1e-6) / b) * b - 1, cap);
            parts.push('next ' + (b >= 60 ? (b / 60) + 'h' : b + 'min') + ' bar final ' + hm(nxt % 1440) + ' (in ' + left(nxt - t) + ')');
        });
        parts.push('night session ends ' + hm(nEnd) + ' (in ' + left(cap - t) + ')');
    } else if (open) {
        const closes = (data.flatten || []).map(f => parse(f.close));
        const close = closes.length ? Math.min.apply(null, closes) : 15 * 60;
        const cap = now < 11 * 60 + 30 ? 11 * 60 + 30 : close;
        (data.bars || []).forEach(b => {
            // minute bars are end-labelled, so a bar is final one minute before its boundary (10:30-bar -> 10:59)
            const nxt = Math.min(Math.ceil((now + 1 + 1e-6) / b) * b - 1, cap);
            parts.push('next ' + (b >= 60 ? (b / 60) + 'h' : b + 'min') + ' bar final ' + hm(nxt) + ' (in ' + left(nxt - now) + ')');
        });
        parts.push('session close ' + hm(close) + ' (in ' + left(close - now) + ')');
    } else {
        parts.push('market closed');
    }
    const warn = data.warn_min || 10;
    const lines = [];
    (data.flatten || []).forEach(f => {
        const l = parse(f.close) - now;
        if (open && l <= warn && l > -15) lines.push('FLATTEN before ' + f.close + ' (' + left(l) + '): ' + f.text);
    });
    const pending = data.pending || [];
    if (!window._fdTitle) window._fdTitle = document.title.replace(/^\\(\\d+\\) /, '');
    document.title = (pending.length ? '(' + pending.length + ') ' : '') + window._fdTitle;
    const seen = window._fdSeen = window._fdSeen || {};
    const fresh = [];
    pending.forEach(p => { if (!seen[p.key]) { seen[p.key] = 1; fresh.push(p.text); } });
    lines.forEach(t => { const k = 'flat|' + t.split(':')[0] + '|' + bj.toISOString().slice(0, 10); if (!seen[k]) { seen[k] = 1; fresh.push(t); } });
    // the first render with data only records what is already on screen; later changes notify
    if (data.pending) {
        if (window._fdInit && fresh.length && window.Notification && Notification.permission === 'granted') {
            fresh.forEach(t => { try { new Notification('Futures Desk', {body: t}); } catch (e) {} });
        }
        window._fdInit = true;
    }
    const style = lines.length
        ? {display: 'block', padding: '8px 12px', borderRadius: '6px', fontWeight: '700', fontSize: '12px',
           color: '#fff', background: 'rgba(248,113,113,0.85)', marginBottom: '8px'}
        : {display: 'none'};
    return [parts.join(' · '), lines.join('  |  '), style];
}
"""

ALERTS_JS = """
function(n) {
    if (!window.Notification) { return '🔔 Not supported in this browser'; }
    if (Notification.permission === 'granted') { return '🔔 Alerts on'; }
    Notification.requestPermission();
    return '🔔 Allow in the browser prompt, then click again';
}
"""
