# -*- coding: utf-8 -*-
"""FX Hedge Ticket panel: the forward that neutralises foreign bonds' embedded
currency, netted against the FX sleeve (multiasset.book.fx.fx_hedge_ticket)."""

from __future__ import annotations

from dash import html, dash_table

from ...data import THEME


def build_fx_hedge_ticket(rows):
    """Build the FX hedge ticket panel from the store's ``fx_ticket`` records."""
    if rows is None:
        return html.Div("Run Analysis first to compute portfolio exposures.",
                        style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px'})
    if not rows:
        return html.Div("No foreign bonds or FX sleeves in the current allocation.",
                        style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px'})
    cols = ['Currency', 'Bond FX (CNY m)', 'FX sleeve (CNY m)', 'Net forward (CNY m)', 'Direction']
    return dash_table.DataTable(
        data=rows,
        columns=[{'name': c, 'id': c} for c in cols],
        style_cell={'textAlign': 'center', 'padding': '8px 10px', 'fontSize': '12px',
                    'backgroundColor': THEME['table_row_odd'], 'color': THEME['text_main'], 'border': 'none'},
        style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_main'],
                      'fontWeight': 'bold', 'border': 'none'},
        style_data_conditional=[
            {'if': {'row_index': 'even'}, 'backgroundColor': THEME['table_row_even']},
            {'if': {'filter_query': '{Direction} = "SELL FWD"', 'column_id': 'Direction'},
             'color': THEME.get('danger', '#e74c3c'), 'fontWeight': 'bold'},
            {'if': {'filter_query': '{Direction} = "BUY FWD"', 'column_id': 'Direction'},
             'color': THEME.get('success', '#27ae60'), 'fontWeight': 'bold'},
        ],
        style_table={'overflowX': 'auto'},
    )
