# -*- coding: utf-8 -*-
"""IRDL Hedge Overlay panel: builds the hedge-ticket table from
compute_irdl_hedge results."""

from __future__ import annotations

from dash import html, dash_table

from multiasset.main import compute_irdl_hedge

from ...data import THEME


def build_irdl_hedge_ticket(factor_risk, hedge_ratio_pct, instrument, irs_maturity,
                             dv01_values, dv01_ids, capital_value, capital_unit):
    """Build the IRDL hedge ticket panel. Returns an html.Div."""
    if factor_risk.empty:
        return html.Div(
            "Run Analysis first to compute portfolio exposures.",
            style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px'},
        )
    if 'Net Exposure' not in factor_risk.columns:
        return html.Div(
            "Net Exposure column not available — re-run Analysis.",
            style={'color': THEME['warning'], 'fontSize': '12px'},
        )

    try:
        # Build capital
        multiplier = 1e9 if capital_unit == 'billion' else 1e6
        total_capital = float(capital_value or 10) * multiplier

        # Build DV01 overrides dict
        dv01_overrides = {}
        for val, id_dict in zip(dv01_values or [], dv01_ids or []):
            cty = id_dict['index']
            if val is not None:
                try:
                    dv01_overrides[cty] = float(val)
                except (ValueError, TypeError):
                    pass

        hedge_ratio = (hedge_ratio_pct or 0) / 100.0

        tickets = compute_irdl_hedge(
            factor_risk_records=factor_risk.to_dict('records'),
            total_capital=total_capital,
            hedge_ratio=hedge_ratio,
            instrument=instrument or 'futures',
            dv01_overrides=dv01_overrides if dv01_overrides else None,
            irs_maturity=irs_maturity or '10Y',
        )

        if not tickets:
            return html.Div(
                "No IRDL factors found in current allocation.",
                style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px'},
            )

        _dir_color = {
            'SHORT':     THEME.get('danger', '#e74c3c'),
            'PAY FIXED': THEME.get('danger', '#e74c3c'),
            'LONG':      THEME.get('success', '#27ae60'),
            'RCV FIXED': THEME.get('success', '#27ae60'),
        }

        return html.Div([
            html.Div(
                f"Hedge ratio: {hedge_ratio_pct}%  ·  Instrument: "
                f"{'Bond Futures' if instrument == 'futures' else 'Pay-fixed IRS'}  ·  "
                f"Capital: {float(capital_value or 10):,.0f} {capital_unit}",
                style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '8px'},
            ),
            dash_table.DataTable(
                data=tickets,
                columns=[
                    {'name': 'Country',            'id': 'Country'},
                    {'name': 'Net IRDL Exp (DY)',  'id': 'Net IRDL Exp (DY)'},
                    {'name': 'Port DV01 (CNY/bp)', 'id': 'Port DV01 (CNY/bp)'},
                    {'name': 'Hedge DV01 (CNY/bp)', 'id': 'Hedge DV01 (CNY/bp)'},
                    {'name': 'Quantity',           'id': 'Quantity'},
                    {'name': 'Direction',          'id': 'Direction'},
                    {'name': 'Instrument',         'id': 'Instrument'},
                ],
                style_cell={
                    'textAlign': 'center', 'padding': '8px 10px',
                    'fontSize': '12px',
                    'backgroundColor': THEME['table_row_odd'],
                    'color': THEME['text_main'], 'border': 'none',
                },
                style_header={
                    'backgroundColor': THEME['table_header'],
                    'color': THEME['text_main'],
                    'fontWeight': 'bold', 'border': 'none',
                },
                style_data_conditional=[
                    {'if': {'row_index': 'even'}, 'backgroundColor': THEME['table_row_even']},
                    *[
                        {'if': {'filter_query': f'{{Direction}} = "{d}"', 'column_id': 'Direction'},
                         'color': c, 'fontWeight': 'bold'}
                        for d, c in _dir_color.items()
                    ],
                    {'if': {'filter_query': '{Net IRDL Exp (DY)} > 0', 'column_id': 'Net IRDL Exp (DY)'},
                     'color': THEME.get('success', '#27ae60')},
                    {'if': {'filter_query': '{Net IRDL Exp (DY)} < 0', 'column_id': 'Net IRDL Exp (DY)'},
                     'color': THEME.get('danger', '#e74c3c')},
                ],
                style_table={'overflowX': 'auto'},
            ),
        ])

    except Exception as exc:
        return html.Div(
            f"Error computing hedge: {exc}",
            style={'color': THEME['danger'], 'fontSize': '12px'},
        )
