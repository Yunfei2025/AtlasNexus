# -*- coding: utf-8 -*-
"""Bond signals tab callback: refresh bond signal cards on demand."""

from __future__ import annotations

import traceback
from datetime import datetime

import dash
from dash import html
from dash.dependencies import Input, Output

from ..data import THEME, BOND_SIGNAL_LABELS
from ..layouts import _build_bond_signal_cards


def register_bond_callbacks(app):
    """Register Bond signals tab callbacks."""

    @app.callback(
        [Output('beta-bond-signals-container', 'children'),
         Output('beta-bond-status', 'children')],
        [Input('beta-bond-refresh-btn', 'n_clicks'),
         Input('beta-bond-type-selector', 'value')],
        prevent_initial_call=False,
    )
    def refresh_beta_bond_signals(refresh_clicks, bond_type):
        selected_bond_type = bond_type or 'TBond'
        try:
            signal_cards, bond_count = _build_bond_signal_cards(selected_bond_type)
            action = 'Loaded'
            ctx = dash.callback_context
            if ctx.triggered:
                trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
                if trigger_id == 'beta-bond-refresh-btn':
                    action = 'Refreshed'
                elif trigger_id == 'beta-bond-type-selector':
                    action = 'Switched'

            label = BOND_SIGNAL_LABELS.get(selected_bond_type, selected_bond_type)
            if bond_count is None:
                status = f"{action} {label} · no live signal rows available · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            else:
                status = f"{action} {label} · {bond_count} live rows · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            return signal_cards, status
        except Exception as e:
            traceback.print_exc()
            return (
                html.Div(f"Error loading bond signals: {e}", style={'color': THEME['danger'], 'padding': '20px'}),
                f"Load failed · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            )

