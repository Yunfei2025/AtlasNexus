# -*- coding: utf-8 -*-
"""Bond signals tab layout."""

from __future__ import annotations

from dash import dcc, html

from ..data import BOND_SIGNAL_LABELS


_LBL = {
    'color': 'var(--text-muted)',
    'fontSize': '9px',
    'fontWeight': '600',
    'textTransform': 'uppercase',
    'letterSpacing': '0.06em',
    'marginBottom': '4px',
    'display': 'block',
}


def build_multiasset_bond_layout():
    """Build the layout for the dedicated Bond signals tab."""
    dropdown_options = [
        {'label': f"{BOND_SIGNAL_LABELS.get(bond_type, bond_type)} ({bond_type})", 'value': bond_type}
        for bond_type in ['TBond', 'CBond', 'GBond', 'LBond', 'BBond', 'MNote']
    ]

    return html.Div([
        # ── Header ──────────────────────────────────────────────────────────
        html.Div([
            html.Div([
                html.H4("Bond Trading Signals (Z-Score)", style={
                    'margin': '0 0 4px',
                    'color': 'var(--text-primary)',
                    'fontSize': '20px',
                    'fontWeight': '600',
                }),
                html.Div(
                    "Realtime relative-value signals by maturity bucket. "
                    "Labels are inverted per request: low Z shows SELL and high Z shows BUY.",
                    style={'color': 'var(--text-muted)', 'fontSize': '11px'},
                ),
            ], style={'flex': '1 1 auto', 'minWidth': '280px'}),

            # Bond type selector + Refresh
            html.Div([
                html.Div([
                    html.Div('Bond Type', style=_LBL),
                    dcc.Dropdown(
                        id='beta-bond-type-selector',
                        options=dropdown_options,
                        value='TBond',
                        clearable=False,
                        style={'minWidth': '200px', 'fontSize': '12px'},
                    ),
                ]),
                html.Button(
                    'Refresh Data',
                    id='beta-bond-refresh-btn',
                    n_clicks=0,
                    style={
                        'background': 'var(--accent-blue)',
                        'color': '#fff',
                        'padding': '7px 14px',
                        'border': 'none',
                        'borderRadius': '5px',
                        'cursor': 'pointer',
                        'fontSize': '11px',
                        'fontWeight': '600',
                        'alignSelf': 'flex-end',
                    },
                ),
            ], style={
                'display': 'flex',
                'gap': '10px',
                'alignItems': 'flex-end',
                'flexShrink': '0',
            }),
        ], style={
            'display': 'flex',
            'justifyContent': 'space-between',
            'alignItems': 'flex-start',
            'gap': '12px',
            'flexWrap': 'wrap',
            'marginBottom': '14px',
        }),

        # ── Meta row ────────────────────────────────────────────────────────
        html.Div(id='beta-bond-status', style={
            'color': 'var(--text-muted)',
            'fontSize': '10px',
            'marginBottom': '16px',
        }),

        # ── Signals grid ────────────────────────────────────────────────────
        dcc.Loading(
            id='beta-bond-loading',
            type='circle',
            color='var(--accent-blue)',
            style={'minHeight': '420px'},
            children=html.Div(id='beta-bond-signals-container', style={'minHeight': '420px'}),
        ),
    ], style={'padding': '16px', 'margin': '10px'})
