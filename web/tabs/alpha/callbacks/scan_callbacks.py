# -*- coding: utf-8 -*-
"""Scan and candidate-list callbacks for the Alpha candidates subtab."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from dash import dcc, html
from dash.dependencies import Input, Output, State

from ..data import THEME, ZSCORE_ENTRY_THRESHOLD, _get_input_dir, load_spread_data, display_key, _get_borrow_cost_annual_bp, _get_ttm_display, _get_current_fr007_bp
from ..scoring import compute_scan_score
from .helpers import (
    _ALPHA_CORR_COLORSCALE,
    _apply_seasonal_quality_gate,
    _get_upstream_regime,
    _load_alpha_book_positions,
    _load_seasonal_screener,
    _merge_curated_entries,
    _normalize_curated_entry,
    _style_to_regime,
)


def register_scan_callbacks(app) -> None:
    @app.callback(
        [Output('alpha-candidates-table-container', 'children'),
         Output('alpha-scan-status', 'children'),
         Output('alpha-selected-candidates', 'data'),
         Output('alpha-regime-store', 'data')],
        Input('alpha-scan-btn', 'n_clicks'),
        [State('alpha-spread-categories', 'value'),
         State('alpha-zscore-threshold', 'value'),
         State('alpha-direction-filter', 'value'),
         State('seasonal-prefilter-toggle', 'value'),
         State('seasonal-prefilter-min-consistency', 'value'),
         State('seasonal-prefilter-p-thresh', 'value')],
        prevent_initial_call=True,
    )
    def scan_candidates(n_clicks, categories, zscore_thd, direction, seasonal_prefilter, seasonal_min_consistency, seasonal_p_thresh):
        if not n_clicks or not categories:
            return html.Div("Select spread categories and click Scan.", style={'color': THEME['text_sub']}), "", [], {}

        use_seasonal_gate = bool(seasonal_prefilter and 'on' in (seasonal_prefilter or []))
        min_consistency = float(seasonal_min_consistency or 75) / 100.0
        seas_p_thresh = float(seasonal_p_thresh or 0.10)

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
                df_all = df_all[(~is_mr_row) | (df_all['Zscore'] <= -z_thd)].copy()
            elif direction == 'sell':
                df_all = df_all[(~is_mr_row) | (df_all['Zscore'] >= z_thd)].copy()

        if df_all.empty:
            return (
                html.Div(f"Candidates exist, but none match direction filter at zscore≥{z_thd:g}.", style={'color': THEME['warning']}),
                f"Scanned at {scanned_time}", [], {},
            )

        if 'direction' not in df_all.columns and 'Zscore' in df_all.columns:
            df_all = df_all.copy()
            df_all['direction'] = df_all['Zscore'].apply(lambda z: 'BUY' if float(z) < 0 else 'SELL')

        if 'style' in df_all.columns:
            inferred_regime = df_all['style'].map(_style_to_regime)
            if 'regime' not in df_all.columns:
                df_all['regime'] = inferred_regime
            else:
                regime_text = df_all['regime'].astype(str).str.strip().str.lower()
                missing_regime = regime_text.isin({'', 'nan', 'none', 'unknown', 'uncertain'})
                df_all.loc[missing_regime, 'regime'] = inferred_regime.loc[missing_regime]

        _seasonal_data = _load_seasonal_screener()
        if use_seasonal_gate:
            df_all, excluded_count, evaluated_count = _apply_seasonal_quality_gate(
                df_all,
                _seasonal_data,
                min_consistency=min_consistency,
                p_value_threshold=seas_p_thresh,
            )
            if excluded_count:
                scanned_time += f' · seasonal gate excluded {excluded_count}'
            elif not evaluated_count:
                scanned_time += ' · seasonal gate: no current-month data'

        if df_all.empty:
            return (
                html.Div(
                    f"No candidates passed the seasonal gate "
                    f"(consistency≥{min_consistency:.0%}, p<{seas_p_thresh}). "
                    "Relax the filter or turn it off.",
                    style={'color': THEME['warning']},
                ),
                f"Scanned at {scanned_time}", [], {},
            )

        if 'score' not in df_all.columns:
            df_all = compute_scan_score(df_all, seasonal_data=_seasonal_data)
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

        _TENOR_RATIO = 2.0
        _FINANCING_RATE_BP = _get_current_fr007_bp() or 137.0

        if 'carry_roll' in df_all.columns and 'spread_type' in df_all.columns and 'ID' in df_all.columns:
            _ts_mask = df_all['spread_type'].eq('TenorSpread')
            if _ts_mask.any():
                from ..data import _get_tenor_yields_for_spread
                _cr_ts_annual = pd.to_numeric(df_all.loc[_ts_mask, 'carry_roll'], errors='coerce')
                _dir_ts = df_all.loc[_ts_mask].get('direction', pd.Series('', index=df_all.index[_ts_mask])).astype(str).str.strip().str.upper()
                _fin_adj = pd.Series(0.0, index=df_all.index[_ts_mask], dtype=float)
                _bc_adj = pd.Series(0.0, index=df_all.index[_ts_mask], dtype=float)

                for _bidx in df_all.index[_ts_mask]:
                    inst_id = str(df_all.at[_bidx, 'ID'])
                    try:
                        y_short, y_long = _get_tenor_yields_for_spread(inst_id)
                        if y_long is not None:
                            y_long_bp = y_long * 100.0
                            _fin_adj.at[_bidx] = 0.5 * (_FINANCING_RATE_BP - y_long_bp)
                    except Exception:
                        _fin_adj.at[_bidx] = 0.0

                    _bc_l, _bc_s = _get_borrow_cost_annual_bp('TenorSpread', inst_id)
                    if _dir_ts.at[_bidx] == 'BUY':
                        _bc_annual = _bc_l * 0.5
                    else:
                        _bc_annual = _bc_s * 0.5
                    _bc_adj.at[_bidx] = _bc_annual / 4.0

                _cr_annual_adjusted = _cr_ts_annual + _fin_adj - _bc_adj * 4.0
                _cr_3m = _cr_annual_adjusted * (90.0 / 360.0)
                df_all.loc[_ts_mask, 'carry_roll'] = _cr_3m.round(4)

        _snap_ttm_cache: dict = {}

        def _ttm_cached(stype: str, inst: str):
            if stype in ('TBondCurve', 'CBondCurve', 'TBondSwap', 'CBondSwap'):
                if stype not in _snap_ttm_cache:
                    _snap_ttm_cache[stype] = load_spread_data(stype)
                snap = _snap_ttm_cache[stype]
                if isinstance(snap, pd.DataFrame) and inst in snap.index and 'ttm' in snap.columns:
                    v = float(snap.loc[inst, 'ttm'])
                    return round(v, 1) if v > 0 else None
                return None
            return _get_ttm_display(stype, inst)

        if 'spread_type' in df_all.columns and 'ID' in df_all.columns:
            df_all['ttm_display'] = [
                _ttm_cached(str(r.get('spread_type', '')), str(r.get('ID', '')))
                for _, r in df_all.iterrows()
            ]
            if 'carry_roll' in df_all.columns:
                _cr_be = pd.to_numeric(df_all['carry_roll'], errors='coerce')
                _dir_be = df_all.get('direction', pd.Series('', index=df_all.index)).astype(str).str.strip().str.upper()
                _dir_sign_be = pd.Series(1.0, index=df_all.index, dtype=float)
                _dir_sign_be[_dir_be.eq('SELL')] = -1.0
                _cr_disp_be = _cr_be * _dir_sign_be
                _ttm_be = pd.to_numeric(df_all['ttm_display'], errors='coerce').replace(0, np.nan)
                _be_raw = (-_cr_disp_be / _ttm_be).where(_cr_disp_be.lt(0) & _ttm_be.notna())
                df_all['breakeven_3m'] = _be_raw.round(4)

        _spread_v = pd.to_numeric(df_all.get('spread', pd.Series(dtype=float)), errors='coerce')
        _mean_v = pd.to_numeric(df_all.get('mean', pd.Series(dtype=float)), errors='coerce')
        _risk_vol = (
            pd.to_numeric(df_all['risk_vol_63d'], errors='coerce').abs()
            if 'risk_vol_63d' in df_all.columns
            else pd.Series(np.nan, index=df_all.index, dtype=float)
        )
        _ou_vol = pd.to_numeric(df_all.get('vol', pd.Series(dtype=float)), errors='coerce').abs()
        _vol_v = _risk_vol.where(_risk_vol.gt(0) & _risk_vol.notna(), _ou_vol)
        _style_v = df_all.get('style', pd.Series(dtype=str)).astype(str).str.strip().str.lower()
        _is_mr_v = _style_v.eq('meanreversion')
        _dist_v = (_spread_v - _mean_v).abs()
        _z_v = pd.to_numeric(df_all.get('Zscore', pd.Series(dtype=float)), errors='coerce')
        _dir_v = df_all.get('direction', pd.Series(dtype=str)).astype(str).str.strip().str.upper()
        _dir_sign_v = pd.Series(1.0, index=df_all.index, dtype=float)
        _dir_sign_v[_dir_v.eq('SELL')] = -1.0

        _trend_target_bp = (_dir_sign_v * ZSCORE_ENTRY_THRESHOLD - _z_v).abs() * _vol_v

        df_all['stop_loss'] = np.where(_is_mr_v, (_dist_v + 1.5 * _vol_v).round(4), (2.0 * _vol_v).round(4))
        df_all['profit_target'] = np.where(_is_mr_v, _dist_v.round(4), _trend_target_bp.round(4))

        if 'breakeven_3m' in df_all.columns and 'vol' in df_all.columns:
            _be_f = pd.to_numeric(df_all['breakeven_3m'], errors='coerce')
            _vol_f = pd.to_numeric(df_all['vol'], errors='coerce').abs()
            _ttm_f = pd.to_numeric(df_all.get('ttm_display', pd.Series(dtype=float)), errors='coerce')
            _reject = _be_f.gt(_vol_f) & _be_f.notna() & _vol_f.gt(0) & _ttm_f.notna()
            if _reject.any():
                df_all = df_all[~_reject].copy()
                if df_all.empty:
                    return (
                        html.Div("All candidates filtered out by breakeven > vol constraint.", style={'color': THEME['warning']}),
                        f"Filtered at {scanned_time}", [], {},
                    )

        _mr_display_cols = ['ID', 'spread_type', 'ttm_display', 'direction', 'regime', 'Zscore', 'spread', 'mean', 'vol', 'halflife', 'carry_roll', 'breakeven_3m', 'seasonal_edge_bps', 'seasonal_label', 'score', 'stop_loss', 'profit_target']
        _trend_display_cols = ['ID', 'spread_type', 'ttm_display', 'direction', 'regime', 'Zscore', 'spread', 'mean', 'vol', 'carry_roll', 'breakeven_3m', 'seasonal_edge_bps', 'seasonal_label', 'score', 'trend_state', 'stop_loss', 'profit_target']

        _all_display_cols = list(dict.fromkeys(_mr_display_cols + _trend_display_cols + ['style']))
        df_display = df_all.copy()
        if 'ID' not in df_display.columns and df_display.index.name == 'ID':
            df_display = df_display.reset_index()
        if 'ID' in df_display.columns:
            df_display = df_display.drop_duplicates(subset=['ID'], keep='first')
        available_all = [c for c in _all_display_cols if c in df_display.columns]
        df_display = df_display[available_all].copy()

        if 'style' in df_display.columns:
            def _style_to_regime_label(value):
                style_value = str(value).strip().lower()
                if style_value in {'meanreversion', 'mean_reverting'}:
                    return 'mean-reverting'
                if style_value in {'trend', 'trendfollowing', 'carry', 'mixed'}:
                    return 'momentum'
                return value

            df_display['style'] = df_display['style'].map(_style_to_regime_label)

        candidate_data = df_display.to_dict('records')

        if 'carry_roll' in df_display.columns and 'direction' in df_display.columns:
            _sell_mask = df_display['direction'].astype(str).str.strip().str.upper().eq('SELL')
            df_display.loc[_sell_mask, 'carry_roll'] = (
                pd.to_numeric(df_display.loc[_sell_mask, 'carry_roll'], errors='coerce').multiply(-1)
            )

        for col in ['Zscore', 'spread', 'mean', 'vol', 'carry_roll', 'halflife', 'score', 'stop_loss', 'profit_target', 'trend_state', 'regime_confidence', 'efficiency_ratio', 'hurst', 'ttm_display', 'breakeven_3m', 'seasonal_edge_bps']:
            if col in df_display.columns:
                df_display[col] = pd.to_numeric(df_display[col], errors='coerce').round(1)

        df_mr = pd.DataFrame()
        df_trend = pd.DataFrame()

        _mr_avail = [c for c in _mr_display_cols if c in df_display.columns]
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

        mr_by_regime = regime_s.eq('mean_reverting')
        trend_by_regime = regime_s.eq('trending')
        uncertain_mask = regime_s.eq('uncertain')
        no_regime = ~mr_by_regime & ~trend_by_regime & ~uncertain_mask
        style_mr = (no_regime | uncertain_mask) & style_s.isin({'meanreversion', 'mean-reverting', 'mean_reverting', 'mr'})
        style_trend = (no_regime | uncertain_mask) & style_s.isin({'carry', 'trend', 'trendfollowing', 'momentum', 'mixed'})
        uncertain_unmapped = uncertain_mask & ~style_mr & ~style_trend

        df_mr = df_display[mr_by_regime | style_mr][_mr_avail].copy()
        df_trend = df_display[trend_by_regime | style_trend][_trend_avail].copy()
        df_uncertain = df_display[uncertain_unmapped][_mr_avail].copy()

        regime_counts = regime_s.value_counts(dropna=False)
        regime_summary = ', '.join([f"{k}: {int(v)}" for k, v in regime_counts.items()])
        style_summary_div = html.Div(f"Regime: {regime_summary}", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '8px'})

        def _signal_cards(df_rows, max_z=4.0):
            cards = []
            for row in df_rows:
                inst = str(row.get('ID', '') or '')
                stype = str(row.get('spread_type', '') or '')
                label = display_key(stype, inst)
                direction = str(row.get('direction', '') or '').upper()
                z_raw = row.get('Zscore', None)
                try:
                    z = float(z_raw)
                except (TypeError, ValueError):
                    z = 0.0

                if direction == 'BUY':
                    pill = html.Span('BUY', style={
                        'backgroundColor': THEME['success'], 'color': '#000',
                        'fontWeight': 'bold', 'fontSize': '10px', 'padding': '2px 8px',
                        'borderRadius': '3px', 'minWidth': '36px', 'textAlign': 'center',
                        'display': 'inline-block',
                    })
                elif direction == 'SELL':
                    pill = html.Span('SELL', style={
                        'backgroundColor': THEME['danger'], 'color': '#fff',
                        'fontWeight': 'bold', 'fontSize': '10px', 'padding': '2px 8px',
                        'borderRadius': '3px', 'minWidth': '36px', 'textAlign': 'center',
                        'display': 'inline-block',
                    })
                else:
                    pill = html.Span('—', style={'color': THEME['text_sub'], 'fontSize': '10px', 'minWidth': '36px', 'display': 'inline-block'})

                z_clamped = max(-max_z, min(max_z, z))
                bar_pct = abs(z_clamped) / max_z * 50.0
                bar_color = THEME['danger'] if z < 0 else THEME['success']
                if z < 0:
                    bar_style = {
                        'position': 'absolute', 'right': '50%',
                        'width': f'{bar_pct:.1f}%', 'height': '100%',
                        'backgroundColor': bar_color, 'opacity': '0.7',
                        'borderRadius': '2px 0 0 2px',
                    }
                else:
                    bar_style = {
                        'position': 'absolute', 'left': '50%',
                        'width': f'{bar_pct:.1f}%', 'height': '100%',
                        'backgroundColor': bar_color, 'opacity': '0.7',
                        'borderRadius': '0 2px 2px 0',
                    }

                z_bar = html.Div(style={'position': 'relative', 'height': '6px',
                                        'backgroundColor': THEME['bg_main'],
                                        'borderRadius': '3px', 'overflow': 'hidden',
                                        'width': '72px', 'display': 'inline-block',
                                        'verticalAlign': 'middle', 'marginLeft': '6px'},
                                 children=[html.Div(style=bar_style)])
                z_label = html.Span(f'{z:+.1f}σ', style={
                    'fontSize': '10px', 'color': bar_color,
                    'fontWeight': 'bold', 'marginLeft': '4px', 'verticalAlign': 'middle',
                })

                seas_label = str(row.get('seasonal_label', '') or '').strip().lower()
                seas_tag = None
                if seas_label == 'strong':
                    seas_tag = html.Span('S↑↑', title='Strong seasonal tailwind (consistency ≥75%)', style={
                        'backgroundColor': '#0d5c0d', 'color': '#7fff7f',
                        'fontSize': '9px', 'fontWeight': 'bold', 'padding': '1px 4px',
                        'borderRadius': '3px', 'marginLeft': '5px',
                        'verticalAlign': 'middle', 'cursor': 'default',
                    })
                elif seas_label == 'weak':
                    seas_tag = html.Span('S↑', title='Weak seasonal tailwind (consistency ≥60%)', style={
                        'backgroundColor': '#2a4a2a', 'color': '#a0d0a0',
                        'fontSize': '9px', 'fontWeight': 'bold', 'padding': '1px 4px',
                        'borderRadius': '3px', 'marginLeft': '5px',
                        'verticalAlign': 'middle', 'cursor': 'default',
                    })
                elif seas_label == 'against':
                    seas_tag = html.Span('S↓', title='Seasonal headwind (consistency ≥60% in opposite direction)', style={
                        'backgroundColor': '#4a1a1a', 'color': '#d09090',
                        'fontSize': '9px', 'fontWeight': 'bold', 'padding': '1px 4px',
                        'borderRadius': '3px', 'marginLeft': '5px',
                        'verticalAlign': 'middle', 'cursor': 'default',
                    })

                right_cluster = [z_bar, z_label]
                if seas_tag is not None:
                    right_cluster.append(seas_tag)

                card = html.Div([
                    html.Div([
                        pill,
                        html.Span(label, style={
                            'color': THEME['text_main'], 'fontSize': '12px',
                            'fontWeight': '500', 'marginLeft': '10px',
                        }),
                    ], style={
                        'display': 'flex', 'alignItems': 'center',
                        'flex': '1', 'minWidth': '0', 'overflow': 'hidden',
                    }),
                    html.Div(right_cluster, style={
                        'display': 'flex', 'alignItems': 'center',
                        'flexShrink': '0', 'marginLeft': '8px',
                    }),
                ], style={
                    'display': 'flex', 'alignItems': 'center',
                    'padding': '5px 10px', 'borderRadius': '4px',
                    'backgroundColor': THEME['bg_card'],
                    'borderLeft': f'3px solid {THEME["success"] if direction == "BUY" else (THEME["danger"] if direction == "SELL" else THEME["table_header"])}',
                    'marginBottom': '4px',
                })
                cards.append(card)
            return cards

        def _three_col_grid(cards):
            return html.Div(cards, style={
                'display': 'grid',
                'gridTemplateColumns': 'repeat(3, 1fr)',
                'gap': '4px',
            })

        _empty_style = {'color': THEME['text_sub'], 'fontSize': '12px', 'padding': '6px 8px', 'fontStyle': 'italic'}

        def _section_header(label, count, accent):
            return html.Div([
                html.Span('▌', style={'color': accent, 'fontSize': '14px', 'marginRight': '6px', 'verticalAlign': 'middle'}),
                html.Span(label, style={'color': THEME['text_main'], 'fontSize': '12px', 'fontWeight': '700', 'verticalAlign': 'middle'}),
                html.Span(f'  {count} signals', style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '6px', 'verticalAlign': 'middle'}),
            ], style={'marginBottom': '8px', 'marginTop': '0', 'paddingBottom': '5px',
                      'borderBottom': f'1px solid {accent}33'})

        mr_rows = df_mr.head(20).to_dict('records') if not df_mr.empty else []
        trend_rows = df_trend.head(20).to_dict('records') if not df_trend.empty else []
        uncertain_rows = df_uncertain.head(20).to_dict('records') if not df_uncertain.empty else []

        mr_cards = _signal_cards(mr_rows)
        trend_cards = _signal_cards(trend_rows)
        uncertain_cards = _signal_cards(uncertain_rows)

        sections = []
        if mr_cards:
            sections.append(html.Div([
                _section_header('Mean-Reversion', len(mr_rows), THEME['success']),
                _three_col_grid(mr_cards),
            ], style={'marginBottom': '18px'}))

        if trend_cards:
            sections.append(html.Div([
                _section_header('Momentum / Carry', len(trend_rows), '#FF9800'),
                _three_col_grid(trend_cards),
            ], style={'marginBottom': '18px'} if uncertain_cards else {}))

        if uncertain_cards:
            sections.append(html.Div([
                _section_header('Uncertain', len(uncertain_rows), THEME['text_sub']),
                html.Div(
                    "Regime unresolved — check spread chart before trading.",
                    style={**_empty_style, 'marginBottom': '6px', 'fontStyle': 'italic'},
                ),
                _three_col_grid(uncertain_cards),
            ]))

        if not sections:
            sections = [html.Div("No candidates found.", style=_empty_style)]

        table_out = html.Div([
            style_summary_div,
            html.Div(sections, style={'maxHeight': '500px', 'overflowY': 'auto', 'paddingRight': '4px'}),
        ])
        status = f"Found {len(df_all)} candidates at {scanned_time}"

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
