# -*- coding: utf-8 -*-
"""Bond signal display helpers used by the Bond layout and bond callbacks."""

from __future__ import annotations

import os

import pandas as pd
from dash import html, dash_table

from settings.paths import DIR_INPUT

from ..data import (
    THEME,
    BOND_SIGNAL_FILE_MAP,
    BOND_SIGNAL_LABELS,
    BOND_SIGNAL_BUCKETS,
)


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
                value = round(float(value), 4)
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
