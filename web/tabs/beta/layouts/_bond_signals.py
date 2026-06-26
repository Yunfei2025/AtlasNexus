# -*- coding: utf-8 -*-
"""Bond signal display helpers used by the Bond layout and bond callbacks."""

from __future__ import annotations

import os

import pandas as pd
from dash import html

from settings.paths import DIR_INPUT

from ..data import (
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


def _build_bond_signal_mini_table(df: pd.DataFrame, columns: dict, title: str, is_sell: bool):
    if df.empty:
        return html.Div(
            "No signals in this bucket.",
            style={
                'color': 'var(--text-muted)',
                'fontSize': '11px',
                'padding': '12px',
                'textAlign': 'center',
                'background': 'var(--surface-input)',
                'borderRadius': '6px',
            },
        )

    col_id = columns['id']
    col_ttm = columns['ttm']
    col_z = columns['z']
    col_mid = columns.get('mid')
    col_cr3m = columns.get('cr3m')

    badge_bg = '#b91c1c' if is_sell else '#166534'
    z_color  = '#f87171' if is_sell else '#34d399'

    def _z_bg(z_val: float) -> str:
        if is_sell:
            alpha = min(abs(z_val) / 4, 1) * 0.3
            return f'rgba(239,68,68,{alpha:.2f})'
        alpha = min(abs(z_val) / 3, 1) * 0.25
        return f'rgba(52,211,153,{alpha:.2f})'

    _th = {
        'padding': '3px 6px',
        'fontSize': '8px',
        'fontWeight': '600',
        'textTransform': 'uppercase',
        'letterSpacing': '0.05em',
        'color': 'var(--text-muted)',
        'borderBottom': '1px solid rgba(255,255,255,0.08)',
    }
    _td_base = {'padding': '4px 6px', 'fontSize': '10px',
                'borderBottom': '1px solid rgba(255,255,255,0.04)'}

    rows = []
    for _, row in df.iterrows():
        try:
            z_val = float(row[col_z]) if pd.notna(row[col_z]) else 0.0
        except (TypeError, ValueError):
            z_val = 0.0
        mid_str = f"{float(row[col_mid]):.3f}" if col_mid and col_mid in df.columns and pd.notna(row.get(col_mid)) else '—'
        cr_val  = float(row[col_cr3m]) if col_cr3m and col_cr3m in df.columns and pd.notna(row.get(col_cr3m)) else None
        ttm_str = f"{float(row[col_ttm]):.2f}Y" if pd.notna(row[col_ttm]) else '—'

        cr_color = '#34d399' if (cr_val is not None and cr_val >= 0) else '#f87171'
        cr_str   = f"{cr_val:.2f}" if cr_val is not None else '—'

        rows.append(html.Tr([
            html.Td(str(row[col_id]), style={**_td_base, 'color': 'var(--text-primary)', 'fontWeight': '500', 'textAlign': 'left'}),
            html.Td(mid_str,          style={**_td_base, 'color': 'var(--text-secondary)', 'textAlign': 'right'}),
            html.Td(cr_str,           style={**_td_base, 'color': cr_color, 'textAlign': 'right'}),
            html.Td(ttm_str,          style={**_td_base, 'color': 'var(--text-muted)', 'textAlign': 'right'}),
            html.Td(f"{z_val:.2f}",   style={**_td_base, 'color': z_color, 'fontWeight': '700',
                                             'textAlign': 'right', 'background': _z_bg(z_val)}),
        ]))

    return html.Div([
        html.Div(
            title,
            style={
                'display': 'inline-block',
                'padding': '2px 10px',
                'borderRadius': '12px',
                'background': badge_bg,
                'color': '#fff',
                'fontSize': '9px',
                'fontWeight': '700',
                'letterSpacing': '0.06em',
                'marginBottom': '6px',
            },
        ),
        html.Table([
            html.Thead(html.Tr([
                html.Th('NAME',      style={**_th, 'textAlign': 'left'}),
                html.Th('MID PRICE', style={**_th, 'textAlign': 'right'}),
                html.Th('C+R,3M',   style={**_th, 'textAlign': 'right'}),
                html.Th('TTM',       style={**_th, 'textAlign': 'right'}),
                html.Th('Z-SCORE',   style={**_th, 'textAlign': 'right'}),
            ])),
            html.Tbody(rows),
        ], style={'width': '100%', 'borderCollapse': 'collapse', 'fontSize': '10px'}),
    ], style={'marginBottom': '10px'})


def _build_bond_signal_cards(bond_type: str):
    frame, source_key = _load_bond_signal_frame(bond_type)
    if frame is None:
        empty_state = html.Div([
            html.H5(
                f"{BOND_SIGNAL_LABELS.get(bond_type, bond_type)} signals unavailable",
                style={'color': 'var(--accent-amber)', 'marginBottom': '8px'},
            ),
            html.P(
                source_key,
                style={'color': 'var(--text-muted)', 'margin': '0', 'fontSize': '13px'},
            ),
        ], style={
            'padding': '28px',
            'background': 'var(--surface-panel)',
            'borderRadius': '8px',
            'border': '1px dashed var(--border-strong)',
            'textAlign': 'center',
        })
        return empty_state, None

    columns = _resolve_bond_signal_columns(frame)
    if columns is None:
        return html.Div(
            "Missing required columns for bond signals (ttm, z-score, code).",
            style={'color': '#f87171', 'padding': '20px', 'textAlign': 'center'},
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
            style={'color': 'var(--accent-amber)', 'padding': '20px', 'textAlign': 'center'},
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

        avg_z_pos = avg_z is not None and pd.notna(avg_z) and avg_z >= 0
        avg_z_badge = []
        if avg_z is not None and pd.notna(avg_z):
            avg_z_badge = [html.Span(
                f"Avg Z {avg_z:+.2f}",
                style={
                    'padding': '2px 8px',
                    'borderRadius': '10px',
                    'fontSize': '9px',
                    'fontWeight': '700',
                    'background': 'rgba(52,211,153,0.18)' if avg_z_pos else 'rgba(239,68,68,0.18)',
                    'color': '#34d399' if avg_z_pos else '#f87171',
                },
            )]

        bucket_cards.append(
            html.Div([
                # ── Card header ─────────────────────────────────────────────
                html.Div([
                    html.Span(bucket_label, style={
                        'color': 'var(--text-primary)',
                        'fontSize': '14px',
                        'fontWeight': '700',
                    }),
                ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'baseline', 'marginBottom': '3px'}),
                html.Div(f"TTM in ({min_ttm:.0f}, {max_ttm:.0f}] years", style={
                    'color': 'var(--text-muted)',
                    'fontSize': '9px',
                    'marginBottom': '8px',
                }),
                html.Div(
                    [html.Span(f"{len(bucket_df)} bonds", style={
                        'color': 'var(--text-muted)', 'fontSize': '10px',
                    })] + avg_z_badge,
                    style={'display': 'flex', 'gap': '8px', 'alignItems': 'center', 'marginBottom': '12px'},
                ),
                # ── SELL table ──────────────────────────────────────────────
                _build_bond_signal_mini_table(sell_candidates, columns, 'SELL (LOW Z)', is_sell=True),
                # ── BUY table ───────────────────────────────────────────────
                _build_bond_signal_mini_table(buy_candidates, columns, 'BUY (HIGH Z)', is_sell=False),
            ], style={
                'background': 'var(--surface-panel)',
                'border': '1px solid var(--border-strong)',
                'borderRadius': '8px',
                'padding': '14px',
            })
        )

    return html.Div(
        bucket_cards,
        style={
            'display': 'grid',
            'gridTemplateColumns': 'repeat(3, 1fr)',
            'gap': '14px',
            'alignItems': 'start',
        },
    ), len(frame)
