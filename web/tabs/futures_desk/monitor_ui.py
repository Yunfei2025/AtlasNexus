# -*- coding: utf-8 -*-
"""Futures Desk > Monitor: status table, forward P&L vs expected cone, apply / halt actions."""

from __future__ import annotations

import time

from dash import dcc, html
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go

from web.tabs.beta.data import THEME

from . import approvals
from .monitor import (
    BAND_HORIZON, HAIRCUT, MIN_FORWARD_DAYS, band, computed_to_applied, monitor_rows,
)
from .today import _TH, _td, _row, _note, _table, _GREEN, _RED, _AMBER

_STATUS = {'ok': ('OK', _GREEN), 'early': ('Early', 'var(--text-muted)'),
           'watch': ('Watch', _AMBER), 'halted': ('Halted', _RED),
           'approved': ('Approved', _GREEN)}


def _figure(row, watch_sig, halt_sig):
    ser, mean, std = row['fwd']['series'], row['mean'], row['std']
    n = len(ser)
    horizon = max(n + 5, BAND_HORIZON)
    x, mid, lo1, hi1 = band(mean, std, horizon, watch_sig)
    _, _, lo2, hi2 = band(mean, std, horizon, halt_sig)
    pct = lambda a: a * 100
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=pct(lo2), mode='lines', line={'width': 0}, hoverinfo='skip', showlegend=False))
    fig.add_trace(go.Scatter(x=x, y=pct(hi2), mode='lines', line={'width': 0}, fill='tonexty',
                             fillcolor='rgba(230,103,103,0.10)', hoverinfo='skip', name=f'±{halt_sig:g}σ'))
    fig.add_trace(go.Scatter(x=x, y=pct(lo1), mode='lines', line={'width': 0}, hoverinfo='skip', showlegend=False))
    fig.add_trace(go.Scatter(x=x, y=pct(hi1), mode='lines', line={'width': 0}, fill='tonexty',
                             fillcolor='rgba(57,135,229,0.16)', hoverinfo='skip', name=f'±{watch_sig:g}σ'))
    fig.add_trace(go.Scatter(x=x, y=pct(mid), mode='lines', line={'width': 1, 'dash': 'dot', 'color': '#a4b6d2'},
                             name='expected', hovertemplate='day %{x}: %{y:.2f}%<extra>expected</extra>'))
    if n:
        fig.add_trace(go.Scatter(
            x=list(range(1, n + 1)), y=pct(ser.cumsum().values), mode='lines+markers',
            line={'width': 2, 'color': '#e9eef8'}, marker={'size': 5}, name='paper P&L',
            text=[f"{d:%Y-%m-%d}" for d in ser.index],
            hovertemplate='%{text}: %{y:.2f}%<extra>paper P&L</extra>'))
    fig.update_layout(
        height=210, template=THEME['chart_template'], paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font={'color': '#e9eef8', 'size': 10}, margin=dict(l=44, r=8, t=26, b=30), showlegend=False,
        title={'text': f"{row['product']} · {row['rec']['candidate']}", 'font': {'size': 11}, 'x': 0.01, 'y': 0.96},
        xaxis={'title': {'text': 'forward trading day', 'font': {'size': 9}}, 'gridcolor': 'rgba(100,140,200,0.12)', 'rangemode': 'tozero'},
        yaxis={'title': {'text': 'return on notional, %', 'font': {'size': 9}}, 'gridcolor': 'rgba(100,140,200,0.12)', 'zeroline': True},
    )
    return fig


