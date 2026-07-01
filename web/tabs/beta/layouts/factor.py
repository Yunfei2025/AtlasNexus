# -*- coding: utf-8 -*-
"""Candidates (Factor Selection Pool) tab layout."""

from __future__ import annotations

from dash import dcc, html

from ..data import SELECTED_FACTOR_POOL


_LBL = {
    'color': 'var(--text-muted)',
    'fontSize': '9px',
    'fontWeight': '600',
    'textTransform': 'uppercase',
    'letterSpacing': '0.08em',
    'marginBottom': '8px',
    'display': 'block',
}

_CARD_HEADER = {
    'padding': '11px 16px',
    'background': 'var(--surface-panel)',
    'borderBottom': '1px solid var(--border-strong)',
}

_CARD_TITLE = {
    'fontSize': '13px',
    'fontWeight': '600',
    'color': 'var(--text-primary)',
}

_CARD_WRAP = {
    'border': '1px solid var(--border-strong)',
    'borderRadius': '8px',
    'overflow': 'hidden',
}


def _section_label(text):
    return html.Div(text, style=_LBL)


def _short_sep():
    return html.Div(style={
        'width': '1px', 'background': 'var(--border-default)',
        'alignSelf': 'center', 'height': '75%', 'flexShrink': '0',
        'margin': '0 16px',
    })


