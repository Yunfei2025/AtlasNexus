# -*- coding: utf-8 -*-
"""Summary > Tickets subtab.

One row per instrument of the executable (short-substitution) combined book:
the user types the current holding (MM) and, optionally, an open price; the
table shows the signed target, the trade needed to reach it, the latest close
and the P&L since the open. "Generate Tickets" turns holding -> target into
broker lines such as ``bid 2600006.IB 200MM @ 1.8300``.

Yield-quoted instruments only (cash bonds, FR007 swaps, curve labels): P&L is
holding x duration x (open yield - close yield), so a long gains when yield falls.

Execution model: the order is always To Trade = Target - Holding, recomputed from what is actually held, so an
unfilled remainder carries over by itself. The limit is a WORST price: a buy limit is a yield no lower than the
close (price no higher), a sell limit a yield no higher than the close. Max/day (MM, typed by judgement) caps
today's size for thin bonds; the rest shows as Left. Age / Filled % show how long and how far a trade has run.
"""

from __future__ import annotations

import json
import math
import re

import dash
from dash import dash_table
from dash.dash_table.Format import Format, Scheme, Sign
from dash.dependencies import Input, Output, State
import numpy as np
import pandas as pd

from settings.paths import DIR_INPUT
from web.tabs.beta.data import THEME

_STATE_FILE = DIR_INPUT / 'ticket_book.json'   # {code: {holding, open_px, ticket_px, override}}
_HISTORY_FILE = DIR_INPUT / 'ticket_holdings_history.pkl'   # one snapshot per day, latest edit wins
_TOTAL = 'TOTAL'
_MIN_TRADE_MM = 0.05
_TOL_BP = 0.0   # slippage tolerance on the limit (bp of yield); 0 = no worse than the close


def _fmt(precision: int, signed: bool = False) -> Format:
    f = Format(precision=precision, scheme=Scheme.fixed).group(True)
    return f.sign(Sign.positive) if signed else f


_COLUMNS = [
    {'name': 'Instrument', 'id': 'Instrument'},
    # Executable instrument the user actually trades, e.g. a more liquid bond; defaults to Instrument.
    {'name': 'Override', 'id': 'Override', 'type': 'text', 'editable': True},
    {'name': 'Holding (MM)', 'id': 'Holding', 'type': 'numeric', 'editable': True, 'format': _fmt(1, True)},
    {'name': 'Target (MM)', 'id': 'Target', 'type': 'numeric', 'format': _fmt(1, True)},
    {'name': 'To Trade (MM)', 'id': 'Trade', 'type': 'numeric', 'format': _fmt(1, True)},
    # Liquidity cap per day, typed by judgement; blank = no cap.
    {'name': 'Max/day (MM)', 'id': 'MaxDay', 'type': 'numeric', 'editable': True, 'format': _fmt(1)},
    {'name': 'Today (MM)', 'id': 'Today', 'type': 'numeric', 'format': _fmt(1, True)},
    {'name': 'Left (MM)', 'id': 'Left', 'type': 'numeric', 'format': _fmt(1, True)},
    {'name': 'Side', 'id': 'Side', 'type': 'text'},
    {'name': 'Limit, worst (%)', 'id': 'TicketPx', 'type': 'numeric', 'editable': True, 'format': _fmt(4)},
    {'name': 'Age (bd)', 'id': 'Age', 'type': 'numeric', 'format': _fmt(0)},
    {'name': 'Filled (%)', 'id': 'Filled', 'type': 'numeric', 'format': _fmt(0)},
    {'name': 'Open Px (%)', 'id': 'OpenPx', 'type': 'numeric', 'editable': True, 'format': _fmt(4)},
    {'name': 'Close Px (%)', 'id': 'Close', 'type': 'numeric', 'format': _fmt(4)},
    {'name': 'PnL (MM)', 'id': 'Pnl', 'type': 'numeric', 'format': _fmt(4, True)},
]


