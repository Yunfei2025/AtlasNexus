# -*- coding: utf-8 -*-
"""Futures Desk > Today: data refresh, today's book and the pool screen."""

from __future__ import annotations

import math
import time

from dash import html
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate

from .pool import MAX_BOOK, build_book, screen_rows

_GREEN, _RED, _AMBER = '#34d399', '#f87171', '#fbbf24'
_TH = {'padding': '5px 8px', 'textAlign': 'right', 'fontSize': '8px', 'color': 'var(--text-muted)',
       'textTransform': 'uppercase', 'letterSpacing': '0.05em', 'whiteSpace': 'nowrap'}


def _td(txt, color='var(--text-secondary)', left=False, bold=False):
    return html.Td(txt, style={'padding': '5px 8px', 'fontSize': '10px', 'color': color, 'whiteSpace': 'nowrap',
                               'textAlign': 'left' if left else 'right', 'fontWeight': '600' if bold else '400'})


def _table(head, body, left=(0,)):
    return html.Div(html.Table(
        [html.Thead(html.Tr([html.Th(h, style={**_TH, 'textAlign': 'left' if i in left else 'right'})
                             for i, h in enumerate(head)])), html.Tbody(body)],
        style={'width': '100%', 'borderCollapse': 'collapse'}), style={'overflowX': 'auto'})


def _row(cells):
    return html.Tr(cells, style={'borderBottom': '1px solid rgba(255,255,255,0.04)'})


def _note(txt, color='var(--text-muted)'):
    return html.Div(txt, style={'fontSize': '10px', 'color': color, 'lineHeight': '1.5', 'marginTop': '4px'})


# Position badge: filled colour plus an arrow, so direction never relies on colour alone
_BADGE = {1: ('▲ LONG', '52,211,153', _GREEN), -1: ('▼ SHORT', '248,113,113', _RED),
          0: ('■ FLAT', '164,182,210', 'var(--text-muted)')}


def signal_cell(direction, since):
    label, rgb, color = _BADGE[int(direction)]
    return html.Td([
        html.Span(label, className='fd-signal', style={
            'display': 'inline-block', 'minWidth': '64px', 'textAlign': 'center', 'padding': '3px 10px',
            'borderRadius': '4px', 'fontSize': '11px', 'fontWeight': '700', 'letterSpacing': '0.05em',
            'color': color, 'background': f'rgba({rgb},0.18)', 'border': f'1px solid rgba({rgb},0.65)'}),
        html.Span(f"since {since:%m-%d %H:%M}", style={'marginLeft': '8px', 'fontSize': '9px',
                                                       'color': 'var(--text-muted)'}),
    ], style={'padding': '5px 8px', 'textAlign': 'left', 'whiteSpace': 'nowrap'})


def _cny(v):
    return f"{v:,.0f}"


def book_view(book, capital, risk_pct, loss_limit_pct):
    if not book['rows']:
        return html.Div([
            html.Div("No approved strategies yet.", style={'fontSize': '12px', 'color': 'var(--text-primary)'}),
            _note("Research → pick a product (intraday mode) → ▶ Run walk-forward → Approve a candidate that passes "
                  "the gates. Trading fewer than five products, or none, is a valid outcome."),
        ])
    body = []
    for r in book['rows']:
        if 'error' in r:
            body.append(_row([_td(r['product'], left=True, bold=True), _td(r['candidate']),
                              html.Td(f"unavailable: {r['error']}", colSpan=8,
                                      style={'padding': '5px 8px', 'fontSize': '10px', 'color': _RED})]))
            continue
        body.append(_row([
            _td(r['product'], left=True, bold=True), _td(r['candidate']),
            _td(r['contract']), _td(f"{r['last_price']:,.2f}"),
            signal_cell(r['signal'], r['since']),
            _td(f"{r['stop_pts']:,.2f}" + (" σ" if r.get('stop_src') == 'σ' else "")),
            _td('—' if r['stop_price'] is None else f"{r['stop_price']:,.2f}"),
            _td(str(r['lots']), _AMBER if r['lots'] == 0 else 'var(--text-primary)', bold=True),
            _td(_cny(r['risk_cny'])), _td(_cny(r['notional'])),
        ]))
    head = ["Product", "Strategy", "Contract", "Last", "Position", "Stop dist", "Stop at", "Lots", "Risk CNY", "Notional"]
    live = [r for r in book['rows'] if 'error' not in r]
    ts = max((r['last_time'] for r in live), default=None)
    out = [_table(head, body, left=(0, 4)),
           _note(f"Capital {_cny(capital)} · {risk_pct:g}% risk per product · gross notional {_cny(book['notional'])} "
                 f"({book['leverage']:.2f}x capital) · if every stop hits: {_cny(book['risk_cny'])} "
                 f"({book['risk_cny'] / capital * 100:.2f}% of capital) vs daily loss limit "
                 f"{_cny(book['loss_limit_cny'])} ({loss_limit_pct:g}%)"
                 + (f" · latest bar {ts:%Y-%m-%d %H:%M}" if ts is not None else ""))]
    if book.get('halted'):
        out.append(_note(f"Halted, not in the book: {', '.join(book['halted'])}. Re-approve in Research to resume.", _RED))
    if book['excluded']:
        out.append(_note(f"Not in today's {MAX_BOOK}: {', '.join(book['excluded'])} (more correlated with the others, "
                         f"by strategy P&L).", _AMBER))
    for w in book['warnings']:
        out.append(_note(f"⚠ {w}", _AMBER))
    out.append(_note("Signal = the approved strategy at its default parameters on the latest bars; positions are "
                     "closed before the close. Stop distance = the approved strategy's stop loss when it has one, "
                     "else stop multiple × 20-day daily σ. Lots = floor(risk "
                     "budget / (stop distance × multiplier)). Multipliers are typed in from exchange specs: verify "
                     "before trading."))
    return html.Div(out)


