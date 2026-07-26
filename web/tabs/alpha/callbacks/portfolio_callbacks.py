# -*- coding: utf-8 -*-
"""Portfolio-related callbacks for the Alpha candidates subtab."""

from __future__ import annotations

import numpy as np
import pandas as pd

from dash import dcc, html, callback_context
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go

from ..data import THEME, display_key
from .helpers import _ALPHA_CORR_COLORSCALE, _get_upstream_regime, _load_alpha_book_positions, _merge_curated_entries


def register_portfolio_callbacks(app) -> None:
    @app.callback(
        Output('alpha-book-positions-store', 'data'),
        Input('an-alpha-subtabs', 'value'),
    )
    def refresh_positions_store(active_subtab):
        if active_subtab != 'portfolio':
            raise PreventUpdate
        return _load_alpha_book_positions()

    @app.callback(
        [Output('alpha-curated-table-div', 'children'),
         Output('alpha-curated-corr-div', 'children')],
        [Input('alpha-curated-instruments-store', 'data'),
         Input('alpha-book-positions-store', 'data'),
         Input('an-alpha-subtabs', 'value'),
         Input('alpha-corr-matrix-store', 'data')],
    )
    def render_curated_content(instruments, positions, active_subtab, matrix_data):
        if active_subtab is not None and active_subtab != 'portfolio':
            raise PreventUpdate

        _sub = {'color': THEME['text_sub'], 'fontSize': '12px', 'fontStyle': 'italic'}

        instruments = _merge_curated_entries(instruments or [])
        positions = _merge_curated_entries(positions or [])
        matrix_cols = set(matrix_data.keys()) if matrix_data else set()

        _entry_key = lambda e: (e.get('spread_type', ''), e.get('instrument', ''))
        _pos_key_set = {_entry_key(e) for e in positions}
        instruments = [e for e in instruments if _entry_key(e) not in _pos_key_set]

        _REGIME_OPTIONS = [
            {'label': 'mean-reverting', 'value': 'mean-reverting'},
            {'label': 'momentum', 'value': 'momentum'},
        ]
        _DIR_OPTIONS = [
            {'label': 'BUY', 'value': 'BUY'},
            {'label': 'SELL', 'value': 'SELL'},
        ]
        _dd_style = {'fontSize': '11px', 'minWidth': '110px'}
        _dd_warn = {'fontSize': '11px', 'minWidth': '110px', 'border': f"1px solid {THEME['warning']}", 'borderRadius': '4px'}

        def _dir_border(direction):
            if direction == 'BUY':
                return THEME['success']
            if direction == 'SELL':
                return THEME['danger']
            return THEME['table_header']

        def _dir_pill(direction):
            if direction == 'BUY':
                return html.Span('BUY', style={
                    'backgroundColor': THEME['success'], 'color': '#000',
                    'fontWeight': 'bold', 'fontSize': '10px', 'padding': '1px 6px',
                    'borderRadius': '3px', 'display': 'inline-block',
                })
            if direction == 'SELL':
                return html.Span('SELL', style={
                    'backgroundColor': THEME['danger'], 'color': '#fff',
                    'fontWeight': 'bold', 'fontSize': '10px', 'padding': '1px 6px',
                    'borderRadius': '3px', 'display': 'inline-block',
                })
            return html.Span('—', style={'color': THEME['text_sub'], 'fontSize': '10px'})

        def _regime_chip(regime):
            if regime == 'mean-reverting':
                return html.Span('MR', style={
                    'backgroundColor': '#0d6e6e', 'color': '#7fffd4',
                    'fontWeight': 'bold', 'fontSize': '9px', 'padding': '1px 5px',
                    'borderRadius': '3px', 'display': 'inline-block',
                    'letterSpacing': '0.5px',
                })
            if regime == 'momentum':
                return html.Span('MOM', style={
                    'backgroundColor': '#7a4500', 'color': '#ffd580',
                    'fontWeight': 'bold', 'fontSize': '9px', 'padding': '1px 5px',
                    'borderRadius': '3px', 'display': 'inline-block',
                    'letterSpacing': '0.5px',
                })
            return html.Span('?', style={
                'backgroundColor': THEME['table_header'], 'color': THEME['text_sub'],
                'fontWeight': 'bold', 'fontSize': '9px', 'padding': '1px 5px',
                'borderRadius': '3px', 'display': 'inline-block',
            })

        def _matrix_dot(inst, stype=''):
            col_key = display_key(stype, inst) if stype else inst
            in_matrix = col_key in matrix_cols or inst in matrix_cols
            return (html.Span("●", title="in correlation matrix", style={'color': THEME['success'], 'fontSize': '9px'}) if in_matrix else html.Span("○", title="not in matrix", style={'color': THEME['text_sub'], 'fontSize': '9px'}))

        def _z_bar(z, max_z=4.0):
            try:
                z = float(z)
            except (TypeError, ValueError):
                z = 0.0
            z_clamped = max(-max_z, min(max_z, z))
            bar_pct = abs(z_clamped) / max_z * 50.0
            bar_color = THEME['danger'] if z < 0 else THEME['success']
            if z < 0:
                bar_style = {'position': 'absolute', 'right': '50%', 'width': f'{bar_pct:.1f}%', 'height': '100%', 'backgroundColor': bar_color, 'opacity': '0.7', 'borderRadius': '2px 0 0 2px'}
            else:
                bar_style = {'position': 'absolute', 'left': '50%', 'width': f'{bar_pct:.1f}%', 'height': '100%', 'backgroundColor': bar_color, 'opacity': '0.7', 'borderRadius': '0 2px 2px 0'}
            return html.Div([
                html.Div(style={'position': 'relative', 'height': '5px', 'backgroundColor': THEME['bg_main'], 'borderRadius': '3px', 'overflow': 'hidden', 'width': '50px', 'display': 'inline-block', 'verticalAlign': 'middle'}, children=[html.Div(style=bar_style)]),
                html.Span(f'{z:+.1f}σ', style={'fontSize': '10px', 'color': bar_color, 'fontWeight': 'bold', 'marginLeft': '3px', 'verticalAlign': 'middle'}),
            ], style={'display': 'inline-flex', 'alignItems': 'center'})

        def _seas_chip(label):
            label = str(label or '').strip().lower()
            if label == 'strong':
                return html.Span('S↑↑', title='Strong seasonal tailwind (consistency ≥75%)', style={'backgroundColor': '#0d5c0d', 'color': '#7fff7f', 'fontSize': '9px', 'fontWeight': 'bold', 'padding': '1px 4px', 'borderRadius': '3px', 'cursor': 'default'})
            if label == 'weak':
                return html.Span('S↑', title='Weak seasonal tailwind (consistency ≥60%)', style={'backgroundColor': '#2a4a2a', 'color': '#a0d0a0', 'fontSize': '9px', 'fontWeight': 'bold', 'padding': '1px 4px', 'borderRadius': '3px', 'cursor': 'default'})
            if label == 'against':
                return html.Span('S↓', title='Seasonal headwind (consistency ≥60% against)', style={'backgroundColor': '#4a1a1a', 'color': '#d09090', 'fontSize': '9px', 'fontWeight': 'bold', 'padding': '1px 4px', 'borderRadius': '3px', 'cursor': 'default'})
            return None

        curated_cards = []
        for entry_id, entry in enumerate(instruments):
            stype = entry.get('spread_type', '')
            inst = entry.get('instrument', '')
            stored_regime = entry.get('regime', 'uncertain')
            regime = (_get_upstream_regime(stype, inst) or 'uncertain' if stored_regime == 'uncertain' else stored_regime)
            direction = entry.get('direction', '') or ''
            manual = bool(entry.get('manual', False))
            z_val = entry.get('Zscore', None)
            seas_label = entry.get('seasonal_label', '')

            regime_known = regime in {'mean-reverting', 'momentum'}
            dir_known = direction in {'BUY', 'SELL'}
            regime_editable = manual or not regime_known
            direction_editable = manual or not dir_known

            regime_widget = (
                dcc.Dropdown(
                    id={'type': 'curated-regime', 'stype': stype, 'inst': inst},
                    options=_REGIME_OPTIONS,
                    value=regime if regime_known else None,
                    placeholder='regime…', clearable=False,
                    style=_dd_style if regime_known else _dd_warn,
                ) if regime_editable else _regime_chip(regime)
            )
            dir_widget = (
                dcc.Dropdown(
                    id={'type': 'curated-direction', 'stype': stype, 'inst': inst},
                    options=_DIR_OPTIONS,
                    value=direction if dir_known else None,
                    placeholder='dir…', clearable=False,
                    style=_dd_style if dir_known else _dd_warn,
                ) if direction_editable else _dir_pill(direction)
            )

            curated_cards.append(html.Div([
                html.Div([
                    html.Span(display_key(stype, inst), style={'color': THEME['text_main'], 'fontSize': '11px', 'fontWeight': '600', 'flex': '1', 'overflow': 'hidden', 'textOverflow': 'ellipsis', 'whiteSpace': 'nowrap'}),
                    _matrix_dot(inst, stype),
                    html.Button('×', id={'type': 'curated-del', 'stype': stype, 'inst': inst}, n_clicks=0, style={'background': 'none', 'border': f"1px solid {THEME['danger']}", 'color': THEME['danger'], 'borderRadius': '3px', 'cursor': 'pointer', 'padding': '0px 4px', 'fontSize': '11px', 'lineHeight': '1.3', 'marginLeft': '4px', 'flexShrink': '0'}),
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '4px'}),
                html.Div([
                    html.Span(stype, style={'backgroundColor': THEME['table_header'], 'color': THEME['text_sub'], 'fontSize': '9px', 'padding': '1px 4px', 'borderRadius': '2px', 'marginRight': '5px', 'flexShrink': '0'}),
                    _z_bar(z_val) if z_val is not None else html.Span('z=—', style={'color': THEME['text_sub'], 'fontSize': '10px'}),
                    *([html.Div(_seas_chip(seas_label), style={'marginLeft': '5px', 'flexShrink': '0'})] if _seas_chip(seas_label) else []),
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '5px'}),
                html.Div([
                    html.Div(regime_widget, style={'marginRight': '5px', 'flexShrink': '0'}),
                    html.Div(dir_widget, style={'flexShrink': '0'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),
            ], style={'padding': '7px 8px', 'borderRadius': '4px', 'backgroundColor': THEME['bg_card'], 'borderLeft': f"3px solid {_dir_border(direction)}"}))

        if curated_cards:
            grid_a = html.Div(curated_cards, style={'display': 'grid', 'gridTemplateColumns': 'repeat(3, 1fr)', 'gap': '5px', 'maxHeight': '300px', 'overflowY': 'auto', 'paddingRight': '2px'})
        else:
            grid_a = html.Div("Run Check Correlation in the Candidates subtab to populate this list.", style=_sub)

        pos_cards = []
        for entry in positions:
            stype = entry.get('spread_type', '')
            inst = entry.get('instrument', '')
            stored_regime = entry.get('regime', 'uncertain')
            regime = (_get_upstream_regime(stype, inst) or 'uncertain' if stored_regime == 'uncertain' else stored_regime)
            direction = entry.get('direction', '') or ''
            z_val = entry.get('Zscore', None)
            seas_label = entry.get('seasonal_label', '')
            pos_cards.append(html.Div([
                html.Div([
                    html.Span(display_key(stype, inst), style={'color': THEME['text_main'], 'fontSize': '11px', 'fontWeight': '600', 'flex': '1', 'overflow': 'hidden', 'textOverflow': 'ellipsis', 'whiteSpace': 'nowrap'}),
                    _matrix_dot(inst, stype),
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '4px'}),
                html.Div([
                    html.Span(stype, style={'backgroundColor': THEME['table_header'], 'color': THEME['text_sub'], 'fontSize': '9px', 'padding': '1px 4px', 'borderRadius': '2px', 'marginRight': '5px', 'flexShrink': '0'}),
                    _z_bar(z_val) if z_val is not None else html.Span('z=—', style={'color': THEME['text_sub'], 'fontSize': '10px'}),
                    *([html.Div(_seas_chip(seas_label), style={'marginLeft': '5px', 'flexShrink': '0'})] if _seas_chip(seas_label) else []),
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '5px'}),
                html.Div([
                    _regime_chip(regime),
                    html.Div(style={'flex': '1'}),
                    _dir_pill(direction),
                ], style={'display': 'flex', 'alignItems': 'center', 'gap': '5px'}),
            ], style={'padding': '7px 8px', 'borderRadius': '4px', 'backgroundColor': THEME['bg_card'], 'borderLeft': f"3px solid {_dir_border(direction)}", 'opacity': '0.85'}))

        if pos_cards:
            grid_b = html.Div(pos_cards, style={'display': 'grid', 'gridTemplateColumns': 'repeat(3, 1fr)', 'gap': '5px', 'maxHeight': '200px', 'overflowY': 'auto', 'paddingRight': '2px'})
        else:
            grid_b = html.Div("No saved positions found in alpha_book_positions.parquet.", style=_sub)

        table_div = html.Div([
            html.Div([
                html.Div([
                    html.Span('▌', style={'color': THEME['accent'], 'fontSize': '14px', 'marginRight': '6px', 'verticalAlign': 'middle'}),
                    html.Span('Candidate Instruments', style={'color': THEME['text_main'], 'fontSize': '12px', 'fontWeight': '700', 'verticalAlign': 'middle'}),
                    html.Span(f"  {len(instruments)} trades", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '6px', 'verticalAlign': 'middle'}),
                ], style={'marginBottom': '8px', 'paddingBottom': '5px', 'borderBottom': f"1px solid {THEME['accent']}33"}),
                grid_a,
            ]),
            html.Div([
                html.Div([
                    html.Span('▌', style={'color': THEME['warning'], 'fontSize': '14px', 'marginRight': '6px', 'verticalAlign': 'middle'}),
                    html.Span('Saved Positions', style={'color': THEME['text_main'], 'fontSize': '12px', 'fontWeight': '700', 'verticalAlign': 'middle'}),
                    html.Span(f"  {len(positions)} trades", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '6px', 'verticalAlign': 'middle'}),
                    html.Span(' · read-only', style={'color': THEME['text_sub'], 'fontSize': '10px', 'marginLeft': '4px', 'fontStyle': 'italic'}),
                ], style={'marginBottom': '8px', 'paddingBottom': '5px', 'borderBottom': f"1px solid {THEME['warning']}33"}),
                grid_b,
            ]),
        ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '12px'})

        _inst_key_set = {_entry_key(e) for e in instruments}
        all_instruments = instruments + [p for p in positions if _entry_key(p) not in _inst_key_set]

        def _col_key(e):
            return display_key(e.get('spread_type', ''), e.get('instrument', ''))

        valid_ids = [_col_key(e) for e in all_instruments if _col_key(e) in matrix_cols]

        if matrix_data and len(valid_ids) >= 2:
            sub_dict = {
                col: {row: matrix_data[col].get(row, np.nan) for row in valid_ids}
                for col in valid_ids if col in matrix_data
            }
            sub_matrix = pd.DataFrame(sub_dict).reindex(index=valid_ids, columns=valid_ids)

            corr_vals = sub_matrix.values.copy()
            mask_upper = np.triu(np.ones(corr_vals.shape), k=0).astype(bool)
            corr_vals[mask_upper] = np.nan

            heatmap = go.Figure(data=go.Heatmap(
                z=corr_vals,
                x=sub_matrix.columns.tolist(),
                y=sub_matrix.index.tolist(),
                colorscale=_ALPHA_CORR_COLORSCALE,
                zmin=-1,
                zmax=1,
                hovertemplate='%{y} vs %{x}<br>Corr: %{z:.3f}<extra></extra>',
            ))
            heatmap.update_layout(
                title='Curated Correlation Matrix',
                height=max(260, 28 * len(valid_ids) + 100),
                margin=dict(l=110, r=20, t=40, b=80),
                plot_bgcolor=THEME['bg_main'],
                paper_bgcolor=THEME['bg_main'],
                font=dict(color=THEME['text_main'], size=10),
                xaxis=dict(tickangle=45),
            )
            corr_div = html.Div([dcc.Graph(figure=heatmap)])
        else:
            corr_div = html.Div('Click ↻ Recalculate Correlation to build the matrix for all instruments.', style=_sub)

        return table_div, corr_div
