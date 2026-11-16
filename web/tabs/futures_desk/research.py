# -*- coding: utf-8 -*-
"""Futures Desk > Research: multi-contract walk-forward table and strategy approval."""

from __future__ import annotations

import math

import numpy as np
from dash import ALL, ctx, html, no_update
from dash.exceptions import PreventUpdate
from dash.dependencies import Input, Output, State

from futures.backtest.costs import describe_exits, normalize_exits, product_of
from futures.backtest.live_bars import NIGHT_END
from futures.backtest.minute_bars import list_contracts, load_minute_bars
from futures.backtest.walkforward import (
    PANEL_STRATEGY, load_walkforward, run_walkforward, save_walkforward,
)

from .approvals import DESK_DIR, approve, approve_daily, candidate_exits, daily_gate, load_approved, load_approved_daily
from .pool import add_to_portfolio

_TH = {'padding': '5px 8px', 'textAlign': 'right', 'fontSize': '8px', 'color': 'var(--text-muted)',
       'textTransform': 'uppercase', 'letterSpacing': '0.05em', 'whiteSpace': 'nowrap'}
_GREEN, _RED, _AMBER_TXT = '#34d399', '#f87171', '#fbbf24'


def _num(v, fmt, color=True):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return '—', 'var(--text-muted)'
    txt = format(v, fmt)
    return txt, (_GREEN if v > 0 else _RED) if color else 'var(--text-secondary)'


def _cell(txt, color='var(--text-secondary)', left=False, bold=False, pick=None):
    """pick=(candidate, contract) makes the cell click-to-chart ('' contract = the selected one)."""
    extra = {'id': {'type': 'bf-wf-pick', 'cand': pick[0], 'c': pick[1]}, 'n_clicks': 0,
             'title': 'Click to chart this candidate'} if pick else {}
    return html.Td(txt, **extra, style={'padding': '5px 8px', 'fontSize': '10px', 'color': color,
                                        'whiteSpace': 'nowrap', 'textAlign': 'left' if left else 'right',
                                        'fontWeight': '600' if bold else '400',
                                        'cursor': 'pointer' if pick else 'default',
                                        'textDecoration': 'underline dotted' if pick and left else 'none'})


MAX_SHOWN = 10
MIN_SHOWN_NIGHT = 5   # the night table shows at least this many candidates, passing or not