def build_tickets_table() -> dash_table.DataTable:
    """The (initially empty) table; filled by update_tickets."""
    return dash_table.DataTable(
        id='tickets-table', data=[], columns=_COLUMNS,
        style_cell={'textAlign': 'right', 'padding': '6px 10px', 'fontSize': '12px',
                    'backgroundColor': THEME['table_row_odd'], 'color': THEME['text_main'], 'border': 'none'},
        style_cell_conditional=[{'if': {'column_id': 'Instrument'}, 'textAlign': 'left', 'fontWeight': '600'},
                                {'if': {'column_id': 'Override'}, 'textAlign': 'left'}],
        style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_main'],
                      'fontWeight': 'bold', 'border': 'none'},
        style_data_conditional=[
            {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
            *[{'if': {'column_id': c}, 'backgroundColor': 'rgba(99,179,237,0.08)'}
              for c in ('Override', 'Holding', 'MaxDay', 'OpenPx', 'TicketPx')],
            *[c for col in ('Trade', 'Today') for c in (
                {'if': {'filter_query': f'{{{col}}} > 0', 'column_id': col}, 'color': THEME['success'], 'fontWeight': 'bold'},
                {'if': {'filter_query': f'{{{col}}} < 0', 'column_id': col}, 'color': THEME['danger'], 'fontWeight': 'bold'})],
            {'if': {'filter_query': '{Pnl} > 0', 'column_id': 'Pnl'}, 'color': THEME['success']},
            {'if': {'filter_query': '{Pnl} < 0', 'column_id': 'Pnl'}, 'color': THEME['danger']},
            {'if': {'filter_query': f'{{Instrument}} = "{_TOTAL}"'}, 'backgroundColor': THEME['table_header'],
             'fontWeight': 'bold', 'borderTop': f"1px solid {THEME['accent']}"},
        ],
        style_table={'overflowX': 'auto'},
        page_size=100,
    )


def _load_state() -> dict:
    try:
        return json.loads(_STATE_FILE.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding='utf-8')


def _save_history(rows: list[dict]) -> None:
    """Replace today's holdings snapshot in the history pickle (long format, one row per held instrument)."""
    today = pd.Timestamp.today().normalize()
    snap = pd.DataFrame([{
        'date': today, 'instrument': r['Instrument'], 'holding_mm': _num(r.get('Holding')) or 0.0,
        'target_mm': _num(r.get('Target')), 'open_px': _num(r.get('OpenPx')), 'close_px': _num(r.get('Close')),
    } for r in rows if r.get('Instrument') != _TOTAL
        and (_num(r.get('Holding')) is not None or abs(_num(r.get('Target')) or 0.0) >= _MIN_TRADE_MM)])
    try:
        hist = pd.read_pickle(_HISTORY_FILE)
        hist = hist[hist['date'] != today]
    except Exception:
        hist = pd.DataFrame()
    hist = pd.concat([hist, snap], ignore_index=True)
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    hist.to_pickle(_HISTORY_FILE)


def _num(v):
    try:
        f = float(v)
        return f if pd.notna(f) else None
    except (TypeError, ValueError):
        return None


def _verb(code: str, trade: float) -> str:
    """Broker verb for a signed trade: swaps receive/pay fixed, everything else bid/offer."""
    if str(code).upper().endswith('.IR'):
        return 'receive' if trade > 0 else 'pay'        # swap: buy = receive fixed
    return 'bid' if trade > 0 else 'offer'


def _run_stats(code: str, hold: float, tgt: float, hist: pd.DataFrame) -> tuple:
    """(age in business days, filled %) of the trade now open on ``code``; (None, None) when nothing to trade.

    The open run is the unbroken stretch of snapshots (plus today's live state) with |target - holding| above
    the minimum. Age counts business days since the run's first snapshot. Filled is the move in holding since
    the run began, as a share of the distance the run had to cover: (hold - base) / (target - base), where base
    is the holding at the last snapshot before the run (the earliest known holding when the run is the whole history).
    """
    if abs(tgt - hold) < _MIN_TRADE_MM:
        return None, None
    today = pd.Timestamp.today().normalize()
    h = hist[(hist['instrument'] == code) & (hist['date'] < today)].sort_values('date') if len(hist) else hist
    pts = [(r.date, r.holding_mm, r.target_mm) for r in h.itertuples()]
    start = len(pts)
    while start > 0 and abs((pts[start - 1][2] or 0.0) - pts[start - 1][1]) >= _MIN_TRADE_MM:
        start -= 1
    if start < len(pts):
        first_date = pts[start][0]
        base = pts[start - 1][1] if start > 0 else pts[start][1]
    else:
        first_date, base = today, hold
    age = int(np.busday_count(first_date.date(), today.date()))
    span = tgt - base
    filled = max(0.0, min(100.0, 100.0 * (hold - base) / span)) if abs(span) >= _MIN_TRADE_MM else None
    return age, filled


