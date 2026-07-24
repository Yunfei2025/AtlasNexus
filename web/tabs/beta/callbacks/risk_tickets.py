# -*- coding: utf-8 -*-
"""Summary > Tickets subtab callbacks.

Derives opening tickets from the Beta/Alpha book positions files — there is
no order/fill pipeline in this engine, so a "ticket" here is the opening
trade implied by a position's Open Date/Price/Volume fields.
  FILLED  = open_date + volume both set
  PENDING = volume set but open_date missing (sized, not yet booked)
  OPEN    = neither set (candidate in the book, no trade yet) — excluded
"""

from __future__ import annotations

import os

import dash
from dash import html, dash_table
from dash.dependencies import Input, Output
import pandas as pd

from ..data import THEME
from ._common import (
    _BETA_BOOK_POSITIONS_PARQUET,
    _BETA_BOOK_USER_PARQUET,
    _ALPHA_POSITIONS_PARQUET,
)

_TICKET_STATUS_STYLE = {
    'FILLED':  {'bg': 'rgba(52,211,153,0.12)', 'color': '#34d399'},
    'PENDING': {'bg': 'rgba(224,162,60,0.15)', 'color': THEME['warning']},
}


def _build_tickets() -> list[dict]:
    import os as _os
    tickets: list[dict] = []

    # ── Beta book: positions + user-entered open price/date/volume ────────
    if _os.path.exists(_BETA_BOOK_POSITIONS_PARQUET):
        try:
            bdf = pd.read_parquet(_BETA_BOOK_POSITIONS_PARQUET)
            user_data: dict = {}
            if os.path.exists(_BETA_BOOK_USER_PARQUET):
                udf = pd.read_parquet(_BETA_BOOK_USER_PARQUET)
                for _, r in udf.iterrows():
                    key = (str(r.get('asset_name', '')), str(r.get('instrument', '')))
                    user_data[key] = {
                        'open_price': str(r.get('open_price', '')).strip(),
                        'open_date':  str(r.get('open_date', '')).strip(),
                        'volume':     str(r.get('volume', '')).strip(),
                    }

            for _, row in bdf.iterrows():
                if str(row.get('Asset Type', '')) == 'TOTAL':
                    continue
                asset_name = str(row.get('Asset Name', ''))
                instrument = str(row.get('Instrument', ''))
                saved = user_data.get((asset_name, instrument), {})
                volume_str = saved.get('volume', '')
                open_date_str = saved.get('open_date', '')
                if not volume_str:
                    continue  # no sized trade — nothing to ticket yet
                try:
                    qty = float(volume_str)
                except (TypeError, ValueError):
                    continue
                status = 'FILLED' if open_date_str else 'PENDING'
                try:
                    price = float(saved.get('open_price', '') or 0) or None
                except (TypeError, ValueError):
                    price = None
                tickets.append({
                    'id': f"BETA-{instrument}",
                    'date': open_date_str or '—',
                    'book': 'Beta',
                    'spread': instrument or asset_name,
                    'action': 'BUY',
                    'qty': qty,
                    'price': price,
                    'status': status,
                })
        except Exception:
            pass

    # ── Alpha book: positions + open price/volume/date ─────────────────────
    if _os.path.exists(_ALPHA_POSITIONS_PARQUET):
        try:
            adf = pd.read_parquet(_ALPHA_POSITIONS_PARQUET)
            for _, row in adf.iterrows():
                trade_id = str(row.get('ID', ''))
                if trade_id in ('', 'TOTAL'):
                    continue
                volume_str = str(row.get('volume_mm', '') or '').strip()
                open_date_str = str(row.get('open_date', '') or '').strip()
                if not volume_str:
                    continue
                try:
                    qty = float(volume_str)
                except (TypeError, ValueError):
                    continue
                status = 'FILLED' if open_date_str else 'PENDING'
                try:
                    price = float(row.get('open_price_bp', '') or 0) or None
                except (TypeError, ValueError):
                    price = None
                tickets.append({
                    'id': f"ALPHA-{trade_id}",
                    'date': open_date_str or '—',
                    'book': 'Alpha',
                    'spread': trade_id,
                    'action': str(row.get('direction', 'BUY')).upper() or 'BUY',
                    'qty': qty,
                    'price': price,
                    'status': status,
                })
        except Exception:
            pass

    tickets.sort(key=lambda t: t['date'], reverse=True)
    return tickets


def _tickets_filter_pills(active: str) -> list:
    def _pill_style(is_active: bool):
        style = {
            'padding': '5px 10px', 'fontSize': '10px', 'fontWeight': '600',
            'border': 'none', 'borderRadius': '3px', 'cursor': 'pointer',
            'fontFamily': 'var(--font-mono)', 'transition': 'all 100ms',
        }
        if is_active:
            style.update({'backgroundColor': THEME['accent'], 'color': '#ffffff'})
        else:
            style.update({'backgroundColor': 'transparent', 'color': THEME['text_sub']})
        return style
    return [
        html.Button(label, id=f'tickets-filter-{label}', n_clicks=0, style=_pill_style(active == label))
        for label in ('All', 'FILLED', 'PENDING')
    ]