def monitor_view(rows, watch_sig, halt_sig):
    if not rows:
        return html.Div([
            html.Div("No approved strategies to monitor.", style={'fontSize': '12px', 'color': 'var(--text-primary)'}),
            _note("Approve a candidate in Research first (walk-forward → Approve)."),
        ])
    body, notes, graphs = [], [], []
    for r in rows:
        prod, rec = r['product'], r['rec']
        if 'error' in r:
            body.append(_row([_td(prod, left=True, bold=True), _td(rec['candidate']),
                              html.Td(f"unavailable: {r['error']}", colSpan=9,
                                      style={'padding': '5px 8px', 'fontSize': '10px', 'color': _RED})]))
            continue
        a, fwd = r['assessment'], r['fwd']
        n = len(fwd['series'])
        ret = fwd['series'].sum() * 100
        exp = HAIRCUT * r['mean'] * n * 100 if r['mean'] is not None else float('nan')
        comp = _STATUS[a['status']]
        cur = _STATUS.get(r['current'], (r['current'], 'var(--text-muted)'))
        body.append(_row([
            _td(prod, left=True, bold=True), _td(rec['candidate']), _td(f"{rec['wf_last_day']}"), _td(str(n)),
            _td(f"{ret:+.2f}%", _GREEN if ret > 0 else (_RED if ret < 0 else 'var(--text-secondary)')),
            _td(f"{exp:+.2f}%"), _td('—' if a['z'] is None else f"{a['z']:+.1f}"),
            _td(str(a['streak']), _AMBER if a['streak'] >= 3 else 'var(--text-secondary)'),
            _td(str(fwd['trades'])), _td(comp[0], comp[1], bold=True), _td(cur[0], cur[1], bold=True),
        ]))
        for why in a['reasons']:
            notes.append(_note(f"{prod}: {why}", comp[1]))
        if r['current'] == 'halted':
            notes.append(_note(f"{prod} is halted ({rec.get('status_reason', '')}, {rec.get('status_at', '')}); "
                               "re-run the walk-forward and approve again in Research to resume.", _RED))
        graphs.append(dcc.Graph(figure=_figure(r, watch_sig, halt_sig), config={'displayModeBar': False}))
    head = ["Product", "Strategy", "Evidence to", "Fwd days", "Fwd return", "Expected", "z", "Losing streak",
            "Round trips", "Computed", "Stored"]
    return html.Div([
        _table(head, body), *notes,
        html.Div(graphs, style={'display': 'grid', 'gridTemplateColumns': 'repeat(auto-fit, minmax(340px, 1fr))',
                                'gap': '8px', 'marginTop': '10px'}),
        _note(f"Paper replay of each approved strategy (default parameters, its approved cost, flat at the close) "
              f"on the local contract files for the trading days after its walk-forward ended; it is not your "
              f"actual fills. Expected path = {HAIRCUT:g} × the walk-forward's mean daily return (haircut for "
              f"selection bias); bands = ±σ·√days from the walk-forward's daily volatility. With fewer than "
              f"{MIN_FORWARD_DAYS} forward days the status stays Early. Return is on notional, before position sizing."),
    ])


def register_monitor_callbacks(app):
    thresholds = [State('fd-mon-watch', 'value'), State('fd-mon-halt', 'value'), State('fd-mon-losses', 'value')]

    def _params(w, h, n):
        if not all(isinstance(v, (int, float)) and v > 0 for v in (w, h, n)) or w >= h:
            return None
        return float(w), float(h), int(n)

    @app.callback(
        [Output('fd-mon-container', 'children'), Output('fd-mon-pick', 'options')],
        [Input('fd-data-stamp', 'data'), Input('fd-subtabs', 'value'), Input('fd-mon-watch', 'value'),
         Input('fd-mon-halt', 'value'), Input('fd-mon-losses', 'value')],
    )
    def fd_monitor(_stamp, subtab, watch, halt, losses):
        if subtab != 'monitor':
            raise PreventUpdate
        p = _params(watch, halt, losses)
        if p is None:
            return html.Div("Watch σ must be positive and below Halt σ; losing days must be positive.",
                            style={'color': _RED, 'fontSize': '11px'}), []
        try:
            rows = monitor_rows(*p)
            opts = [{'label': f"{r['product']} · {r['rec']['candidate']}", 'value': r['product']}
                    for r in rows if r['current'] != 'halted']
            return monitor_view(rows, p[0], p[1]), opts
        except Exception as e:
            return html.Div(f"Monitor unavailable: {e}", style={'color': _RED, 'fontSize': '11px'}), []

    @app.callback(
        [Output('fd-mon-note', 'children'), Output('fd-data-stamp', 'data', allow_duplicate=True)],
        Input('fd-mon-apply', 'n_clicks'), thresholds, prevent_initial_call=True,
    )
    def fd_apply(_n, watch, halt, losses):
        p = _params(watch, halt, losses)
        if p is None:
            return "Fix the thresholds first.", no_stamp()
        changed = []
        for r in monitor_rows(*p):
            if 'error' in r:
                continue
            new = computed_to_applied(r['current'], r['assessment']['status'])
            if new != r['current']:
                reason = '; '.join(r['assessment']['reasons']) or 'back within the band'
                approvals.set_status(r['product'], new, reason)
                changed.append(f"{r['product']} → {new}")
        msg = "Applied: " + (', '.join(changed) if changed else "no status changes") + "."
        return msg, {'t': time.time(), 'msg': msg}

    @app.callback(
        [Output('fd-mon-note', 'children', allow_duplicate=True),
         Output('fd-data-stamp', 'data', allow_duplicate=True)],
        Input('fd-mon-halt-now', 'n_clicks'), State('fd-mon-pick', 'value'), prevent_initial_call=True,
    )
    def fd_halt_now(_n, product):
        if not product:
            return "Pick a product to halt.", no_stamp()
        approvals.set_status(product, 'halted', 'halted manually')
        msg = f"{product} halted manually; it leaves today's book until re-approved in Research."
        return msg, {'t': time.time(), 'msg': msg}


def no_stamp():
    from dash import no_update
    return no_update
