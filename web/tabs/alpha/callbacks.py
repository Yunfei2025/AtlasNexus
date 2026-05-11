# -*- coding: utf-8 -*-
"""Dash callback registration for the Alpha Book tabs."""

from __future__ import annotations

import json as _json
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from dash import dcc, html, dash_table, callback_context, no_update
from dash.dependencies import Input, Output, State, ALL
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go

from settings.paths import DIR_INPUT as _DIR_INPUT

from .data import (
    THEME, SPREAD_CATEGORIES, ZSCORE_ENTRY_THRESHOLD, MACRO_PREFIX,
    _get_input_dir, _load_pickle_safe,
    load_spread_data, load_spread_timeseries, load_carry_roll_timeseries,
    load_macro_series, _get_duration_mult,
)

_SUMMARY_ALPHA_PARQUET = str(_DIR_INPUT / 'summary_alpha_portfolio.parquet')
from .scoring import (
    compute_spread_correlation, rank_low_correlation_pairs,
    _compute_risk_parity_weights, compute_scan_score,
)
from .layouts import build_individual_backtest_panel, build_portfolio_backtest_panel
from .backtest import run_spread_backtest, run_trend_backtest_dc, build_backtest_results_display


def register_alpha_callbacks(app) -> None:
    """Register all callbacks for the Alpha Book tabs."""

    # -------------------------------------------------------------------------
    # CANDIDATES: Scan Button
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('alpha-candidates-table-container', 'children'),
         Output('alpha-scan-status', 'children'),
         Output('alpha-selected-candidates', 'data'),
         Output('alpha-regime-store', 'data')],
        Input('alpha-scan-btn', 'n_clicks'),
        [State('alpha-spread-categories', 'value'),
         State('alpha-zscore-threshold', 'value'),
         State('alpha-direction-filter', 'value')],
        prevent_initial_call=True
    )
    def scan_candidates(n_clicks, categories, zscore_thd, direction):
        if not n_clicks or not categories:
            return html.Div("Select spread categories and click Scan.", style={'color': THEME['text_sub']}), "", [], {}

        try:
            z_thd = float(zscore_thd) if zscore_thd is not None else float(ZSCORE_ENTRY_THRESHOLD)
        except Exception:
            z_thd = float(ZSCORE_ENTRY_THRESHOLD)

        try:
            from curves.refreshers.alpha import load_alpha_candidates

            obj = load_alpha_candidates(
                dir_input=_get_input_dir(),
                refresh=True,
                allowed_categories=categories,
                zscore_threshold=z_thd,
                max_per_style=20,
                lookback_days=252,
                max_abs_corr=0.6,
                top_n_low_corr=10,
            )
            df_all = obj.get('candidates')
            df_low = obj.get('selected_lowcorr')
            if isinstance(df_all, pd.DataFrame) and not df_all.empty:
                pass
            else:
                df_all = pd.DataFrame()
            if not isinstance(df_low, pd.DataFrame):
                df_low = pd.DataFrame()
        except Exception:
            df_all = pd.DataFrame()
            df_low = pd.DataFrame()

        scanned_time = datetime.now().strftime('%H:%M:%S')

        if df_all.empty:
            return (
                html.Div(f"No candidates found (MR rows require stationary=YES, zscore≥{z_thd:g}).", style={'color': THEME['warning']}),
                f"Scanned at {scanned_time}", [], {},
            )

        if 'Zscore' in df_all.columns and 'style' in df_all.columns:
            style_s = df_all['style'].astype(str).str.strip().str.lower()
            is_mr_row = style_s.eq('meanreversion')
            if direction == 'buy':
                df_all = df_all[(~is_mr_row) | (df_all['Zscore'] >= z_thd)].copy()
            elif direction == 'sell':
                df_all = df_all[(~is_mr_row) | (df_all['Zscore'] <= -z_thd)].copy()

        if df_all.empty:
            return (
                html.Div(f"Candidates exist, but none match direction filter at zscore≥{z_thd:g}.", style={'color': THEME['warning']}),
                f"Scanned at {scanned_time}", [], {},
            )

        if 'direction' not in df_all.columns and 'Zscore' in df_all.columns:
            df_all = df_all.copy()
            df_all['direction'] = df_all['Zscore'].apply(lambda z: 'BUY' if float(z) > 0 else 'SELL')

        if 'score' not in df_all.columns:
            df_all = compute_scan_score(df_all)
            if 'composite_score_preview' in df_all.columns:
                df_all = df_all.copy()
                df_all['score'] = pd.to_numeric(df_all['composite_score_preview'], errors='coerce')

        if 'score' in df_all.columns:
            df_all = df_all.sort_values('score', ascending=False)
        elif 'abs_zscore' in df_all.columns:
            df_all = df_all.sort_values('abs_zscore', ascending=False)

        df_all = df_all.copy()
        _PCT_TYPES = {'TBondCurve', 'CBondCurve', 'TBondSwap', 'CBondSwap', 'TenorSpread', 'SwapSpread'}
        if 'spread_type' in df_all.columns:
            _pct_mask = df_all['spread_type'].isin(_PCT_TYPES)
            for _col in ('spread', 'mean', 'vol', 'risk_vol_63d'):
                if _col in df_all.columns:
                    df_all.loc[_pct_mask, _col] = (
                        pd.to_numeric(df_all.loc[_pct_mask, _col], errors='coerce') * 100.0
                    )
        _spread_v = pd.to_numeric(df_all.get('spread', pd.Series(dtype=float)), errors='coerce')
        _mean_v   = pd.to_numeric(df_all.get('mean',   pd.Series(dtype=float)), errors='coerce')
        _risk_vol = (
            pd.to_numeric(df_all['risk_vol_63d'], errors='coerce').abs()
            if 'risk_vol_63d' in df_all.columns
            else pd.Series(np.nan, index=df_all.index, dtype=float)
        )
        _ou_vol  = pd.to_numeric(df_all.get('vol', pd.Series(dtype=float)), errors='coerce').abs()
        _vol_v   = _risk_vol.where(_risk_vol.gt(0) & _risk_vol.notna(), _ou_vol)
        _style_v = df_all.get('style', pd.Series(dtype=str)).astype(str).str.strip().str.lower()
        _is_mr_v = _style_v.eq('meanreversion')
        _dist_v  = (_spread_v - _mean_v).abs()
        _z_v     = pd.to_numeric(df_all.get('Zscore', pd.Series(dtype=float)), errors='coerce')
        _dir_v   = df_all.get('direction', pd.Series(dtype=str)).astype(str).str.strip().str.upper()
        _dir_sign_v = pd.Series(1.0, index=df_all.index, dtype=float)
        _dir_sign_v[_dir_v.eq('SELL')] = -1.0

        _trend_target_bp = (_dir_sign_v * ZSCORE_ENTRY_THRESHOLD - _z_v).abs() * _vol_v

        df_all['stop_loss'] = np.where(_is_mr_v, (_dist_v + 1.5 * _vol_v).round(4), (2.0 * _vol_v).round(4))
        df_all['profit_target'] = np.where(_is_mr_v, _dist_v.round(4), _trend_target_bp.round(4))

        _mr_display_cols = ['ID', 'spread_type', 'direction', 'regime', 'Zscore', 'spread', 'mean', 'vol', 'halflife', 'carry_roll', 'score', 'stop_loss', 'profit_target']
        _trend_display_cols = ['ID', 'spread_type', 'direction', 'regime', 'Zscore', 'spread', 'mean', 'vol', 'carry_roll', 'score', 'trend_state', 'stop_loss', 'profit_target']

        _all_display_cols = list(dict.fromkeys(_mr_display_cols + _trend_display_cols + ['style']))
        df_display = df_all.copy()
        if 'ID' not in df_display.columns and df_display.index.name == 'ID':
            df_display = df_display.reset_index()
        available_all = [c for c in _all_display_cols if c in df_display.columns]
        df_display = df_display[available_all].copy()

        for col in ['Zscore', 'spread', 'mean', 'vol', 'carry_roll', 'halflife', 'score', 'stop_loss', 'profit_target', 'trend_state', 'regime_confidence', 'efficiency_ratio', 'hurst']:
            if col in df_display.columns:
                df_display[col] = pd.to_numeric(df_display[col], errors='coerce').round(4)

        df_mr = pd.DataFrame()
        df_trend = pd.DataFrame()

        _mr_avail    = [c for c in _mr_display_cols    if c in df_display.columns]
        _trend_avail = [c for c in _trend_display_cols if c in df_display.columns]

        regime_s = (
            df_display['regime'].astype(str).str.strip().str.lower().replace('nan', 'unknown')
            if 'regime' in df_display.columns
            else pd.Series('unknown', index=df_display.index, dtype=str)
        )
        style_s = (
            df_display['style'].astype(str).str.strip().str.lower()
            if 'style' in df_display.columns
            else pd.Series('', index=df_display.index, dtype=str)
        )

        mr_by_regime    = regime_s.eq('mean_reverting')
        trend_by_regime = regime_s.eq('trending')
        uncertain_mask  = regime_s.eq('uncertain')
        no_regime       = ~mr_by_regime & ~trend_by_regime & ~uncertain_mask
        style_mr    = no_regime & style_s.eq('meanreversion')
        style_trend = no_regime & style_s.isin({'carry', 'trend', 'trendfollowing'})

        df_mr    = df_display[mr_by_regime    | uncertain_mask | style_mr   ][_mr_avail   ].copy()
        df_trend = df_display[trend_by_regime | uncertain_mask | style_trend][_trend_avail].copy()

        regime_counts  = regime_s.value_counts(dropna=False)
        regime_summary = ', '.join([f"{k}: {int(v)}" for k, v in regime_counts.items()])
        style_summary_div = html.Div(f"Regime: {regime_summary}", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '8px'})

        _table_style_table  = {'overflowX': 'auto', 'maxHeight': '300px', 'overflowY': 'auto'}
        _table_style_header = {'backgroundColor': THEME['table_header'], 'color': THEME['text_main'], 'fontWeight': 'bold', 'textAlign': 'left'}
        _table_style_cell   = {'backgroundColor': THEME['bg_card'], 'color': THEME['text_main'], 'textAlign': 'left', 'padding': '8px', 'fontSize': '12px'}
        _table_style_data_conditional = [
            {'if': {'filter_query': '{direction} = "BUY"'},  'backgroundColor': 'rgba(0, 204, 150, 0.15)'},
            {'if': {'filter_query': '{direction} = "SELL"'}, 'backgroundColor': 'rgba(239, 85, 59, 0.15)'},
            {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['table_row_odd']},
            {'if': {'filter_query': '{regime} = "trending"',      'column_id': 'regime'}, 'color': '#FF9800', 'fontWeight': 'bold'},
            {'if': {'filter_query': '{regime} = "mean_reverting"', 'column_id': 'regime'}, 'color': '#4CAF50', 'fontWeight': 'bold'},
            {'if': {'filter_query': '{regime} = "uncertain"',      'column_id': 'regime'}, 'color': '#9E9E9E'},
        ]
        _col_labels = {
            'spread_type': 'type', 'carry_roll': 'carry+roll(3m,bp)',
            'stop_loss': 'stop(bp)', 'profit_target': 'target(bp)',
            'spread': 'spread(bp)', 'mean': 'mean(bp)', 'vol': 'vol(bp)',
            'regime': 'regime', 'trend_state': 'trend', 'regime_confidence': 'reg.conf',
        }

        def _col_defs(df):
            return [{'name': _col_labels.get(c, c), 'id': c} for c in df.columns]

        mr_body = html.Div("No mean-reversion candidates under current filters.", style={'color': THEME['text_sub'], 'fontSize': '12px', 'padding': '8px'})
        if not df_mr.empty:
            mr_body = dash_table.DataTable(
                id='alpha-candidates-table-mr',
                columns=_col_defs(df_mr),
                data=df_mr.head(20).to_dict('records'),
                row_selectable='multi', selected_rows=[],
                style_table=_table_style_table, style_header=_table_style_header,
                style_cell=_table_style_cell, style_data_conditional=_table_style_data_conditional,
                page_size=20, sort_action='native',
            )

        table_mr = html.Div([html.H6(f"Mean-Reversion Candidates (max 20) - {len(df_mr)} found", style={'color': THEME['text_main'], 'marginBottom': '8px'}), style_summary_div, mr_body], style={'marginBottom': '20px'})

        trend_body = html.Div("No carry & momentum candidates under current filters.", style={'color': THEME['text_sub'], 'fontSize': '12px', 'padding': '8px'})
        if not df_trend.empty:
            trend_body = dash_table.DataTable(
                id='alpha-candidates-table-trend',
                columns=_col_defs(df_trend),
                data=df_trend.head(20).to_dict('records'),
                row_selectable='multi', selected_rows=[],
                style_table=_table_style_table, style_header=_table_style_header,
                style_cell=_table_style_cell, style_data_conditional=_table_style_data_conditional,
                page_size=20, sort_action='native',
            )

        table_trend = html.Div([html.H6(f"Carry & Momentum Candidates (max 20) - {len(df_trend)} found", style={'color': THEME['text_main'], 'marginBottom': '8px'}), style_summary_div, trend_body], style={'marginBottom': '20px'})

        table_out = html.Div([table_mr, table_trend])
        status = f"Found {len(df_all)} candidates at {scanned_time}"
        candidate_data = df_display.to_dict('records')

        regime_store: dict = {}
        if 'regime' in df_all.columns and 'ID' in df_all.columns and 'spread_type' in df_all.columns:
            for _, _r in df_all.iterrows():
                _key = f"{_r.get('spread_type', '')}|{_r.get('ID', '')}"
                _reg = str(_r.get('regime', '')).strip().lower()
                _conf = _r.get('regime_confidence', np.nan)
                try:
                    _conf_f = float(_conf)
                except Exception:
                    _conf_f = float('nan')
                regime_store[_key] = {'regime': _reg, 'score': _conf_f}

        return table_out, status, candidate_data, regime_store

    # -------------------------------------------------------------------------
    # CANDIDATES: Correlation Check
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('alpha-corr-results', 'children'),
         Output('alpha-corr-pairs-store', 'data'),
         Output('alpha-corr-matrix-store', 'data'),
         Output('alpha-curated-instruments-store', 'data')],
        Input('alpha-corr-btn', 'n_clicks'),
        [State('alpha-spread-categories', 'value'),
         State('alpha-corr-lookback', 'value'),
         State('alpha-max-corr', 'value'),
         State('alpha-selected-candidates', 'data')],
        prevent_initial_call=True
    )
    def check_correlation(n_clicks, categories, lookback, max_corr, all_candidates):
        if not n_clicks or not categories:
            return html.Div("Select categories and click Check Correlation.", style={'color': THEME['text_sub']}), [], {}, []

        corr_matrix = None

        if all_candidates and len(all_candidates) > 0:
            df_candidates = pd.DataFrame(all_candidates)
            if 'ID' in df_candidates.columns and 'spread_type' in df_candidates.columns:
                all_spreads = {}
                for _, row in df_candidates.iterrows():
                    trade_id = row.get('ID', '')
                    spread_type = row.get('spread_type', '')
                    if not trade_id or not spread_type:
                        continue
                    ts = load_spread_timeseries(spread_type)
                    if ts is not None and isinstance(ts, pd.DataFrame) and trade_id in ts.columns:
                        all_spreads[trade_id] = ts[trade_id]

                if len(all_spreads) >= 2:
                    df_spreads = pd.DataFrame(all_spreads).tail(lookback)
                    df_changes = df_spreads.diff().dropna()
                    if len(df_changes) >= 20:
                        corr_matrix = df_changes.corr()
                    else:
                        corr_matrix = None
                else:
                    corr_matrix = None

                if corr_matrix is None or corr_matrix.empty:
                    corr_matrix = None

        if corr_matrix is None:
            spread_types = []
            for cat in categories:
                if cat in SPREAD_CATEGORIES:
                    spread_types.extend(SPREAD_CATEGORIES[cat]['types'])

            if len(spread_types) == 0:
                return html.Div("No spread types selected.", style={'color': THEME['warning']}), [], {}, []

            dir_input = _get_input_dir()
            candidates_data = _load_pickle_safe(dir_input / 'Alpha-candidates.pkl')

            if candidates_data and isinstance(candidates_data, dict):
                corr_matrix = candidates_data.get('corr')

            if corr_matrix is None or not isinstance(corr_matrix, pd.DataFrame) or corr_matrix.empty:
                corr_matrix, _ = compute_spread_correlation(spread_types, lookback_days=lookback)

        if corr_matrix is None or corr_matrix.empty:
            return html.Div("Insufficient data for correlation analysis. Need at least 2 instruments with historical data.", style={'color': THEME['warning']}), [], {}, []

        low_corr_pairs = rank_low_correlation_pairs(corr_matrix, top_n=10)
        high_corr = low_corr_pairs[low_corr_pairs['AbsCorr'] > max_corr]

        top_assets = set(low_corr_pairs['Asset A'].head(10)).union(set(low_corr_pairs['Asset B'].head(10)))
        top_assets = sorted(list(top_assets))[:12]

        if len(top_assets) >= 2:
            sub_corr = corr_matrix.loc[top_assets, top_assets]
            corr_vals = sub_corr.values.copy()
            mask_upper = np.triu(np.ones(corr_vals.shape), k=1).astype(bool)
            corr_vals[mask_upper] = np.nan

            heatmap = go.Figure(data=go.Heatmap(
                z=corr_vals, x=sub_corr.columns, y=sub_corr.index,
                colorscale='RdBu', zmin=-1, zmax=1,
                hovertemplate='%{y} vs %{x}<br>Corr: %{z:.3f}<extra></extra>',
            ))
            heatmap.update_layout(
                title='Spread Correlation Matrix (Lower Triangle)', height=350,
                margin=dict(l=100, r=20, t=40, b=80),
                plot_bgcolor=THEME['bg_main'], paper_bgcolor=THEME['bg_main'],
                font=dict(color=THEME['text_main'], size=10),
                xaxis=dict(tickangle=45),
            )
            heatmap_div = dcc.Graph(figure=heatmap, style={'height': '350px'})
        else:
            heatmap_div = html.Div("Not enough assets for heatmap.", style={'color': THEME['text_sub']})

        low_corr_pairs['Correlation'] = low_corr_pairs['Correlation'].round(4)
        low_corr_pairs['AbsCorr'] = low_corr_pairs['AbsCorr'].round(4)

        pairs_table = dash_table.DataTable(
            columns=[{'name': c, 'id': c} for c in ['Asset A', 'Asset B', 'Correlation', 'AbsCorr']],
            data=low_corr_pairs[['Asset A', 'Asset B', 'Correlation', 'AbsCorr']].to_dict('records'),
            style_table={'overflowX': 'auto', 'maxHeight': '200px'},
            style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_main'], 'fontWeight': 'bold'},
            style_cell={'backgroundColor': THEME['bg_card'], 'color': THEME['text_main'], 'fontSize': '11px', 'padding': '5px'},
            style_data_conditional=[{'if': {'filter_query': f'{{AbsCorr}} > {max_corr}'}, 'backgroundColor': 'rgba(239, 85, 59, 0.2)'}],
            page_size=10,
        )

        warning_div = html.Div()
        if len(high_corr) > 0:
            warning_div = html.Div([
                html.P(f"⚠️ {len(high_corr)} pairs exceed max correlation threshold ({max_corr}). "
                       "Consider removing correlated candidates before sizing.",
                       style={'color': THEME['warning'], 'fontSize': '12px', 'marginTop': '10px'})
            ])

        pairs_data = low_corr_pairs.to_dict('records') if isinstance(low_corr_pairs, pd.DataFrame) else []

        id_to_type: dict = {}
        if all_candidates:
            for c in all_candidates:
                if 'ID' in c and 'spread_type' in c:
                    id_to_type[c['ID']] = c['spread_type']

        seen_insts: set = set()
        curated_instruments: list = []
        for _, pair_row in low_corr_pairs.iterrows():
            for col in ['Asset A', 'Asset B']:
                inst = pair_row[col]
                if inst not in seen_insts and inst in corr_matrix.columns:
                    seen_insts.add(inst)
                    curated_instruments.append({'spread_type': id_to_type.get(inst, 'Unknown'), 'instrument': inst})
                    if len(curated_instruments) >= 10:
                        break
            if len(curated_instruments) >= 10:
                break

        return html.Div([
            heatmap_div,
            html.H6("Lowest Correlation Pairs", style={'color': THEME['text_main'], 'marginTop': '15px', 'marginBottom': '10px'}),
            pairs_table,
            warning_div,
        ]), pairs_data, corr_matrix.to_dict(), curated_instruments

    # -------------------------------------------------------------------------
    # CANDIDATES: Cascade instrument dropdown from spread type
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('alpha-add-instrument', 'options'),
         Output('alpha-add-instrument', 'value')],
        Input('alpha-add-spread-type', 'value'),
        [State('alpha-corr-matrix-store', 'data'),
         State('alpha-selected-candidates', 'data')],
    )
    def cascade_add_instrument(spread_type, matrix_data, all_candidates):
        if not spread_type:
            return [], None

        df = load_spread_data(spread_type)
        if df is not None:
            opts = [{'label': i, 'value': i} for i in sorted(df.index.tolist())]
        else:
            opts = []

        return opts, (opts[0]['value'] if opts else None)

    # -------------------------------------------------------------------------
    # CANDIDATES: Add / delete instruments in curated list
    # -------------------------------------------------------------------------
    @app.callback(
        Output('alpha-curated-instruments-store', 'data'),
        [Input('alpha-add-trade-btn', 'n_clicks'),
         Input({'type': 'curated-del', 'index': ALL}, 'n_clicks')],
        [State('alpha-curated-instruments-store', 'data'),
         State('alpha-add-spread-type', 'value'),
         State('alpha-add-instrument', 'value')],
        prevent_initial_call=True,
    )
    def mutate_curated_instruments(add_clicks, del_clicks, current, spread_type, instrument):
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        current = current or []

        raw_prop = ctx.triggered[0]['prop_id']
        raw_id   = raw_prop.rsplit('.', 1)[0]
        try:
            trig_dict = _json.loads(raw_id)
        except (ValueError, TypeError):
            trig_dict = None

        if raw_id == 'alpha-add-trade-btn':
            if not spread_type or not instrument:
                raise PreventUpdate
            if any(e['instrument'] == instrument for e in current):
                raise PreventUpdate
            return current + [{'spread_type': spread_type, 'instrument': instrument}]

        if trig_dict and trig_dict.get('type') == 'curated-del':
            if not any(nc for nc in del_clicks if nc):
                raise PreventUpdate
            idx = trig_dict['index']
            return [e for i, e in enumerate(current) if i != idx]

        raise PreventUpdate

    # -------------------------------------------------------------------------
    # CANDIDATES: Render curated instrument table + curated correlation view
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('alpha-curated-table-div', 'children'),
         Output('alpha-curated-corr-div', 'children')],
        [Input('alpha-curated-instruments-store', 'data'),
         Input('an-alpha-subtabs', 'value'),
         Input('alpha-corr-matrix-store', 'data')],
    )
    def render_curated_content(instruments, active_subtab, matrix_data):
        if active_subtab is not None and active_subtab != 'portfolio':
            raise PreventUpdate

        _sub = {'color': THEME['text_sub'], 'fontSize': '12px', 'fontStyle': 'italic'}

        if not instruments:
            return html.Div("No instruments in list — run Check Correlation in the Candidates subtab first.", style=_sub), html.Div()

        matrix_cols = set(matrix_data.keys()) if matrix_data else set()

        _cell = {'padding': '6px 10px', 'fontSize': '12px', 'color': THEME['text_main']}
        _hdr  = {**_cell, 'color': THEME['text_sub'], 'fontWeight': '600', 'fontSize': '11px', 'borderBottom': f"1px solid {THEME['table_header']}"}

        header_row = html.Tr([
            html.Th("Spread Type", style=_hdr),
            html.Th("Instrument",  style=_hdr),
            html.Th("In Matrix",   style={**_hdr, 'textAlign': 'center'}),
            html.Th("",            style=_hdr),
        ])

        body_rows = []
        for i, entry in enumerate(instruments):
            stype = entry.get('spread_type', '')
            inst  = entry.get('instrument', '')
            in_m  = inst in matrix_cols
            indicator = (html.Span("✓", style={'color': THEME['success']}) if in_m else html.Span("—", style={'color': THEME['text_sub']}))
            body_rows.append(html.Tr([
                html.Td(stype, style=_cell),
                html.Td(inst,  style={**_cell, 'fontWeight': '500'}),
                html.Td(indicator, style={**_cell, 'textAlign': 'center'}),
                html.Td(
                    html.Button("×", id={'type': 'curated-del', 'index': i}, n_clicks=0,
                                style={'background': 'none', 'border': f"1px solid {THEME['danger']}", 'color': THEME['danger'], 'borderRadius': '3px', 'cursor': 'pointer', 'padding': '1px 7px', 'fontSize': '13px', 'lineHeight': '1.2'}),
                    style={'textAlign': 'center'},
                ),
            ], style={'borderBottom': 'rgba(42,82,152,0.25) solid 1px'}))

        table_div = html.Div(
            html.Table([html.Thead(header_row), html.Tbody(body_rows)], style={'width': '100%', 'borderCollapse': 'collapse'}),
            style={'overflowY': 'auto', 'maxHeight': '240px', 'border': f"1px solid {THEME['table_header']}", 'borderRadius': '4px'},
        )

        valid_ids = [e['instrument'] for e in instruments if e['instrument'] in matrix_cols]

        if matrix_data and len(valid_ids) >= 2:
            sub_dict = {
                col: {row: matrix_data[col].get(row, np.nan) for row in valid_ids}
                for col in valid_ids if col in matrix_data
            }
            sub_matrix = pd.DataFrame(sub_dict).reindex(index=valid_ids, columns=valid_ids)

            corr_vals = sub_matrix.values.copy()
            mask_upper = np.triu(np.ones(corr_vals.shape), k=1).astype(bool)
            corr_vals[mask_upper] = np.nan

            hm = go.Figure(data=go.Heatmap(
                z=corr_vals, x=sub_matrix.columns.tolist(), y=sub_matrix.index.tolist(),
                colorscale='RdBu', zmin=-1, zmax=1,
                hovertemplate='%{y} vs %{x}<br>Corr: %{z:.3f}<extra></extra>',
            ))
            hm.update_layout(
                title='Curated Instrument Correlation',
                height=max(260, 28 * len(valid_ids) + 100),
                margin=dict(l=110, r=20, t=40, b=80),
                plot_bgcolor=THEME['bg_main'], paper_bgcolor=THEME['bg_main'],
                font=dict(color=THEME['text_main'], size=10),
                xaxis=dict(tickangle=45),
            )

            curated_pairs = rank_low_correlation_pairs(sub_matrix, top_n=len(valid_ids) * 3)
            curated_pairs['Correlation'] = curated_pairs['Correlation'].round(4)
            curated_pairs['AbsCorr']     = curated_pairs['AbsCorr'].round(4)

            pairs_tbl = dash_table.DataTable(
                columns=[{'name': c, 'id': c} for c in ['Asset A', 'Asset B', 'Correlation', 'AbsCorr']],
                data=curated_pairs[['Asset A', 'Asset B', 'Correlation', 'AbsCorr']].to_dict('records'),
                style_table={'overflowX': 'auto', 'maxHeight': '180px'},
                style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_sub'], 'fontWeight': '600', 'fontSize': '11px', 'padding': '6px 10px'},
                style_cell={'backgroundColor': THEME['bg_card'], 'color': THEME['text_main'], 'fontSize': '12px', 'padding': '6px 10px'},
                page_size=15,
            )

            not_in_count = len(instruments) - len(valid_ids)
            notice = (
                html.P(
                    f"ℹ️ {not_in_count} instrument(s) marked '—' are not yet in the matrix. "
                    "Click ↻ Recalculate Correlation below to rebuild the matrix including all curated instruments.",
                    style={**_sub, 'marginTop': '6px'},
                ) if not_in_count > 0 else html.Div()
            )

            corr_div = html.Div([
                html.H6("Curated Correlation Matrix", style={'color': THEME['text_main'], 'marginBottom': '8px'}),
                dcc.Graph(figure=hm),
                html.H6("Curated Pairs — Lowest Correlation", style={'color': THEME['text_main'], 'marginTop': '14px', 'marginBottom': '8px'}),
                pairs_tbl,
                notice,
            ])

        elif len(valid_ids) < 2:
            corr_div = html.Div("Click ↻ Recalculate Correlation to build the matrix for your curated instruments.", style=_sub)

        return table_div, corr_div

    # -------------------------------------------------------------------------
    # PORTFOLIO: Recalculate correlation matrix for the curated instrument list
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('alpha-corr-matrix-store', 'data', allow_duplicate=True),
         Output('alpha-curated-recalc-status', 'children')],
        Input('alpha-curated-recalc-btn', 'n_clicks'),
        [State('alpha-curated-instruments-store', 'data'),
         State('alpha-corr-lookback', 'value')],
        prevent_initial_call=True,
    )
    def recalc_curated_correlation(n_clicks, instruments, lookback):
        if not instruments:
            raise PreventUpdate

        lookback = lookback or 252

        all_spreads = {}
        for entry in instruments:
            inst = entry.get('instrument', '')
            spread_type = entry.get('spread_type', '')
            if not inst or not spread_type:
                continue
            ts = load_spread_timeseries(spread_type)
            if ts is not None and isinstance(ts, pd.DataFrame) and inst in ts.columns:
                all_spreads[inst] = ts[inst]

        if len(all_spreads) < 2:
            return no_update, "⚠ Need ≥ 2 instruments with time-series data."

        df_spreads = pd.DataFrame(all_spreads).tail(lookback)
        df_changes = df_spreads.diff().dropna()

        if len(df_changes) < 20:
            return no_update, "⚠ Insufficient history (< 20 days)."

        corr_matrix = df_changes.corr()
        ts_now = pd.Timestamp.now().strftime('%H:%M:%S')
        status = f"✓ Recalculated at {ts_now} ({len(all_spreads)} instruments, {len(df_changes)} days)"
        return corr_matrix.to_dict(), status

    # -------------------------------------------------------------------------
    # PORTFOLIO: Run Scoring & Allocation
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('alpha-scored-table-container', 'children'),
         Output('alpha-risk-chart-container', 'children'),
         Output('alpha-portfolio-summary', 'children'),
         Output('alpha-optimized-weights', 'data')],
        Input('alpha-score-btn', 'n_clicks'),
        [State('alpha-selected-candidates', 'data'),
         State('alpha-mom-k', 'value'),
         State('alpha-mom-window', 'value'),
         State('alpha-total-capital', 'value'),
         State('alpha-alloc-method', 'value'),
         State('alpha-enforce-corr', 'value'),
         State('alpha-curated-instruments-store', 'data')],
        prevent_initial_call=True
    )
    def run_scoring(n_clicks, candidates, mom_k, mom_window, total_capital, alloc_method, enforce_corr, curated_instruments):
        if not n_clicks:
            return html.Div(), html.Div(), html.Div(), []

        if not candidates:
            return (
                html.Div("No candidates. Run scan in Candidates tab first.", style={'color': THEME['warning']}),
                html.Div(), html.Div(), []
            )

        try:
            total_capital = float(total_capital) if total_capital is not None else 10.0
            total_capital_mm = total_capital * 1000

            df = pd.DataFrame(candidates)

            if curated_instruments:
                curated_ids = {e['instrument'] for e in curated_instruments}
                df_curated = df[df['ID'].isin(curated_ids)].copy()
                present_ids = set(df_curated['ID'].tolist())
                median_score = df_curated['score'].median() if len(df_curated) > 0 and 'score' in df_curated.columns else 0.01
                extra_rows = []
                _snap_cache: Dict[str, Any] = {}
                _snap_cols = ['Zscore', 'spread', 'vol', 'halflife', 'stationary',
                              'carry_roll', 'mean', 'reg_slope_per_day',
                              'expected_return_H', 'risk', 'direction', 'style',
                              'score', 'ttm_used', 'category']
                for entry in curated_instruments:
                    if entry['instrument'] not in present_ids:
                        inst  = entry['instrument']
                        stype = entry['spread_type']
                        cat = next(
                            (c for c, info in SPREAD_CATEGORIES.items() if stype in info.get('types', [])),
                            stype,
                        )
                        inst_row: Dict[str, Any] = {'ID': inst, 'spread_type': stype, 'category': cat}
                        if stype not in _snap_cache:
                            _snap_cache[stype] = load_spread_data(stype)
                        snap = _snap_cache[stype]
                        if snap is not None and inst in snap.index:
                            snap_row = snap.loc[inst]
                            for col in _snap_cols:
                                if col in snap_row.index and pd.notna(snap_row.get(col)):
                                    inst_row[col] = snap_row[col]
                        inst_row.setdefault('score', median_score)
                        inst_row.setdefault('direction', 'N/A')
                        extra_rows.append(inst_row)
                if extra_rows:
                    df_curated = pd.concat([df_curated, pd.DataFrame(extra_rows)], ignore_index=True)
                df = df_curated

            if 'score' not in df.columns:
                df['score'] = 0.0
            df['score'] = pd.to_numeric(df['score'], errors='coerce').fillna(0.0)
            df_scored = df.sort_values('score', ascending=False)

            if not curated_instruments:
                df_scored = df_scored[df_scored['score'] > 0.001].copy()

            n_trades = len(df_scored)
            if n_trades == 0:
                return (
                    html.Div("No candidates with positive expected edge. Run Scan in Candidates tab first.", style={'color': THEME['warning']}),
                    html.Div(), html.Div(), []
                )

            alloc_method = alloc_method or 'risk_parity'

            if alloc_method == 'equal':
                df_scored['weight'] = 1 / n_trades
            elif alloc_method == 'score':
                score_sum = df_scored['score'].sum()
                df_scored['weight'] = df_scored['score'] / score_sum if score_sum > 0 else 1 / n_trades
            elif alloc_method == 'inv_vol':
                if 'vol' in df_scored.columns:
                    inv_vol = 1 / df_scored['vol'].replace(0, np.nan).fillna(df_scored['vol'].mean())
                    df_scored['weight'] = inv_vol / inv_vol.sum()
                else:
                    df_scored['weight'] = 1 / n_trades
            else:  # risk_parity
                try:
                    weights_dict, risk_contrib = _compute_risk_parity_weights(df_scored)
                    df_scored['weight'] = df_scored['ID'].map(weights_dict).fillna(1 / n_trades)
                    rc_map = dict(zip(weights_dict.keys(), risk_contrib))
                    df_scored['risk_contribution'] = df_scored['ID'].map(rc_map).fillna(df_scored['weight'])
                except Exception as e:
                    print(f"⚠ Risk parity failed: {e}, falling back to equal weights")
                    df_scored['weight'] = 1 / n_trades
                    df_scored['risk_contribution'] = 1 / n_trades

            weight_sum = df_scored['weight'].sum()
            if weight_sum > 0 and abs(weight_sum - 1.0) > 1e-9:
                df_scored['weight'] = df_scored['weight'] / weight_sum

            df_scored['notional_mm'] = (np.floor(df_scored['weight'] * total_capital_mm / 10) * 10)
            df_scored['_duration'] = df_scored.apply(
                lambda r: _get_duration_mult(str(r.get('ID', '')), str(r.get('spread_type', ''))),
                axis=1,
            )
            df_scored['DV01_k'] = (df_scored['notional_mm'] * df_scored['_duration'] / 10_000 * 1_000).round(1)
            df_scored.drop(columns=['_duration'], inplace=True)

            df_nonzero = df_scored[df_scored['weight'] > 0.0001].copy()
            optimized_results = df_nonzero.to_dict('records')

            display_cols = [
                'ID', 'spread_type', 'category', 'style', 'direction',
                'Zscore', 'spread', 'carry_roll', 'vol',
                'reg_slope_per_day', 'ttm_used', 'expected_return_H', 'risk',
                'score', 'weight', 'risk_contribution', 'notional_mm', 'DV01_k',
            ]
            available_cols = [c for c in display_cols if c in df_scored.columns]
            df_display = df_scored[available_cols].copy()

            for col in df_display.columns:
                if col == 'risk_contribution':
                    df_display[col] = df_display[col].round(2)
                elif df_display[col].dtype in ['float64', 'float32']:
                    df_display[col] = df_display[col].round(4)

            if 'carry_roll' in df_display.columns and 'direction' in df_display.columns:
                _sell = df_display['direction'].astype(str).str.strip().str.upper().eq('SELL')
                df_display.loc[_sell, 'carry_roll'] = (
                    pd.to_numeric(df_display.loc[_sell, 'carry_roll'], errors='coerce')
                    .multiply(-1).round(4)
                )

            summary_row: dict = {c: "" for c in df_display.columns}
            summary_row['ID'] = 'TOTAL'
            for col, decimals in [('weight', 4), ('risk_contribution', 2), ('notional_mm', 0), ('DV01_k', 1)]:
                if col in df_display.columns:
                    total = df_display[col].sum()
                    summary_row[col] = round(total, decimals)
            df_display = pd.concat([df_display, pd.DataFrame([summary_row])], ignore_index=True)

            conditional_style = []
            if 'direction' in df_display.columns:
                conditional_style = [
                    {'if': {'filter_query': '{direction} = "BUY"'},  'backgroundColor': 'rgba(0, 204, 150, 0.15)'},
                    {'if': {'filter_query': '{direction} = "SELL"'}, 'backgroundColor': 'rgba(239, 85, 59, 0.15)'},
                ]

            last_row_idx = len(df_display) - 1
            conditional_style += [{'if': {'row_index': last_row_idx}, 'fontWeight': 'bold', 'borderTop': f'1px solid {THEME["accent"]}'}]

            table = dash_table.DataTable(
                id='alpha-scored-table',
                columns=[{'name': c, 'id': c} for c in df_display.columns],
                data=df_display.to_dict('records'),
                style_table={'overflowX': 'auto', 'maxHeight': '350px', 'overflowY': 'auto'},
                style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_main'], 'fontWeight': 'bold', 'textAlign': 'left'},
                style_cell={'backgroundColor': THEME['bg_card'], 'color': THEME['text_main'], 'textAlign': 'left', 'padding': '8px', 'fontSize': '12px'},
                style_data_conditional=conditional_style,
                sort_action='native', page_size=15,
            )

            summary = html.Div([
                html.Div([
                    html.Div([html.Strong("Total Trades: ", style={'color': THEME['text_sub']}), html.Span(f"{len(df_scored)}", style={'color': THEME['text_main']})], style={'marginRight': '30px'}),
                    html.Div([html.Strong("Capital Allocated: ", style={'color': THEME['text_sub']}), html.Span(f"{total_capital:.1f} B CNY", style={'color': THEME['text_main']})], style={'marginRight': '30px'}),
                    html.Div([html.Strong("Avg Score: ", style={'color': THEME['text_sub']}), html.Span(f"{df_scored['score'].mean():.3f}", style={'color': THEME['text_main']})], style={'marginRight': '30px'}),
                    html.Div([html.Strong("Risk Parity: ", style={'color': THEME['text_sub']}), html.Span(f"σ(RC)={df_scored['risk_contribution'].std():.3f}" if 'risk_contribution' in df_scored.columns else "N/A", style={'color': THEME['text_main']})], style={'marginRight': '30px'}),
                    html.Div([html.Strong("BUY/SELL: ", style={'color': THEME['text_sub']}), html.Span(f"{(df_scored['direction'] == 'BUY').sum()} / {(df_scored['direction'] == 'SELL').sum()}" if 'direction' in df_scored.columns else "N/A", style={'color': THEME['text_main']})]),
                ], style={'display': 'flex', 'flexWrap': 'wrap', 'marginBottom': '15px'}),
                html.Div([
                    html.Strong("By Style: ", style={'color': THEME['text_sub']}),
                    html.Span(" | ".join([f"{style}: {count}" for style, count in df_scored.groupby('style').size().items()]), style={'color': THEME['text_main'], 'fontSize': '12px'}) if 'style' in df_scored.columns else "",
                ]),
            ])

            risk_chart = html.Div()
            if 'risk_contribution' in df_scored.columns and 'weight' in df_scored.columns:
                fig = go.Figure()
                df_chart = df_scored.nlargest(15, 'weight')[['ID', 'weight', 'risk_contribution']].copy()
                fig.add_trace(go.Bar(x=df_chart['ID'], y=df_chart['weight'] * 100, name='Weight (%)', marker_color=THEME['accent'], yaxis='y'))
                fig.add_trace(go.Bar(x=df_chart['ID'], y=df_chart['risk_contribution'] * 100, name='Risk Contribution (%)', marker_color=THEME['success'], yaxis='y'))
                fig.update_layout(
                    title={'text': 'Portfolio Allocation: Weights vs Risk Contributions', 'font': {'size': 14, 'color': THEME['text_main']}},
                    xaxis={'title': 'Trade ID', 'tickangle': -45, 'color': THEME['text_main']},
                    yaxis={'title': 'Percentage (%)', 'color': THEME['text_main']},
                    barmode='group', template='plotly_dark',
                    paper_bgcolor=THEME['bg_card'], plot_bgcolor=THEME['bg_card'],
                    height=400, margin={'l': 60, 'r': 20, 't': 50, 'b': 100},
                    legend={'orientation': 'h', 'y': 1.1, 'x': 0.5, 'xanchor': 'center'},
                )
                risk_chart = dcc.Graph(figure=fig, config={'displayModeBar': False})

            # ── Save Alpha snapshot for Summary tab ───────────────────────────────
            try:
                import pathlib as _pl
                _pl.Path(_SUMMARY_ALPHA_PARQUET).parent.mkdir(parents=True, exist_ok=True)
                _save_cols = [
                    c for c in [
                        'ID', 'spread_type', 'category', 'style', 'direction',
                        'Zscore', 'spread', 'carry_roll', 'vol', 'halflife',
                        'notional_mm', 'DV01_k', 'weight', 'risk_contribution',
                    ] if c in df_scored.columns
                ]
                _snap = df_scored[_save_cols].copy()
                _snap['_timestamp'] = datetime.now().isoformat()
                _snap.to_parquet(_SUMMARY_ALPHA_PARQUET, index=False)
                print(f"✓ Alpha portfolio snapshot saved → {_SUMMARY_ALPHA_PARQUET}")
            except Exception as _se:
                print(f"Warning: Could not save Alpha snapshot: {_se}")

            return table, risk_chart, summary, optimized_results

        except Exception as e:
            import traceback
            error_msg = f"Error in portfolio optimization: {str(e)}"
            print(f"[ERROR] {error_msg}")
            print(traceback.format_exc())
            return (
                html.Div(error_msg, style={'color': THEME['warning'], 'padding': '10px'}),
                html.Div(),
                html.Div(f"Details: {str(e)[:100]}", style={'color': THEME['warning'], 'fontSize': '11px'}),
                []
            )

    # -------------------------------------------------------------------------
    # BACKTEST: Mode Tab Selector
    # -------------------------------------------------------------------------
    @app.callback(
        Output('backtest-mode-content', 'children'),
        Input('backtest-mode-tabs', 'value'),
    )
    def render_backtest_mode(mode):
        if mode == 'individual':
            return build_individual_backtest_panel()
        elif mode == 'portfolio':
            return build_portfolio_backtest_panel()
        return html.Div("Select a backtest mode.")

    # -------------------------------------------------------------------------
    # BACKTEST: Populate Instrument Dropdown
    # -------------------------------------------------------------------------
    @app.callback(
        Output('bt-instrument', 'options'),
        Input('bt-spread-type', 'value'),
    )
    def update_instrument_options(spread_type):
        if not spread_type:
            return []

        macro_options = []
        if spread_type == 'TBondSwap':
            macro_options = [
                {'label': 'Macro: TBond-FR007:1Y', 'value': f"{MACRO_PREFIX}TBond-FR007:1Y"},
                {'label': 'Macro: TBond-FR007:5Y', 'value': f"{MACRO_PREFIX}TBond-FR007:5Y"},
            ]

        df = load_spread_data(spread_type)
        if df is None or df.empty:
            return macro_options

        options = [{'label': str(idx), 'value': str(idx)} for idx in df.index]
        return macro_options + options

    # -------------------------------------------------------------------------
    # BACKTEST: Auto-detect regime and set trade style from instrument
    # -------------------------------------------------------------------------
    _BT_BASE_OPTIONS = [
        {'label': ' Mean-Reversion', 'value': 'mr'},
        {'label': ' Carry', 'value': 'carry'},
        {'label': ' Trend (Directional-Change)', 'value': 'trend'},
    ]
    _BT_DISABLED_OPTIONS = [
        {'label': ' Mean-Reversion', 'value': 'mr', 'disabled': True},
        {'label': ' Carry', 'value': 'carry', 'disabled': True},
        {'label': ' Trend (Directional-Change)', 'value': 'trend', 'disabled': True},
    ]
    _BT_STYLE_DIV_HIDDEN  = {'marginBottom': '5px', 'display': 'none'}
    _BT_STYLE_DIV_VISIBLE = {'marginBottom': '5px'}

    @app.callback(
        [Output('bt-trade-style', 'value'),
         Output('bt-trade-style', 'options'),
         Output('bt-regime-badge', 'children'),
         Output('bt-trade-style-div', 'style')],
        [Input('bt-spread-type', 'value'),
         Input('bt-instrument', 'value')],
        [State('alpha-regime-store', 'data')],
    )
    def update_trade_style_and_regime(spread_type, instrument, regime_store):
        style_key = 'mr'
        if spread_type:
            for _, info in SPREAD_CATEGORIES.items():
                if spread_type in info.get('types', []):
                    s = info.get('style', 'MeanReversion')
                    if s == 'Trend':
                        style_key = 'trend'
                    elif s == 'Carry' or (s == 'Mixed' and spread_type in ['TBondSwap', 'CBondSwap', 'TenorSpread']):
                        style_key = 'carry'
                    break

        if not instrument or not spread_type:
            return style_key, _BT_BASE_OPTIONS, "", _BT_STYLE_DIV_HIDDEN

        try:
            from curves.calibration.regime import DEFAULT_REGIME_WINDOW, compute_regime_features
            regime = 'uncertain'
            score = 0.0
            regime_source = 'time-series'

            _store_key = f"{spread_type}|{instrument}"
            _store_entry = (regime_store or {}).get(_store_key)
            if _store_entry and isinstance(_store_entry, dict):
                _stored_regime = str(_store_entry.get('regime', '')).strip().lower()
                if _stored_regime in {'mean_reverting', 'trending', 'uncertain'}:
                    regime = _stored_regime
                    regime_source = 'candidates'
                    try:
                        score = float(_store_entry.get('score', np.nan))
                    except Exception:
                        score = np.nan

            if regime_source == 'time-series' and not (isinstance(instrument, str) and instrument.startswith(MACRO_PREFIX)):
                snap_df = load_spread_data(spread_type)
                if isinstance(snap_df, pd.DataFrame) and not snap_df.empty:
                    row = None
                    if instrument in snap_df.index:
                        row = snap_df.loc[instrument]
                    elif 'ID' in snap_df.columns:
                        m = snap_df[snap_df['ID'].astype(str) == str(instrument)]
                        if not m.empty:
                            row = m.iloc[0]
                    if row is not None and isinstance(row, (pd.Series, pd.DataFrame)):
                        if isinstance(row, pd.DataFrame):
                            row = row.iloc[0]
                        snap_regime = str(row.get('regime', '')).strip().lower()
                        if snap_regime in {'mean_reverting', 'trending', 'uncertain'}:
                            regime = snap_regime
                            regime_source = 'snapshot'
                            snap_score = row.get('regime_confidence', np.nan)
                            try:
                                score = float(snap_score)
                            except Exception:
                                score = np.nan

            ts = None
            if regime_source == 'time-series':
                if isinstance(instrument, str) and instrument.startswith(MACRO_PREFIX):
                    macro_name = instrument[len(MACRO_PREFIX):]
                    ts = load_macro_series(macro_name)
                else:
                    spread_df = load_spread_timeseries(spread_type)
                    if spread_df is not None and instrument in spread_df.columns:
                        ts = spread_df[instrument].dropna()

                if ts is None or len(ts) < DEFAULT_REGIME_WINDOW + 5:
                    return style_key, _BT_BASE_OPTIONS, html.Span("Not enough history for regime detection.", style={'color': THEME['warning'], 'fontSize': '12px'}), _BT_STYLE_DIV_VISIBLE

                regime_info = compute_regime_features(ts, window=DEFAULT_REGIME_WINDOW)
                regime = regime_info.get('regime', 'uncertain')
                score  = regime_info.get('regime_score', 0.0)

            if np.isnan(score):
                score = 0.0

            regime_color = {'mean_reverting': THEME['success'], 'trending': THEME['accent'], 'uncertain': THEME['warning']}.get(regime, THEME['text_sub'])

            if regime == 'mean_reverting':
                style_key = 'mr'
                auto_options = _BT_DISABLED_OPTIONS
            elif regime == 'trending':
                style_key = 'trend'
                auto_options = _BT_DISABLED_OPTIONS
            else:
                auto_options = _BT_BASE_OPTIONS

            badge_extra = (
                html.Span("  — please select trade style manually", style={'color': THEME['warning'], 'fontSize': '11px'})
                if regime == 'uncertain' else
                html.Span(f"  (score: {score:+.2f}, source: {regime_source})", style={'color': THEME['text_sub'], 'fontSize': '11px'})
            )
            badge = html.Div([
                html.Span("Auto-detected regime: ", style={'color': THEME['text_sub'], 'fontSize': '12px'}),
                html.Span(regime.upper().replace('_', '-'), style={'color': regime_color, 'fontWeight': 'bold', 'fontSize': '13px'}),
                badge_extra,
            ])
            return style_key, auto_options, badge, _BT_STYLE_DIV_VISIBLE

        except Exception as exc:
            err_badge = html.Span(f"Regime detection error: {exc}", style={'color': THEME['warning'], 'fontSize': '11px'})
            return style_key, _BT_BASE_OPTIONS, err_badge, _BT_STYLE_DIV_VISIBLE

    # -------------------------------------------------------------------------
    # BACKTEST: Show/hide parameter panels based on trade style
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('bt-mr-params-div', 'style'),
         Output('bt-trend-params-div', 'style')],
        Input('bt-trade-style', 'value'),
    )
    def toggle_backtest_params(style):
        base_mr    = {'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}
        base_trend = {'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px', 'marginBottom': '15px'}
        if style == 'trend':
            base_mr['display'] = 'none'
        else:
            base_trend['display'] = 'none'
        return base_mr, base_trend

    # -------------------------------------------------------------------------
    # BACKTEST: Run Individual Backtest
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('bt-individual-results', 'children'),
         Output('bt-individual-status', 'children')],
        Input('bt-run-individual-btn', 'n_clicks'),
        [State('bt-spread-type', 'value'),
         State('bt-instrument', 'value'),
         State('bt-entry-z', 'value'),
         State('bt-exit-z', 'value'),
         State('bt-stop-z', 'value'),
         State('bt-max-hold', 'value'),
         State('bt-period', 'value'),
         State('bt-trade-style', 'value'),
         State('bt-theta', 'value'),
         State('bt-mom-window', 'value'),
         State('bt-vol-window', 'value'),
         State('bt-trailing-mult', 'value'),
         State('bt-carry-buffer', 'value'),
         State('bt-allow-short', 'value')],
        prevent_initial_call=True
    )
    def run_individual_backtest(
        n_clicks, spread_type, instrument, entry_z, exit_z, stop_z, max_hold, period, style,
        theta, mom_window, vol_window, trailing_mult, carry_buffer, allow_short
    ):
        if not n_clicks:
            return html.Div(), ""

        if not spread_type or not instrument:
            return html.Div("Please select spread type and instrument.", style={'color': THEME['warning']}), ""

        ts = None
        display_instrument = instrument
        if isinstance(instrument, str) and instrument.startswith(MACRO_PREFIX):
            macro_name = instrument[len(MACRO_PREFIX):]
            display_instrument = macro_name
            ts = load_macro_series(macro_name)
            if ts is not None:
                ts = ts.tail(period)
        else:
            spread_ts = load_spread_timeseries(spread_type)
            if spread_ts is None:
                return html.Div(f"No time series data available for {spread_type}.", style={'color': THEME['warning']}), ""
            if instrument in spread_ts.columns:
                ts = spread_ts[instrument].tail(period)
            else:
                return html.Div(f"Instrument {instrument} not found in data.", style={'color': THEME['warning']}), ""

        if ts is None or len(ts.dropna()) < 60:
            return html.Div("Insufficient data for backtest.", style={'color': THEME['warning']}), ""

        carry_roll_ts_instrument: Optional[pd.Series] = None
        carry_roll_bp = 0.0
        if not (isinstance(instrument, str) and instrument.startswith(MACRO_PREFIX)):
            try:
                cr_df = load_carry_roll_timeseries(spread_type)
                if isinstance(cr_df, pd.DataFrame) and not cr_df.empty:
                    if instrument in cr_df.columns:
                        carry_roll_ts_instrument = cr_df[instrument].dropna()
                    else:
                        cols_lower = {c.strip().lower(): c for c in cr_df.columns}
                        key_lower = str(instrument).strip().lower()
                        if key_lower in cols_lower:
                            carry_roll_ts_instrument = cr_df[cols_lower[key_lower]].dropna()

                snap_df = load_spread_data(spread_type)
                if isinstance(snap_df, pd.DataFrame) and not snap_df.empty:
                    row = None
                    if instrument in snap_df.index:
                        row = snap_df.loc[instrument]
                    elif 'ID' in snap_df.columns:
                        _m = snap_df['ID'].astype(str) == str(instrument)
                        if _m.any():
                            row = snap_df.loc[_m].iloc[0]

                    if row is not None:
                        for c in ['carry_roll', 'carry', 'CarryRoll3m', 'CarryRoll', 'Carry', 'carry_roll_3m']:
                            if c in row.index:
                                v = row.get(c)
                                if v is not None and np.isfinite(float(v)):
                                    carry_roll_bp = float(v)
                                    break
            except Exception:
                carry_roll_ts_instrument = None
                carry_roll_bp = 0.0

        style = style or 'mr'
        try:
            duration_mult = _get_duration_mult(instrument, spread_type)

            if style == 'trend':
                results = run_trend_backtest_dc(
                    spread_ts=ts,
                    theta=float(theta) if theta is not None else 0.02,
                    mom_window=int(mom_window) if mom_window is not None else 20,
                    vol_window=int(vol_window) if vol_window is not None else 60,
                    trailing_mult=float(trailing_mult) if trailing_mult is not None else 1.5,
                    carry_buffer=float(carry_buffer) if carry_buffer is not None else 0.0,
                    max_hold=int(max_hold) if max_hold is not None else 60,
                    allow_short=bool(allow_short and 'allow' in allow_short),
                    carry_roll_ts=carry_roll_ts_instrument,
                    carry_roll_bp=carry_roll_bp,
                    duration_mult=duration_mult,
                )
            else:
                results = run_spread_backtest(
                    spread_ts=ts,
                    entry_z=entry_z or 2.0,
                    exit_z=exit_z or 0.5,
                    stop_z=stop_z or 4.0,
                    max_hold=max_hold or 60,
                    trade_style=style,
                    carry_roll_ts=carry_roll_ts_instrument,
                    carry_roll_bp=carry_roll_bp,
                    duration_mult=duration_mult,
                )
        except Exception as exc:
            import traceback
            return html.Div(f"Backtest engine error: {exc}\n{traceback.format_exc(limit=8)}", style={'color': THEME['warning'], 'whiteSpace': 'pre-wrap', 'fontSize': '11px', 'padding': '10px'}), f"Error at {datetime.now().strftime('%H:%M:%S')}"

        status = f"Backtest completed at {datetime.now().strftime('%H:%M:%S')}"
        try:
            display = build_backtest_results_display(results, title=f"Backtest: {display_instrument} ({spread_type})")
        except Exception as exc:
            import traceback
            display = html.Div(f"Display error: {exc}\n{traceback.format_exc(limit=6)}", style={'color': THEME['warning'], 'whiteSpace': 'pre-wrap', 'fontSize': '11px', 'padding': '10px'})

        return display, status

    # -------------------------------------------------------------------------
    # BACKTEST: Portfolio Data Preview Callback
    # -------------------------------------------------------------------------
    @app.callback(
        Output('bt-portfolio-data-preview', 'children'),
        Input('alpha-optimized-weights', 'data')
    )
    def update_portfolio_preview(optimized_data):
        if not optimized_data:
            return html.P("No portfolio data loaded. Please go to the 'Portfolio' tab and run 'Calculate Score & Allocation' first.", style={'color': THEME['warning'], 'fontStyle': 'italic'})

        try:
            n_assets = len(optimized_data)
            total_weight = sum(item.get('weight', 0) for item in optimized_data)
            n_buy  = sum(1 for item in optimized_data if item.get('direction') == 'BUY')
            n_sell = sum(1 for item in optimized_data if item.get('direction') == 'SELL')

            style_counts: dict = {}
            for item in optimized_data:
                style = item.get('style', 'Unknown')
                style_counts[style] = style_counts.get(style, 0) + 1

            sorted_assets = sorted(optimized_data, key=lambda x: x.get('weight', 0), reverse=True)
            asset_list = []
            for item in sorted_assets:
                w = item.get('weight', 0)
                if w <= 0.0001:
                    continue
                asset_list.append(html.Li(f"{item.get('ID', 'Unknown')} - {w*100:.1f}% ({item.get('direction', 'N/A')})", style={'color': THEME['text_main'], 'fontSize': '11px', 'marginBottom': '3px'}))

            return html.Div([
                html.Div([
                    html.Div([html.Strong("Total Assets: ", style={'color': THEME['text_sub']}), html.Span(f"{len(asset_list)}", style={'color': THEME['success'], 'fontWeight': 'bold', 'fontSize': '16px'})], style={'marginRight': '30px'}),
                    html.Div([html.Strong("Weight Sum: ", style={'color': THEME['text_sub']}), html.Span(f"{total_weight*100:.1f}%", style={'color': THEME['text_main']})], style={'marginRight': '30px'}),
                    html.Div([html.Strong("Direction: ", style={'color': THEME['text_sub']}), html.Span(f"BUY: {n_buy} / SELL: {n_sell}", style={'color': THEME['text_main']})], style={'marginRight': '30px'}),
                    html.Div([html.Strong("Styles: ", style={'color': THEME['text_sub']}), html.Span(' | '.join([f"{k}: {v}" for k, v in style_counts.items()]), style={'color': THEME['text_main'], 'fontSize': '12px'})]),
                ], style={'display': 'flex', 'flexWrap': 'wrap', 'marginBottom': '15px'}),
                html.Div([
                    html.Strong("Active Portfolio Assets (Backtest Universe):", style={'color': THEME['text_sub'], 'display': 'block', 'marginBottom': '8px'}),
                    html.Div([html.Ul(asset_list, style={'margin': '0', 'paddingLeft': '20px'})], style={'maxHeight': '150px', 'overflowY': 'auto', 'border': '1px solid #444', 'padding': '5px', 'borderRadius': '4px'})
                ]),
            ])
        except Exception as e:
            return html.P(f"Error parsing portfolio data: {str(e)}", style={'color': THEME['danger']})

    # -------------------------------------------------------------------------
    # BACKTEST: Run Portfolio Backtest
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('bt-portfolio-results', 'children'),
         Output('bt-portfolio-status', 'children')],
        Input('bt-run-portfolio-btn', 'n_clicks'),
        [State('alpha-optimized-weights', 'data'),
         State('bt-initial-capital', 'value'),
         State('bt-txn-cost', 'value'),
         State('bt-port-period', 'value')],
        prevent_initial_call=True
    )
    def run_portfolio_backtest(n_clicks, optimized_data, capital, txn_cost, period):
        if not n_clicks:
            return html.Div(), ""

        if not optimized_data:
            return html.Div("No optimized portfolio data found. Please go to the 'Portfolio' tab and run 'Calculate Score & Allocation' first.", style={'color': THEME['warning'], 'padding': '20px'}), "Waiting for portfolio data..."

        try:
            capital = float(capital) if capital is not None else 10000000.0
            txn_cost_bp = float(txn_cost) if txn_cost is not None else 1.0
            lookback_days = int(period) if period is not None else 252

            asset_data = {}
            weights = {}
            valid_assets = []

            for item in optimized_data:
                full_id = item.get('ID')
                weight = float(item.get('weight', 0.0))
                if not full_id or weight <= 0:
                    continue
                spread_type = item.get('spread_type')
                instrument = full_id
                if '|' in full_id:
                    _type, _inst = full_id.split('|', 1)
                    if not spread_type:
                        spread_type = _type
                    instrument = _inst
                if not spread_type:
                    continue
                df_spread = load_spread_timeseries(spread_type)
                if df_spread is None or instrument not in df_spread.columns:
                    print(f"[WARN] Data not found for {full_id} (Type={spread_type}, Inst={instrument})")
                    continue
                series = df_spread[instrument].dropna()
                if len(series) < 10:
                    continue
                asset_data[full_id] = series
                weights[full_id] = weight
                valid_assets.append(full_id)

            if not valid_assets:
                return html.Div("Failed to load historical data for any selected assets.", style={'color': THEME['danger']}), "Data load failed"

            df_prices = pd.DataFrame(asset_data)
            df_prices = df_prices.sort_index().ffill().dropna()
            if lookback_days < len(df_prices):
                df_prices = df_prices.iloc[-lookback_days:]
            if df_prices.empty:
                return html.Div("No overlapping historical data found for the selected portfolio.", style={'color': THEME['danger']}), "Data align failed"

            # --- Per-trade signal-driven backtests, combined by portfolio weight ---
            item_lookup = {_i.get('ID'): _i for _i in optimized_data if _i.get('ID')}
            total_weight_raw = sum(weights[a] for a in valid_assets)
            alloc_weights = {a: weights[a] / total_weight_raw for a in valid_assets}

            _TRACE_COLORS = [
                'rgba(100,149,237,0.8)', 'rgba(255,165,0,0.8)',   'rgba(255,99,71,0.8)',
                'rgba(144,238,144,0.8)', 'rgba(238,130,238,0.8)', 'rgba(64,224,208,0.8)',
                'rgba(255,215,0,0.8)',   'rgba(250,128,114,0.8)', 'rgba(173,216,230,0.8)',
                'rgba(255,182,193,0.8)',
            ]

            weighted_equity: dict = {}
            trade_summaries: list = []

            for asset in valid_assets:
                _item = item_lookup.get(asset, {})
                weight = alloc_weights[asset]
                spread_type = _item.get('spread_type', '')
                run_trend = 'trend' in str(_item.get('style', '')).lower()

                ts = df_prices[asset]

                _cr_ts, _cr_bp = None, 0.0
                try:
                    _cr_df = load_carry_roll_timeseries(spread_type)
                    if isinstance(_cr_df, pd.DataFrame) and asset in _cr_df.columns:
                        _cr_ts = _cr_df[asset].dropna()
                    _snap = load_spread_data(spread_type)
                    if isinstance(_snap, pd.DataFrame) and asset in _snap.index:
                        _row = _snap.loc[asset]
                        for _c in ['carry_roll', 'carry', 'CarryRoll3m']:
                            if _c in _row.index:
                                _v = _row.get(_c)
                                if _v is not None and np.isfinite(float(_v)):
                                    _cr_bp = float(_v)
                                    break
                except Exception:
                    pass

                dur = _get_duration_mult(asset, spread_type)

                try:
                    if run_trend:
                        res = run_trend_backtest_dc(
                            spread_ts=ts, carry_roll_ts=_cr_ts,
                            carry_roll_bp=_cr_bp, duration_mult=dur,
                        )
                    else:
                        res = run_spread_backtest(
                            spread_ts=ts, carry_roll_ts=_cr_ts,
                            carry_roll_bp=_cr_bp, duration_mult=dur,
                        )
                except Exception:
                    continue

                if 'error' in res or not isinstance(res.get('equity_ts'), pd.Series):
                    continue

                eq = res['equity_ts'].copy()
                eq.index = pd.to_datetime(eq.index)
                weighted_equity[asset] = eq * weight

                trade_summaries.append({
                    'Asset': asset,
                    'Direction': _item.get('direction', 'N/A'),
                    'Style': _item.get('style', 'N/A'),
                    'Weight': f"{weight * 100:.1f}%",
                    '# Trades': res.get('n_trades', 0),
                    'Win Rate': f"{res.get('win_rate', 0):.0f}%",
                    'Wtd PnL (bp)': round(float(res.get('total_pnl', 0)) * weight, 1),
                })

            if not weighted_equity:
                return html.Div("No backtest results for any assets.", style={'color': THEME['danger'], 'padding': '20px'}), "No results"

            df_equity = pd.DataFrame(weighted_equity).sort_index().ffill().fillna(0)
            portfolio_equity = df_equity.sum(axis=1)

            total_pnl = float(portfolio_equity.iloc[-1])
            n_days = len(portfolio_equity)
            port_daily = portfolio_equity.diff().fillna(0)
            avg_pnl = float(port_daily.mean())
            std_pnl = float(port_daily.std())
            sharpe = (avg_pnl / std_pnl * np.sqrt(252)) if std_pnl > 0 else 0.0
            running_max = np.maximum.accumulate(portfolio_equity.values)
            max_drawdown = float((running_max - portfolio_equity.values).max())
            win_days = (port_daily > 0).sum()
            win_rate = (win_days / n_days * 100) if n_days > 0 else 0.0

            # --- Chart: per-trade weighted equity + portfolio total ---
            fig = go.Figure()
            _sorted_assets = sorted(weighted_equity, key=lambda a: -alloc_weights[a])
            for _ci, _a in enumerate(_sorted_assets):
                _eq = weighted_equity[_a]
                _dir = item_lookup.get(_a, {}).get('direction', '')
                _color = _TRACE_COLORS[_ci % len(_TRACE_COLORS)]
                fig.add_trace(go.Scatter(
                    x=_eq.index, y=_eq.values,
                    mode='lines',
                    name=f"{_a} ({alloc_weights[_a]*100:.0f}% {_dir})",
                    line=dict(color=_color, width=1),
                    opacity=0.65,
                ))
            fig.add_trace(go.Scatter(
                x=portfolio_equity.index, y=portfolio_equity.values,
                mode='lines', name='Portfolio Total',
                line=dict(color=THEME['success'], width=2.5),
                fill='tozeroy', fillcolor='rgba(0,204,150,0.07)',
            ))
            fig.add_hline(y=0, line_dash='dot', line_color=THEME['text_sub'])
            fig.update_layout(
                title=f'Portfolio Cumulative PnL — {len(weighted_equity)} trades (signal-driven, weighted by allocation)',
                xaxis={'title': '', 'gridcolor': THEME['bg_card'], 'tickformat': '%b\n%Y'},
                yaxis={'title': 'Weighted PnL (bp)', 'gridcolor': THEME['bg_card']},
                template='plotly_dark', paper_bgcolor=THEME['bg_card'], plot_bgcolor=THEME['bg_card'],
                height=420, margin={'l': 60, 'r': 180, 't': 50, 'b': 40},
                legend=dict(orientation='v', yanchor='top', y=0.99, xanchor='left', x=1.01,
                            font=dict(size=9), bgcolor='rgba(0,0,0,0)', tracegroupgap=1),
            )
            chart = dcc.Graph(figure=fig)

            label_style = {'color': THEME['text_sub'], 'fontSize': '12px'}
            val_style   = {'color': THEME['text_main'], 'fontWeight': 'bold', 'fontSize': '16px'}
            item_style  = {'display': 'flex', 'flexDirection': 'column'}
            stats = html.Div([
                html.Div([html.Span("Total Return",     style=label_style), html.Span(f"{total_pnl:+.1f} bp", style={**val_style, 'color': THEME['success'] if total_pnl > 0 else THEME['danger']})], style=item_style),
                html.Div([html.Span("Sharpe Ratio",     style=label_style), html.Span(f"{sharpe:.2f}",         style=val_style)], style=item_style),
                html.Div([html.Span("Win Rate (daily)", style=label_style), html.Span(f"{win_rate:.1f}%",      style=val_style)], style=item_style),
                html.Div([html.Span("Max Drawdown",     style=label_style), html.Span(f"-{max_drawdown:.1f} bp", style={**val_style, 'color': THEME['danger']})], style=item_style),
                html.Div([html.Span("Daily Vol",        style=label_style), html.Span(f"{std_pnl:.2f} bp",    style=val_style)], style=item_style),
                html.Div([html.Span("Trades loaded",    style=label_style), html.Span(f"{len(weighted_equity)}/{len(valid_assets)}", style=val_style)], style=item_style),
            ], style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '20px', 'marginBottom': '10px'})

            contrib_table = dash_table.DataTable(
                columns=[{'name': c, 'id': c} for c in ['Asset', 'Direction', 'Style', 'Weight', '# Trades', 'Win Rate', 'Wtd PnL (bp)']],
                data=sorted(trade_summaries, key=lambda x: -x['Wtd PnL (bp)']),
                page_size=15,
                style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_main'], 'fontWeight': 'bold'},
                style_cell={'backgroundColor': THEME['bg_card'], 'color': THEME['text_main'], 'textAlign': 'left', 'fontSize': '12px', 'padding': '6px 10px'},
                style_data_conditional=[
                    {'if': {'filter_query': '{Wtd PnL (bp)} > 0', 'column_id': 'Wtd PnL (bp)'}, 'color': THEME['success']},
                    {'if': {'filter_query': '{Wtd PnL (bp)} < 0', 'column_id': 'Wtd PnL (bp)'}, 'color': THEME['danger']},
                    {'if': {'filter_query': '{Direction} = "BUY"',  'column_id': 'Direction'}, 'color': THEME['success']},
                    {'if': {'filter_query': '{Direction} = "SELL"', 'column_id': 'Direction'}, 'color': THEME['danger']},
                ],
            )

            results_content = html.Div([
                stats,
                chart,
                html.H6("Per-Trade Breakdown", style={'color': THEME['text_main'], 'marginTop': '20px', 'marginBottom': '8px'}),
                contrib_table,
            ])
            status_msg = f"Backtest completed at {datetime.now().strftime('%H:%M:%S')} — {len(weighted_equity)}/{len(valid_assets)} trades over {n_days} days"

            return results_content, status_msg

        except Exception as e:
            import traceback
            traceback.print_exc()
            return html.Div(f"Error executing portfolio backtest: {str(e)}", style={'color': THEME['danger']}), "Error"