def register_risk_tickets_callbacks(app):
    """Register Summary > Tickets subtab callbacks."""

    @app.callback(
        Output('tickets-filter-row', 'children'),
        Input('tickets-filter', 'data'),
    )
    def _render_tickets_filter_pills(active):
        return _tickets_filter_pills(active or 'All')

    @app.callback(
        Output('tickets-filter', 'data'),
        [Input('tickets-filter-All', 'n_clicks'),
         Input('tickets-filter-FILLED', 'n_clicks'),
         Input('tickets-filter-PENDING', 'n_clicks')],
        prevent_initial_call=True,
    )
    def _set_tickets_filter(_n_all, _n_filled, _n_pending):
        triggered = dash.ctx.triggered_id
        return {
            'tickets-filter-All': 'All',
            'tickets-filter-FILLED': 'FILLED',
            'tickets-filter-PENDING': 'PENDING',
        }.get(triggered, 'All')

    @app.callback(
        [Output('tickets-kpi-container', 'children'),
         Output('tickets-table-container', 'children'),
         Output('tickets-subtitle', 'children')],
        [Input('an-summary-subtabs', 'value'),
         Input('tickets-filter', 'data'),
         Input('summary-refresh-btn', 'n_clicks')],
        prevent_initial_call=False,
    )
    def update_tickets(tab_value, ticket_filter, _n_refresh):
        if tab_value != 'tickets':
            raise dash.exceptions.PreventUpdate

        all_tickets = _build_tickets()
        filled = [t for t in all_tickets if t['status'] == 'FILLED']
        pending = [t for t in all_tickets if t['status'] == 'PENDING']

        subtitle = f"{len(all_tickets)} opening tickets · derived from Beta + Alpha book positions"

        kpis = [
            ("Total Tickets", str(len(all_tickets)), THEME['text_main']),
            ("Filled", str(len(filled)), THEME['success']),
            ("Pending", str(len(pending)), THEME['warning']),
            ("Fill Rate", f"{(len(filled) / len(all_tickets) * 100):.0f}%" if all_tickets else "—", THEME['accent']),
        ]
        kpi_strip = html.Div([
            html.Div([
                html.Div(label, className='risk-kpi-label'),
                html.Div(value, className='risk-kpi-value', style={'color': color}),
            ], className='risk-kpi-card')
            for label, value, color in kpis
        ], className='risk-kpi-strip')

        ticket_filter = ticket_filter or 'All'
        rows = all_tickets if ticket_filter == 'All' else [t for t in all_tickets if t['status'] == ticket_filter]

        if not rows:
            table = html.Div(
                "No tickets yet — set Open Date and Volume on a Beta/Alpha position to create one.",
                style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'textAlign': 'center', 'padding': '30px'},
            )
            return kpi_strip, table, subtitle

        status_styles = [
            {'if': {'filter_query': f'{{Status}} = "{status}"', 'column_id': 'Status'},
             'backgroundColor': style['bg'], 'color': style['color'], 'fontWeight': 'bold'}
            for status, style in _TICKET_STATUS_STYLE.items()
        ]
        book_styles = [
            {'if': {'filter_query': '{Book} = "Beta"', 'column_id': 'Book'}, 'color': THEME['accent'], 'fontWeight': 'bold'},
            {'if': {'filter_query': '{Book} = "Alpha"', 'column_id': 'Book'}, 'color': THEME['warning'], 'fontWeight': 'bold'},
        ]
        action_styles = [
            {'if': {'filter_query': '{Action} = "BUY"', 'column_id': 'Action'}, 'color': THEME['success']},
            {'if': {'filter_query': '{Action} = "SELL"', 'column_id': 'Action'}, 'color': THEME['danger']},
        ]

        table_data = [{
            'Ticket ID': t['id'],
            'Open Date': t['date'],
            'Book': t['book'],
            'Spread / Instrument': t['spread'],
            'Action': t['action'],
            'Qty (MM)': f"{t['qty']:,.1f}",
            'Price': f"{t['price']:,.4f}" if t['price'] is not None else '—',
            'Status': t['status'],
        } for t in rows]

        table = dash_table.DataTable(
            data=table_data,
            columns=[{'name': c, 'id': c} for c in
                     ['Ticket ID', 'Open Date', 'Book', 'Spread / Instrument', 'Action', 'Qty (MM)', 'Price', 'Status']],
            style_cell={'textAlign': 'center', 'padding': '6px 10px', 'fontSize': '12px',
                        'backgroundColor': THEME['table_row_odd'], 'color': THEME['text_main'], 'border': 'none'},
            style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_main'],
                          'fontWeight': 'bold', 'border': 'none'},
            style_data_conditional=[
                {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                *status_styles, *book_styles, *action_styles,
            ],
            style_table={'overflowX': 'auto'},
            sort_action='native',
            page_size=30,
        )
        return kpi_strip, table, subtitle