def _derive(rows: list[dict]) -> list[dict]:
    """Fill Trade / Today / Left / Side / Limit / Age / Filled / Pnl and append the TOTAL row."""
    try:
        hist = pd.read_pickle(_HISTORY_FILE)
    except Exception:
        hist = pd.DataFrame()
    out, total = [], 0.0
    for r in rows:
        if r.get('Instrument') == _TOTAL:
            continue
        hold, tgt = _num(r.get('Holding')), _num(r.get('Target')) or 0.0
        op, close, dur = _num(r.get('OpenPx')), _num(r.get('Close')), _num(r.get('_dur'))
        r['Trade'] = round(tgt - (hold or 0.0), 4)
        cap = _num(r.get('MaxDay'))
        trade = r['Trade']
        live = abs(trade) >= _MIN_TRADE_MM
        r['Today'] = round(math.copysign(min(abs(trade), cap), trade), 4) if live and cap and cap > 0 else trade
        r['Left'] = round(trade - r['Today'], 4)
        r['Side'] = _verb(r['Instrument'], trade).upper() if live else ''
        r['Age'], r['Filled'] = _run_stats(r['Instrument'], hold or 0.0, tgt, hist)
        r['Pnl'] = (round(hold * dur * (op - close) / 100.0, 4)
                    if None not in (hold, dur, op, close) else None)
        if r['Pnl'] is not None:
            total += r['Pnl']
        if _num(r.get('TicketPx')) is None and close is not None:
            # worst acceptable yield: a buyer accepts a lower yield, a seller a higher one, by _TOL_BP
            r['TicketPx'] = round(close - math.copysign(_TOL_BP / 100.0, trade), 6) if live else close
        elif _num(r.get('TicketPx')) is None:
            r['TicketPx'] = close
        r['Override'] = str(r.get('Override') or '').strip() or r['Instrument']   # blank -> back to default
        out.append(r)
    out.append({'Instrument': _TOTAL, 'Pnl': round(total, 4)})
    return out


def _tradable_codes(net_pos: dict, otr_cgb: dict) -> dict:
    """Re-key the Beta book's CGB-nY curve labels to the on-the-run bond for that tenor
    (the sticky most-liquid pick Beta Portfolio uses), merging with any Alpha position
    in the same bond. Labels with no bond (LGB3Y, ...) are left as they are."""
    out: dict = {}
    for code, e in net_pos.items():
        m = re.fullmatch(r'CGB-(\d+Y)', str(code), re.IGNORECASE)
        bond = otr_cgb.get(m.group(1).upper()) if m else None
        t = out.setdefault(bond if bond and bond != '—' else code,
                           {'Beta': 0.0, 'Alpha': 0.0, 'BetaDV01': 0.0, 'AlphaDV01': 0.0})
        for k in t:
            t[k] += e.get(k, 0.0)
    return out


