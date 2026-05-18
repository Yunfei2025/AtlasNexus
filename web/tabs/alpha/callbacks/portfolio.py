# -*- coding: utf-8 -*-
"""Portfolio subtab callbacks: Recalculate correlation, Scoring & Allocation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

import numpy as np
import pandas as pd

from dash import dcc, html, dash_table, no_update
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go

from settings.paths import DIR_INPUT as _DIR_INPUT

from ..data import (
    THEME, SPREAD_CATEGORIES,
    load_spread_data, load_spread_timeseries,
    _get_duration_mult,
)
from ..scoring import _compute_risk_parity_weights


_SUMMARY_ALPHA_PARQUET = str(_DIR_INPUT / 'summary_alpha_portfolio.parquet')


def _upsert_snapshot(new_df: pd.DataFrame, parquet_path: str, id_cols: list[str]) -> pd.DataFrame:
    """Insert-or-update by id_cols: keep existing rows, replace matched ones, add new ones."""
    import os
    existing = None
    if os.path.exists(parquet_path):
        try:
            existing = pd.read_parquet(parquet_path)
        except Exception:
            existing = None

    if existing is None or existing.empty:
        new_df.to_parquet(parquet_path, index=False)
        return new_df

    all_cols = list(dict.fromkeys(list(existing.columns) + list(new_df.columns)))
    existing = existing.reindex(columns=all_cols)
    new_df = new_df.reindex(columns=all_cols)

    if all(c in existing.columns and c in new_df.columns for c in id_cols):
        merge_key = existing[id_cols].astype(str).agg('|'.join, axis=1)
        new_key = set(new_df[id_cols].astype(str).agg('|'.join, axis=1).tolist())
        kept = existing.loc[~merge_key.isin(new_key)].copy()
    else:
        kept = existing.copy()

    merged = pd.concat([kept, new_df], ignore_index=True)
    merged.to_parquet(parquet_path, index=False)
    return merged


def register_portfolio_callbacks(app) -> None:
    """Register all Portfolio subtab callbacks."""

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
                        'notional_mm', '_duration', 'DV01_k', 'weight', 'risk_contribution',
                    ] if c in df_scored.columns
                ]
                _snap = df_scored[_save_cols].copy()
                _snap['_timestamp'] = datetime.now().isoformat()
                # Upsert by (spread_type, ID): keeps prior trades that aren't in this run,
                # replaces values for trades that re-appear, adds genuinely new trades.
                _id_cols = [c for c in ('spread_type', 'ID') if c in _snap.columns] or ['ID']
                merged = _upsert_snapshot(_snap, _SUMMARY_ALPHA_PARQUET, _id_cols)
                print(f"✓ Alpha snapshot merged → {_SUMMARY_ALPHA_PARQUET} ({len(merged)} rows after upsert)")
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