def wf_table(wf, approved_candidate=None):
    """The candidates that pass the gates, best pooled Sharpe first, at most MAX_SHOWN."""
    passing = sorted(((k, r) for k, r in wf['rows'].items() if r['passes']), key=lambda kv: -kv[1]['pooled'])
    rows = passing[:MAX_SHOWN]
    g = wf['gates']
    contracts = [c for c, v in wf['contracts'].items() if v['days'] >= g['min_contract_days']]  # judged contracts
    searched = wf.get('exits') == 'search'
    head = [html.Th("Candidate", style={**_TH, 'textAlign': 'left'})] + (
            [html.Th("Stop / target", style={**_TH, 'textAlign': 'left'}), html.Th("No exits", style=_TH)]
            if searched else []) + [html.Th("Pooled", style=_TH), html.Th("± SE", style=_TH)] + [html.Th(c, style=_TH) for c in contracts] + [
            html.Th("Overnight", style=_TH, title="Same candidate, costs and exits, but the position is held through "
                    "each close. Information only: the desk trades flat at the close."),
            html.Th("Δ vs flat", style=_TH, title="Overnight Sharpe minus flat Sharpe. Coloured only when the "
                    "difference is larger than one standard error of the flat Sharpe."),
            html.Th("Max DD flat → over", style=_TH, title="Largest peak-to-trough fall of cumulative return on "
                    "notional, in %"),
            html.Th("Trades/d", style=_TH), html.Th("Win", style=_TH), html.Th("Payoff", style=_TH),
            html.Th("Exp bp", style=_TH), html.Th("Gate", style=_TH)]
    body = []
    for name, r in rows:
        label = ('✔ ' if name == approved_candidate else '') + name
        tds = [_cell(label, left=True, bold=True, pick=(name, ''))]
        if searched:
            tds += [_cell(describe_exits(r.get('exits')), left=True), _cell(*_num(r.get('base_pooled'), '+.2f'))]
        tds += [_cell(*_num(r['pooled'], '+.2f')),
               _cell(*_num(r['se'], '.2f', color=False))]
        for c in contracts:
            tds.append(_cell(*_num(r['per_contract'].get(c), '+.1f'), pick=(name, c)))
        tds += _overnight_cells(r)
        tds += [_cell(f"{r['trades_per_day']:.1f}"),
                _cell('—' if math.isnan(r['win']) else f"{r['win'] * 100:.0f}%"),
                _cell(*_num(r['payoff'], '.2f', color=False)),
                _cell(*_num(r['expectancy_bp'], '+.1f')),
                _cell('pass' if r['passes'] else '—', _GREEN if r['passes'] else 'var(--text-muted)')]
        body.append(html.Tr(tds, style={'borderBottom': '1px solid rgba(255,255,255,0.04)'}))
    n_pass = sum(r['passes'] for r in wf['rows'].values())
    cdesc = ', '.join(f"{c} {v['days']}d" for c, v in wf['contracts'].items())
    return html.Div([
        html.Div(f"{wf['product']} · {wf['days']} days to {wf['last_day']} · {describe_exits(wf.get('exits'))} · "
                 f"cost {wf['cost_bp']:.2f}bp/side "
                 f"(half-spread {wf['half_spread_bp']:.2f} + fee {wf['fee_bp']:.2f}) · run {wf['run_at']}",
                 style={'fontSize': '9px', 'color': 'var(--text-muted)', 'marginBottom': '2px'}),
        html.Div(daily_vs_intraday(wf) + ".",
                 style={'fontSize': '10px', 'color': 'var(--text-primary)', 'marginBottom': '4px'}),
        overnight_summary(wf, passing),
        html.Div(f"{n_pass} of {len(wf['rows'])} candidates pass" + (f" (best {MAX_SHOWN} shown)" if n_pass > MAX_SHOWN else "") + f". Gate: pooled Sharpe > 0, ≥ {g['min_trades']} trades, "
                 f"net-positive on at least 2/3 of contracts with ≥ {g['min_contract_days']} days. "
                 f"Sharpe per contract; contracts: {cdesc}. Click a candidate (or one contract's Sharpe) to chart it below.",
                 style={'fontSize': '9px', 'color': 'var(--text-muted)', 'marginBottom': '6px'}),
        html.Div("Stop / target were searched per candidate (stop 0 / 0.3 / 0.5 / 1%, target 0 / 0.5 / 1%), keeping "
                 "the best pooled Sharpe. Compare Pooled with No exits and with ± SE: a gain of about one SE or "
                 "less is what searching 12 settings gives by chance.",
                 style={'fontSize': '9px', 'color': _AMBER_TXT, 'marginBottom': '6px'}) if searched else None,
        html.Div(html.Table([html.Thead(html.Tr(head)), html.Tbody(body)],
                            style={'width': '100%', 'borderCollapse': 'collapse'}), style={'overflowX': 'auto'})
        if body else html.Div("No candidate passes the gates for this product. Use Controls > Run Backtest to "
                              "look at a strategy anyway.", style={'fontSize': '10px', 'color': _AMBER_TXT}),
        overnight_by_contract(wf, passing, approved_candidate),
        daily_table(wf),
    ])