def screen_view(rows):
    body = []
    for r in rows:
        stale = r['stale_days'] > 1
        status = {'approved': ('Approved', _GREEN), 'watch': ('Watch', _AMBER), 'halted': ('Halted', _RED)}.get(
            r['status'], ('—', 'var(--text-muted)'))
        body.append(_row([
            _td(r['product'], left=True, bold=True),
            _td(f"{r['daily_last']:%Y-%m-%d}" + (f" ({r['stale_days']}d old)" if stale else ''),
                _RED if stale else 'var(--text-secondary)'),
            _td(str(r['gaps_1y']), _AMBER if r['gaps_1y'] else 'var(--text-secondary)'),
            _td(f"{r['volume_20d']:,.0f}"), _td(f"{r['vol_ann'] * 100:.1f}%"),
            _td(f"{r['cost_bp']:.2f} ({r['cost_src']})",
                'var(--text-secondary)' if r['cost_src'] == 'measured' else 'var(--text-muted)'),
            _td(f"{r['intraday_to']:%m-%d %H:%M}" if r['intraday_to'] is not None else
                ('not synced' if r['has_ticks'] else '—'),
                _AMBER if r['intraday_to'] is None and r['has_ticks'] else 'var(--text-secondary)'),
            _td(status[0], status[1], bold=True),
            _td('—' if not r['candidate'] else f"{r['candidate']} · {r['pooled_sharpe']:+.2f}"),
        ]))
    head = ["Product", "Daily bars to", "Missing days (1y)", "Avg vol 20d", "Vol (ann.)", "Cost bp/side",
            "Intraday to", "Status", "Approved strategy · pooled Sharpe"]
    return html.Div([_table(head, body),
                     _note("Cost is measured (half-spread + fee) once a walk-forward has run for the product, "
                           "otherwise a default. Run walk-forward in Research to screen a product in.")])


def register_today_callbacks(app):
    @app.callback(
        Output('fd-data-stamp', 'data'),
        [Input('fd-today-refresh', 'n_clicks'), Input('bf-corr-refresh', 'n_clicks')],
        prevent_initial_call=True,
    )
    def fd_reload(_a, _b):
        """Re-read the local data files (written by the other data apps); no Wind or other external call."""
        return {'t': time.time(), 'msg': 'Reloaded local files.'}

    @app.callback(
        Output('fd-data-stamp', 'data', allow_duplicate=True),
        Input('fd-sync', 'n_clicks'), prevent_initial_call=True,
    )
    def fd_sync(_n):
        """Export minute bars of every tick file to the shared input folder (local files only)."""
        from futures.backtest import minute_bars
        if not minute_bars.TICK_DIR.is_dir():
            msg = "No tick files on this computer; using the shared bar cache as is."
        else:
            try:
                built = minute_bars.sync()
                msg = (f"Bar cache synced: {len(built)} contracts rebuilt, "
                       f"{minute_bars.cache_size_mb():.1f} MB in input/futures_desk/bars.")
            except Exception as e:
                msg = f"Bar cache sync failed: {e}"
        return {'t': time.time(), 'msg': msg}

    @app.callback(
        [Output('fd-book-container', 'children'), Output('fd-screen-container', 'children'),
         Output('fd-today-status', 'children')],
        [Input('fd-data-stamp', 'data'), Input('fd-capital', 'value'), Input('fd-risk-pct', 'value'),
         Input('fd-stop-mult', 'value'), Input('fd-loss-limit', 'value'), Input('fd-subtabs', 'value')],
    )
    def fd_today(stamp, capital, risk_pct, stop_mult, loss_limit, subtab):
        if subtab != 'today':
            raise PreventUpdate
        vals = (capital, risk_pct, stop_mult, loss_limit)
        if any(v is None or not isinstance(v, (int, float)) or math.isnan(v) or v <= 0 for v in vals):
            bad = html.Div("Capital, risk, stop and loss limit must all be positive numbers.",
                           style={'color': _RED, 'fontSize': '11px'})
            return bad, html.Div(), ''
        status = (stamp or {}).get('msg', '')
        try:
            book = build_book(capital, risk_pct, stop_mult, loss_limit)
            book_out = book_view(book, capital, risk_pct, loss_limit)
        except Exception as e:
            book_out = html.Div(f"Book unavailable: {e}", style={'color': _RED, 'fontSize': '11px'})
        try:
            screen_out = screen_view(screen_rows())
        except Exception as e:
            screen_out = html.Div(f"Screen unavailable: {e}", style={'color': _RED, 'fontSize': '11px'})
        return book_out, screen_out, status
