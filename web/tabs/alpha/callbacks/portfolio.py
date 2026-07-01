# -*- coding: utf-8 -*-
"""Portfolio subtab callbacks: Recalculate correlation, Scoring & Allocation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from dash import dcc, html, dash_table, no_update
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go

from settings.paths import DIR_INPUT as _DIR_INPUT

from ..data import (
    THEME, SPREAD_CATEGORIES,
    load_spread_data, load_spread_timeseries, display_key,
    _get_duration_mult, resolve_legs, _load_leg_data,
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
         State('alpha-book-positions-store', 'data'),
         State('alpha-corr-lookback', 'value')],
        prevent_initial_call=True,
    )
    def recalc_curated_correlation(n_clicks, instruments, positions, lookback):
        all_entries = list(instruments or []) + list(positions or [])
        if not all_entries:
            raise PreventUpdate

        lookback = lookback or 252

        seen: set = set()
        all_spreads = {}
        for entry in all_entries:
            inst = entry.get('instrument', '')
            spread_type = entry.get('spread_type', '')
            if not inst or not spread_type:
                continue
            col_key = display_key(spread_type, inst)
            if col_key in seen:
                continue
            seen.add(col_key)
            ts = load_spread_timeseries(spread_type)
            if ts is not None and isinstance(ts, pd.DataFrame) and inst in ts.columns:
                s = ts[inst].copy()
                s.index = s.index.astype(str)
                all_spreads[col_key] = s

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
         State('alpha-curated-instruments-store', 'data'),
         State('alpha-book-positions-store', 'data'),
         State('alpha-dv01-budget', 'value')],
        prevent_initial_call=True
    )
    def run_scoring(n_clicks, candidates, mom_k, mom_window, total_capital, alloc_method, enforce_corr, curated_instruments, book_positions, total_dv01_budget):
        if not n_clicks:
            return html.Div(), html.Div(), html.Div(), []

        if not candidates:
            # Fall back to saved positions instead of blocking
            saved = list(book_positions or []) + list(curated_instruments or [])
            if not saved:
                return (
                    html.Div("No candidates or saved positions. Run scan in Candidates tab first.", style={'color': THEME['warning']}),
                    html.Div(), html.Div(), []
                )
            # Build minimal candidate rows from saved positions so the rest of the
            # pipeline can proceed without a prior scan.
            _seen: set = set()
            candidates = []
            for _e in saved:
                _inst = _e.get('instrument', '')
                if not _inst or _inst in _seen:
                    continue
                _seen.add(_inst)
                candidates.append({
                    'ID': _inst,
                    'spread_type': _e.get('spread_type', ''),
                    'direction': _e.get('direction', 'BUY'),
                    'style': _e.get('regime', _e.get('style', '')),
                    'score': float(_e.get('score', 0.01)),
                })

        try:
            total_capital = float(total_capital) if total_capital is not None else 10.0
            total_capital_mm = total_capital * 1000
            total_dv01_budget = float(total_dv01_budget) if total_dv01_budget is not None else 5.0

            # Merge all instruments from correlation matrix (curated_instruments) with saved positions (book_positions).
            # Combine both: curated from correlation check (new candidates) + book_positions (saved old trades).
            # When overlapping, curated takes precedence for updated metadata.
            _seen_insts: set = set()
            _merged_curated: list = []
            for _e in list(curated_instruments or []) + list(book_positions or []):
                _iname = _e.get('instrument', '')
                if _iname and _iname not in _seen_insts:
                    _seen_insts.add(_iname)
                    _merged_curated.append(_e)
            curated_instruments = _merged_curated

            df = pd.DataFrame(candidates)

            if curated_instruments:
                curated_ids = {e['instrument'] for e in curated_instruments}
                df_curated = df[df['ID'].isin(curated_ids)].copy()
                # Drop duplicates: candidates store may have the same ID under both
                # MR and trend sections; keep highest-score occurrence (already sorted).
                df_curated = df_curated.drop_duplicates(subset=['ID'], keep='first')
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
                        # Snap carry_roll is BUY-side raw; flip for SELL so it matches
                        # the convention stored in alpha-selected-candidates.
                        _inst_dir = str(inst_row.get('direction', '') or '').strip().upper()
                        if _inst_dir == 'SELL' and 'carry_roll' in inst_row:
                            try:
                                inst_row['carry_roll'] = -float(inst_row['carry_roll'])
                            except (TypeError, ValueError):
                                pass
                        extra_rows.append(inst_row)
                if extra_rows:
                    df_curated = pd.concat([df_curated, pd.DataFrame(extra_rows)], ignore_index=True)

                # Apply user-assigned regime and direction overrides from curated store
                _entry_map = {e['instrument']: e for e in curated_instruments}
                for inst, entry in _entry_map.items():
                    # Normalize regime: handle 'momentum' vs 'trend-following' synonyms
                    stored_regime = str(entry.get('regime', '') or '').strip().lower()
                    if stored_regime in {'mean-reverting', 'meanreversion', 'mean_reverting', 'mr'}:
                        stored_regime = 'mean-reverting'
                    elif stored_regime in {'trend', 'trendfollowing', 'trend_following', 'carry', 'mixed', 'momentum'}:
                        stored_regime = 'momentum'

                    # Normalize direction
                    stored_dir = str(entry.get('direction', '') or '').strip().upper()
                    if stored_dir not in {'BUY', 'SELL'}:
                        stored_dir = ''

                    mask = df_curated['ID'] == inst
                    if mask.any():
                        if stored_dir:
                            df_curated.loc[mask, 'direction'] = stored_dir
                        if stored_regime in {'mean-reverting', 'momentum'}:
                            df_curated.loc[mask, 'style'] = stored_regime

                df = df_curated

            if 'score' not in df.columns:
                df['score'] = 0.0
            df['score'] = pd.to_numeric(df['score'], errors='coerce').fillna(0.0)
            df_scored = df.sort_values('score', ascending=False)

            if not curated_instruments:
                df_scored = df_scored[df_scored['score'] > 0.001].copy()

            # df can be either a fresh pd.DataFrame(candidates) (default RangeIndex)
            # or df_curated (rebuilt via pd.concat(..., ignore_index=True) at the
            # extra_rows step above) — both start their own index at 0, so after
            # sort_values() the index may contain duplicate labels. A unique
            # RangeIndex here keeps every later .loc/.reindex by index safe.
            df_scored = df_scored.reset_index(drop=True)

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
                    weights_dict, risk_contrib, vol_computed = _compute_risk_parity_weights(df_scored)
                    df_scored['weight'] = df_scored['ID'].map(weights_dict).fillna(1 / n_trades)
                    rc_map = dict(zip(weights_dict.keys(), risk_contrib))
                    df_scored['risk_contribution'] = df_scored['ID'].map(rc_map).fillna(df_scored['weight'])

                    # Override vol with computed value from same 252-day window —
                    # but only for spread types whose native (or converted) units
                    # are yield-% decimals (TenorSpread, SwapSpread, and now
                    # TermBasis, which _compute_risk_parity_weights converts to a
                    # yield-equivalent via CTD duration). NetBasis/FuturesSwap stay
                    # in raw CNY price-point units, so their annualized std here is
                    # a meaningless huge number (e.g. 16000%+); keep their original
                    # snapshot-sourced vol (already in sensible bp units).
                    _RAW_UNIT_TYPES = {'NetBasis', 'FuturesSwap'}
                    _is_raw_unit = (
                        df_scored['spread_type'].isin(_RAW_UNIT_TYPES)
                        if 'spread_type' in df_scored.columns
                        else pd.Series(False, index=df_scored.index)
                    )
                    _new_vol = df_scored['ID'].map(vol_computed)
                    df_scored['vol'] = _new_vol.where(~_is_raw_unit, df_scored.get('vol')).fillna(df_scored.get('vol', np.nan))
                except Exception as e:
                    print(f"⚠ Risk parity failed: {e}, falling back to equal weights")
                    df_scored['weight'] = 1 / n_trades
                    df_scored['risk_contribution'] = 1 / n_trades

            weight_sum = df_scored['weight'].sum()
            if weight_sum > 0 and abs(weight_sum - 1.0) > 1e-9:
                df_scored['weight'] = df_scored['weight'] / weight_sum

            # Direction sign: +1 for BUY, -1 for SELL
            _direction_sign = (
                df_scored['direction'].apply(lambda d: -1.0 if str(d).strip().upper() == 'SELL' else 1.0)
                if 'direction' in df_scored.columns
                else pd.Series(1.0, index=df_scored.index)
            )

            # Step A: initial unsigned notional from weights
            df_scored['notional_mm'] = np.floor(df_scored['weight'] * total_capital_mm / 10) * 10

            # Step B: capital constraint for bond/swap/tenor spreads
            _CAPITAL_TYPES = {'TBondCurve', 'CBondCurve', 'TBondSwap', 'CBondSwap', 'TenorSpread', 'BondCurve', 'BondSwap'}
            _is_bond = (
                df_scored['spread_type'].isin(_CAPITAL_TYPES)
                if 'spread_type' in df_scored.columns
                else pd.Series(False, index=df_scored.index)
            )
            if _is_bond.any():
                _raw_signed = (df_scored.loc[_is_bond, 'notional_mm'] * _direction_sign[_is_bond]).sum()
                if abs(_raw_signed) > 1e-6:
                    _cap_scale = total_capital_mm / _raw_signed
                    df_scored.loc[_is_bond, 'notional_mm'] = (
                        np.floor(df_scored.loc[_is_bond, 'notional_mm'] * _cap_scale / 10) * 10
                    )

            # Step C: apply direction sign to all notionals
            df_scored['notional_mm'] = df_scored['notional_mm'] * _direction_sign

            # Step D: duration and DV01
            # Pre-load snapshots once per spread type so _get_duration_mult never
            # triggers a pickle read inside the per-row apply loop.
            _BOND_SNAP_TYPES = ('TBondCurve', 'TBondSwap', 'CBondCurve', 'CBondSwap')
            _snap_cache: dict[str, Optional[pd.DataFrame]] = {}
            if 'spread_type' in df_scored.columns:
                for _stype in df_scored['spread_type'].unique():
                    if _stype in _BOND_SNAP_TYPES and _stype not in _snap_cache:
                        try:
                            _snap_cache[_stype] = load_spread_data(_stype)
                        except Exception:
                            _snap_cache[_stype] = None

            df_scored['_duration'] = df_scored.apply(
                lambda r: _get_duration_mult(
                    str(r.get('ID', '')),
                    str(r.get('spread_type', '')),
                    snap=_snap_cache.get(str(r.get('spread_type', ''))),
                ),
                axis=1,
            )
            df_scored['DV01_k'] = (df_scored['notional_mm'].abs() * df_scored['_duration'] / 10_000 * 1_000).round(1)

            # Step E: DV01 constraint — each side ≤ total_dv01_budget MM CNY/bp
            _dv01_budget_k = total_dv01_budget * 1000
            _buy_mask  = _direction_sign > 0
            _sell_mask = _direction_sign < 0
            _buy_dv01  = df_scored.loc[_buy_mask,  'DV01_k'].sum() if _buy_mask.any()  else 0.0
            _sell_dv01 = df_scored.loc[_sell_mask, 'DV01_k'].sum() if _sell_mask.any() else 0.0
            # use the larger of the two sides so both sides stay within budget after scaling
            _single_side_dv01 = max(_buy_dv01, _sell_dv01) if (_buy_dv01 > 0 and _sell_dv01 > 0) else (_buy_dv01 + _sell_dv01)
            if _single_side_dv01 > 1e-6 and _dv01_budget_k > 0:
                _dv01_scale = _dv01_budget_k / _single_side_dv01
                df_scored['notional_mm'] = np.floor(df_scored['notional_mm'] * _dv01_scale / 10) * 10
                df_scored['DV01_k'] = (df_scored['notional_mm'].abs() * df_scored['_duration'] / 10_000 * 1_000).round(1)

            df_nonzero = df_scored[df_scored['weight'] > 0.0001].copy()
            optimized_results = df_nonzero.to_dict('records')

            # Step F: Resolve underlying instrument legs for each trade
            try:
                _leg_data = _load_leg_data()
                leg1_list = []
                leg2_list = []
                for _, row in df_scored.iterrows():
                    stype = str(row.get('spread_type', ''))
                    tid = str(row.get('ID', ''))
                    dur = float(row.get('_duration', 0.0)) if pd.notna(row.get('_duration')) else 0.0
                    l1, l2 = resolve_legs(stype, tid, dur, _leg_data)
                    leg1_list.append(l1)
                    leg2_list.append(l2)
                df_scored['Leg1'] = leg1_list
                df_scored['Leg2'] = leg2_list
            except Exception as e:
                print(f"⚠ Leg resolution failed: {e}")
                df_scored['Leg1'] = ''
                df_scored['Leg2'] = ''

            display_cols = [
                'ID', 'Leg1', 'Leg2', 'style', 'direction',
                'Zscore', 'spread', 'mean', 'vol',
                'carry_roll', 'breakeven_3m', 'stop_loss', 'profit_target',
                'seasonal_edge_bps', 'score',
                'weight', 'risk_contribution', 'notional_mm', 'DV01_k',
            ]
            available_cols = [c for c in display_cols if c in df_scored.columns]
            df_display = df_scored[available_cols].copy()

            # Display-only ID rename:
            #   NetBasis  → "<code>-CTD"  (long CTD bond, short futures)
            #   TermBasis → "<code>-Cal"  (front/next calendar spread)
            #   FuturesSwap keeps its raw code (T / TL / TF / TS)
            # df_scored['ID'] stays raw throughout — renaming it in place would
            # break risk-parity lookups and snapshot persistence.
            _FUTURES_CODES = {'T', 'TL', 'TF', 'TS'}

            def _display_trade_id(row):
                trade_id = str(row.get('ID', ''))
                spread_type = str(df_scored.loc[row.name, 'spread_type']) if 'spread_type' in df_scored.columns else ''
                if trade_id in _FUTURES_CODES and 'NetBasis' in spread_type:
                    return f'{trade_id}-CTD'
                elif trade_id in _FUTURES_CODES and 'TermBasis' in spread_type:
                    return f'{trade_id}-Cal'
                elif trade_id in _FUTURES_CODES and 'FuturesSwap' in spread_type:
                    return f'{trade_id}-FtSwp'
                return trade_id

            if 'ID' in df_display.columns:
                df_display['ID'] = df_display.apply(_display_trade_id, axis=1)

            if 'style' in df_display.columns:
                def _style_to_regime_label(value):
                    style_value = str(value).strip().lower()
                    if style_value in {'meanreversion', 'mean_reverting'}:
                        return 'mean-reverting'
                    if style_value in {'trend', 'trendfollowing', 'carry', 'mixed'}:
                        return 'momentum'
                    return value

                df_display['style'] = df_display['style'].map(_style_to_regime_label)

            for col in df_display.columns:
                if col == 'risk_contribution':
                    df_display[col] = df_display[col].round(4)
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
            for col, decimals in [('weight', 4), ('risk_contribution', 2), ('notional_mm', 0)]:
                if col in df_display.columns:
                    total = df_display[col].sum()
                    summary_row[col] = round(total, decimals)
            # DV01_k TOTAL: single-side (larger of BUY / SELL) to match budget constraint
            if 'DV01_k' in df_display.columns:
                _dir_s = df_display['direction'].astype(str).str.strip().str.upper() if 'direction' in df_display.columns else pd.Series('BUY', index=df_display.index)
                _ss_buy  = pd.to_numeric(df_display.loc[_dir_s.eq('BUY'),  'DV01_k'], errors='coerce').sum()
                _ss_sell = pd.to_numeric(df_display.loc[_dir_s.eq('SELL'), 'DV01_k'], errors='coerce').sum()
                summary_row['DV01_k'] = round(max(_ss_buy, _ss_sell), 1)
            df_display = pd.concat([df_display, pd.DataFrame([summary_row])], ignore_index=True)

            # Colors mirror guide/AlphaPortfolio.jsx STEP3_ROWS table:
            # translucent pill badges for regime/direction, sign-colored data cells.
            _GREEN, _RED = '#34d399', '#f87171'
            conditional_style = [
                {'if': {'filter_query': '{style} = "momentum"', 'column_id': 'style'},
                 'backgroundColor': 'rgba(224,162,60,0.15)', 'color': THEME['accent'], 'fontWeight': '600'},
                {'if': {'filter_query': '{style} = "mean-reverting"', 'column_id': 'style'},
                 'backgroundColor': 'rgba(34,211,238,0.12)', 'color': THEME['cyan'], 'fontWeight': '600'},

                {'if': {'filter_query': '{direction} = "BUY"', 'column_id': 'direction'},
                 'backgroundColor': 'rgba(52,211,153,0.18)', 'color': _GREEN, 'fontWeight': '700'},
                {'if': {'filter_query': '{direction} = "SELL"', 'column_id': 'direction'},
                 'backgroundColor': 'rgba(239,68,68,0.18)', 'color': _RED, 'fontWeight': '700'},

                {'if': {'filter_query': '{Zscore} > 0', 'column_id': 'Zscore'}, 'color': _GREEN, 'fontWeight': '600'},
                {'if': {'filter_query': '{Zscore} < 0', 'column_id': 'Zscore'}, 'color': _RED, 'fontWeight': '600'},

                {'if': {'filter_query': '{carry_roll} >= 0', 'column_id': 'carry_roll'}, 'color': _GREEN},
                {'if': {'filter_query': '{carry_roll} < 0', 'column_id': 'carry_roll'}, 'color': _RED},

                {'if': {'column_id': 'stop_loss'}, 'color': _RED},
                {'if': {'column_id': 'profit_target'}, 'color': _GREEN},
                {'if': {'column_id': 'score'}, 'color': THEME['accent'], 'fontWeight': '600'},
            ]

            last_row_idx = len(df_display) - 1
            conditional_style += [
                {'if': {'row_index': 'odd'}, 'backgroundColor': 'rgba(255,255,255,0.015)'},
                {'if': {'row_index': last_row_idx}, 'fontWeight': 'bold', 'borderTop': f'1px solid {THEME["accent"]}'},
            ]

            _port_col_labels = {
                'Leg1': 'leg 1', 'Leg2': 'leg 2', 'style': 'style',
                'Zscore': 'z-score', 'spread': 'spread(bp)', 'mean': 'mean(bp)',
                'vol': 'vol(bp)',
                'carry_roll': 'CR(3m)', 'breakeven_3m': 'b/e(3m)',
                'stop_loss': 'stop(bp)', 'profit_target': 'target(bp)',
                'seasonal_edge_bps': 'seas.edge', 'score': 'score',
                'weight': 'weight', 'risk_contribution': 'RC%',
                'notional_mm': 'notional(MM)', 'DV01_k': 'DV01(k)',
                'direction': 'DIR',
            }
            table = dash_table.DataTable(
                id='alpha-scored-table',
                columns=[{'name': _port_col_labels.get(c, c), 'id': c} for c in df_display.columns],
                data=df_display.to_dict('records'),
                style_table={'overflowX': 'auto', 'overflowY': 'auto', 'maxHeight': '400px', 'backgroundColor': 'transparent', 'minWidth': '100%'},
                style_header={'backgroundColor': 'var(--surface-panel)', 'color': THEME['text_sub'],
                              'fontWeight': '600', 'textAlign': 'left', 'border': 'none',
                              'borderBottom': '1px solid var(--border-strong)', 'fontSize': '10px',
                              'textTransform': 'uppercase', 'letterSpacing': '0.05em', 'position': 'sticky', 'top': '0'},
                style_cell={'backgroundColor': 'transparent', 'color': THEME['text_main'], 'textAlign': 'left',
                            'padding': '6px 8px', 'fontSize': '11px', 'border': 'none',
                            'borderBottom': '1px solid rgba(255,255,255,0.04)', 'minWidth': '80px'},
                style_data_conditional=conditional_style,
                sort_action='native', page_size=15,
            )

            summary = html.Div([
                html.Div([
                    html.Div([html.Strong("Total Trades: ", style={'color': THEME['text_sub']}), html.Span(f"{len(df_scored)}", style={'color': THEME['text_main']})], style={'marginRight': '30px'}),
                    html.Div([html.Strong("Capital Allocated: ", style={'color': THEME['text_sub']}), html.Span(f"{total_capital:.1f} B CNY", style={'color': THEME['text_main']})], style={'marginRight': '30px'}),
                    html.Div([html.Strong("DV01 Budget: ", style={'color': THEME['text_sub']}), html.Span(f"{total_dv01_budget:.1f} MM CNY", style={'color': THEME['text_main']})], style={'marginRight': '30px'}),
                    html.Div([html.Strong("Avg Score: ", style={'color': THEME['text_sub']}), html.Span(f"{df_scored['score'].mean():.3f}", style={'color': THEME['text_main']})], style={'marginRight': '30px'}),
                    html.Div([html.Strong("Risk Parity: ", style={'color': THEME['text_sub']}), html.Span(f"σ(RC)={df_scored['risk_contribution'].std():.3f}" if 'risk_contribution' in df_scored.columns else "N/A", style={'color': THEME['text_main']})], style={'marginRight': '30px'}),
                    html.Div([html.Strong("BUY/SELL: ", style={'color': THEME['text_sub']}), html.Span(f"{(df_scored['direction'] == 'BUY').sum()} / {(df_scored['direction'] == 'SELL').sum()}" if 'direction' in df_scored.columns else "N/A", style={'color': THEME['text_main']})]),
                ], style={'display': 'flex', 'flexWrap': 'wrap', 'marginBottom': '15px'}),
                html.Div([
                    html.Strong("By Regime: ", style={'color': THEME['text_sub']}),
                    html.Span(
                        " | ".join([f"{style}: {count}" for style, count in df_display['style'].value_counts(dropna=False).items()])
                        if 'style' in df_display.columns else "",
                        style={'color': THEME['text_main'], 'fontSize': '12px'},
                    ),
                ]),
            ])

            risk_chart = html.Div()
            if 'risk_contribution' in df_scored.columns and 'weight' in df_scored.columns:
                fig = go.Figure()
                # df_display['ID'] (display alias) shares df_scored's unique
                # RangeIndex (reset above), so a plain index lookup is safe here.
                _chart_ids = df_display['ID'] if 'ID' in df_display.columns else df_scored['ID']
                df_chart = df_scored.nlargest(15, 'weight')[['ID', 'weight', 'risk_contribution']].copy()
                df_chart['ID'] = _chart_ids.reindex(df_chart.index)
                fig.add_trace(go.Bar(x=df_chart['ID'], y=df_chart['weight'] * 100, name='Weight (%)', marker_color=THEME['accent'], yaxis='y'))
                fig.add_trace(go.Bar(x=df_chart['ID'], y=df_chart['risk_contribution'] * 100, name='Risk Contribution (%)', marker_color=THEME['success'], yaxis='y'))
                fig.update_layout(
                    title={'text': 'Portfolio Allocation: Weights vs Risk Contributions', 'font': {'size': 14, 'color': THEME['text_main']}},
                    xaxis={'title': 'Trade ID', 'tickangle': -45, 'color': THEME['text_main']},
                    yaxis={'title': 'Percentage (%)', 'color': THEME['text_main']},
                    barmode='group', template='plotly_dark',
                    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
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
                        'Leg1', 'Leg2',
                        'Zscore', 'spread', 'carry_roll', 'breakeven_3m', 'vol', 'halflife',
                        'stop_loss', 'profit_target',
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