def night_table(wf):
    """A night + day run: every candidate (none can pass yet), the day-only result next to it and both P&Ls on the
    trade days that really had a night session. Information only: it cannot be approved."""
    g = wf['gates']
    n, need = wf.get('night_days', 0), g.get('min_night_days', 0)
    head = ["Candidate", "Day only", "Night + day", "± SE", "Night days", "P&L day only", "P&L with night", "Δ P&L", "Gate"]
    ranked = sorted(wf['rows'].items(), key=lambda kv: -(-9 if math.isnan(kv[1]['pooled']) else kv[1]['pooled']))
    # the candidates that pass, best first, topped up with the best of the rest so at least MIN_SHOWN_NIGHT show
    rows = [kv for kv in ranked if kv[1]['passes']]
    rows += [kv for kv in ranked if not kv[1]['passes']][:max(0, MIN_SHOWN_NIGHT - len(rows))]
    rows = rows[:MAX_SHOWN]
    body = []
    for name, r in rows:
        c = r.get('night_cmp') or {}
        delta = None if not c else c['with_night'] - c['day_only']
        body.append(html.Tr([
            _cell(name, left=True, bold=True), _cell(*_num(c.get('day_pooled'), '+.2f')), _cell(*_num(r['pooled'], '+.2f')),
            _cell(*_num(r['se'], '.2f', color=False)), _cell(str(c.get('days', '—'))),
            _cell(*_num(None if not c else c['day_only'] * 100, '+.2f')),
            _cell(*_num(None if not c else c['with_night'] * 100, '+.2f')),
            _cell(*_num(None if delta is None else delta * 100, '+.2f')),
            _cell('pass', _GREEN) if r['passes'] else
            _cell(f"needs {need} night days" if r.get('passes_ex_night') else "fails the day gates", _AMBER_TXT)],
            style={'borderBottom': '1px solid rgba(255,255,255,0.04)'}))
    return html.Div([
        html.Div(f"{wf['product']} · night + day session · {wf['days']} days to {wf['last_day']} · run {wf['run_at']}",
                 style={'fontSize': '9px', 'color': 'var(--text-muted)', 'marginBottom': '2px'}),
        html.Div(f"Only {n} of {wf['days']} trade days have a night session on file; at least {need} are needed before "
                 f"a candidate can pass. The best {len(rows)} are shown (top 5 when fewer pass); the Gate column says why one does not pass. The P&L columns compare the two sessions on those days only (% of "
                 "notional, summed). The night history is being collected from the live fetch plus the 7-night "
                 "backfill, so read this as a preview. Night + day runs cannot be approved: Today, the Monitor and "
                 "the book trade the day session only.",
                 style={'fontSize': '10px', 'color': _AMBER_TXT, 'marginBottom': '6px'}),
        html.Div(html.Table([html.Thead(html.Tr([html.Th(h, style={**_TH, 'textAlign': 'left' if i == 0 else 'right'})
                                                 for i, h in enumerate(head)])), html.Tbody(body)],
                            style={'width': '100%', 'borderCollapse': 'collapse'}), style={'overflowX': 'auto'}),
    ])


def _overnight_cells(r):
    """Overnight Sharpe, its difference to the flat Sharpe and the drawdown pair for one candidate row."""
    ov = r.get('overnight')
    if not ov:
        return [_cell('—', 'var(--text-muted)')] * 3
    d = ov['pooled'] - r['pooled']
    se = r['se']
    big = not (math.isnan(d) or math.isnan(se)) and abs(d) > se
    dcol = (_GREEN if d > 0 else _RED) if big else 'var(--text-muted)'
    dd = f"{r['max_dd'] * 100:.1f} → {ov['max_dd'] * 100:.1f}%" if r.get('max_dd') is not None else '—'
    return [_cell(*_num(ov['pooled'], '+.2f')),
            _cell('—' if math.isnan(d) else f"{d:+.2f}", dcol, bold=big),
            _cell(dd, _AMBER_TXT if r.get('max_dd') is not None and ov['max_dd'] > 1.25 * r['max_dd'] else
                  'var(--text-secondary)')]


