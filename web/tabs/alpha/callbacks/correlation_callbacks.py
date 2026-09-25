# -*- coding: utf-8 -*-
"""Correlation and curated-instrument callbacks for the Alpha candidates subtab."""

from __future__ import annotations

import json as _json

import numpy as np
import pandas as pd

from dash import dcc, html, callback_context
from dash.dependencies import Input, Output, State, ALL
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go

from ..data import THEME, SPREAD_CATEGORIES, _get_input_dir, _load_pickle_safe, load_spread_data, load_spread_timeseries, display_key, _get_duration_mult
from ..scoring import compute_spread_correlation, rank_low_correlation_pairs, select_diverse_instruments
from .helpers import _ALPHA_CORR_COLORSCALE, _get_upstream_regime, _load_alpha_book_positions, _merge_curated_entries, _normalize_corr_labels, _build_heatmap, _style_to_regime


def register_correlation_callbacks(app) -> None:
    @app.callback(
        [Output('alpha-corr-results', 'children'),
         Output('alpha-corr-pairs-store', 'data'),
         Output('alpha-corr-matrix-store', 'data'),
         Output('alpha-curated-instruments-store', 'data')],
        Input('alpha-corr-btn', 'n_clicks'),
        [State('alpha-spread-categories-core', 'value'),
         State('alpha-spread-categories-satellite', 'value'),
         State('alpha-corr-lookback', 'value'),
         State('alpha-max-corr', 'value'),
         State('alpha-corr-candidate-count', 'value'),
         State('alpha-selected-candidates', 'data')],
        prevent_initial_call=True,
    )
    def check_correlation(n_clicks, core_categories, satellite_categories, lookback, max_corr, candidate_count, all_candidates):
        categories = list(core_categories or []) + list(satellite_categories or [])
        if not n_clicks or not categories:
            return html.Div("Select categories and click Check Correlation.", style={'color': THEME['text_sub']}), [], {}, []

        try:
            target_count = max(1, int(candidate_count or 10))
        except (TypeError, ValueError):
            target_count = 10

        corr_matrix = None

        # Core (default TenorSpread) book seed: diversify satellite candidates
        # against the book's *actual current holdings*, not only against each
        # other -- see docs/plans/portfolio_construction_beta_alpha.md §5.2.
        # Locked to instruments with an OPEN POSITION today (from the live
        # alpha_book_positions parquet), not load_core_seed's full ~24-name
        # structural membership list -- the correlation matrix should reflect
        # what's actually held, not the whole eligible universe. Corrected
        # 2026-09-25 per user: the full core seed made an ordinary 5-candidate
        # check render a 24+-instrument matrix, most of it names with no
        # position on today.
        core_seed = [
            p for p in _load_alpha_book_positions()
            if str(p.get('spread_type', '') or '') == 'TenorSpread'
        ]

        if all_candidates and len(all_candidates) > 0:
            df_candidates = pd.DataFrame(all_candidates)
            if 'ID' in df_candidates.columns and 'spread_type' in df_candidates.columns:
                _ts_cache: dict[str, pd.DataFrame | None] = {}
                all_spreads = {}
                duration_by_key: dict[str, float] = {}
                # Include the locked core seed's price series in the same
                # duration-adjusted matrix as the scanned candidates, so
                # select_diverse_instruments' locked=core_seed check below has
                # actual correlation values to compare against -- a locked
                # instrument missing from corr_matrix.columns is silently
                # dropped there.
                for _, row in pd.concat([df_candidates, pd.DataFrame(core_seed)], ignore_index=True).iterrows():
                    trade_id = row.get('ID', '')
                    spread_type = row.get('spread_type', '')
                    if not trade_id or not spread_type:
                        continue
                    if spread_type not in _ts_cache:
                        _ts_cache[spread_type] = load_spread_timeseries(spread_type)
                    ts = _ts_cache[spread_type]
                    if ts is not None and isinstance(ts, pd.DataFrame) and trade_id in ts.columns:
                        col_key = display_key(spread_type, trade_id)
                        if col_key in all_spreads:
                            continue
                        series = ts[trade_id]
                        if series.index.has_duplicates:
                            series = series[~series.index.duplicated(keep='last')]
                        all_spreads[col_key] = series
                        duration_by_key[col_key] = max(
                            0.01,
                            float(_get_duration_mult(str(trade_id), str(spread_type))),
                        )

                if len(all_spreads) >= 2:
                    for key in all_spreads:
                        all_spreads[key].index = all_spreads[key].index.astype(str)
                    df_spreads = pd.DataFrame(all_spreads).tail(lookback)
                    df_changes = df_spreads.diff().dropna()
                    if len(df_changes) >= 20:
                        duration_s = pd.Series(duration_by_key).reindex(df_changes.columns).fillna(1.0)
                        price_changes = df_changes.mul(duration_s, axis='columns')
                        corr_matrix = price_changes.corr()
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
            # Make sure the core seed's own category is in the universe even
            # if the user's checklist doesn't include it -- otherwise the
            # locked seed has no columns to be found in below.
            if core_seed and 'TenorSpread' not in spread_types:
                spread_types.append('TenorSpread')

            if len(spread_types) == 0:
                return html.Div("No spread types selected.", style={'color': THEME['warning']}), [], {}, []

            dir_input = _get_input_dir()
            candidates_data = _load_pickle_safe(dir_input / 'Alpha-candidates.pkl')

            if candidates_data and isinstance(candidates_data, dict):
                corr_matrix = candidates_data.get('corr')
                if isinstance(corr_matrix, dict):
                    corr_matrix = pd.DataFrame(corr_matrix)
                if isinstance(corr_matrix, pd.DataFrame):
                    corr_matrix = _normalize_corr_labels(corr_matrix)

            if corr_matrix is None or not isinstance(corr_matrix, pd.DataFrame) or corr_matrix.empty:
                corr_matrix, _ = compute_spread_correlation(spread_types, lookback_days=lookback)

        if isinstance(corr_matrix, pd.DataFrame):
            corr_matrix = _normalize_corr_labels(corr_matrix)

        if corr_matrix is None or corr_matrix.empty:
            return html.Div("Insufficient data for correlation analysis. Need at least 2 instruments with historical data.", style={'color': THEME['warning']}), [], {}, []

        low_corr_pairs = rank_low_correlation_pairs(corr_matrix, top_n=target_count)
        high_corr = low_corr_pairs[low_corr_pairs['AbsCorr'] > max_corr]

        diverse_keys = select_diverse_instruments(
            corr_matrix, all_candidates or [], n=target_count,
            max_abs_corr=float(max_corr) if max_corr is not None else 1.0,
            locked=core_seed,
        )
        locked_in_matrix = [display_key(c['spread_type'], c['ID']) for c in core_seed
                            if display_key(c['spread_type'], c['ID']) in corr_matrix.columns]
        heatmap_assets = [k for k in (locked_in_matrix + diverse_keys) if k in corr_matrix.columns]

        # Explain the matrix's scope up front, above the heatmap, not just as
        # a trailing caption -- otherwise a 5-candidate check next to a
        # locked core position or two reads as "why does this have more rows
        # than I asked for" (see prior 24-name core-seed version of this note).
        core_seed_note = html.Div()
        if core_seed:
            n_dropped = len(core_seed) - len(locked_in_matrix)
            dropped_txt = f', {n_dropped} without price history for this lookback' if n_dropped > 0 else ''
            core_seed_note = html.Div(
                f"ℹ️ Showing {len(diverse_keys)} candidate(s) + {len(locked_in_matrix)} open core "
                f"(TenorSpread) position(s) as a fixed diversification backdrop{dropped_txt} -- "
                "core positions are locked in, not new picks.",
                style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '8px'},
            )
        elif diverse_keys or heatmap_assets:
            core_seed_note = html.Div(
                f"ℹ️ Showing {len(diverse_keys)} candidate(s). No open core (TenorSpread) "
                "positions today, so nothing else is locked into the matrix.",
                style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '8px'},
            )

        if len(heatmap_assets) >= 2:
            sub_corr = corr_matrix.loc[heatmap_assets, heatmap_assets]
            corr_vals = sub_corr.values.copy()
            mask_upper = np.triu(np.ones(corr_vals.shape), k=0).astype(bool)
            corr_vals[mask_upper] = np.nan
            title = f'Duration-Adjusted Correlation Matrix — {len(heatmap_assets)} instruments (max |corr| ≤ {max_corr})'
            if locked_in_matrix:
                title += f', {len(locked_in_matrix)} open core position(s)'
            heatmap_div = dcc.Graph(figure=_build_heatmap(corr_vals, title=title, height=max(350, 28 * len(heatmap_assets) + 100), labels=heatmap_assets), config={'displayModeBar': False}, style={'height': f'{max(350, 28 * len(heatmap_assets) + 100)}px'})
        else:
            heatmap_div = html.Div("Not enough assets passed the correlation filter.", style={'color': THEME['text_sub']})

        warning_div = html.Div()
        if len(high_corr) > 0:
            warning_div = html.Div([
                html.P(f"⚠️ {len(high_corr)} pairs exceed max correlation threshold ({max_corr}). Consider removing correlated candidates before sizing.", style={'color': THEME['warning'], 'fontSize': '12px', 'marginTop': '10px'})
            ])

        col_key_to_stype: dict = {}
        col_key_to_id: dict = {}
        if all_candidates:
            for c in all_candidates:
                if 'ID' in c and 'spread_type' in c:
                    ck = display_key(c['spread_type'], c['ID'])
                    col_key_to_stype[ck] = c['spread_type']
                    col_key_to_id[ck] = c['ID']

        curated_instruments: list = []
        for col_key in diverse_keys:
            stype = col_key_to_stype.get(col_key, 'Unknown')
            inst = col_key_to_id.get(col_key, col_key)
            row_meta = {
                'spread_type': stype,
                'instrument': inst,
                'manual': False,
                'regime': 'uncertain',
                'direction': '',
            }
            if all_candidates:
                for c in all_candidates:
                    if c.get('ID') == inst and c.get('spread_type') == stype:
                        _cand_style = str(c.get('style', '') or '').strip()
                        _cand_regime = str(c.get('regime', '') or '').strip()
                        row_meta['regime'] = _style_to_regime(_cand_style or _cand_regime)
                        row_meta['direction'] = c.get('direction', '')
                        try:
                            row_meta['Zscore'] = float(c.get('Zscore', 0) or 0)
                        except (TypeError, ValueError):
                            pass
                        sl = str(c.get('seasonal_label', '') or '').strip()
                        if sl:
                            row_meta['seasonal_label'] = sl
                        break
            if row_meta['regime'] == 'uncertain':
                row_meta['regime'] = _get_upstream_regime(stype, inst) or 'uncertain'
            curated_instruments.append(row_meta)

        curated_instruments = _merge_curated_entries(curated_instruments)

        if diverse_keys:
            valid_keys = [k for k in diverse_keys if k in corr_matrix.columns]
            corr_matrix_store = corr_matrix.loc[valid_keys, valid_keys]
        else:
            corr_matrix_store = corr_matrix

        return html.Div([core_seed_note, heatmap_div, warning_div]), [], corr_matrix_store.to_dict(), curated_instruments

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

    @app.callback(
        Output('alpha-curated-instruments-store', 'data'),
        [Input('alpha-add-trade-btn', 'n_clicks'),
         Input({'type': 'curated-del', 'stype': ALL, 'inst': ALL}, 'n_clicks')],
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
        if not current:
            current = _load_alpha_book_positions()

        raw_prop = ctx.triggered[0]['prop_id']
        raw_id = raw_prop.rsplit('.', 1)[0]
        try:
            trig_dict = _json.loads(raw_id)
        except (ValueError, TypeError):
            trig_dict = None

        if raw_id == 'alpha-add-trade-btn':
            if not spread_type or not instrument:
                raise PreventUpdate
            if any(
                e.get('spread_type') == spread_type and e.get('instrument') == instrument
                for e in current
            ):
                raise PreventUpdate
            _regime = 'uncertain'
            _direction = ''
            try:
                snap = load_spread_data(spread_type)
                if snap is not None and instrument in snap.index:
                    snap_row = snap.loc[instrument]
                    _regime = _style_to_regime(snap_row.get('style', ''))
                    raw_dir = str(snap_row.get('direction', '') or '').strip().upper()
                    if raw_dir in {'BUY', 'SELL'}:
                        _direction = raw_dir
            except Exception:
                pass
            if _regime == 'uncertain':
                _regime = _get_upstream_regime(spread_type, instrument)
            _zscore = None
            try:
                snap = load_spread_data(spread_type)
                if snap is not None and instrument in snap.index and 'Zscore' in snap.columns:
                    _zscore = float(snap.loc[instrument, 'Zscore'])
            except Exception:
                pass
            _entry: dict = {
                'spread_type': spread_type,
                'instrument': instrument,
                'regime': _regime,
                'direction': _direction,
                'manual': True,
            }
            if _zscore is not None:
                _entry['Zscore'] = _zscore
            return _merge_curated_entries(current, [_entry])

        if trig_dict and trig_dict.get('type') == 'curated-del':
            if not any(nc for nc in del_clicks if nc):
                raise PreventUpdate
            trig_stype = trig_dict.get('stype', '')
            trig_inst = trig_dict.get('inst', '')
            return [e for e in current if not (e.get('spread_type') == trig_stype and e.get('instrument') == trig_inst)]

        raise PreventUpdate

    @app.callback(
        Output('alpha-curated-instruments-store', 'data', allow_duplicate=True),
        [Input({'type': 'curated-regime', 'stype': ALL, 'inst': ALL}, 'value'),
         Input({'type': 'curated-direction', 'stype': ALL, 'inst': ALL}, 'value')],
        State('alpha-curated-instruments-store', 'data'),
        prevent_initial_call=True,
    )
    def update_curated_meta(regimes, directions, current):
        ctx = callback_context
        if not ctx.triggered or not current:
            raise PreventUpdate

        raw_prop = ctx.triggered[0]['prop_id']
        raw_id = raw_prop.rsplit('.', 1)[0]
        try:
            trig_dict = _json.loads(raw_id)
        except (ValueError, TypeError):
            raise PreventUpdate

        trig_type = trig_dict.get('type', '')
        trig_stype = trig_dict.get('stype', '')
        trig_inst = trig_dict.get('inst', '')
        if not trig_stype or not trig_inst:
            raise PreventUpdate

        updated = [dict(e) for e in current]
        new_val = ctx.triggered[0]['value']
        for e in updated:
            if e.get('spread_type') == trig_stype and e.get('instrument') == trig_inst:
                if trig_type == 'curated-regime':
                    e['regime'] = new_val or 'uncertain'
                elif trig_type == 'curated-direction':
                    e['direction'] = new_val or ''
                else:
                    raise PreventUpdate
                return updated
        raise PreventUpdate
