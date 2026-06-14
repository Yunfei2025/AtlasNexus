# -*- coding: utf-8 -*-
"""Bond signals tab layout."""

from __future__ import annotations

from dash import dcc, html

from ..data import THEME, BOND_SIGNAL_LABELS


def build_multiasset_bond_layout():
    """Build the layout for the dedicated Bond signals tab."""
    dropdown_options = [
        {'label': f"{BOND_SIGNAL_LABELS.get(bond_type, bond_type)} ({bond_type})", 'value': bond_type}
        for bond_type in ['TBond', 'CBond', 'GBond', 'LBond', 'BBond', 'MNote']
    ]

    return html.Div([
        html.Div([
            html.Div([
                html.H4("Bond Trading Signals (Z-Score)", style={
                    'margin': '0 0 6px 0',
                    'color': THEME['text_main'],
                }),
                html.P(
                    "Realtime relative-value signals by maturity bucket. Labels are inverted per request: low Z shows SELL and high Z shows BUY.",
                    style={'margin': '0', 'color': THEME['text_sub'], 'fontSize': '13px'},
                ),
            ], style={'flex': '1 1 auto', 'minWidth': '280px'}),
            html.Div([
                html.Div([
                    html.Label('Bond Type', style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '6px', 'display': 'block'}),
                    dcc.Dropdown(
                        id='beta-bond-type-selector',
                        options=dropdown_options,
                        value='TBond',
                        clearable=False,
                        style={'minWidth': '240px', 'fontSize': '13px'},
                    ),
                ], style={'minWidth': '240px'}),
                html.Button(
                    'Refresh Data',
                    id='beta-bond-refresh-btn',
                    n_clicks=0,
                    style={
                        'backgroundColor': THEME['accent'],
                        'color': 'white',
                        'padding': '10px 16px',
                        'border': 'none',
                        'borderRadius': '8px',
                        'cursor': 'pointer',
                        'fontSize': '13px',
                        'fontWeight': 'bold',
                        'height': '40px',
                        'alignSelf': 'flex-end',
                    },
                ),
            ], style={
                'display': 'flex',
                'gap': '12px',
                'alignItems': 'stretch',
                'flexWrap': 'wrap',
                'justifyContent': 'flex-end',
            }),
        ], style={
            'display': 'flex',
            'justifyContent': 'space-between',
            'gap': '16px',
            'flexWrap': 'wrap',
            'marginBottom': '14px',
        }),
        html.Div(id='beta-bond-status', style={
            'color': THEME['text_sub'],
            'fontSize': '12px',
            'marginBottom': '16px',
        }),
        dcc.Loading(
            id='beta-bond-loading',
            type='circle',
            color=THEME['accent'],
            style={'minHeight': '420px'},
            children=html.Div(id='beta-bond-signals-container', style={'minHeight': '420px'}),
        ),
    ], style={
        'padding': '18px',
        'backgroundColor': THEME['bg_main'],
        'borderRadius': '10px',
    })