def overnight_summary(wf, passing):
    """One paragraph answering: does holding through the close help this product, or just add gap risk?"""
    rows = [(k, r) for k, r in passing if r.get('overnight')]
    note = {'fontSize': '10px', 'color': 'var(--text-primary)', 'marginBottom': '4px'}
    if not rows:
        return html.Div("Held overnight: this walk-forward was run before the comparison existed. Click ▶ Run "
                        "walk-forward again to add it.", style={**note, 'color': _AMBER_TXT})
    deltas = [r['overnight']['pooled'] - r['pooled'] for _, r in rows]
    deltas = [d for d in deltas if not math.isnan(d)]
    better = sum(d > 0 for d in deltas)
    med = float(np.median(deltas)) if deltas else float('nan')
    se = float(np.nanmedian([r['se'] for _, r in rows]))
    pct = lambda vals: float(np.median(vals)) * 100
    dd_f, dd_o = pct([r['max_dd'] for _, r in rows]), pct([r['overnight']['max_dd'] for _, r in rows])
    wd_f, wd_o = pct([r['worst_day'] for _, r in rows]), pct([r['overnight']['worst_day'] for _, r in rows])
    if math.isnan(med) or abs(med) <= se:
        verdict = "The difference is inside one SE: no evidence that holding overnight changes the result."
    elif med > 0:
        verdict = ("Overnight looks better by more than one SE, but the stop / target cannot cap an overnight gap "
                   "and the bars hold day sessions only (night-session moves are inside the gap).")
    else:
        verdict = "Holding overnight is worse by more than one SE: keep flat at the close."
    worse = [w for w, bad in (("drawdown", dd_o > 1.25 * dd_f), ("worst day", wd_o < 1.25 * wd_f)) if bad]
    if worse:
        verdict += f" The {' and '.join(worse)} {'are' if len(worse) > 1 else 'is'} at least 25% larger overnight."
    return html.Div(
        f"Held overnight vs flat, {len(rows)} passing candidates: better on {better}, median Sharpe change "
        f"{med:+.2f} (typical SE {se:.2f}); median max drawdown {dd_f:.1f}% → {dd_o:.1f}%, median worst day "
        f"{wd_f:.1f}% → {wd_o:.1f}%. {verdict}", style=note)


def overnight_by_contract(wf, passing, approved_candidate=None):
    """Flat vs overnight Sharpe per contract for one candidate (the approved one, else the best), so the
    question can be answered for a given contract."""
    pick = next(((k, r) for k, r in passing if k == approved_candidate and r.get('overnight')), None) or \
        next(((k, r) for k, r in passing if r.get('overnight')), None)
    if pick is None:
        return None
    name, r = pick
    g = wf['gates']
    body = []
    for c, flat in r['per_contract'].items():
        over = r['overnight']['per_contract'].get(c)
        d = None if over is None else over - flat
        body.append(html.Tr([
            _cell(c, left=True, bold=True), _cell(str(wf['contracts'][c]['days'])), _cell(*_num(flat, '+.1f')),
            _cell(*_num(over, '+.1f')), _cell(*_num(d, '+.1f', color=False)),
        ], style={'borderBottom': '1px solid rgba(255,255,255,0.04)'}))
    if not body:
        return None
    head = ["Contract", "Days", "Flat", "Overnight", "Δ"]
    return html.Div([
        html.Div(f"Flat vs held overnight by contract: {name}", style={
            'fontSize': '10px', 'fontWeight': '600', 'color': 'var(--text-primary)', 'margin': '10px 0 2px'}),
        html.Div(f"Sharpe per contract over its main-contract days (contracts with ≥ {g['min_contract_days']} days). "
                 "Held overnight keeps the strategy's position through each close, with the same cost and exits.",
                 style={'fontSize': '9px', 'color': 'var(--text-muted)', 'marginBottom': '4px'}),
        html.Div(html.Table([html.Thead(html.Tr([html.Th(h, style={**_TH, 'textAlign': 'left' if i == 0 else 'right'})
                                                 for i, h in enumerate(head)])), html.Tbody(body)],
                            style={'width': 'auto', 'minWidth': '320px', 'borderCollapse': 'collapse'})),
    ])


def daily_vs_intraday(wf):
    """One line: best intraday candidate vs best daily-bar candidate over the same dates (whether or not
    they pass the gates)."""
    ok = [(k, r) for k, r in wf['rows'].items() if not math.isnan(r['pooled'])]
    bi = max(ok, key=lambda kv: kv[1]['pooled'], default=None)
    d = (wf.get('daily') or {}).get('rows') or {}
    bd = max(((k, r) for k, r in d.items() if not math.isnan(r['recent'])), key=lambda kv: kv[1]['recent'], default=None)
    return ("best intraday: " + ("none" if bi is None else f"{bi[0]} {bi[1]['pooled']:+.2f} ± {bi[1]['se']:.2f}")
            + " · best daily over the same dates: "
            + ("none" if bd is None else f"{bd[0]} {bd[1]['recent']:+.2f} ± {bd[1]['recent_se']:.2f}"))