def build_multiasset_factor_layout():
    """Build the layout for the Candidates (Factor Selection) tab."""
    domiciles = ['CN', 'US', 'EU', 'JP', 'UK']
    domicile_flags = {'CN': '🇨🇳', 'US': '🇺🇸', 'EU': '🇪🇺', 'JP': '🇯🇵', 'UK': '🇬🇧'}
    ir_kinds = ['IRDL', 'IRSL', 'IRCV']

    # ── Selection card: IR grid | FX | Equities | Commodities | Train Params ──
    # One Checklist per domicile (preserves factor-selection-ir-{code} IDs used
    # by the pool-counter and correlation-rank callbacks). Each option's own
    # label carries the IRDL/IRSL/IRCV text so rows can never drift out of
    # sync with a separately-laid-out label column.
    ir_grid = html.Div([
        _section_label("Interest Rates"),
        html.Div([
            html.Div([
                html.Div(domicile_flags[d], style={'fontSize': '16px', 'lineHeight': '1', 'textAlign': 'center'}),
                html.Div(d, style={'fontSize': '9px', 'color': 'var(--text-muted)', 'fontWeight': '500',
                                    'marginTop': '2px', 'textAlign': 'center', 'marginBottom': '6px'}),
                dcc.Checklist(
                    id=f'factor-selection-ir-{d.lower()}',
                    options=[{'label': f' {k}', 'value': f'{k}.{d}'} for k in ir_kinds],
                    value=[v for v in SELECTED_FACTOR_POOL['ir_factors'] if v.endswith(f'.{d}')],
                    inputStyle={'marginRight': '5px'},
                    labelStyle={'display': 'flex', 'alignItems': 'center', 'color': 'var(--text-secondary)',
                                'fontSize': '10px', 'padding': '3px 0', 'whiteSpace': 'nowrap'},
                ),
            ], style={'width': '64px', 'flexShrink': '0'})
            for d in domiciles
        ], style={'display': 'flex', 'gap': '10px'}),
        html.Div(
            "* FX bonds require CNY-hedged.",
            style={
                'fontSize': '8.5px', 'color': 'var(--text-muted)', 'marginTop': '6px',
                'lineHeight': '1.5', 'fontStyle': 'italic',
            }
        ),
    ], style={'flexShrink': '0'})

    # ── Credit grid: CRDL/CRSL/CRCV rows × LGB/MTN/ICP columns ──
    # Same shape as the IR grid above (one Checklist per column, kind options
    # as rows) so factor-selection-cr-{universe} IDs slot into the pool
    # counter / correlation callbacks the same way factor-selection-ir-{d} do.
    credit_universes = ['CDB', 'LGB', 'MTN', 'ICP']
    credit_icons = {'CDB': '🏦', 'LGB': '🏛️', 'MTN': '🏢', 'ICP': '🏭'}
    cr_kinds = ['CRDL', 'CRSL', 'CRCV']
    cr_grid = html.Div([
        _section_label("Credit"),
        html.Div([
            html.Div([
                html.Div(credit_icons[u], style={'fontSize': '16px', 'lineHeight': '1', 'textAlign': 'center'}),
                html.Div(u, style={'fontSize': '9px', 'color': 'var(--text-muted)', 'fontWeight': '500',
                                    'marginTop': '2px', 'textAlign': 'center', 'marginBottom': '6px'}),
                dcc.Checklist(
                    id=f'factor-selection-cr-{u.lower()}',
                    options=[{'label': f' {k}', 'value': f'{k}.{u}'} for k in cr_kinds],
                    value=[v for v in SELECTED_FACTOR_POOL.get('cr_factors', []) if v.endswith(f'.{u}')],
                    inputStyle={'marginRight': '5px'},
                    labelStyle={'display': 'flex', 'alignItems': 'center', 'color': 'var(--text-secondary)',
                                'fontSize': '10px', 'padding': '3px 0', 'whiteSpace': 'nowrap'},
                ),
            ], style={'width': '64px', 'flexShrink': '0'})
            for u in credit_universes
        ], style={'display': 'flex', 'gap': '10px'}),
    ], style={'flexShrink': '0'})

    fx = ['FXDL.USDCNY', 'FXDL.EURCNY', 'FXDL.JPYCNY', 'FXDL.GBPCNY']
    fx_col = html.Div([
        _section_label("FX"),
        dcc.Checklist(
            id='factor-selection-fx',
            options=[{'label': f' {f.replace("FXDL.", "")}', 'value': f} for f in fx],
            value=SELECTED_FACTOR_POOL['fx_factors'],
            labelStyle={'display': 'flex', 'alignItems': 'center', 'color': 'var(--text-primary)',
                        'fontSize': '11px', 'padding': '3px 0'},
            inputStyle={'marginRight': '7px'},
        ),
    ], style={'flexShrink': '0'})

    eq = [('EQDL.IF', 'CSI300'), ('EQDL.IC', 'CSI 500'), ('EQDL.IH', 'SSE 50'), ('EQDL.IM', 'CSI 1000')]
    eq_col = html.Div([
        _section_label("Equities"),
        dcc.Checklist(
            id='factor-selection-eq',
            options=[{'label': f' {k.replace("EQDL.", "")} · {desc}', 'value': k} for k, desc in eq],
            value=SELECTED_FACTOR_POOL['eq_factors'],
            labelStyle={'display': 'flex', 'alignItems': 'center', 'color': 'var(--text-primary)',
                        'fontSize': '11px', 'padding': '3px 0'},
            inputStyle={'marginRight': '7px'},
        ),
    ], style={'flexShrink': '0'})

    cm = [
        ('CMDL.AU', 'Gold'), ('CMDL.AG', 'Silver'), ('CMDL.AL', 'Aluminum'), ('CMDL.CU', 'Copper'),
        ('CMDL.ZN', 'Zinc'), ('CMDL.SC', 'Crude Oil'), ('CMDL.RB', 'Rebar'), ('CMDL.LC', 'Live Hog'),
        ('CMDL.SA', 'Soda Ash'), ('CMDL.JM', 'Coking Coal'), ('CMDL.EC', 'Exch. Code'),
    ]
    cm_col = html.Div([
        _section_label("Commodities"),
        dcc.Checklist(
            id='factor-selection-cmd',
            options=[{'label': f' {k.replace("CMDL.", "")} · {desc}', 'value': k} for k, desc in cm],
            value=SELECTED_FACTOR_POOL['cmd_factors'],
            labelStyle={'display': 'flex', 'alignItems': 'center', 'color': 'var(--text-primary)',
                        'fontSize': '11px', 'padding': '3px 0'},
            inputStyle={'marginRight': '7px'},
            style={'display': 'grid', 'gridTemplateColumns': '94px 94px 94px', 'columnGap': '4px'},
        ),
    ], style={'width': '286px', 'flexShrink': '0'})

    train_params = html.Div([
        _section_label("Train Params"),
        html.Div([
            html.Div([
                html.Div("Months", style={'fontSize': '9px', 'fontWeight': '600',
                                           'color': 'var(--text-muted)', 'marginBottom': '4px'}),
                dcc.Input(id='factor-fm-train', type='number', value=12, min=3,
                          style={'width': '100%', 'background': 'var(--surface-input)',
                                 'border': '1px solid var(--border-default)', 'borderRadius': '4px',
                                 'padding': '5px 4px', 'fontSize': '11px', 'color': 'var(--text-primary)',
                                 'textAlign': 'center', 'boxSizing': 'border-box'}),
            ]),
            html.Div([
                html.Div("IC Thr", style={'fontSize': '9px', 'fontWeight': '600',
                                           'color': 'var(--text-muted)', 'marginBottom': '4px'}),
                dcc.Input(id='factor-fm-ic', type='number', value=0.05, step=0.01, min=0.01,
                          style={'width': '100%', 'background': 'var(--surface-input)',
                                 'border': '1px solid var(--border-default)', 'borderRadius': '4px',
                                 'padding': '5px 4px', 'fontSize': '11px', 'color': 'var(--text-primary)',
                                 'textAlign': 'center', 'boxSizing': 'border-box'}),
            ]),
            html.Div([
                html.Div("Top N", style={'fontSize': '9px', 'fontWeight': '600',
                                          'color': 'var(--text-muted)', 'marginBottom': '4px'}),
                dcc.Input(id='factor-fm-topn', type='number', value=8, min=1,
                          style={'width': '100%', 'background': 'var(--surface-input)',
                                 'border': '1px solid var(--border-default)', 'borderRadius': '4px',
                                 'padding': '5px 4px', 'fontSize': '11px', 'color': 'var(--text-primary)',
                                 'textAlign': 'center', 'boxSizing': 'border-box'}),
            ]),
        ], style={'display': 'grid', 'gridTemplateColumns': '1fr 1fr 1fr', 'gap': '6px'}),
        html.Div([
            html.Button("Train Model", id='factor-train-btn', n_clicks=0,
                        title="Train model using data up to the first day of the current month. "
                              "No recent daily data — reduces overfitting.",
                        style={'flex': '1', 'padding': '7px 0', 'background': 'var(--accent-purple, #7c70d6)',
                               'color': '#fff', 'border': 'none', 'borderRadius': '5px',
                               'fontSize': '11px', 'fontWeight': '700', 'cursor': 'pointer'}),
            html.Button("Predict", id='factor-predict-btn', n_clicks=0,
                        title="Use the latest saved model to refresh the current signal view. "
                              "If parameters changed, retrain first.",
                        style={'flex': '1', 'padding': '7px 0', 'background': 'var(--accent-blue)',
                               'color': '#fff', 'border': 'none', 'borderRadius': '5px',
                               'fontSize': '11px', 'fontWeight': '700', 'cursor': 'pointer'}),
        ], style={'display': 'flex', 'gap': '6px'}),
        html.Div(
            "Train the factor model on data up to the first day of the current month "
            "(no recent daily data — reduces overfitting). Outputs the latest signal "
            "state and top driving indicators.",
            style={'borderTop': '1px solid var(--border-default)', 'paddingTop': '8px',
                   'fontSize': '9px', 'color': 'var(--text-muted)', 'lineHeight': '1.55'},
        ),
    ], style={'width': '270px', 'flexShrink': '0', 'display': 'flex',
              'flexDirection': 'column', 'gap': '10px'})

    selection_card = html.Div([
        html.Div(html.Span("Selection", style=_CARD_TITLE), style=_CARD_HEADER),
        html.Div([
            ir_grid, _short_sep(),
            cr_grid, _short_sep(),
            fx_col, _short_sep(),
            eq_col, _short_sep(),
            cm_col,
            html.Div(style={'width': '1px', 'background': 'var(--border-strong)',
                             'margin': '0 20px', 'flexShrink': '0'}),
            train_params,
        ], style={'padding': '14px 18px', 'display': 'flex', 'alignItems': 'stretch',
                   'flexWrap': 'wrap'}),
    ], style=_CARD_WRAP)

    # ── Left column: signal cards + status, then lowest-correlations table ──
    signal_state_left = html.Div([
        dcc.Loading(
            type='circle',
            color='var(--accent-blue)',
            style={'minHeight': '80px'},
            children=html.Div([
                html.Div(id='factor-train-status',
                         style={'color': 'var(--text-muted)', 'fontSize': '12px', 'marginBottom': '8px'}),
                html.Div(id='factor-signal-container', style={'minHeight': '80px'}),
            ]),
        ),
        dcc.Loading(
            id="loading-correlation-table",
            type="circle",
            color='var(--accent-blue)',
            style={'minHeight': '40px'},
            children=html.Div(id='correlation-table-container',
                               style={'borderTop': '1px solid var(--border-strong)',
                                      'marginTop': '12px', 'paddingTop': '12px'}),
        ),
    ], style={'flex': '1', 'minWidth': '0', 'borderRight': '1px solid var(--border-strong)',
              'padding': '14px 16px'})

    # ── Right column: correlation matrix controls + heatmap ──
    signal_state_right = html.Div([
        html.Div([
            html.Div([
                html.Label("Lookback Period:", style={'fontSize': '11px', 'color': 'var(--text-secondary)',
                                                        'marginRight': '8px'}),
                dcc.Dropdown(
                    id='correlation-period-selector',
                    options=[
                        {'label': '3 Months', 'value': '3M'},
                        {'label': '6 Months', 'value': '6M'},
                        {'label': '1 Year', 'value': '1Y'},
                    ],
                    value='1Y', clearable=False,
                    style={'width': '140px', 'fontSize': '11px'},
                ),
            ], style={'display': 'flex', 'alignItems': 'center', 'gap': '4px'}),
            html.Div([
                html.Label("Top Pairs:", style={'fontSize': '11px', 'color': 'var(--text-secondary)',
                                                 'marginRight': '8px'}),
                dcc.Dropdown(
                    id='correlation-top-pairs-selector',
                    options=[{'label': str(n), 'value': n} for n in (5, 10, 15, 20)],
                    value=10, clearable=False,
                    style={'width': '90px', 'fontSize': '11px'},
                ),
            ], style={'display': 'flex', 'alignItems': 'center', 'gap': '4px'}),
            html.Button(
                "Rank Correlations", id='rank-correlations-btn', n_clicks=0,
                style={'padding': '6px 16px', 'background': 'var(--accent-blue)', 'color': '#fff',
                       'border': 'none', 'borderRadius': '4px', 'fontSize': '11px', 'fontWeight': '700',
                       'cursor': 'pointer', 'marginLeft': 'auto'},
            ),
        ], style={'padding': '10px 16px', 'background': 'rgba(255,255,255,0.02)',
                   'borderBottom': '1px solid var(--border-strong)', 'display': 'flex',
                   'alignItems': 'center', 'gap': '20px', 'flexWrap': 'wrap'}),

        dcc.Store(id='low-corr-factors-store', data=[]),

        dcc.Loading(
            id="loading-correlations",
            type="circle",
            color='var(--accent-blue)',
            style={'minHeight': '60px'},
            children=html.Div(id='correlation-heatmap-container', style={'padding': '14px 16px'}),
        ),

        html.Div(id='diversified-recommendation-container',
                 style={'borderTop': '1px solid var(--border-strong)', 'padding': '14px 16px'}),
    ], style={'flexShrink': '0', 'minWidth': '520px', 'display': 'flex', 'flexDirection': 'column'})

    # ── Combined "Current Signal State" card: signal cards + low-corr table
    #    on the left, correlation matrix on the right (matches guide layout).
    signal_state_card = html.Div([
        html.Div(html.Span("Current Signal State", style=_CARD_TITLE), style=_CARD_HEADER),
        html.Div([signal_state_left, signal_state_right],
                 style={'display': 'flex', 'alignItems': 'flex-start'}),
    ], style=_CARD_WRAP)

    return html.Div([

        dcc.Store(id='factor-selection-store', storage_type='session', data={
            'ir': SELECTED_FACTOR_POOL['ir_factors'],
            'cr': SELECTED_FACTOR_POOL.get('cr_factors', []),
            'fx': SELECTED_FACTOR_POOL['fx_factors'],
            'cmd': SELECTED_FACTOR_POOL['cmd_factors'],
            'eq': SELECTED_FACTOR_POOL['eq_factors'],
        }),
        html.Div([
            html.H1("Beta Candidates", style={'margin': '0 0 3px', 'fontSize': '20px',
                                               'fontWeight': '600', 'color': 'var(--text-primary)'}),
            html.Div("Factor selection, signal state, drivers, and correlations",
                     style={'fontSize': '11px', 'color': 'var(--text-muted)'}),
        ]),

        selection_card,

        signal_state_card,

        html.Div(id='factor-pool-count', style={'display': 'none'}),

    ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '12px', 'padding': '16px', 'margin': '10px'})