def _build_rows() -> list[dict]:
    from .dashboard import build_risk_positions
    from .short_substitution import build_short_substitutions, executable_positions
    from .ticket_prices import latest_marks

    pos = build_risk_positions()
    net_pos = _tradable_codes(pos['net_pos'], pos['otr_cgb'])
    exe = executable_positions(net_pos, build_short_substitutions(net_pos, pos['otr_cgb']))
    state = _load_state()
    # Held instruments stay listed even once their target is 0, so they can be closed out.
    codes = [c for c, e in exe.items() if abs(e['net']) > 1e-6 or abs(e['strat']) > 1e-6
             or _num(state.get(c, {}).get('holding'))]
    marks = latest_marks({c: (abs(exe[c]['dv01']) / abs(exe[c]['net']) if c in exe and abs(exe[c]['net']) > 1e-6
                              else None) for c in codes})
    rows = []
    for c in sorted(codes, key=str.upper):
        st = state.get(c, {})
        rows.append({
            'Instrument': c,
            'Override': st.get('override') or c,
            'Holding': _num(st.get('holding')),
            'Target': round(exe[c]['net'], 4) if c in exe else 0.0,
            'MaxDay': _num(st.get('max_day')),
            'OpenPx': _num(st.get('open_px')),
            'Close': marks[c]['close'],
            'TicketPx': _num(st.get('ticket_px')),
            '_dur': marks[c]['dur'],
        })
    return _derive(rows)


def _trade_lines(rows: list[dict]) -> list[str]:
    lines = []
    for r in rows:
        code = r.get('Instrument')
        trade = _num(r.get('Today'))     # today's slice: the delta capped by Max/day
        if code == _TOTAL or trade is None or abs(trade) < _MIN_TRADE_MM:
            continue
        code = str(r.get('Override') or '').strip() or code   # trade the override when the user set one
        px = _num(r.get('TicketPx'))
        verb = _verb(code, trade)
        lines.append(f"{verb} {code} {abs(trade):g}MM @ {f'{px:.4f}' if px is not None else 'N/A'}")
    return lines


def register_risk_tickets_callbacks(app):
    """Register Summary > Tickets subtab callbacks."""

    @app.callback(
        [Output('tickets-table', 'data'),
         Output('tickets-subtitle', 'children')],
        [Input('an-summary-subtabs', 'value'),
         Input('summary-refresh-btn', 'n_clicks')],
        prevent_initial_call=False,
    )
    def update_tickets(tab_value, _n_refresh):
        if tab_value != 'tickets':
            raise dash.exceptions.PreventUpdate
        rows = _build_rows()
        n = len(rows) - 1
        return rows, (f"{n} instruments · executable (substitute) mixed book · "
                      "yields in %, P&L = holding x duration x (open - close)")

    @app.callback(
        Output('tickets-table', 'data', allow_duplicate=True),
        Input('tickets-table', 'data_timestamp'),
        State('tickets-table', 'data'),
        prevent_initial_call=True,
    )
    def save_edits(_ts, rows):
        if not rows:
            raise dash.exceptions.PreventUpdate
        state = _load_state()
        for r in rows:
            code = r.get('Instrument')
            if code in (None, _TOTAL):
                continue
            close, tpx = _num(r.get('Close')), _num(r.get('TicketPx'))
            ov = str(r.get('Override') or '').strip()
            entry = {'holding': _num(r.get('Holding')), 'open_px': _num(r.get('OpenPx')),
                     'override': ov if ov and ov != code else None,   # only a real override is kept
                     'max_day': _num(r.get('MaxDay')),
                     # only a price the user changed is kept; otherwise it follows the latest close
                     'ticket_px': tpx if tpx is not None and (close is None or abs(tpx - close) > 1e-9) else None}
            if any(v is not None for v in entry.values()):
                state[code] = entry
            else:
                state.pop(code, None)
        _save_state(state)
        _save_history(rows)
        return _derive(rows)

    @app.callback(
        [Output('tickets-output', 'value'),
         Output('tickets-gen-status', 'children')],
        Input('tickets-generate-btn', 'n_clicks'),
        State('tickets-table', 'data'),
        prevent_initial_call=True,
    )
    def generate_tickets(n_clicks, rows):
        if not n_clicks:
            raise dash.exceptions.PreventUpdate
        lines = _trade_lines(rows or [])
        if not lines:
            return '', 'Nothing to trade: holdings already match targets.'
        left = sum(1 for r in rows if (_num(r.get('Left')) or 0.0) and abs(_num(r.get('Left'))) >= _MIN_TRADE_MM)
        return '\n'.join(lines), f"{len(lines)} tickets" + (f" · {left} capped by Max/day, remainder carries over" if left else "")