def daily_table(wf):
    """Daily-bar candidates (held overnight) on the continuous daily series, for comparison."""
    dd = wf.get('daily')
    if not dd or not dd.get('rows'):
        return None
    head = ["Candidate", "Same dates", "± SE", "Days", "Full history", "± SE", "Years", "Trades", "Win", "Payoff", "Exp bp", "Gate"]
    body = []
    for name, r in sorted(dd['rows'].items(), key=lambda kv: -(kv[1]['recent'] if not math.isnan(kv[1]['recent']) else -9)):
        body.append(html.Tr([
            _cell(name, left=True, bold=True),
            _cell(*_num(r['recent'], '+.2f')), _cell(*_num(r['recent_se'], '.2f', color=False)),
            _cell(str(r['recent_days'])),
            _cell(*_num(r['pooled'], '+.2f')), _cell(*_num(r['se'], '.2f', color=False)),
            _cell(f"{r['years_positive']}/{r['years']} +"),
            _cell(str(r['trades'])),
            _cell('—' if r['win'] is None or math.isnan(r['win']) else f"{r['win'] * 100:.0f}%"),
            _cell(*_num(r['payoff'], '.2f', color=False)), _cell(*_num(r['expectancy_bp'], '+.1f')),
            _cell('pass', _GREEN) if daily_gate(dd, name)[0] else _cell('—', 'var(--text-muted)'),
        ], style={'borderBottom': '1px solid rgba(255,255,255,0.04)'}))
    return html.Div([
        html.Div("Daily strategies (held overnight)", style={'fontSize': '10px', 'fontWeight': '600',
                                                           'color': 'var(--text-primary)', 'margin': '10px 0 2px'}),
        html.Div(f"Continuous daily series {dd['start']} to {dd['end']}, default parameters, same cost per side, no "
                 f"stop / target. 'Same dates' = Sharpe over the days of the intraday run above (the fair comparison, "
                 f"but a short sample: see ± SE); 'Full history' uses all years. Gate = full-history Sharpe above 0 on at "
                 f"least {dd.get('min_trades', 30)} trades: a candidate that passes can be approved next to the product's "
                 f"intraday strategy (pick it below). It is traded near the close and held overnight, so it carries "
                 f"gap risk the stop cannot cap. Rolls of the continuous series are not adjusted.",
                 style={'fontSize': '9px', 'color': 'var(--text-muted)', 'marginBottom': '4px'}),
        html.Div(html.Table([html.Thead(html.Tr([html.Th(h, style={**_TH, 'textAlign': 'left' if i == 0 else 'right'})
                                                 for i, h in enumerate(head)])), html.Tbody(body)],
                            style={'width': '100%', 'borderCollapse': 'collapse'}), style={'overflowX': 'auto'}),
    ])


def portfolio_message(product, daily=False):
    """Approving puts the product in the Portfolio; says what happened (a full portfolio does not undo the approval)."""
    try:
        members = add_to_portfolio(product, daily=daily)
        return f" Added to the Portfolio ({', '.join(members)})."
    except ValueError as e:
        return " Already in the Portfolio." if 'already' in str(e) else f" Not added to the Portfolio: {e}."


def approved_note(product):
    a = load_approved().get(product) if product else None
    d = load_approved_daily().get(product) if product else None
    if not a and not d:
        return f"{product or '—'}: not approved."
    night = (f" · night + day, {a.get('night_days', 0)} night days" + (" (forced)" if a.get('forced') else "")
             if a and a.get('session') == 'night+day' else "")
    daily = (f" · daily: {d['candidate']} (full history {d['pooled_sharpe']:+.2f} ± {d['sharpe_se']:.2f}, "
             f"{d['years_positive']}/{d['years']} years +)" if d else "")
    if not a:
        return f"{product}: no intraday strategy" + daily
    return (f"{product}: approved {a['candidate']} on {a['approved_at']} · pooled Sharpe {a['pooled_sharpe']:+.2f} "
            f"± {a['sharpe_se']:.2f} · cost {a['cost_bp']:.2f}bp" + night + daily)


