# -*- coding: utf-8 -*-
"""
All layout builder functions for the Multi-Asset Dashboard tabs.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import dash
from dash import dcc, html, dash_table
import plotly.graph_objects as go
import pandas as pd
import dash_bootstrap_components as dbc

from .data import (
    THEME,
    BOND_SIGNAL_FILE_MAP,
    BOND_SIGNAL_LABELS,
    BOND_SIGNAL_BUCKETS,
    FACTOR_TO_ASSET_MAP,
    ALLOCATION_RESULTS,
    SELECTED_FACTOR_POOL,
    FUTURES_AVAILABLE,
)

# Conditionally import futures discovery helper
if FUTURES_AVAILABLE:
    from futures.backtest.data_loader import discover_pkl_files

from multiasset.storage import load_last_asset_pool
from settings.paths import DIR_INPUT


# ---------------------------------------------------------------------------
# Bond signal display helpers (called only by layouts / bond callback)
# ---------------------------------------------------------------------------

def _load_bond_signal_frame(bond_type: str):
    """Load realtime bond spread data for the requested bond type."""
    file_name = BOND_SIGNAL_FILE_MAP.get(bond_type, f'{bond_type}-spdsrt.pkl')
    signal_file = os.path.join(DIR_INPUT, file_name)

    if not os.path.exists(signal_file):
        return None, f"No realtime file found for {bond_type} ({file_name})."

    data = pd.read_pickle(signal_file)
    source_key = 'table'

    if isinstance(data, dict):
        if isinstance(data.get('BondCurve'), pd.DataFrame):
            data = data['BondCurve']
            source_key = 'BondCurve'
        else:
            first_frame = next((value for value in data.values() if isinstance(value, pd.DataFrame)), None)
            if first_frame is None:
                return None, f"{file_name} does not contain a tabular signal payload."
            data = first_frame

    if not isinstance(data, pd.DataFrame) or data.empty:
        return None, f"{file_name} does not contain usable bond signals."

    frame = data.copy()
    frame['Code'] = frame.index.astype(str)
    return frame, source_key


def _resolve_bond_signal_columns(frame: pd.DataFrame):
    def _normalize_column_name(col) -> str:
        return ''.join(ch for ch in str(col).lower() if ch.isalnum())

    normalized = {
        _normalize_column_name(col): col
        for col in frame.columns
    }
    col_ttm = normalized.get('ttm') or normalized.get('term') or normalized.get('ptmyear')
    col_z = normalized.get('zscore') or normalized.get('z')
    col_id = normalized.get('code') or normalized.get('windcode') or 'Code'
    col_name = normalized.get('name') or normalized.get('windcode') or col_id
    col_mid = (
        normalized.get('mid')
        or normalized.get('midprice')
        or normalized.get('price')
        or normalized.get('lastprice')
        or normalized.get('close')
        or normalized.get('cleanprice')
        or normalized.get('dirtyprice')
    )
    col_bid = (
        normalized.get('bid')
        or normalized.get('bidprice')
        or normalized.get('rtbid1')
        or normalized.get('rtbid')
    )
    col_ofr = (
        normalized.get('ofr')
        or normalized.get('offer')
        or normalized.get('ask')
        or normalized.get('askprice')
        or normalized.get('rtask1')
        or normalized.get('rtask')
    )
    col_carry_3m = normalized.get('carry3mbp') or normalized.get('carry3m')
    col_roll_3m = normalized.get('roll3mbp') or normalized.get('roll3m')
    col_cr3m = (
        normalized.get('cr3m')
        or normalized.get('cr3mbp')
        or normalized.get('carryroll3m')
        or normalized.get('carryroll3mbp')
        or normalized.get('carryroll')
        or normalized.get('carry')
        or normalized.get('bondcarry')
    )
    col_carry = (
        normalized.get('cr3mbp')
        or normalized.get('carryroll3m')
        or normalized.get('carryroll3mbp')
        or normalized.get('carryroll')
        or normalized.get('carry')
        or normalized.get('bondcarry')
    )

    required = all(col in frame.columns for col in [col_ttm, col_z, col_id] if col is not None)
    if not required or col_ttm is None or col_z is None:
        return None

    return {
        'ttm': col_ttm,
        'z': col_z,
        'id': col_id,
        'name': col_name,
        'mid': col_mid,
        'bid': col_bid,
        'ofr': col_ofr,
        'cr3m': col_cr3m,
        'carry_3m': col_carry_3m,
        'roll_3m': col_roll_3m,
        'carry': col_carry,
    }


def _build_bond_signal_mini_table(df: pd.DataFrame, columns: dict, title: str, color: str):
    if df.empty:
        return html.Div(
            "No signals in this bucket.",
            style={
                'color': THEME['text_sub'],
                'fontSize': '12px',
                'padding': '18px 12px',
                'textAlign': 'center',
                'backgroundColor': THEME['bg_input'],
                'borderRadius': '8px',
                'border': f'1px solid {THEME["table_header"]}',
            },
        )

    col_id = columns['id']
    col_name = columns['name']
    col_ttm = columns['ttm']
    col_z = columns['z']
    col_mid = columns.get('mid')
    col_cr3m = columns.get('cr3m')

    target_cols = [col_id]
    if col_name != col_id:
        target_cols.append(col_name)
    if col_mid and col_mid in df.columns:
        target_cols.append(col_mid)
    if col_cr3m and col_cr3m in df.columns:
        target_cols.append(col_cr3m)
    target_cols.extend([col_ttm, col_z])
    valid_cols = [col for col in target_cols if col in df.columns]

    display_cols_map = {
        col_id: 'Code',
        col_name: 'Name',
        col_mid: 'Mid Price',
        col_cr3m: 'C+R,3m',
        col_ttm: 'TTM',
        col_z: 'Z-Score',
    }

    records = []
    for record in df[valid_cols].to_dict('records'):
        formatted = {}
        for col in valid_cols:
            value = record.get(col)
            if col == col_ttm and pd.notna(value):
                value = f"{float(value):.2f}Y"
            elif col == col_mid and pd.notna(value):
                value = f"{float(value):.3f}"
            elif col == col_cr3m and pd.notna(value):
                value = f"{float(value):.2f}"
            elif col == col_z and pd.notna(value):
                value = round(float(value), 4)   # keep numeric for bar gradient
            formatted[display_cols_map.get(col, col)] = value
        records.append(formatted)

    # ── Z-Score bar styles (center-anchored, green right / red left) ──────────
    z_vals = pd.to_numeric(df[col_z], errors='coerce')
    _pos_clr = "rgba(39,174,96,0.55)"
    _neg_clr = "rgba(231,76,60,0.55)"
    _max_abs = max(abs(z_vals.dropna()).max() if not z_vals.dropna().empty else 1.0, 0.1)
    z_bar_styles: list[dict] = []
    for _i, _v in enumerate(z_vals):
        try:
            _v = float(_v)
        except (TypeError, ValueError):
            continue
        _norm = max(-1.0, min(1.0, _v / _max_abs))
        _half = abs(_norm) * 50
        if _norm >= 0:
            _grad = (f"transparent 50%, "
                     f"{_pos_clr} 50%, {_pos_clr} {50 + _half:.1f}%, "
                     f"transparent {50 + _half:.1f}%")
        else:
            _grad = (f"transparent {50 - _half:.1f}%, "
                     f"{_neg_clr} {50 - _half:.1f}%, {_neg_clr} 50%, "
                     f"transparent 50%")
        z_bar_styles.append({
            "if": {"row_index": _i, "column_id": "Z-Score"},
            "background": f"linear-gradient(to right, {_grad})",
        })

    return html.Div([
        html.Div(title, style={
            'color': color,
            'fontSize': '12px',
            'fontWeight': '700',
            'letterSpacing': '0.04em',
            'marginBottom': '8px',
            'textTransform': 'uppercase',
        }),
        dash_table.DataTable(
            data=records,
            columns=[
                (
                    {'name': display_cols_map.get(col, col), 'id': display_cols_map.get(col, col),
                     'type': 'numeric', 'format': {'specifier': '.2f'}}
                    if col == col_z else
                    {'name': display_cols_map.get(col, col), 'id': display_cols_map.get(col, col)}
                )
                for col in valid_cols
            ],
            style_cell={
                'textAlign': 'center',
                'padding': '7px 8px',
                'backgroundColor': THEME['bg_input'],
                'color': THEME['text_main'],
                'border': 'none',
                'fontSize': '11px',
                'whiteSpace': 'normal',
                'height': 'auto',
            },
            style_header={
                'backgroundColor': THEME['table_header'],
                'fontWeight': 'bold',
                'color': color,
                'border': 'none',
            },
            style_data_conditional=[
                {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['table_row_even']},
                *z_bar_styles,
            ],
            style_table={'overflowX': 'auto'},
        ),
    ])


def _build_bond_signal_cards(bond_type: str):
    frame, source_key = _load_bond_signal_frame(bond_type)
    if frame is None:
        empty_state = html.Div([
            html.H5(
                f"{BOND_SIGNAL_LABELS.get(bond_type, bond_type)} signals unavailable",
                style={'color': THEME['warning'], 'marginBottom': '8px'},
            ),
            html.P(
                source_key,
                style={'color': THEME['text_sub'], 'margin': '0', 'fontSize': '13px'},
            ),
        ], style={
            'padding': '28px',
            'backgroundColor': THEME['bg_card'],
            'borderRadius': '12px',
            'border': f'1px dashed {THEME["table_header"]}',
            'textAlign': 'center',
        })
        return empty_state, None

    columns = _resolve_bond_signal_columns(frame)
    if columns is None:
        return html.Div(
            "Missing required columns for bond signals (ttm, z-score, code).",
            style={'color': THEME['danger'], 'padding': '20px', 'textAlign': 'center'},
        ), None

    col_ttm = columns['ttm']
    col_z = columns['z']
    col_mid = columns.get('mid')
    col_bid = columns.get('bid')
    col_ofr = columns.get('ofr')
    col_cr3m = columns.get('cr3m')
    col_carry_3m = columns.get('carry_3m')
    col_roll_3m = columns.get('roll_3m')
    col_carry = columns.get('carry')
    frame[col_ttm] = pd.to_numeric(frame[col_ttm], errors='coerce')
    frame[col_z] = pd.to_numeric(frame[col_z], errors='coerce')
    if col_mid and col_mid in frame.columns:
        frame[col_mid] = pd.to_numeric(frame[col_mid], errors='coerce')
    elif col_bid and col_ofr and col_bid in frame.columns and col_ofr in frame.columns:
        frame['__mid_price__'] = (
            pd.to_numeric(frame[col_bid], errors='coerce')
            + pd.to_numeric(frame[col_ofr], errors='coerce')
        ) / 2.0
        columns['mid'] = '__mid_price__'
        col_mid = '__mid_price__'
    if col_cr3m and col_cr3m in frame.columns:
        frame[col_cr3m] = pd.to_numeric(frame[col_cr3m], errors='coerce')
    if col_carry_3m and col_carry_3m in frame.columns:
        frame[col_carry_3m] = pd.to_numeric(frame[col_carry_3m], errors='coerce')
    if col_roll_3m and col_roll_3m in frame.columns:
        frame[col_roll_3m] = pd.to_numeric(frame[col_roll_3m], errors='coerce')
    if (not col_cr3m or col_cr3m not in frame.columns) and col_carry_3m and col_roll_3m and col_carry_3m in frame.columns and col_roll_3m in frame.columns:
        frame['__cr_3m__'] = frame[col_carry_3m] + frame[col_roll_3m]
        columns['cr3m'] = '__cr_3m__'
    elif (not col_cr3m or col_cr3m not in frame.columns) and col_carry and col_carry in frame.columns:
        columns['cr3m'] = col_carry
    if col_carry and col_carry in frame.columns:
        frame[col_carry] = pd.to_numeric(frame[col_carry], errors='coerce')
    frame = frame.dropna(subset=[col_ttm, col_z]).copy()

    if frame.empty:
        return html.Div(
            "No valid numeric signal rows found in the realtime dataset.",
            style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'},
        ), None

    bucket_cards = []
    for bucket_label, min_ttm, max_ttm in BOND_SIGNAL_BUCKETS:
        bucket_df = frame[(frame[col_ttm] > min_ttm) & (frame[col_ttm] <= max_ttm)].copy()
        if bucket_df.empty:
            sell_candidates = bucket_df
            buy_candidates = bucket_df
            avg_z = None
        else:
            sell_candidates = bucket_df.sort_values(col_z, ascending=True).head(5)
            buy_candidates = bucket_df.sort_values(col_z, ascending=False).head(5)
            avg_z = bucket_df[col_z].mean()

        stats = [
            html.Span(
                f"{len(bucket_df)} bonds",
                style={
                    'padding': '4px 10px',
                    'borderRadius': '999px',
                    'backgroundColor': THEME['bg_input'],
                    'color': THEME['text_sub'],
                    'fontSize': '11px',
                },
            )
        ]
        if avg_z is not None and pd.notna(avg_z):
            stats.append(
                html.Span(
                    f"Avg Z {avg_z:+.2f}",
                    style={
                        'padding': '4px 10px',
                        'borderRadius': '999px',
                        'backgroundColor': 'rgba(52, 152, 219, 0.15)',
                        'color': THEME['accent'],
                        'fontSize': '11px',
                    },
                )
            )

        bucket_cards.append(
            html.Div([
                html.Div([
                    html.Div(bucket_label, style={
                        'color': THEME['text_main'],
                        'fontSize': '16px',
                        'fontWeight': '700',
                    }),
                    html.Div(f"TTM in ({min_ttm:.0f}, {max_ttm:.0f}] years", style={
                        'color': THEME['text_sub'],
                        'fontSize': '12px',
                        'marginTop': '2px',
                    }),
                ]),
                html.Div(stats, style={'display': 'flex', 'gap': '8px', 'flexWrap': 'wrap'}),
                html.Div([
                    html.Div(
                        _build_bond_signal_mini_table(
                            sell_candidates,
                            columns,
                            'SELL (Low Z)',
                            THEME['danger'],
                        ),
                        style={'flex': '1 1 0'},
                    ),
                    html.Div(
                        _build_bond_signal_mini_table(
                            buy_candidates,
                            columns,
                            'BUY (High Z)',
                            THEME['success'],
                        ),
                        style={'flex': '1 1 0'},
                    ),
                ], style={'display': 'flex', 'gap': '12px', 'flexWrap': 'wrap', 'marginTop': '16px'}),
            ], style={
                'background': 'linear-gradient(180deg, rgba(12,43,100,0.98), rgba(8,34,85,0.98))',
                'border': f'1px solid {THEME["table_header"]}',
                'borderRadius': '14px',
                'padding': '18px',
                'boxShadow': '0 10px 24px rgba(0, 0, 0, 0.18)',
            })
        )

    return html.Div(
        bucket_cards,
        style={
            'display': 'grid',
            'gridTemplateColumns': 'repeat(auto-fit, minmax(360px, 1fr))',
            'gap': '16px',
            'alignItems': 'start',
        },
    ), len(frame)


# ---------------------------------------------------------------------------
# Layout builders
# ---------------------------------------------------------------------------

def build_multiasset_factor_layout():
    """Build the layout for the Factor (Regime) tab."""
    return html.Div([

        # Hidden store to persist factor selections across tab switches
        dcc.Store(id='factor-selection-store', storage_type='session', data={
            'ir': SELECTED_FACTOR_POOL['ir_factors'],
            'sp': SELECTED_FACTOR_POOL['sp_factors'],
            'fx': SELECTED_FACTOR_POOL['fx_factors'],
            'cmd': SELECTED_FACTOR_POOL['cmd_factors']
        }),

        # Factor Selection Panel at the top
        html.Div([
            html.H5("🎯 Factor Selection Pool", style={'color': THEME['text_main'], 'marginBottom': '15px'}),
            html.P("Select factors to include in correlation analysis:", style={'color': THEME['text_sub'], 'fontSize': '13px', 'marginBottom': '10px'}),

            # Interest Rate Factors
            html.Div([
                html.H6("📊 Interest Rates (IR)", style={'color': THEME['accent'], 'marginBottom': '8px', 'fontSize': '14px'}),
                dcc.Checklist(
                    id='factor-selection-ir',
                    options=[
                        {'label': ' IRDL.CN (China Level)', 'value': 'IRDL.CN'},
                        {'label': ' IRDL.US (US Level)', 'value': 'IRDL.US'},
                        {'label': ' IRDL.EU (Europe Level)', 'value': 'IRDL.EU'},
                        {'label': ' IRDL.JP (Japan Level)', 'value': 'IRDL.JP'},
                        {'label': ' IRDL.UK (UK Level)', 'value': 'IRDL.UK'},
                        {'label': ' IRSL.CN (China Slope)', 'value': 'IRSL.CN'},
                        {'label': ' IRSL.US (US Slope)', 'value': 'IRSL.US'},
                        {'label': ' IRSL.EU (Europe Slope)', 'value': 'IRSL.EU'},
                        {'label': ' IRSL.JP (Japan Slope)', 'value': 'IRSL.JP'},
                        {'label': ' IRSL.UK (UK Slope)', 'value': 'IRSL.UK'},
                    ],
                    value=SELECTED_FACTOR_POOL['ir_factors'],
                    inline=True,
                    labelStyle={'color': THEME['text_main'], 'marginRight': '15px', 'fontSize': '12px'},
                    inputStyle={'marginRight': '5px'},
                    style={'marginBottom': '12px'}
                ),
            ], style={'marginBottom': '15px'}),

            # Spread Factors
            html.Div([
                html.H6("📈 Spreads (SP)", style={'color': THEME['accent'], 'marginBottom': '8px', 'fontSize': '14px'}),
                dcc.Checklist(
                    id='factor-selection-sp',
                    options=[
                        {'label': ' SPDL.IRS (IRS Level)', 'value': 'SPDL.IRS'},
                        {'label': ' SPSL.IRS (IRS Slope)', 'value': 'SPSL.IRS'},
                        {'label': ' SPDL.CDB (CDB Level)', 'value': 'SPDL.CDB'},
                        {'label': ' SPSL.CDB (CDB Slope)', 'value': 'SPSL.CDB'},
                        {'label': ' SPDL.ICP (ICP Level)', 'value': 'SPDL.ICP'},
                    ],
                    value=SELECTED_FACTOR_POOL['sp_factors'],
                    inline=True,
                    labelStyle={'color': THEME['text_main'], 'marginRight': '15px', 'fontSize': '12px'},
                    inputStyle={'marginRight': '5px'},
                    style={'marginBottom': '12px'}
                ),
            ], style={'marginBottom': '15px'}),

            # FX Factors
            html.Div([
                html.H6("💱 FX", style={'color': THEME['accent'], 'marginBottom': '8px', 'fontSize': '14px'}),
                dcc.Checklist(
                    id='factor-selection-fx',
                    options=[
                        {'label': ' FXDL.USDCNY', 'value': 'FXDL.USDCNY'},
                        {'label': ' FXDL.EURCNY', 'value': 'FXDL.EURCNY'},
                        {'label': ' FXDL.JPYCNY', 'value': 'FXDL.JPYCNY'},
                        {'label': ' FXDL.GBPCNY', 'value': 'FXDL.GBPCNY'},
                    ],
                    value=SELECTED_FACTOR_POOL['fx_factors'],
                    inline=True,
                    labelStyle={'color': THEME['text_main'], 'marginRight': '15px', 'fontSize': '12px'},
                    inputStyle={'marginRight': '5px'},
                    style={'marginBottom': '12px'}
                ),
            ], style={'marginBottom': '15px'}),

            # Commodity Factors
            html.Div([
                html.H6("🪙 Commodities (CMD)", style={'color': THEME['accent'], 'marginBottom': '8px', 'fontSize': '14px'}),
                dcc.Checklist(
                    id='factor-selection-cmd',
                    options=[
                        {'label': ' CMDL.AU (Gold)', 'value': 'CMDL.AU'},
                        {'label': ' CMDL.AL (Aluminium)', 'value': 'CMDL.AL'},
                        {'label': ' CMDL.CU (Copper)', 'value': 'CMDL.CU'},
                        {'label': ' CMDL.SC (Crude Oil)', 'value': 'CMDL.SC'},
                    ],
                    value=SELECTED_FACTOR_POOL['cmd_factors'],
                    inline=True,
                    labelStyle={'color': THEME['text_main'], 'marginRight': '15px', 'fontSize': '12px'},
                    inputStyle={'marginRight': '5px'},
                    style={'marginBottom': '12px'}
                ),
            ], style={'marginBottom': '10px'}),

            html.Div([
                html.Span(id='factor-pool-count', style={'color': THEME['text_sub'], 'fontSize': '12px', 'fontStyle': 'italic'}),
            ]),

        ], style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'borderRadius': '5px', 'border': f'1px solid {THEME["table_header"]}', 'marginBottom': '20px'}),

                # New Correlation Analysis Section
        html.Div([
             html.H5("Cross-Asset Correlation Analysis", style={'color': THEME['text_main'], 'marginBottom': '15px'}),
             html.Div([
                html.Label("Lookback Period:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                dcc.Dropdown(
                    id='correlation-period-selector',
                    options=[
                        {'label': '3 Months', 'value': '3M'},
                        {'label': '6 Months', 'value': '6M'},
                        {'label': '1 Year', 'value': '1Y'},
                    ],
                    value='3M',
                    clearable=False,
                    style={'width': '150px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'marginRight': '20px'}
                ),
                html.Label("Top Pairs:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                dcc.Dropdown(
                    id='correlation-top-pairs-selector',
                    options=[
                        {'label': '5', 'value': 5},
                        {'label': '10', 'value': 10},
                        {'label': '15', 'value': 15},
                        {'label': '20', 'value': 20},
                    ],
                    value=10,
                    clearable=False,
                    style={'width': '100px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'marginRight': '20px'}
                ),
                html.Button(
                    "Rank Correlations",
                    id='rank-correlations-btn',
                    n_clicks=0,
                    style={'backgroundColor': THEME['accent'], 'color': 'white', 'padding': '5px 15px', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer', 'fontWeight': 'bold'}
                ),
             ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '15px'}),

             # Store for tracking the lowest correlation factors
             dcc.Store(id='low-corr-factors-store', data=[]),

             dcc.Loading(
                 id="loading-correlations",
                 type="default",
                 children=html.Div(id='correlation-results-container')
             )
        ], style={'maxWidth': '800px', 'margin': '0 auto 20px auto', 'padding': '15px', 'backgroundColor': THEME['bg_card'], 'borderRadius': '5px', 'border': f'1px solid {THEME["table_header"]}'}),

        html.H4("Risk Factor Historical Performance", style={'textAlign': 'center', 'color': THEME['text_main'], 'marginTop': '10px', 'marginBottom': '20px'}),

        # Cascaded dropdown selection
        html.Div([
            # Row 1: Asset Class Selection
            html.Div([
                html.Label("Asset Class:", style={'fontWeight': 'bold', 'marginRight': '10px', 'width': '100px', 'color': THEME['text_main']}),
                dcc.Dropdown(
                    id='factor-asset-class-selector',
                    options=[
                        {'label': 'Rates', 'value': 'Rates'},
                        {'label': 'Spread', 'value': 'Spread'},
                        {'label': 'FX', 'value': 'FX'},
                        {'label': 'Commodities', 'value': 'Commodities'},
                    ],
                    value=None,
                    placeholder="Select asset class...",
                    clearable=True,
                    style={'flex': '1', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                )
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'}),

            # Row 2: Region/Type Selection
            html.Div([
                html.Label("Region/Type:", style={'fontWeight': 'bold', 'marginRight': '10px', 'width': '100px', 'color': THEME['text_main']}),
                dcc.Dropdown(
                    id='factor-region-selector',
                    options=[],
                    value=None,
                    placeholder="Select region or type...",
                    clearable=True,
                    style={'flex': '1', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                )
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'}),

            # Row 3: Factor Selection
            html.Div([
                html.Label("Factors:", style={'fontWeight': 'bold', 'marginRight': '10px', 'width': '100px', 'color': THEME['text_main']}),
                dcc.Dropdown(
                    id='factor-type-selector',
                    options=[],
                    value=[],
                    multi=True,
                    placeholder="Select factors...",
                    style={'flex': '1', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                )
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'}),
        ], style={'maxWidth': '800px', 'margin': '0 auto 20px auto', 'padding': '15px', 'backgroundColor': THEME['bg_card'], 'borderRadius': '5px', 'border': f'1px solid {THEME["table_header"]}'}),


        dcc.Graph(id='factor-history-chart'),

    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px', 'borderRadius': '5px', 'margin': '10px'})


def build_multiasset_portfolio_layout():
    """Build the layout for the Portfolio (Allocation) tab."""

    # Load last saved state
    try:
        last_run_data = load_last_asset_pool()
    except Exception:
        last_run_data = {}

    initial_pool = []
    initial_n_clicks = 0
    initial_capital = 10
    initial_unit = 'billion'

    if last_run_data:
        if 'asset_pool' in last_run_data:
            initial_pool = last_run_data['asset_pool']
            # Note: Do NOT auto-trigger run_analysis on page load
            # User should click 'RUN ANALYSIS' manually to ensure Risk Budgets are loaded
            # initial_n_clicks remains 0

        if 'metadata' in last_run_data:
            meta = last_run_data['metadata']
            if 'capital' in meta:
                initial_capital = meta['capital']
            if 'unit' in meta:
                initial_unit = meta['unit']

    # Generate initial pool display
    if not initial_pool:
        pool_display = [html.Div("No assets selected. Add assets above.",
                           style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px', 'textAlign': 'center', 'padding': '15px'})]
        pool_count_text = "(0)"
    else:
        pool_display = []
        for asset in initial_pool:
            # Using simple styles for pool items, relying on container for bg
            if asset['type'] == 'Commodities':
                bg_col = '#b48b32' # Darker gold
            else:
                bg_col = '#2c5e40' # Darker green

            pool_display.append(
                html.Div([
                    html.Span(f"• {asset['name']}", style={'fontWeight': 'bold', 'color': 'white'}),
                    html.Span(f" ({asset.get('universe','')} - {asset.get('sector','')})", style={'color': '#ddd', 'fontSize': '11px', 'marginLeft': '5px'}),
                ], style={'padding': '5px', 'marginBottom': '5px', 'backgroundColor': bg_col, 'borderRadius': '3px'})
            )
        pool_count_text = f"({len(initial_pool)})"

    return html.Div([
        # Data Stores
        dcc.Store(id='portfolio-data-store'),
        dcc.Store(id='asset-pool-store', data=initial_pool),
        dcc.Store(id='rp-budget-store', data={}),

        html.Div([
            # Section 1: Configuration Header & Capital
            html.Div([
                html.Div([
                    html.H5("Configuration", style={'margin': '0', 'color': THEME['text_main'], 'fontSize': '14px'}),
                ], style={'flex': '1'}),

                html.Div([
                    html.Label("Total Capital:", style={'fontWeight': 'bold', 'marginRight': '10px', 'fontSize': '12px', 'color': THEME['text_main']}),
                    dcc.Input(
                        id='capital-input',
                        type='number',
                        value=initial_capital,
                        style={'width': '100px', 'marginRight': '5px', 'padding': '5px', 'borderRadius': '4px', 'border': '1px solid #444', 'backgroundColor': '#fff', 'color': '#000'}
                    ),
                    dcc.Dropdown(
                        id='capital-unit',
                        options=[
                            {"label": "Million", "value": "million"},
                            {"label": "Billion", "value": "billion"},
                        ],
                        value=initial_unit,
                        clearable=False,
                        style={'width': '100px', 'marginRight': '5px', 'fontSize': '12px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                    ),
                    html.Span("CNY", style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginRight': '20px'}),

                    html.Label("Model:", style={'fontWeight': 'bold', 'marginRight': '10px', 'fontSize': '12px', 'color': THEME['text_main']}),
                    html.Span(
                        "Deterministic",
                        style={
                            'fontSize': '12px',
                            'fontWeight': 'bold',
                            'color': THEME['text_main'],
                            'backgroundColor': THEME['bg_card'],
                            'padding': '4px 10px',
                            'borderRadius': '999px',
                            'border': f'1px solid {THEME["accent"]}',
                        }
                    ),
                ], style={'display': 'flex', 'alignItems': 'center'}),
            ], style={'display': 'flex', 'alignItems': 'center', 'padding': '15px 20px', 'backgroundColor': THEME['bg_input'], 'borderBottom': f'1px solid {THEME["table_header"]}', 'borderRadius': '8px 8px 0 0'}),

            # Section 2: Two-column — sidebar (asset controls) | Risk Budgets (primary)
            html.Div([
                # ── Left sidebar: Asset Selection + Pool stacked ──────────────────
                html.Div([
                    # Asset Selection (compact)
                    html.Div([
                        html.H6("Asset Selection", style={'color': THEME['text_main'], 'marginTop': '0', 'marginBottom': '10px', 'fontSize': '13px'}),
                        html.Div([
                            html.Label("Type:", style={'fontWeight': 'bold', 'width': '55px', 'fontSize': '12px', 'color': THEME['text_main']}),
                            dcc.RadioItems(
                                id='asset-type-selector',
                                options=[
                                    {'label': ' Rates', 'value': 'Rates'},
                                    {'label': ' Spread', 'value': 'Spread'},
                                    {'label': ' Cmdty', 'value': 'Commodities'},
                                ],
                                value=None,
                                inline=True,
                                labelStyle={'color': THEME['text_main'], 'fontSize': '12px'},
                                inputStyle={'marginRight': '4px', 'marginLeft': '6px'},
                                style={'fontSize': '12px'},
                            ),
                        ], style={'marginBottom': '8px', 'display': 'flex', 'alignItems': 'center'}),
                        html.Div([
                            html.Label("Universe:", style={'fontWeight': 'bold', 'width': '55px', 'fontSize': '12px', 'color': THEME['text_main']}),
                            dcc.Dropdown(
                                id='universe-selector',
                                options=[], value=None,
                                placeholder="Select...", clearable=True,
                                style={'width': '100%', 'fontSize': '12px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']},
                            ),
                        ], id='universe-selection-row', style={'display': 'none', 'marginBottom': '8px', 'alignItems': 'center'}),
                        html.Div([
                            html.Label("Sector:", style={'fontWeight': 'bold', 'width': '55px', 'fontSize': '12px', 'alignSelf': 'flex-start', 'marginTop': '4px', 'color': THEME['text_main']}),
                            html.Div([
                                dcc.Checklist(
                                    id='sector-selector',
                                    options=[
                                        {'label': ' 1Y', 'value': '1Y'},
                                        {'label': ' 2Y', 'value': '2Y'},
                                        {'label': ' 5Y', 'value': '5Y'},
                                        {'label': ' 10Y', 'value': '10Y'},
                                        {'label': ' 30Y', 'value': '30Y'},
                                    ],
                                    value=[], inline=True,
                                    labelStyle={'color': THEME['text_main'], 'fontSize': '12px'},
                                    inputStyle={'marginRight': '2px', 'marginLeft': '5px'},
                                    style={'fontSize': '12px', 'marginBottom': '6px'},
                                ),
                                html.Button('Add to Pool', id='add-to-pool-btn', n_clicks=0,
                                    style={'backgroundColor': '#2ecc71', 'color': 'white', 'padding': '3px 10px', 'border': 'none', 'borderRadius': '3px', 'cursor': 'pointer', 'fontSize': '12px'}),
                            ], style={'flex': '1'}),
                        ], id='sector-selection-row', style={'display': 'none', 'marginBottom': '8px', 'alignItems': 'flex-start'}),
                        html.Div([
                            html.Label("Items:", style={'fontWeight': 'bold', 'width': '55px', 'fontSize': '12px', 'alignSelf': 'flex-start', 'marginTop': '4px', 'color': THEME['text_main']}),
                            html.Div([
                                dcc.Checklist(
                                    id='commodities-selector',
                                    options=[
                                        {'label': ' Gold', 'value': 'Gold'},
                                        {'label': ' Alum', 'value': 'Aluminium'},
                                        {'label': ' Copper', 'value': 'Copper'},
                                        {'label': ' Oil', 'value': 'Crude_Oil'},
                                    ],
                                    value=[], inline=True,
                                    labelStyle={'color': THEME['text_main'], 'fontSize': '12px'},
                                    inputStyle={'marginRight': '2px', 'marginLeft': '5px'},
                                    style={'fontSize': '12px', 'marginBottom': '6px'},
                                ),
                                html.Button('Add to Pool', id='add-commodities-btn', n_clicks=0,
                                    style={'backgroundColor': '#f39c12', 'color': 'white', 'padding': '3px 10px', 'border': 'none', 'borderRadius': '3px', 'cursor': 'pointer', 'fontSize': '12px'}),
                            ], style={'flex': '1'}),
                        ], id='commodities-confirm-row', style={'display': 'none', 'marginBottom': '8px', 'alignItems': 'flex-start'}),
                    ], style={'padding': '12px 14px', 'borderBottom': f'1px solid {THEME["table_header"]}'}),
                    # ── Asset Pool ────────────────────────────────────────────────────
                    html.Div([
                        html.Div([
                            html.H6("Asset Pool", style={'color': THEME['text_main'], 'marginTop': '0', 'marginBottom': '0', 'fontSize': '13px'}),
                            html.Span(id='pool-count', children=pool_count_text, style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginLeft': '5px'}),
                            html.Button('Clear', id='clear-pool-btn', n_clicks=0,
                                style={'backgroundColor': THEME['danger'], 'color': 'white', 'padding': '2px 7px', 'border': 'none', 'borderRadius': '3px', 'cursor': 'pointer', 'fontSize': '12px', 'marginLeft': 'auto'}),
                        ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '8px'}),
                        html.Div(
                            id='asset-pool-display', children=pool_display,
                            style={'height': '180px', 'overflowY': 'auto', 'border': f'1px solid {THEME["table_header"]}', 'borderRadius': '4px', 'padding': '6px', 'backgroundColor': THEME['bg_input']},
                        ),
                    ], style={'padding': '12px 14px'}),
                ], style={'width': '45%', 'borderRight': f'1px solid {THEME["table_header"]}', 'display': 'flex', 'flexDirection': 'column'}),

                # ── Right main: Risk Budgets (primary) ───────────────────────────────
                html.Div([
                    html.Div([
                        html.H6("Risk Budgets", style={'color': THEME['text_main'], 'marginTop': '0', 'marginBottom': '0', 'fontSize': '13px', 'fontWeight': 'bold'}),
                        html.Span("Vol from 1Y EWMA  ·  RP Max = inv-vol weights (or user value)  ·  Exposure = RP Max × Coeff",
                                  style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '12px'}),
                    ], style={'display': 'flex', 'alignItems': 'baseline', 'marginBottom': '8px'}),
                    html.Div([
                        dcc.RadioItems(
                            id='allocation-mode',
                            options=[
                                {'label': ' Pure Risk Parity', 'value': 'risk_parity'},
                                {'label': ' Factor Model Scaling', 'value': 'factor_scaling'},
                                {'label': ' User Defined', 'value': 'user_defined'},
                            ],
                            value='risk_parity',
                            inputStyle={'marginRight': '5px'},
                            labelStyle={'display': 'inline', 'marginRight': '16px', 'color': THEME['text_main'], 'fontSize': '12px'},
                            style={'display': 'inline-flex'},
                        ),
                        html.Span(id='factor-signals-toggle-status', style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '8px'}),
                    ], style={'marginBottom': '8px'}),
                    # Column headers: Factor | Vol% ann | RP Max | Coeff | Exposure
                    html.Div([
                        html.Span("Factor",   style={'color': THEME['text_sub'], 'fontSize': '11px', 'width': '80px', 'fontWeight': 'bold', 'flexShrink': '0'}),
                        html.Span("Vol %ann", style={'color': THEME['text_sub'], 'fontSize': '11px', 'width': '62px', 'textAlign': 'right', 'flexShrink': '0'}),
                        html.Span("RP Max",   style={'color': THEME['text_sub'], 'fontSize': '11px', 'width': '54px', 'textAlign': 'right', 'flexShrink': '0'}),
                        html.Span("Coeff",    style={'color': THEME['text_sub'], 'fontSize': '11px', 'width': '44px', 'textAlign': 'center', 'flexShrink': '0'}),
                        html.Span("Exposure", style={'color': THEME['text_sub'], 'fontSize': '11px', 'flex': '1', 'textAlign': 'right'}),
                    ], style={'display': 'flex', 'alignItems': 'center', 'padding': '0 8px 4px 8px',
                              'borderBottom': f'1px solid {THEME["table_header"]}', 'marginBottom': '4px', 'gap': '4px'}),
                    html.Div(
                        id='risk-budget-container',
                        children=[html.Div("Add assets to see risk factors", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px'})] if not initial_pool else [],
                        style={'maxHeight': '280px', 'overflowY': 'auto',
                               'border': f'1px solid {THEME["table_header"]}',
                               'borderRadius': '4px', 'padding': '6px 8px',
                               'backgroundColor': THEME['bg_input']},
                    ),
                    html.Div("Vol auto-refreshes from 1Y EWMA factor history. Run analysis to refresh RP Max from portfolio decomposition.",
                             style={'fontSize': '11px', 'color': THEME['text_sub'], 'marginTop': '5px', 'textAlign': 'center'}),
                ], style={'flex': '1', 'padding': '16px 20px', 'backgroundColor': THEME['bg_card'], 'borderRadius': '0 0 8px 0'}),
            ], style={'display': 'flex'}),

        ], style={'backgroundColor': THEME['bg_card'], 'marginBottom': '20px', 'border': f'1px solid {THEME["table_header"]}', 'borderRadius': '8px'}),

        # ── Factor Model Signals Panel (collapsible) ─────────────────────────
        html.Details([
            html.Summary([
                html.Span("📡 Factor Model Signals",
                          style={'color': THEME['text_main'], 'fontWeight': 'bold', 'fontSize': '13px'}),
                html.Span("  ·  expand to refresh live signal buckets from the factor prediction engine",
                          style={'color': THEME['text_sub'], 'fontSize': '11px'}),
            ], style={'padding': '10px 16px', 'cursor': 'pointer', 'listStyleType': 'none',
                      'WebkitAppearance': 'none', 'MozAppearance': 'none',
                      'backgroundColor': THEME['bg_input'], 'borderRadius': '5px',
                      'userSelect': 'none'}),
            html.Div([
                html.Div([
                    html.Button(
                        "Refresh Signals",
                        id='refresh-factor-signals-btn',
                        n_clicks=0,
                        style={
                            'backgroundColor': THEME['accent'],
                            'color': 'white', 'padding': '5px 15px',
                            'border': 'none', 'borderRadius': '4px',
                            'cursor': 'pointer', 'fontWeight': 'bold',
                            'fontSize': '12px', 'marginRight': '15px',
                        }),
                    html.Span(id='factor-signals-status',
                              style={'color': THEME['text_sub'], 'fontSize': '12px'}),
                ], style={'marginBottom': '12px'}),
                dcc.Loading(
                    id='loading-factor-signals',
                    type='default',
                    children=html.Div(id='factor-signals-table-container'),
                ),
            ], style={'padding': '14px 16px', 'borderTop': f'1px solid {THEME["table_header"]}'}),
        ], style={
            'backgroundColor': THEME['bg_card'],
            'borderRadius': '5px',
            'border': f'1px solid {THEME["table_header"]}',
            'marginBottom': '20px',
        }),
        # Store for the latest signal snapshot (consumed by Portfolio allocation)
        dcc.Store(id='factor-signals-snapshot-store', data={}),

        # Portfolio Table Results
        html.Div([
            html.Div([
                 html.H4("Portfolio Allocation Results", style={'color': THEME['text_main'], 'fontSize': '15px', 'marginBottom': '10px', 'flex': '1'}),
                 html.Div([
                        html.Button(
                            'RUN ANALYSIS',
                            id='run-button',
                            n_clicks=initial_n_clicks,
                            style={'backgroundColor': THEME['accent'], 'color': 'white', 'padding': '8px 20px', 'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer', 'fontSize': '13px', 'fontWeight': 'bold'}
                        ),
                 ], style={'marginLeft': '20px'})
            ], style={'display': 'flex', 'alignItems': 'center', 'justifyContent': 'space-between'}),

            html.Div([
                html.Div(id='status-message', style={'fontSize': '12px', 'color': THEME['text_main'], 'marginRight': '20px'}),
                html.Div(id='timestamp-display', style={'color': THEME['text_sub'], 'fontSize': '11px'})
            ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '15px', 'justifyContent': 'flex-end'}),

            html.Div(id='portfolio-table-container')
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'marginBottom': '20px', 'borderRadius': '5px'}),

        # ── IRDL Hedge Overlay (collapsible) ─────────────────────────────────
        html.Details([
            html.Summary([
                html.Span("🛡 IRDL Hedge Overlay",
                          style={'color': THEME['text_main'], 'fontWeight': 'bold', 'fontSize': '13px'}),
                html.Span("  ·  optional post-optimisation duration hedge via bond futures or pay-fixed IRS",
                          style={'color': THEME['text_sub'], 'fontSize': '11px'}),
            ], style={
                'padding': '10px 16px', 'cursor': 'pointer',
                'listStyleType': 'none', 'WebkitAppearance': 'none', 'MozAppearance': 'none',
                'backgroundColor': THEME['bg_input'], 'borderRadius': '5px', 'userSelect': 'none',
            }),
            html.Div([
                # Controls row
                html.Div([
                    # Hedge ratio
                    html.Div([
                        html.Label("Hedge Ratio", style={
                            'color': THEME['text_sub'], 'fontSize': '11px',
                            'marginBottom': '4px', 'display': 'block',
                        }),
                        dcc.Slider(
                            id='irdl-hedge-ratio',
                            min=0, max=100, step=5, value=50,
                            marks={0: '0%', 25: '25%', 50: '50%', 75: '75%', 100: '100%'},
                            tooltip={'placement': 'bottom', 'always_visible': True},
                        ),
                    ], style={'flex': '2', 'minWidth': '220px'}),
                    # Instrument
                    html.Div([
                        html.Label("Instrument", style={
                            'color': THEME['text_sub'], 'fontSize': '11px',
                            'marginBottom': '4px', 'display': 'block',
                        }),
                        dcc.Dropdown(
                            id='irdl-hedge-instrument',
                            options=[
                                {'label': 'Bond Futures (Short)',   'value': 'futures'},
                                {'label': 'Pay-fixed IRS',          'value': 'irs'},
                            ],
                            value='futures', clearable=False,
                            style={'fontSize': '12px', 'backgroundColor': THEME['bg_input'],
                                   'color': THEME['text_main']},
                        ),
                    ], style={'flex': '1', 'minWidth': '180px'}),
                    # IRS maturity (only relevant when IRS selected)
                    html.Div([
                        html.Label("IRS Tenor", style={
                            'color': THEME['text_sub'], 'fontSize': '11px',
                            'marginBottom': '4px', 'display': 'block',
                        }),
                        dcc.Dropdown(
                            id='irdl-hedge-irs-maturity',
                            options=[
                                {'label': '2Y IRS',  'value': '2Y'},
                                {'label': '5Y IRS',  'value': '5Y'},
                                {'label': '10Y IRS', 'value': '10Y'},
                                {'label': '30Y IRS', 'value': '30Y'},
                            ],
                            value='10Y', clearable=False,
                            style={'fontSize': '12px', 'backgroundColor': THEME['bg_input'],
                                   'color': THEME['text_main']},
                        ),
                    ], style={'flex': '0 0 130px'}),
                ], style={
                    'display': 'flex', 'gap': '20px', 'alignItems': 'flex-end',
                    'flexWrap': 'wrap', 'marginBottom': '16px',
                }),
                # DV01 overrides (compact row)
                html.Div([
                    html.Span("DV01 Override (CNY/bp per contract, blank = default):",
                              style={'color': THEME['text_sub'], 'fontSize': '11px',
                                     'marginRight': '12px', 'alignSelf': 'center'}),
                    *[
                        html.Div([
                            html.Label(cty, style={'color': THEME['text_sub'], 'fontSize': '11px',
                                                   'display': 'block', 'marginBottom': '2px'}),
                            dcc.Input(
                                id={'type': 'irdl-dv01-override', 'index': cty},
                                type='number', placeholder=str(default),
                                debounce=True,
                                style={'width': '72px', 'padding': '4px 6px',
                                       'background': THEME['bg_input'], 'color': THEME['text_main'],
                                       'border': f'1px solid {THEME["table_header"]}',
                                       'borderRadius': '4px', 'fontSize': '12px'},
                            ),
                        ], style={'textAlign': 'center'})
                        for cty, default in [('CN', 800), ('US', 640), ('DE', 750),
                                             ('JP', 560), ('UK', 600)]
                    ],
                ], style={
                    'display': 'flex', 'gap': '12px', 'alignItems': 'flex-end',
                    'marginBottom': '16px', 'flexWrap': 'wrap',
                }),
                # Ticket output
                dcc.Loading(
                    type='default',
                    children=html.Div(id='irdl-hedge-ticket-container',
                                      style={'minHeight': '60px'}),
                ),
                html.Div(
                    "Hedge overlay is advisory only — it does not change portfolio weights. "
                    "Negative contracts = short futures; PAY FIXED = pay fixed rate in IRS.",
                    style={'color': THEME['text_sub'], 'fontSize': '11px',
                           'marginTop': '8px', 'fontStyle': 'italic'},
                ),
            ], style={'padding': '14px 16px', 'borderTop': f'1px solid {THEME["table_header"]}'}),
        ], style={
            'backgroundColor': THEME['bg_card'],
            'borderRadius': '5px',
            'border': f'1px solid {THEME["table_header"]}',
            'marginBottom': '20px',
        }),

    ], style={'padding': '10px', 'backgroundColor': THEME['bg_main']})


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
            type='default',
            children=html.Div(id='beta-bond-signals-container', style={'minHeight': '420px'}),
        ),
    ], style={
        'padding': '18px',
        'backgroundColor': THEME['bg_main'],
        'borderRadius': '10px',
    })


def build_multiasset_risk_layout():
    """
    Build the layout for the Risk/Summary tab.
    Structure:
    1. Combination: Beta/Alpha composition (Total = Rf + Beta + Alpha)
    2. Exposure: Risk Factor sensitivities (Heatmap)
    3. Ticket: Detailed allocation/trade list
    """

    # --- 1. Combination Data (Placeholders as requested) ---
    # TODO: Connect these to actual backtest/optimization metrics in the future
    risk_free_rate = 1.5

    # Beta (Strategic Asset Allocation)
    beta_vol = 15.0
    beta_sharpe = 0.4
    beta_ret = beta_vol * beta_sharpe  # 6.0%

    # Alpha (Tactical Adjustments)
    alpha_vol = 5.0
    alpha_ir = 0.5
    alpha_ret = alpha_vol * alpha_ir   # 2.5%

    total_ret = risk_free_rate + beta_ret + alpha_ret

    # Styling helpers
    def card_style(bg_color=THEME['bg_card']):
        return {
            'backgroundColor': bg_color,
            'padding': '15px',
            'borderRadius': '6px',
            'textAlign': 'center',
            'border': f'1px solid {THEME["table_header"]}',
            'flex': '1',
            'margin': '0 5px',
            'minWidth': '150px'
        }

    def value_style(color=THEME['success']):
        return {'fontSize': '24px', 'fontWeight': 'bold', 'color': color, 'margin': '5px 0'}

    def label_style():
        return {'color': THEME['text_sub'], 'fontSize': '12px', 'textTransform': 'uppercase', 'letterSpacing': '1px'}

    # --- Prepare Data for Exposure ---
    heatmap_fig = go.Figure()
    vol_table = None

    if ALLOCATION_RESULTS['portfolio'] is not None and ALLOCATION_RESULTS['factor_exposures'] is not None:
        try:
            summary = ALLOCATION_RESULTS['summary']
            factor_exp = ALLOCATION_RESULTS['factor_exposures']
            factor_risk = ALLOCATION_RESULTS['factor_risk']
            portfolio = ALLOCATION_RESULTS['portfolio']

            # --- Heatmap Logic ---
            assets_with_allocation = summary[summary['Allocation (CNY)'] >= 1000].nlargest(15, 'Allocation (CNY)')
            # Factor filtering
            factor_names = sorted([f for f in factor_exp['Risk Factor'].unique() if f.startswith(('IRDL', 'IRSL', 'IRCV', 'FXDL', 'CMDL', 'SPDL', 'SPSL'))])
            asset_names = assets_with_allocation['Asset'].tolist()

            sensitivity_matrix = []
            for asset_name in asset_names:
                if asset_name in portfolio.assets:
                    asset = portfolio.assets[asset_name]
                    # Direct dictionary access if available, else 0
                    row = [asset.factors.get(factor, 0.0) for factor in factor_names]
                    sensitivity_matrix.append(row)
                else:
                    sensitivity_matrix.append([0.0] * len(factor_names))

            if asset_names and factor_names:
                heatmap_fig = go.Figure(data=go.Heatmap(
                    z=sensitivity_matrix, x=factor_names, y=asset_names,
                    colorscale='RdBu', zmid=0, text=sensitivity_matrix,
                    texttemplate="%{text:.2f}", textfont={"size": 10}
                ))
                heatmap_fig.update_layout(
                    title=None, height=400, margin=dict(l=10, r=10, t=10, b=10),
                    xaxis_title="Risk Factor", yaxis_title="Asset",
                    template=THEME['chart_template'], paper_bgcolor=THEME['bg_card'], plot_bgcolor=THEME['bg_card'], font={'color': THEME['text_main']}
                )

            # --- Volatility Table Logic ---
            factor_vol_df = factor_risk[factor_risk['Risk Factor'].isin(factor_names)].copy()
            display_cols = ['Risk Factor', 'Volatility (% ann.)']
            if 'Net Exposure' in factor_vol_df.columns:
                display_cols.append('Net Exposure')
            if 'Risk Contribution (%)' in factor_vol_df.columns:
                display_cols.append('Risk Contribution (%)')
            factor_vol_df = factor_vol_df[display_cols].copy()
            # Format
            factor_vol_df['Volatility (% ann.)'] = factor_vol_df['Volatility (% ann.)'].apply(lambda x: f"{x:.2f}%")
            if 'Net Exposure' in factor_vol_df.columns:
                factor_vol_df['Net Exposure'] = factor_vol_df['Net Exposure'].apply(
                    lambda x: f"{x:+.3f}"  # always show sign
                )
            if 'Risk Contribution (%)' in factor_vol_df.columns:
                factor_vol_df['Risk Contribution (%)'] = factor_vol_df['Risk Contribution (%)'].apply(lambda x: f"{x:.1f}%")
            factor_vol_df = factor_vol_df.sort_values('Risk Factor')

            tbl_columns = [
                {'name': 'Risk Factor', 'id': 'Risk Factor'},
                {'name': 'Vol', 'id': 'Volatility (% ann.)'},
            ]
            if 'Net Exposure' in factor_vol_df.columns:
                tbl_columns.append({'name': 'Net Exp', 'id': 'Net Exposure'})
            if 'Risk Contribution (%)' in factor_vol_df.columns:
                tbl_columns.append({'name': 'RC %', 'id': 'Risk Contribution (%)'})

            vol_table = dash_table.DataTable(
                data=factor_vol_df.to_dict('records'),
                columns=tbl_columns,
                style_cell={'textAlign': 'center', 'padding': '8px', 'fontSize': '12px',
                          'backgroundColor': THEME['table_row_odd'], 'color': THEME['text_main'], 'border': 'none'},
                style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_main'], 'fontWeight': 'bold', 'border': 'none'},
                style_data_conditional=[
                    {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                    # Colour Net Exposure: negative = red (short factor), positive = green (long factor)
                    {'if': {'filter_query': '{Net Exposure} contains "-"', 'column_id': 'Net Exposure'},
                     'color': THEME.get('danger', '#e74c3c')},
                    {'if': {'filter_query': '{Net Exposure} contains "+"', 'column_id': 'Net Exposure'},
                     'color': THEME.get('success', '#27ae60')},
                ],
                style_table={'overflowY': 'auto', 'maxHeight': '400px'}
            )

        except Exception as e:
            print(f"Error generating Risk Layout: {e}")
            heatmap_fig.update_layout(title=f"Error: {e}")
            vol_table = html.Div(f"Error generating table: {str(e)}", style={'color': THEME['danger'], 'padding': '10px'})

    # --- Assemble Layout ---
    return html.Div([

        # 1. Combination Section
        html.H4("1. Portfolio Combination", style={'color': THEME['text_main'], 'marginBottom': '15px', 'borderBottom': f'2px solid {THEME["accent"]}', 'paddingBottom': '5px'}),
        html.Div([
            # Equation Row
            html.Div([
                 # Target Return
                 html.Div([
                     html.Div("Target Return", style=label_style()),
                     html.Div(f"{total_ret:.1f}%", style=value_style(THEME['accent'])),
                     html.Div("Total Portfolio Target", style={'fontSize': '11px', 'color': THEME['text_sub']})
                 ], style=card_style()),

                 html.Div("=", style={'fontSize': '24px', 'color': THEME['text_sub'], 'alignSelf': 'center', 'padding': '0 10px'}),

                 # Risk Free
                 html.Div([
                     html.Div("Risk Free Rate", style=label_style()),
                     html.Div(f"{risk_free_rate:.1f}%", style=value_style(THEME['success'])),
                     html.Div("Cash / Treasury", style={'fontSize': '11px', 'color': THEME['text_sub']})
                 ], style=card_style()),

                 html.Div("+", style={'fontSize': '24px', 'color': THEME['text_sub'], 'alignSelf': 'center', 'padding': '0 10px'}),

                 # Beta
                 html.Div([
                     html.Div("Beta Allocation", style=label_style()),
                     html.Div(f"{beta_ret:.1f}%", style=value_style(THEME['warning'])),
                     html.Div([
                         html.Span("Strategic Asset Allocation", style={'display': 'block', 'marginBottom': '5px'}),
                         html.Span(f"{beta_vol}% Vol", style={'fontWeight': 'bold', 'color': THEME['warning']}),
                         html.Span(" × "),
                         html.Span(f"{beta_sharpe} Sharpe", style={'fontWeight': 'bold', 'color': THEME['warning']}),
                     ], style={'fontSize': '11px', 'color': THEME['text_sub'], 'backgroundColor': 'rgba(255,255,255,0.05)', 'padding': '5px', 'borderRadius': '4px'})
                 ], style=card_style()),

                 html.Div("+", style={'fontSize': '24px', 'color': THEME['text_sub'], 'alignSelf': 'center', 'padding': '0 10px'}),

                 # Alpha
                 html.Div([
                     html.Div("Alpha Overlay", style=label_style()),
                     html.Div(f"{alpha_ret:.1f}%", style=value_style(THEME['danger'])),
                     html.Div([
                         html.Span("Tactical Adjustments", style={'display': 'block', 'marginBottom': '5px'}),
                         html.Span(f"{alpha_vol}% Vol", style={'fontWeight': 'bold', 'color': THEME['danger']}),
                         html.Span(" × "),
                         html.Span(f"{alpha_ir} IR", style={'fontWeight': 'bold', 'color': THEME['danger']}),
                     ], style={'fontSize': '11px', 'color': THEME['text_sub'], 'backgroundColor': 'rgba(255,255,255,0.05)', 'padding': '5px', 'borderRadius': '4px'})
                 ], style=card_style()),
            ], style={'display': 'flex', 'flexWrap': 'wrap', 'justifyContent': 'center', 'alignItems': 'stretch'}),
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'borderRadius': '5px', 'marginBottom': '30px'}),

        # 2. Exposure Section
        html.H4("2. Risk Exposure Analysis", style={'color': THEME['text_main'], 'marginBottom': '15px', 'borderBottom': f'2px solid {THEME["accent"]}', 'paddingBottom': '5px'}),
        html.Div([
            # Heatmap
            html.Div([
                html.H6("Asset Sensitivity (Beta to Factors)", style={'textAlign': 'center', 'color': THEME['text_main']}),
                html.Div(
                    id='risk-heatmap-container',
                    children=[
                        dcc.Graph(id='sensitivity-heatmap', figure=heatmap_fig, style={'height': '400px'}) if heatmap_fig and heatmap_fig.data else html.Div("Run Optimization First", style={'padding': '40px', 'textAlign': 'center', 'color': THEME['text_sub']})
                    ]
                )
            ], style={'flex': '3', 'minWidth': '300px', 'backgroundColor': THEME['bg_card'], 'padding': '10px', 'borderRadius': '5px', 'marginRight': '10px'}),

        ], style={'display': 'flex', 'flexWrap': 'wrap', 'marginBottom': '30px'}),

        # 3. Ticket Section (Placeholder)
        html.H4("3. Trade Tickets / Allocation", style={'color': THEME['text_main'], 'marginBottom': '15px', 'borderBottom': f'2px solid {THEME["accent"]}', 'paddingBottom': '5px'}),
        html.Div([
            html.Div("Ticket implementation pending...", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'textAlign': 'center', 'padding': '30px'})
        ], style={'backgroundColor': THEME['bg_card'], 'padding': '20px', 'borderRadius': '5px'})

    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px', 'borderRadius': '5px', 'margin': '10px'})


def build_multiasset_backtest_layout():
    """Build the layout for the Backtest tab.

    Strategy:
    - At the beginning of each month, run Cross-Asset Correlation Analysis
    - Select assets with lowest correlations for diversification
    - Run Risk Parity allocation on the selected assets
    - Track asset pool changes over time
    """
    return html.Div([
        html.H4("Historical Allocation Analysis (Correlation-Based)", style={'color': THEME['text_main'], 'marginBottom': '10px'}),
        html.P(
            "Strategy: At each month start, run correlation analysis to select diversified assets, then apply factor risk parity allocation.",
            style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginBottom': '10px', 'fontStyle': 'italic'}
        ),

        # Factor Pool Info Banner
        html.Div([
            html.Span("📊 Using Factor Pool from Factor tab: ", style={'fontWeight': 'bold', 'color': THEME['text_main']}),
            html.Span(id='backtest-factor-pool-display', style={'color': THEME['accent'], 'fontSize': '12px'}),
        ], style={'padding': '8px 12px', 'backgroundColor': THEME['bg_input'], 'borderRadius': '4px', 'marginBottom': '10px', 'border': f'1px solid {THEME["accent"]}'}),

        # Dynamic Data Range Info (will be updated based on selected factors)
        html.Div([
            html.Span(id='backtest-min-date-info', children="ℹ️ Calculating minimum supported date...",
                     style={'color': THEME['text_sub'], 'fontSize': '11px', 'fontStyle': 'italic'}),
        ], style={'marginBottom': '15px'}),

        # Row 1: Date Range and Capital
        html.Div([
            # Backtest Period
            html.Div([
                html.Label("Backtest Period:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                html.Div([
                    dcc.DatePickerRange(
                        id='history-date-range',
                        min_date_allowed=datetime(2019, 1, 1).date(),
                        max_date_allowed=datetime.now().date(),
                        start_date=datetime(2024, 1, 1).date(),
                        end_date=datetime.now().date(),
                        display_format='YYYY-MM-DD',
                        style={'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']},
                        updatemode='bothdates'
                    )
                ], style={'display': 'inline-block', 'position': 'relative', 'zIndex': 1000}),
            ], style={'display': 'flex', 'alignItems': 'center'}),

            # Total Capital (dedicated for backtest)
            html.Div([
                html.Label("Capital:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                dcc.Input(
                    id='backtest-capital-input',
                    type='number',
                    value=10,
                    style={'width': '80px', 'marginRight': '5px', 'padding': '5px', 'borderRadius': '4px', 'border': '1px solid #444', 'backgroundColor': '#fff', 'color': '#000'}
                ),
                dcc.Dropdown(
                    id='backtest-capital-unit',
                    options=[
                        {"label": "Million", "value": "million"},
                        {"label": "Billion", "value": "billion"},
                    ],
                    value="billion",
                    clearable=False,
                    style={'width': '100px', 'fontSize': '13px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                ),
                html.Span("CNY", style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginLeft': '5px'}),
            ], style={'display': 'flex', 'alignItems': 'center', 'marginLeft': '20px'}),
        ], style={'marginBottom': '10px', 'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap', 'gap': '10px'}),

        # Row 2: Correlation Settings
        html.Div([
            # Correlation Lookback Period
            html.Div([
                html.Label("Correlation Lookback:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                dcc.Dropdown(
                    id='backtest-corr-lookback',
                    options=[
                        {'label': '3 Months', 'value': '3M'},
                        {'label': '6 Months', 'value': '6M'},
                        {'label': '1 Year', 'value': '1Y'},
                    ],
                    value='1Y',
                    clearable=False,
                    style={'width': '120px', 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']}
                ),
            ], style={'display': 'flex', 'alignItems': 'center'}),

            # Number of low-correlation pairs to use
            html.Div([
                html.Label("Top Low-Corr Pairs:", style={'fontWeight': 'bold', 'marginRight': '10px', 'color': THEME['text_main']}),
                dcc.Input(
                    id='backtest-top-pairs',
                    type='number',
                    value=10,
                    min=5,
                    max=20,
                    style={'width': '60px', 'padding': '5px', 'borderRadius': '4px', 'border': '1px solid #444', 'backgroundColor': '#fff', 'color': '#000'}
                ),
            ], style={'display': 'flex', 'alignItems': 'center', 'marginLeft': '20px'}),

            # Performance Metrics Table
            html.Div(id='performance-metrics-container', style={'marginLeft': '20px'}),
        ], style={'marginBottom': '15px', 'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap', 'gap': '10px'}),

        # Row 3: Allocation Mode
        html.Div([
            html.Label("Allocation Mode:", style={'fontWeight': 'bold', 'marginRight': '12px', 'color': THEME['text_main']}),
            dcc.RadioItems(
                id='backtest-alloc-mode',
                options=[
                    {'label': ' Pure Risk Parity', 'value': 'risk_parity'},
                    {'label': ' Factor Model Scaling  (not available — factor backtests pending)', 'value': 'factor_scaling', 'disabled': True},
                ],
                value='risk_parity',
                inline=True,
                inputStyle={'marginRight': '4px'},
                labelStyle={'marginRight': '20px', 'color': THEME['text_main'], 'fontSize': '13px'},
            ),
        ], style={'marginBottom': '15px', 'display': 'flex', 'alignItems': 'center'}),

        html.Div([
            html.Button(
                "Run Historical Analysis",
                id='run-history-button',
                n_clicks=0,
                style={'backgroundColor': THEME['success'], 'color': 'white', 'padding': '10px 20px', 'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer', 'fontSize': '14px', 'fontWeight': 'bold', 'marginBottom': '15px'}
            ),
            dcc.Loading(
                id="loading-history",
                type="default",
                children=[
                    dcc.Graph(id='historical-allocation-chart'),
                    html.Div(style={'height': '20px'}),
                    dcc.Graph(id='pnl-attribution-chart'),
                    html.Div(style={'height': '20px'}),
                    # Asset Pool Changes Section
                    html.Div(id='asset-changes-container')
                ]
            )
        ])
    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px', 'borderRadius': '5px', 'margin': '10px'})


def build_risk_factor_backtest_layout():
    """Build the layout for the Risk Factor Backtest tab (BACKTEST subtab in Beta Book).

    Maps PORTFOLIO-tab risk factors to yield/price series, runs close-only
    technical strategies (MA, Bollinger, Momentum, Z-Score), and persists PnL.
    """
    all_factor_options = [
        # IR
        {'label': 'IRDL.CN (China Level)',   'value': 'IRDL.CN'},
        {'label': 'IRDL.US (US Level)',       'value': 'IRDL.US'},
        {'label': 'IRDL.DE (Europe Level)',   'value': 'IRDL.DE'},
        {'label': 'IRDL.JP (Japan Level)',    'value': 'IRDL.JP'},
        {'label': 'IRDL.UK (UK Level)',       'value': 'IRDL.UK'},
        {'label': 'IRSL.CN (China Slope)',    'value': 'IRSL.CN'},
        {'label': 'IRSL.US (US Slope)',       'value': 'IRSL.US'},
        {'label': 'IRCV.CN (China Curvature)','value': 'IRCV.CN'},
        # Spread
        {'label': 'SPDL.IRS (IRS Level)',     'value': 'SPDL.IRS'},
        {'label': 'SPSL.IRS (IRS Slope)',     'value': 'SPSL.IRS'},
        {'label': 'SPDL.CDB (CDB Level)',     'value': 'SPDL.CDB'},
        {'label': 'SPSL.CDB (CDB Slope)',     'value': 'SPSL.CDB'},
        {'label': 'SPDL.ICP (ICP Level)',     'value': 'SPDL.ICP'},
        # FX
        {'label': 'FXDL.USDCNY',             'value': 'FXDL.USDCNY'},
        {'label': 'FXDL.EURCNY',             'value': 'FXDL.EURCNY'},
        # Commodity
        {'label': 'CMDL.AU (Gold)',           'value': 'CMDL.AU'},
        {'label': 'CMDL.CU (Copper)',         'value': 'CMDL.CU'},
        {'label': 'CMDL.AL (Aluminium)',      'value': 'CMDL.AL'},
        {'label': 'CMDL.SC (Crude Oil)',      'value': 'CMDL.SC'},
    ]

    default_factors = ['IRDL.CN', 'IRSL.CN', 'SPDL.CDB', 'FXDL.USDCNY']

    return html.Div([
        html.H4("Risk Factor Backtest",
                 style={'color': THEME['text_main'], 'marginBottom': '6px'}),
        html.P("Backtest technical strategies on risk factors from the PORTFOLIO tab. "
               "Yield factors use duration-adjusted returns; FX/Commodity use price returns.",
               style={'color': THEME['text_sub'], 'fontSize': '12px',
                      'marginBottom': '16px', 'fontStyle': 'italic'}),

        # ── Row 1: Factor selection ─────────────────────────────────────
        html.Div([
            html.Div([
                html.Label("Factors:", style={'fontWeight': 'bold', 'marginRight': '10px',
                                              'color': THEME['text_main'], 'fontSize': '13px'}),
                dcc.Dropdown(
                    id='rfbt-factor-selector',
                    options=all_factor_options,
                    value=default_factors,
                    multi=True,
                    placeholder="Select factors…",
                    style={'flex': '1', 'minWidth': '360px',
                           'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']},
                ),
            ], style={'display': 'flex', 'alignItems': 'center', 'flex': '1'}),

            # Hidden store – always FactorModel
            dcc.Store(id='rfbt-strategy-selector', data='FactorModel'),
        ], style={'display': 'flex', 'gap': '20px', 'flexWrap': 'wrap',
                  'marginBottom': '12px'}),

        # ── Row 2: Date range & strategy params ─────────────────────────
        html.Div([
            html.Div([
                html.Label("Period:", style={'fontWeight': 'bold', 'marginRight': '10px',
                                             'color': THEME['text_main'], 'fontSize': '13px'}),
                dcc.DatePickerRange(
                    id='rfbt-date-range',
                    min_date_allowed=datetime(2015, 1, 1).date(),
                    max_date_allowed=datetime.now().date(),
                    start_date=datetime(2023, 1, 1).date(),
                    end_date=datetime.now().date(),
                    display_format='YYYY-MM-DD',
                    style={'backgroundColor': THEME['bg_input']},
                ),
            ], style={'display': 'flex', 'alignItems': 'center'}),

            # Hidden placeholders (keep IDs for callback State refs)
            html.Div(id='rfbt-ma-params', children=[
                dcc.Input(id='rfbt-ma-short', type='number', value=10, style={'display': 'none'}),
                dcc.Input(id='rfbt-ma-long', type='number', value=30, style={'display': 'none'}),
            ], style={'display': 'none'}),

            html.Div(id='rfbt-boll-params', children=[
                dcc.Input(id='rfbt-boll-window', type='number', value=20, style={'display': 'none'}),
                dcc.Input(id='rfbt-boll-std', type='number', value=1.5, style={'display': 'none'}),
            ], style={'display': 'none'}),
            html.Div(id='rfbt-mom-params', children=[
                dcc.Input(id='rfbt-mom-window', type='number', value=20, style={'display': 'none'}),
            ], style={'display': 'none'}),
            html.Div(id='rfbt-zscore-params', children=[
                dcc.Input(id='rfbt-zscore-window', type='number', value=60, style={'display': 'none'}),
                dcc.Input(id='rfbt-zscore-entry', type='number', value=1.5, style={'display': 'none'}),
                dcc.Input(id='rfbt-zscore-exit', type='number', value=0.5, style={'display': 'none'}),
            ], style={'display': 'none'}),

            # Factor Model params
            html.Div(id='rfbt-fm-params', children=[
                html.Label("Train (months):", style={'fontWeight': 'bold', 'marginRight': '4px',
                                                     'color': THEME['text_main'], 'fontSize': '12px'}),
                dcc.Input(id='rfbt-fm-train', type='number', value=12, min=3,
                          style={'width': '55px', 'marginRight': '10px', 'padding': '4px',
                                 'borderRadius': '4px', 'border': '1px solid #444',
                                 'backgroundColor': '#fff', 'color': '#000'}),
                html.Label("IC thr:", style={'fontWeight': 'bold', 'marginRight': '4px',
                                             'color': THEME['text_main'], 'fontSize': '12px'}),
                dcc.Input(id='rfbt-fm-ic', type='number', value=0.05, step=0.01, min=0.01,
                          style={'width': '60px', 'marginRight': '10px', 'padding': '4px',
                                 'borderRadius': '4px', 'border': '1px solid #444',
                                 'backgroundColor': '#fff', 'color': '#000'}),
                html.Label("Top N:", style={'fontWeight': 'bold', 'marginRight': '4px',
                                            'color': THEME['text_main'], 'fontSize': '12px'}),
                dcc.Input(id='rfbt-fm-topn', type='number', value=8, min=1,
                          style={'width': '55px', 'padding': '4px',
                                 'borderRadius': '4px', 'border': '1px solid #444',
                                 'backgroundColor': '#fff', 'color': '#000'}),
            ], style={'display': 'flex', 'alignItems': 'center'}),

        ], style={'display': 'flex', 'gap': '16px', 'flexWrap': 'wrap',
                  'marginBottom': '14px', 'alignItems': 'center'}),

        # ── Row 3: Buttons ──────────────────────────────────────────────
        html.Div([
            html.Button("Generate factor-rates.pkl", id='rfbt-generate-btn', n_clicks=0,
                        style={'backgroundColor': THEME['accent'], 'color': 'white',
                               'padding': '8px 16px', 'border': 'none', 'borderRadius': '5px',
                               'cursor': 'pointer', 'fontSize': '12px', 'fontWeight': 'bold',
                               'marginRight': '12px'}),
            html.Button("Run Backtest & Save", id='rfbt-run-btn', n_clicks=0,
                        style={'backgroundColor': THEME['success'], 'color': 'white',
                               'padding': '8px 16px', 'border': 'none', 'borderRadius': '5px',
                               'cursor': 'pointer', 'fontSize': '12px', 'fontWeight': 'bold'}),
            html.Span(id='rfbt-status', style={'marginLeft': '16px',
                                               'color': THEME['text_sub'], 'fontSize': '12px'}),
        ], style={'marginBottom': '16px'}),

        # ── Results area ────────────────────────────────────────────────
        dcc.Loading(
            type='default',
            children=html.Div(id='rfbt-results-container', style={'minHeight': '200px'}),
        ),

    ], style={'backgroundColor': THEME['bg_main'], 'padding': '20px',
              'borderRadius': '5px', 'margin': '10px'})


def build_factor_backtest_layout():
    """Build the layout for the Futures/Factor Backtest tab - uses futures.backtest.layout."""
    from datetime import timedelta
    if not FUTURES_AVAILABLE:
        return html.Div("Futures backtest modules not available.", style={'color': THEME['danger']})

    try:
        # Ensure futures/backtest is in sys.path so that internal imports in layout.py (e.g. 'from data_loader ...') work
        import sys
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # web/ -> ../futures/backtest
        backtest_dir = os.path.abspath(os.path.join(current_dir, '..', '..', 'futures', 'backtest'))
        if backtest_dir not in sys.path:
            sys.path.append(backtest_dir)

        pkl_options = discover_pkl_files()
    except Exception as e:
        pkl_options = []
        print(f"Error discovering pkl files: {e}")

    # Compact style definitions for Strategy Config sidebar
    DARK_INPUT_STYLE = {
        'backgroundColor': '#132C56',
        'color': '#E2E8F0',
        'border': '1px solid #2B4C7E',
        'fontSize': '1.0rem',
        'borderRadius': '4px',
        'padding': '4px 8px'
    }

    SECTION_STYLE = {
        'marginBottom': '25px',
    }

    SECTION_TITLE_STYLE = {
        'color': '#90CDF4',
        'fontSize': '1.0rem',
        'fontWeight': '700',
        'textTransform': 'uppercase',
        'letterSpacing': '0.05em',
        'borderBottom': '1px solid #2B4C7E',
        'paddingBottom': '6px',
        'marginBottom': '12px'
    }

    LABEL_STYLE = {
        'fontSize': '0.95rem',
        'color': '#A0AEC0',
        'marginBottom': '4px',
        'fontWeight': '600',
        'display': 'block'
    }

    # Sidebar (from futures.backtest.layout.create_sidebar) - Compact optimized layout
    sidebar = html.Div([
        html.H4(
            "Strategy Config",
            style={
                'textAlign': 'left',
                'marginBottom': '22px',
                'color': 'white',
                'fontWeight': '600',
                'fontSize': '1.35rem',
                'letterSpacing': '0.03rem',
                'borderBottom': '1px solid #4A5568',
                'paddingBottom': '12px'
            }
        ),

        # Data Settings
        html.Div([
            html.Div("Data Settings", style=SECTION_TITLE_STYLE),
            dbc.Row([
                dbc.Col([
                    html.Label("Source", style=LABEL_STYLE),
                    dcc.RadioItems(
                        id='bf-data-source',
                        options=[{'label': ' Local', 'value': 'local'}, {'label': ' Wind', 'value': 'wind'}],
                        value='local',
                        labelStyle={'display': 'inline-block', 'marginRight': '12px', 'fontSize': '1.0rem', 'color': '#CBD5E0', 'cursor': 'pointer'},
                        inputStyle={"marginRight": "4px", "cursor": 'pointer'}
                    )
                ], width=6),
                dbc.Col([
                    html.Label("Mode", style=LABEL_STYLE),
                    dcc.RadioItems(
                        id='bf-trading-mode',
                        options=[{'label': ' Daily', 'value': 'daily'}, {'label': ' Intraday', 'value': 'intraday'}],
                        value='daily',
                        labelStyle={'display': 'inline-block', 'marginRight': '12px', 'fontSize': '1.0rem', 'color': '#CBD5E0', 'cursor': 'pointer'},
                        inputStyle={"marginRight": "4px", "cursor": 'pointer'}
                    )
                ], width=6),
            ], className="mb-3"),

            html.Div(id='bf-wind-inputs', children=[
                html.Label("Wind Symbol", style=LABEL_STYLE),
                dcc.Dropdown(
                    id='bf-wind-code',
                    placeholder="Select symbol",
                    style={'fontSize': '1.0rem', 'color': 'black'}
                )
            ], className="mb-2"),

            html.Div(id='bf-local-inputs', children=[
                html.Label("Local Symbol", style=LABEL_STYLE),
                dcc.Dropdown(
                    id='bf-local-symbol',
                    options=pkl_options,
                    placeholder="Select symbol",
                    style={'fontSize': '1.0rem', 'color': 'black'}
                )
            ], style={'display': 'none'}, className="mb-2"),

            html.Label("Date Range", style=LABEL_STYLE),
            html.Div([
                dcc.DatePickerRange(
                    id='bf-date-range',
                    start_date=(datetime.now() - timedelta(days=30)).date(),
                    end_date=datetime.now().date(),
                    display_format='YYYY-MM-DD',
                    style={'fontSize': '1.0rem', 'width': '100%'},
                    className="mb-2",
                    with_portal=True,
                    day_size=39
                )
            ], style={'marginBottom': '10px'}),

            html.Div(id='bf-timeframe-container', children=[
                html.Label("Timeframe", style=LABEL_STYLE),
                dcc.Dropdown(
                    id='bf-timeframe',
                    options=[
                        {'label': '1 Min', 'value': '1T'},
                        {'label': '5 Min', 'value': '5T'},
                        {'label': '15 Min', 'value': '15T'},
                        {'label': '30 Min', 'value': '30T'},
                        {'label': '1 Hour', 'value': '1H'}
                    ],
                    value='5T',
                    style={'fontSize': '1.0rem', 'color': 'black'}
                ),
            ], className="mb-2"),

            dbc.Row([
                dbc.Col([
                    html.Label("OOS Split", style=LABEL_STYLE),
                    dcc.DatePickerSingle(
                        id='bf-oos-split-date',
                        date=datetime.now().date(),
                        display_format='YYYY-MM-DD',
                        style={'fontSize': '1.0rem', 'width': '100%'},
                    ),
                ], width=6),
                dbc.Col([
                    html.Label("In-sample", style=LABEL_STYLE),
                    dcc.Dropdown(
                        id='bf-insample-lookback',
                        options=[
                            {'label': '6 Months', 'value': '6M'},
                            {'label': '1 Year', 'value': '1Y'},
                            {'label': '2 Years', 'value': '2Y'},
                        ],
                        value='1Y',
                        clearable=False,
                        style={'fontSize': '1.0rem', 'color': 'black'}
                    ),
                ], width=6)
            ], className="mb-2"),
        ], style=SECTION_STYLE),

        # Strategy Selection
        html.Div([
            html.Div("Strategies", style=SECTION_TITLE_STYLE),
            dcc.Checklist(
                id='bf-strategy-selector',
                options=[
                    {'label': ' MA', 'value': 'MA'},
                    {'label': ' DeMark', 'value': 'DeMark'},
                    {'label': ' Bollinger', 'value': 'Boll'},
                    {'label': ' VWAP', 'value': 'VWAP'},
                    {'label': ' Momentum', 'value': 'Momentum'},
                    {'label': ' ATR', 'value': 'ATR'},
                    {'label': ' SAR', 'value': 'SAR'},
                    {'label': ' Market Regime', 'value': 'MarketRegime'},
                ],
                value=['MA', 'Boll', 'SAR', 'MarketRegime'],
                # Force a compact 3-column layout inside the narrow sidebar.
                labelStyle={
                    'display': 'inline-block',
                    'width': '33%',
                    'marginBottom': '8px',
                    'fontSize': '1.0rem',
                    'color': '#E2E8F0',
                    'cursor': 'pointer',
                    'verticalAlign': 'top'
                },
                inputStyle={"marginRight": "8px", "cursor": 'pointer'},
                style={'marginTop': '6px'}
            )
        ], style=SECTION_STYLE),

        # Market Regime Configuration - 2 columns side by side (Flexbox)
        html.Div([
            html.Div("Regime Logic", style=SECTION_TITLE_STYLE),
            html.Div([
                html.Div([
                    html.Label("Trending", style={'fontSize': '0.95rem', 'color': '#A0AEC0', 'marginBottom': '2px', 'display': 'block'}),
                    dcc.Dropdown(
                        id='bf-mr-trending-strategy',
                        options=[
                            {'label': 'MA', 'value': 'MA'},
                            {'label': 'SAR', 'value': 'SAR'},
                            {'label': 'ATR', 'value': 'ATR'}
                        ],
                        value='SAR',
                        style={'fontSize': '0.95rem', 'color': 'black'},
                    ),
                ], style={'flex': 1, 'paddingRight': '4px', 'minWidth': '0'}),
                html.Div([
                    html.Label("Mean-Rev", style={'fontSize': '0.95rem', 'color': '#A0AEC0', 'marginBottom': '2px', 'display': 'block'}),
                    dcc.Dropdown(
                        id='bf-mr-meanrev-strategy',
                        options=[
                            {'label': 'Boll', 'value': 'Boll'},
                            {'label': 'VWAP', 'value': 'VWAP'},
                            {'label': 'ATR', 'value': 'ATRMeanRev'}
                        ],
                        value='Boll',
                        style={'fontSize': '0.95rem', 'color': 'black'}
                    )
                ], style={'flex': 1, 'paddingLeft': '4px', 'minWidth': '0'}),
            ], style={'display': 'flex', 'flexDirection': 'row', 'width': '100%'})
        ], style={'marginBottom': '15px'}),

        # Parameters - compact 3-column grid (Flexbox)
        html.Div([
            html.Div("Parameters", style=SECTION_TITLE_STYLE),
            # Row 1: MA | Bollinger | VWAP
            html.Div([
                # MA
                html.Div([
                    html.Div("MA", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Div([
                        html.Div([html.Label("S", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-ma-short', type='number', value=5, min=2, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginRight': '2px'}),
                        html.Div([html.Label("L", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-ma-long', type='number', value=20, min=5, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginLeft': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'row'})
                ], style={'flex': 1, 'paddingRight': '4px', 'minWidth': '0'}),
                # Boll
                html.Div([
                    html.Div("Boll", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Div([
                        html.Div([html.Label("P", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-boll-window', type='number', value=20, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginRight': '2px'}),
                        html.Div([html.Label("σ", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-boll-std', type='number', value=1.0, step=0.1, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginLeft': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'row'}),
                    dcc.Checklist(id='bf-boll-exit', options=[{'label': ' Exit@MA', 'value': 'exit'}], value=[], labelStyle={'fontSize': '0.85rem', 'color': '#CBD5E0'}, style={'marginTop': '2px'})
                ], style={'flex': 1, 'paddingLeft': '4px', 'paddingRight': '4px', 'minWidth': '0'}),
                # VWAP
                html.Div([
                    html.Div("VWAP", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Label("Win", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}),
                    dcc.Input(id='bf-vwap-window', type='number', value=20, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})
                ], style={'flex': 1, 'paddingLeft': '4px', 'minWidth': '0'}),
            ], style={'display': 'flex', 'flexDirection': 'row', 'width': '100%', 'marginBottom': '8px'}),

            # Row 2: Momentum | ATR | SAR
            html.Div([
                # Mom
                html.Div([
                    html.Div("Mom", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Label("LB", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}),
                    dcc.Input(id='bf-mom-window', type='number', value=14, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})
                ], style={'flex': 1, 'paddingRight': '4px', 'minWidth': '0'}),
                # ATR
                html.Div([
                    html.Div("ATR", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Div([
                        html.Div([html.Label("E", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-atr-ema-window', type='number', value=11, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'paddingRight': '2px'}),
                        html.Div([html.Label("A", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-atr-window', type='number', value=14, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'paddingLeft': '2px', 'paddingRight': '2px'}),
                        html.Div([html.Label("M", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-atr-mult', type='number', value=2.0, step=0.1, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'paddingLeft': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'row'})
                ], style={'flex': 1, 'paddingLeft': '4px', 'paddingRight': '4px', 'minWidth': '0'}),
                # SAR
                html.Div([
                    html.Div("SAR", style={'fontSize': '0.9rem', 'color': '#90CDF4', 'fontWeight': '600', 'marginBottom': '4px'}),
                    html.Div([
                        html.Div([html.Label("AF", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-sar-af', type='number', value=0.02, step=0.01, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginRight': '2px'}),
                        html.Div([html.Label("Max", style={'fontSize': '0.85rem', 'color': '#A0AEC0', 'display': 'block'}), dcc.Input(id='bf-sar-max-af', type='number', value=0.2, step=0.01, style={**DARK_INPUT_STYLE, 'fontSize': '0.95rem', 'padding': '2px 4px', 'width': '100%'})], style={'flex': 1, 'marginLeft': '2px'}),
                    ], style={'display': 'flex', 'flexDirection': 'row'})
                ], style={'flex': 1, 'paddingLeft': '4px', 'minWidth': '0'}),
            ], style={'display': 'flex', 'flexDirection': 'row', 'width': '100%'})
        ], style={'marginBottom': '15px', 'padding': '10px', 'backgroundColor': '#0a1e3d', 'borderRadius': '4px', 'border': '1px solid #2B4C7E'}),

        dbc.Button("Run Backtest", id='bf-run-button', style={
            'width': '100%', 'padding': '12px', 'backgroundColor': '#007ACE',
            'color': 'white', 'border': 'none', 'cursor': 'pointer',
            'fontSize': '1.1rem', 'fontWeight': 'bold', 'letterSpacing': '0.1rem'
        })
    ], style={
        'width': '320px', 'padding': '2rem 1rem', 'backgroundColor': '#082255',
        'color': 'white', 'overflowY': 'auto', 'fontFamily': '"Open Sans", sans-serif'
    })

    # Content area
    content = html.Div([
        dcc.Loading(
            id="bf-loading-results",
            type="default",
            children=html.Div(id='bf-results-container', style={'minHeight': '400px'})
        )
    ], style={'flex': '1', 'padding': '1.5rem 2rem', 'fontFamily': '"Open Sans", sans-serif', 'minWidth': '0'})

    return html.Div([sidebar, content], style={'display': 'flex', 'flexDirection': 'row', 'width': '100%', 'minHeight': 'calc(100vh - 150px)', 'backgroundColor': THEME['bg_main']})
