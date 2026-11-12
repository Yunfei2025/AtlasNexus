# -*- coding: utf-8 -*-
"""Summary > Tickets subtab.

One row per instrument of the executable (short-substitution) combined book:
the user types the current holding (MM) and, optionally, an open price; the
table shows the signed target, the trade needed to reach it, the latest close
and the P&L since the open. "Generate Tickets" turns holding -> target into
broker lines such as ``bid 2600006.IB 200MM @ 1.8300``.

Yield-quoted instruments only (cash bonds, FR007 swaps, curve labels): P&L is
holding x duration x (open yield - close yield), so a long gains when yield falls.
"""

from __future__ import annotations

import json
import re

import dash
from dash import dash_table
from dash.dash_table.Format import Format, Scheme, Sign
from dash.dependencies import Input, Output, State
import pandas as pd

from settings.paths import DIR_INPUT
from web.tabs.beta.data import THEME

_STATE_FILE = DIR_INPUT / 'ticket_book.json'   # {code: {holding, open_px, ticket_px, override}}
_HISTORY_FILE = DIR_INPUT / 'ticket_holdings_history.pkl'   # one snapshot per day, latest edit wins
_TOTAL = 'TOTAL'
_MIN_TRADE_MM = 0.05


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
    {'name': 'Open Px (%)', 'id': 'OpenPx', 'type': 'numeric', 'editable': True, 'format': _fmt(4)},
    {'name': 'Close Px (%)', 'id': 'Close', 'type': 'numeric', 'format': _fmt(4)},
    {'name': 'PnL (MM)', 'id': 'Pnl', 'type': 'numeric', 'format': _fmt(4, True)},
    {'name': 'Ticket Px (%)', 'id': 'TicketPx', 'type': 'numeric', 'editable': True, 'format': _fmt(4)},
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
              for c in ('Override', 'Holding', 'OpenPx', 'TicketPx')],
            {'if': {'filter_query': '{Trade} > 0', 'column_id': 'Trade'}, 'color': THEME['success'], 'fontWeight': 'bold'},
            {'if': {'filter_query': '{Trade} < 0', 'column_id': 'Trade'}, 'color': THEME['danger'], 'fontWeight': 'bold'},
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
        'date': today, 'instrument': r['Instrument'], 'holding_mm': _num(r.get('Holding')),
        'target_mm': _num(r.get('Target')), 'open_px': _num(r.get('OpenPx')), 'close_px': _num(r.get('Close')),
    } for r in rows if r.get('Instrument') != _TOTAL and _num(r.get('Holding')) is not None])
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


def _derive(rows: list[dict]) -> list[dict]:
    """Fill Trade / Pnl, default Ticket Px to the close, and append the TOTAL row."""
    out, total = [], 0.0
    for r in rows:
        if r.get('Instrument') == _TOTAL:
            continue
        hold, tgt = _num(r.get('Holding')), _num(r.get('Target')) or 0.0
        op, close, dur = _num(r.get('OpenPx')), _num(r.get('Close')), _num(r.get('_dur'))
        r['Trade'] = round(tgt - (hold or 0.0), 4)
        r['Pnl'] = (round(hold * dur * (op - close) / 100.0, 4)
                    if None not in (hold, dur, op, close) else None)
        if r['Pnl'] is not None:
            total += r['Pnl']
        if _num(r.get('TicketPx')) is None:
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
        trade = _num(r.get('Trade'))
        if code == _TOTAL or trade is None or abs(trade) < _MIN_TRADE_MM:
            continue
        code = str(r.get('Override') or '').strip() or code   # trade the override when the user set one
        px = _num(r.get('TicketPx'))
        if str(code).upper().endswith('.IR'):
            verb = 'receive' if trade > 0 else 'pay'        # swap: buy = receive fixed
        else:
            verb = 'bid' if trade > 0 else 'offer'
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
        return '\n'.join(lines), f"{len(lines)} tickets"