def _night_pick_options(wf):
    """Night + day candidates that pass every day gate (the night-days gate can be forced), best first."""
    ok = sorted(((k, r) for k, r in wf['rows'].items() if r.get('passes_ex_night')), key=lambda kv: -kv[1]['pooled'])
    return [{'label': f"{k}" + (f" · {describe_exits(r['exits'])}" if r.get('exits') else '') +
                      f" · pooled {r['pooled']:+.2f} ± {r['se']:.2f}", 'value': k} for k, r in ok]


def _pick_options(wf):
    passing = sorted(((k, r) for k, r in wf['rows'].items() if r['passes']), key=lambda kv: -kv[1]['pooled'])
    opts = [{'label': f"{k}" + (f" · {describe_exits(r['exits'])}" if r.get('exits') else '') +
                      f" · pooled {r['pooled']:+.2f} ± {r['se']:.2f}", 'value': k} for k, r in passing]
    dd = wf.get('daily') or {}
    daily = sorted(((k, r) for k, r in (dd.get('rows') or {}).items() if daily_gate(dd, k)[0]), key=lambda kv: -kv[1]['pooled'])
    return opts + [{'label': f"{k} · daily, held overnight · full history {r['pooled']:+.2f} ± {r['se']:.2f}", 'value': k}
                   for k, r in daily]


def drill_payload(candidate, contract, selected, source, wind_code, wf_dir=None):
    """What the Research chart needs to show one walk-forward candidate: the strategy and bar size, the
    contract's full date range, and the walk-forward's cost. None when there is no data for the contract."""
    product = product_of(candidate_product(selected, source, wind_code))
    wf = load_walkforward(product, wf_dir or DESK_DIR)
    if wf is None or candidate not in wf['rows']:
        return None
    contract = contract or (selected if product_of(selected) == product and selected in list_contracts(product)
                            else (list_contracts(product) or [None])[-1])
    bars = load_minute_bars(contract) if contract else None
    if bars is None or bars.empty:
        return None
    strategy, timeframe = candidate.split('@')
    return {'cand': candidate, 'strategy': PANEL_STRATEGY.get(strategy, strategy), 'timeframe': timeframe,
            'contract': contract, 'cost_bp': wf['cost_bp'], 'exits': candidate_exits(wf, candidate), 'start': str(bars.index.min().date()),
            'end': str(bars.index.max().date())}


def candidate_product(selected, source, wind_code):
    return wind_code if source == 'wind' else selected


def register_research_callbacks(app):
    @app.callback(
        Output('bf-drill', 'data'),
        Input({'type': 'bf-wf-pick', 'cand': ALL, 'c': ALL}, 'n_clicks'),
        [State('bf-local-symbol', 'value'), State('bf-data-source', 'value'), State('bf-wind-code', 'value')],
        prevent_initial_call=True,
    )
    def bf_wf_pick(_clicks, selected, source, wind_code):
        t = ctx.triggered_id
        if not isinstance(t, dict) or not ctx.triggered[0]['value']:  # table re-rendered, nothing clicked
            raise PreventUpdate
        payload = drill_payload(t['cand'], t['c'], selected, source, wind_code)
        if payload is None:
            raise PreventUpdate
        return payload

    @app.callback(
        [Output('bf-wf-container', 'children'), Output('bf-wf-pick', 'options'),
         Output('bf-wf-pick', 'value'), Output('bf-wf-approved-note', 'children')],
        [Input('bf-wf-run', 'n_clicks'), Input('bf-local-symbol', 'value'), Input('bf-wind-code', 'value'),
         Input('bf-wf-night', 'value')],
        [State('bf-data-source', 'value'), State('bf-trading-mode', 'value'),
         State('bf-stop', 'value'), State('bf-target', 'value'), State('bf-exit-unit', 'value'),
         State('bf-wf-search', 'value')],
    )
    def bf_walkforward(_n, local_symbol, wind_code, night, source, mode, stop, target, unit, search):
        product = product_of(wind_code if source == 'wind' else local_symbol)
        note = approved_note(product)
        hint = lambda t: html.Div(t, style={'fontSize': '10px', 'color': 'var(--text-muted)'})
        if not product:
            return hint("Select a symbol."), [], None, note
        running = ctx.triggered_id == 'bf-wf-run'
        night = bool(night) and product in NIGHT_END
        if night:
            try:
                if running:
                    wf = run_walkforward(product, exits=normalize_exits(stop, target, unit),
                                         search_exits=bool(search), night=True)
                    save_walkforward(wf, DESK_DIR)
                else:
                    wf = load_walkforward(product, DESK_DIR, night=True)
            except Exception as e:
                return hint(f"Walk-forward failed: {e}"), [], None, note
            if wf is None:
                return hint(f"No night + day walk-forward for {product} yet. Click ▶ Run walk-forward."), [], None, note
            opts = _night_pick_options(wf)
            return night_table(wf), opts, (opts[0]['value'] if opts else None), note
        if running and mode != 'intraday':
            return hint("Walk-forward needs intraday contracts: switch Mode to Intraday."), [], None, note
        if running:
            try:
                wf = run_walkforward(product, exits=normalize_exits(stop, target, unit),
                                     search_exits=bool(search))
                save_walkforward(wf, DESK_DIR)
            except Exception as e:
                return hint(f"Walk-forward failed: {e}"), [], None, note
        else:
            wf = load_walkforward(product, DESK_DIR)
            if wf is None:
                return hint(f"No walk-forward for {product} yet. Click ▶ Run walk-forward (intraday mode)."), [], None, note
        opts = _pick_options(wf)
        approved = (load_approved().get(product) or {}).get('candidate')
        value = approved if approved in {o['value'] for o in opts} else (opts[0]['value'] if opts else None)
        return wf_table(wf, approved), opts, value, note

    @app.callback(
        [Output('bf-wf-approve-note', 'children'),
         Output('bf-wf-approved-note', 'children', allow_duplicate=True),
         Output('bf-wf-container', 'children', allow_duplicate=True)],
        Input('bf-wf-approve', 'n_clicks'),
        [State('bf-wf-pick', 'value'), State('bf-local-symbol', 'value'), State('bf-wind-code', 'value'),
         State('bf-data-source', 'value'), State('bf-wf-night', 'value')],
        prevent_initial_call=True,
    )
    def bf_approve(_n, candidate, local_symbol, wind_code, source, night):
        product = product_of(wind_code if source == 'wind' else local_symbol)
        night = bool(night) and product in NIGHT_END   # the table on screen decides which run is approved
        wf = load_walkforward(product, DESK_DIR, night=night) if product else None
        if not candidate or wf is None:
            return "Run the walk-forward and pick a passing candidate first.", no_update, no_update
        daily = bool(candidate) and candidate.endswith('@1D')
        try:
            (approve_daily if daily else approve)(product, candidate, wf)
        except ValueError as e:
            return str(e), no_update, no_update
        return (f"Approved {candidate} for {product}" + (" as its daily strategy." if daily else ".")
                + portfolio_message(product, daily=daily), approved_note(product),
                night_table(wf) if night else wf_table(wf, candidate))


    @app.callback(
        [Output('bf-wf-approve-note', 'children', allow_duplicate=True),
         Output('bf-wf-approved-note', 'children', allow_duplicate=True),
         Output('bf-wf-container', 'children', allow_duplicate=True)],
        Input('bf-wf-force', 'submit_n_clicks'),
        [State('bf-wf-pick', 'value'), State('bf-local-symbol', 'value'), State('bf-wind-code', 'value'),
         State('bf-data-source', 'value'), State('bf-wf-night', 'value')],
        prevent_initial_call=True,
    )
    def bf_force_approve(_n, candidate, local_symbol, wind_code, source, night):
        product = product_of(wind_code if source == 'wind' else local_symbol)
        if not night or product not in NIGHT_END:
            return "Force approve is for the night + day table: tick 'include night session' first.", no_update, no_update
        wf = load_walkforward(product, DESK_DIR, night=True) if product else None
        if not candidate or wf is None:
            return "Run the night + day walk-forward and pick a candidate first.", no_update, no_update
        try:
            approve(product, candidate, wf, force=True)
        except ValueError as e:
            return str(e), no_update, no_update
        return (f"Force-approved {candidate} for {product} on night + day bars." + portfolio_message(product),
                approved_note(product),
                night_table(wf))


