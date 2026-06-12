# -*- coding: utf-8 -*-
"""Candidates subtab callbacks: Scan, Correlation Check, Curated instrument list."""

from __future__ import annotations

import json as _json
from datetime import datetime

import numpy as np
import pandas as pd

from dash import dcc, html, dash_table, callback_context
from dash.dependencies import Input, Output, State, ALL
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go

from ..data import (
    THEME, SPREAD_CATEGORIES, ZSCORE_ENTRY_THRESHOLD,
    _get_input_dir, _load_pickle_safe,
    load_spread_data, load_spread_timeseries,
    _get_borrow_cost_annual_bp, _get_ttm_display, _get_current_fr007_bp,
)
from ..scoring import (
    compute_spread_correlation, rank_low_correlation_pairs, compute_scan_score,
)


_ALPHA_BOOK_POSITIONS_PARQUET = _get_input_dir() / 'alpha_book_positions.parquet'
_REGIME_LOOKUP_CACHE: dict[str, dict[str, str]] = {}
_REGIME_CACHE_MTIME: float = 0.0   # mtime of Alpha-spreadsrt.pkl when cache was last built


def _invalidate_regime_cache_if_stale() -> None:
    """Clear _REGIME_LOOKUP_CACHE if the snapshot pickle has been updated since last build."""
    global _REGIME_CACHE_MTIME
    snap_path = _get_input_dir() / 'Alpha-spreadsrt.pkl'
    try:
        current_mtime = snap_path.stat().st_mtime
    except FileNotFoundError:
        return
    if current_mtime != _REGIME_CACHE_MTIME:
        _REGIME_LOOKUP_CACHE.clear()
        _REGIME_CACHE_MTIME = current_mtime


def _style_to_regime(style: object) -> str:
    style_value = str(style or '').strip().lower()
    if style_value in {'meanreversion', 'mean_reverting', 'mean-reverting'}:
        return 'mean-reverting'
    if style_value in {'trend', 'trendfollowing', 'trend_following', 'trending', 'carry', 'mixed', 'momentum'}:
        return 'momentum'
    return 'uncertain'


def _get_upstream_regime(spread_type: str, instrument: str) -> str:
    spread_type = str(spread_type or '').strip()
    instrument = str(instrument or '').strip()
    if not spread_type or not instrument:
        return 'uncertain'

    _invalidate_regime_cache_if_stale()
    cache = _REGIME_LOOKUP_CACHE.get(spread_type)
    if cache is None:
        cache = {}
        try:
            snap = load_spread_data(spread_type)
            if isinstance(snap, pd.DataFrame) and not snap.empty and 'style' in snap.columns:
                style_series = snap['style'].astype(str).str.strip().str.lower()
                for idx, style in style_series.items():
                    cache[str(idx)] = _style_to_regime(style)
        except Exception:
            cache = {}
        _REGIME_LOOKUP_CACHE[spread_type] = cache

    return cache.get(instrument, 'uncertain')


def _normalize_curated_entry(entry: dict, *, infer_regime: bool = True) -> dict:
    instrument = str(entry.get('instrument') or entry.get('ID') or '').strip()
    spread_type = str(entry.get('spread_type') or entry.get('type') or '').strip()
    # Prefer 'style' (already a raw category) over 'regime' when regime is absent/uncertain.
    _raw = str(entry.get('regime') or entry.get('style') or '').strip()
    regime = _style_to_regime(_raw) if _raw else 'uncertain'
    direction = str(entry.get('direction') or '').strip().upper()

    if infer_regime and regime == 'uncertain':
        regime = _get_upstream_regime(spread_type, instrument)

    normalized = dict(entry)
    normalized['instrument'] = instrument
    normalized['spread_type'] = spread_type
    normalized['regime'] = regime
    normalized['direction'] = direction if direction in {'BUY', 'SELL'} else ''
    normalized['manual'] = bool(entry.get('manual', False))
    return normalized


def _load_alpha_book_positions() -> list[dict]:
    if not _ALPHA_BOOK_POSITIONS_PARQUET.exists():
        return []
    try:
        df = pd.read_parquet(_ALPHA_BOOK_POSITIONS_PARQUET)
    except Exception:
        return []

    if not isinstance(df, pd.DataFrame) or df.empty:
        return []

    # Deduplicate by (spread_type, ID) — keep first occurrence.
    _id_cols = [c for c in ('spread_type', 'ID') if c in df.columns]
    if _id_cols:
        df = df.drop_duplicates(subset=_id_cols, keep='first')

    _snap_cache: dict = {}
    rows: list[dict] = []
    for _, row in df.iterrows():
        entry = row.to_dict()
        entry.setdefault('instrument', entry.get('ID', ''))
        entry.setdefault('spread_type', entry.get('spread_type', ''))
        entry.setdefault('manual', False)

        inst  = str(entry.get('instrument', '') or '').strip()
        stype = str(entry.get('spread_type', '') or '').strip()

        # Regime: file 'style' column (from Summary save) > 'regime' column > snap lookup.
        raw_regime = str(entry.get('style', '') or entry.get('regime', '') or '').strip()
        if not raw_regime or raw_regime == 'uncertain':
            if stype not in _snap_cache:
                try:
                    _snap_cache[stype] = load_spread_data(stype)
                except Exception:
                    _snap_cache[stype] = None
            snap = _snap_cache[stype]
            if snap is not None and inst in snap.index and 'style' in snap.columns:
                raw_regime = str(snap.loc[inst, 'style'] or '').strip()
        entry['regime'] = raw_regime or 'uncertain'

        # Direction: file 'direction' column > snap lookup.
        raw_dir = str(entry.get('direction', '') or '').strip().upper()
        if raw_dir not in {'BUY', 'SELL'}:
            if stype not in _snap_cache:
                try:
                    _snap_cache[stype] = load_spread_data(stype)
                except Exception:
                    _snap_cache[stype] = None
            snap = _snap_cache[stype]
            if snap is not None and inst in snap.index and 'direction' in snap.columns:
                raw_dir = str(snap.loc[inst, 'direction'] or '').strip().upper()
        entry['direction'] = raw_dir if raw_dir in {'BUY', 'SELL'} else ''

        entry = _normalize_curated_entry(entry, infer_regime=True)
        if entry['instrument'] and entry['spread_type']:
            rows.append(entry)
    return rows


def _merge_curated_entries(*groups: list[dict] | None) -> list[dict]:
    merged: list[dict] = []
    index: dict[tuple[str, str], int] = {}

    for group in groups:
        if not group:
            continue
        for raw_entry in group:
            if not isinstance(raw_entry, dict):
                continue
            entry = _normalize_curated_entry(raw_entry, infer_regime=True)
            key = (entry['spread_type'], entry['instrument'])
            if not key[0] or not key[1]:
                continue

            existing_idx = index.get(key)
            if existing_idx is None:
                index[key] = len(merged)
                merged.append(entry)
                continue

            existing = merged[existing_idx]
            for field, value in entry.items():
                if field == 'manual':
                    existing[field] = bool(existing.get(field, False)) or bool(value)
                elif field == 'regime':
                    existing_value = str(existing.get(field, '') or '').strip()
                    new_value = str(value or '').strip()
                    if existing_value in {'', 'uncertain'} and new_value:
                        existing[field] = new_value
                elif field == 'direction':
                    existing_value = str(existing.get(field, '') or '').strip()
                    new_value = str(value or '').strip()
                    if existing_value and not new_value:
                        continue
                    if new_value:
                        existing[field] = new_value
                elif value not in (None, '', [], {}):
                    existing[field] = value

    return merged


def register_candidate_callbacks(app) -> None:
    """Register all Candidates subtab callbacks."""

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
         State('alpha-direction-filter', 'value'),
         State('seasonal-prefilter-toggle', 'value'),
         State('seasonal-prefilter-min-consistency', 'value'),
         State('seasonal-prefilter-p-thresh', 'value')],
        prevent_initial_call=True
    )
    def scan_candidates(n_clicks, categories, zscore_thd, direction,
                        seasonal_prefilter, seasonal_min_consistency, seasonal_p_thresh):
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
            # Load seasonal-spds.pkl (for edge term + optional pre-filter gate).
            _seasonal_data = None
            try:
                import pickle as _pkl
                _seas_path = _get_input_dir() / 'seasonal-spds.pkl'
                if _seas_path.exists():
                    with open(_seas_path, 'rb') as _f:
                        _seasonal_data = _pkl.load(_f)
            except Exception:
                _seasonal_data = None

            # ── Seasonal pre-filter gate ───────────────────────────────────────
            # Exclude instruments whose current-month seasonality is too weak
            # (p_value >= threshold or consistency < min_consistency).
            # Only applied when the toggle is ON and seasonal-spds.pkl is available.
            if use_seasonal_gate and _seasonal_data and isinstance(_seasonal_data, dict):
                import datetime as _dt
                _cur_month = _dt.date.today().month
                _month_key = f'm{_cur_month}'
                _has_stype = 'spread_type' in df_all.columns
                _has_id    = 'ID' in df_all.columns
                if _has_stype and _has_id:
                    _keep_mask = pd.Series(True, index=df_all.index)
                    _excluded_count = 0
                    for _idx in df_all.index:
                        _stype = str(df_all.at[_idx, 'spread_type'])
                        _inst  = str(df_all.at[_idx, 'ID'])
                        _sdf   = _seasonal_data.get(_stype)
                        if not isinstance(_sdf, pd.DataFrame) or _inst not in _sdf.index:
                            continue  # no data → don't exclude (benefit of the doubt)
                        if _month_key not in _sdf.columns:
                            continue
                        _cell = _sdf.at[_inst, _month_key]
                        if not isinstance(_cell, dict):
                            continue
                        _p    = float(_cell.get('p_value', 1.0))
                        _cons = float(_cell.get('consistency', 0.0))
                        if _p >= seas_p_thresh or _cons < min_consistency:
                            _keep_mask.at[_idx] = False
                            _excluded_count += 1
                    df_all = df_all.loc[_keep_mask].copy()
                    if _excluded_count:
                        scanned_time += f' · seasonal gate excluded {_excluded_count}'

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
        # ── TenorSpread Carry Calculation ──────────────────────────────────────
        # Assume 2:1 DV01-hedged ratio (long 2 of short-tenor, short 1 of long-tenor).
        _TENOR_RATIO = 2.0  # DV01 hedge ratio (notional_long / notional_short)
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

                _cr_annual_adjusted = -_cr_ts_annual + _fin_adj - _bc_adj * 4.0
                _cr_3m = _cr_annual_adjusted * (90.0 / 360.0)
                df_all.loc[_ts_mask, 'carry_roll'] = _cr_3m.round(4)

        # Compute TTM (years) for display and breakeven calculation
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
                # Breakeven only applies when the direction-adjusted carry is negative.
                _cr_disp_be = _cr_be * _dir_sign_be
                _ttm_be = pd.to_numeric(df_all['ttm_display'], errors='coerce').replace(0, np.nan)
                _be_raw = (-_cr_disp_be / _ttm_be).where(_cr_disp_be.lt(0) & _ttm_be.notna())
                df_all['breakeven_3m'] = _be_raw.round(4)

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

        if 'breakeven_3m' in df_all.columns and 'vol' in df_all.columns:
            _be_f  = pd.to_numeric(df_all['breakeven_3m'], errors='coerce')
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

        _mr_display_cols = ['ID', 'spread_type', 'ttm_display', 'direction', 'regime', 'Zscore', 'spread', 'mean', 'vol', 'halflife', 'carry_roll', 'breakeven_3m', 'seasonal_edge_bps', 'score', 'stop_loss', 'profit_target']
        _trend_display_cols = ['ID', 'spread_type', 'ttm_display', 'direction', 'regime', 'Zscore', 'spread', 'mean', 'vol', 'carry_roll', 'breakeven_3m', 'seasonal_edge_bps', 'score', 'trend_state', 'stop_loss', 'profit_target']

        _all_display_cols = list(dict.fromkeys(_mr_display_cols + _trend_display_cols + ['style']))
        df_display = df_all.copy()
        if 'ID' not in df_display.columns and df_display.index.name == 'ID':
            df_display = df_display.reset_index()
        # Deduplicate by ID: keep the row with the highest score (df_all is already sorted desc).
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

        # Store raw (BUY-side) carry_roll in candidates so the portfolio display
        # flip is applied exactly once. The candidates DataTable flips for display only.
        candidate_data = df_display.to_dict('records')

        # carry_roll display-only sign flip: positive = earns carry from this direction.
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
        style_mr    = (no_regime | uncertain_mask) & style_s.eq('meanreversion')
        style_trend = (no_regime | uncertain_mask) & style_s.isin({'carry', 'trend', 'trendfollowing'})
        uncertain_unmapped = uncertain_mask & ~style_mr & ~style_trend

        df_mr    = df_display[mr_by_regime | style_mr | uncertain_unmapped][_mr_avail   ].copy()
        df_trend = df_display[trend_by_regime | style_trend][_trend_avail].copy()

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
            'spread_type': 'type', 'ttm_display': 'ttm',
            'carry_roll': 'carry+roll(3m,bp)', 'breakeven_3m': 'breakeven(3m,bp)',
            'stop_loss': 'stop(bp)', 'profit_target': 'target(bp)',
            'spread': 'spread(bp)', 'mean': 'mean(bp)', 'vol': 'vol(bp)',
            'regime': 'regime', 'trend_state': 'trend', 'regime_confidence': 'reg.conf',
            'seasonal_edge_bps': 'seas.edge(bp)',
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

        trend_body = html.Div("No momentum candidates under current filters.", style={'color': THEME['text_sub'], 'fontSize': '12px', 'padding': '8px'})
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

        table_trend = html.Div([html.H6(f"Momentum Candidates (max 20) - {len(df_trend)} found", style={'color': THEME['text_main'], 'marginBottom': '8px'}), style_summary_div, trend_body], style={'marginBottom': '20px'})

        table_out = html.Div([table_mr, table_trend])
        status = f"Found {len(df_all)} candidates at {scanned_time}"
        # candidate_data was already captured above (before carry_roll display flip)

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
                # Load each spread type's timeseries once, then index by instrument.
                _ts_cache: dict[str, pd.DataFrame | None] = {}
                all_spreads = {}
                for _, row in df_candidates.iterrows():
                    trade_id = row.get('ID', '')
                    spread_type = row.get('spread_type', '')
                    if not trade_id or not spread_type:
                        continue
                    if spread_type not in _ts_cache:
                        _ts_cache[spread_type] = load_spread_timeseries(spread_type)
                    ts = _ts_cache[spread_type]
                    if ts is not None and isinstance(ts, pd.DataFrame) and trade_id in ts.columns:
                        all_spreads[trade_id] = ts[trade_id]

                if len(all_spreads) >= 2:
                    for key in all_spreads:
                        all_spreads[key].index = all_spreads[key].index.astype(str)
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
                    row_meta = {
                        'spread_type': id_to_type.get(inst, 'Unknown'),
                        'instrument': inst,
                        'manual': False,
                        'regime': 'uncertain',
                        'direction': '',
                    }
                    if all_candidates:
                        for c in all_candidates:
                            if c.get('ID') == inst and c.get('spread_type') == row_meta['spread_type']:
                                # 'style' is already normalized to 'mean-reverting'/'momentum' by scan;
                                # fall back to 'regime' for older store entries.
                                _cand_style = str(c.get('style', '') or '').strip()
                                _cand_regime = str(c.get('regime', '') or '').strip()
                                row_meta['regime'] = _style_to_regime(_cand_style or _cand_regime)
                                row_meta['direction'] = c.get('direction', '')
                                break
                    if row_meta['regime'] == 'uncertain':
                        row_meta['regime'] = _get_upstream_regime(row_meta['spread_type'], inst) or 'uncertain'
                    curated_instruments.append(row_meta)
                    if len(curated_instruments) >= 10:
                        break
            if len(curated_instruments) >= 10:
                break

        curated_instruments = _merge_curated_entries(curated_instruments)

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
        if not current:
            current = _load_alpha_book_positions()

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
            # Auto-populate regime and direction from snapshot
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
            return _merge_curated_entries(current, [{
                'spread_type': spread_type,
                'instrument': instrument,
                'regime': _regime,
                'direction': _direction,
                'manual': True,
            }])

        if trig_dict and trig_dict.get('type') == 'curated-del':
            if not any(nc for nc in del_clicks if nc):
                raise PreventUpdate
            idx = trig_dict['index']
            return [e for i, e in enumerate(current) if i != idx]

        raise PreventUpdate

    # -------------------------------------------------------------------------
    # CANDIDATES: Update regime / direction from curated-table dropdowns
    # -------------------------------------------------------------------------
    @app.callback(
        Output('alpha-curated-instruments-store', 'data', allow_duplicate=True),
        [Input({'type': 'curated-regime',    'index': ALL}, 'value'),
         Input({'type': 'curated-direction', 'index': ALL}, 'value')],
        State('alpha-curated-instruments-store', 'data'),
        prevent_initial_call=True,
    )
    def update_curated_meta(regimes, directions, current):
        ctx = callback_context
        if not ctx.triggered or not current:
            raise PreventUpdate

        raw_prop = ctx.triggered[0]['prop_id']
        raw_id   = raw_prop.rsplit('.', 1)[0]
        try:
            trig_dict = _json.loads(raw_id)
        except (ValueError, TypeError):
            raise PreventUpdate

        trig_type = trig_dict.get('type', '')
        trig_idx  = trig_dict.get('index', None)
        if trig_idx is None or trig_idx >= len(current):
            raise PreventUpdate

        updated = [dict(e) for e in current]
        new_val = ctx.triggered[0]['value']
        if trig_type == 'curated-regime':
            updated[trig_idx]['regime'] = new_val or 'uncertain'
        elif trig_type == 'curated-direction':
            updated[trig_idx]['direction'] = new_val or ''
        else:
            raise PreventUpdate
        return updated

    # -------------------------------------------------------------------------
    # PORTFOLIO: Populate saved-positions store from alpha_book_positions.parquet
    # -------------------------------------------------------------------------
    @app.callback(
        Output('alpha-book-positions-store', 'data'),
        Input('an-alpha-subtabs', 'value'),
    )
    def refresh_positions_store(active_subtab):
        if active_subtab != 'portfolio':
            raise PreventUpdate
        return _load_alpha_book_positions()

    # -------------------------------------------------------------------------
    # CANDIDATES: Render curated instrument table + curated correlation view
    # -------------------------------------------------------------------------
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

        _sub  = {'color': THEME['text_sub'], 'fontSize': '12px', 'fontStyle': 'italic'}
        _cell = {'padding': '6px 10px', 'fontSize': '12px', 'color': THEME['text_main']}
        _hdr  = {**_cell, 'color': THEME['text_sub'], 'fontWeight': '600', 'fontSize': '11px',
                 'borderBottom': f"1px solid {THEME['table_header']}"}

        instruments = instruments or []
        positions   = positions   or []
        matrix_cols = set(matrix_data.keys()) if matrix_data else set()

        # Remove from Table A any instrument already present in Table B (Saved Positions).
        _pos_inst_set = {e.get('instrument', '') for e in positions}
        instruments = [e for e in instruments if e.get('instrument', '') not in _pos_inst_set]

        _REGIME_OPTIONS = [
            {'label': 'mean-reverting', 'value': 'mean-reverting'},
            {'label': 'momentum',       'value': 'momentum'},
        ]
        _DIR_OPTIONS = [
            {'label': 'BUY',  'value': 'BUY'},
            {'label': 'SELL', 'value': 'SELL'},
        ]
        _dd_style = {'fontSize': '12px', 'minWidth': '130px'}
        _dd_warn  = {'fontSize': '12px', 'minWidth': '130px',
                     'border': f"1px solid {THEME['warning']}", 'borderRadius': '4px'}

        def _in_matrix_cell(inst):
            return (html.Span("✓", style={'color': THEME['success']})
                    if inst in matrix_cols
                    else html.Span("—", style={'color': THEME['text_sub']}))

        shared_header = html.Tr([
            html.Th("Spread Type", style=_hdr),
            html.Th("Instrument",  style=_hdr),
            html.Th("Regime",      style=_hdr),
            html.Th("Direction",   style=_hdr),
            html.Th("In Matrix",   style={**_hdr, 'textAlign': 'center'}),
            html.Th("",            style=_hdr),
        ])

        # ── Table A: candidate instruments (from correlation check + user-added) ──
        curated_rows = []
        for i, entry in enumerate(instruments):
            stype = entry.get('spread_type', '')
            inst  = entry.get('instrument', '')
            stored_regime = entry.get('regime', 'uncertain')
            regime    = (_get_upstream_regime(stype, inst) or 'uncertain'
                         if stored_regime == 'uncertain' else stored_regime)
            direction = entry.get('direction', '') or ''
            manual    = bool(entry.get('manual', False))

            regime_known = regime in {'mean-reverting', 'momentum'}
            dir_known    = direction in {'BUY', 'SELL'}
            regime_editable    = manual or not regime_known
            direction_editable = manual or not dir_known

            regime_cell = (
                dcc.Dropdown(
                    id={'type': 'curated-regime', 'index': i},
                    options=_REGIME_OPTIONS,
                    value=regime if regime_known else None,
                    placeholder='Assign regime…', clearable=False,
                    style=_dd_style if regime_known else _dd_warn,
                ) if regime_editable
                else html.Div(regime, style={'padding': '6px 2px', 'fontSize': '12px', 'color': THEME['text_main']})
            )
            dir_cell = (
                dcc.Dropdown(
                    id={'type': 'curated-direction', 'index': i},
                    options=_DIR_OPTIONS,
                    value=direction if dir_known else None,
                    placeholder='Assign…', clearable=False,
                    style=_dd_style if dir_known else _dd_warn,
                ) if direction_editable
                else html.Div(direction, style={'padding': '6px 2px', 'fontSize': '12px', 'color': THEME['text_main']})
            )
            curated_rows.append(html.Tr([
                html.Td(stype, style=_cell),
                html.Td(inst,  style={**_cell, 'fontWeight': '500'}),
                html.Td(regime_cell, style={**_cell, 'padding': '2px 6px'}),
                html.Td(dir_cell,    style={**_cell, 'padding': '2px 6px'}),
                html.Td(_in_matrix_cell(inst), style={**_cell, 'textAlign': 'center'}),
                html.Td(
                    html.Button("×", id={'type': 'curated-del', 'index': i}, n_clicks=0,
                                style={'background': 'none', 'border': f"1px solid {THEME['danger']}",
                                       'color': THEME['danger'], 'borderRadius': '3px',
                                       'cursor': 'pointer', 'padding': '1px 7px',
                                       'fontSize': '13px', 'lineHeight': '1.2'}),
                    style={'textAlign': 'center'},
                ),
            ], style={'borderBottom': 'rgba(42,82,152,0.25) solid 1px'}))

        if curated_rows:
            table_a = html.Div(
                html.Table([html.Thead(shared_header), html.Tbody(curated_rows)],
                           style={'width': '100%', 'borderCollapse': 'collapse'}),
                style={'overflowY': 'auto', 'maxHeight': '220px',
                       'border': f"1px solid {THEME['table_header']}", 'borderRadius': '4px'},
            )
        else:
            table_a = html.Div(
                "Run Check Correlation in the Candidates subtab to populate this list.",
                style=_sub,
            )

        # ── Table B: saved positions (alpha_book_positions.parquet, read-only) ──
        pos_rows = []
        pos_header = html.Tr([
            html.Th("Spread Type", style=_hdr),
            html.Th("Instrument",  style=_hdr),
            html.Th("Regime",      style=_hdr),
            html.Th("Direction",   style=_hdr),
            html.Th("In Matrix",   style={**_hdr, 'textAlign': 'center'}),
            html.Th("",            style=_hdr),  # empty column to match Table A width
        ])
        for entry in positions:
            stype = entry.get('spread_type', '')
            inst  = entry.get('instrument', '')
            stored_regime = entry.get('regime', 'uncertain')
            regime    = (_get_upstream_regime(stype, inst) or 'uncertain'
                         if stored_regime == 'uncertain' else stored_regime)
            direction = entry.get('direction', '') or '—'
            _regime_color = (THEME['text_main'] if regime in {'mean-reverting', 'momentum'}
                             else THEME['text_sub'])
            pos_rows.append(html.Tr([
                html.Td(stype, style=_cell),
                html.Td(inst,  style={**_cell, 'fontWeight': '500'}),
                html.Td(regime,    style={**_cell, 'color': _regime_color}),
                html.Td(direction, style=_cell),
                html.Td(_in_matrix_cell(inst), style={**_cell, 'textAlign': 'center'}),
                html.Td("", style=_cell),
            ], style={'borderBottom': 'rgba(42,82,152,0.25) solid 1px'}))

        if pos_rows:
            table_b = html.Div(
                html.Table([html.Thead(pos_header), html.Tbody(pos_rows)],
                           style={'width': '100%', 'borderCollapse': 'collapse'}),
                style={'overflowY': 'auto', 'maxHeight': '220px',
                       'border': f"1px solid {THEME['table_header']}", 'borderRadius': '4px'},
            )
        else:
            table_b = html.Div("No saved positions found in alpha_book_positions.parquet.", style=_sub)

        table_div = html.Div([
            html.H6("Candidate Instruments", style={'color': THEME['text_main'],
                    'fontSize': '13px', 'marginBottom': '6px', 'marginTop': '0'}),
            table_a,
            html.H6("Saved Positions", style={'color': THEME['text_main'],
                    'fontSize': '13px', 'marginBottom': '6px', 'marginTop': '14px'}),
            table_b,
        ])

        # ── Combined correlation matrix (all instruments from both tables) ──
        all_instruments = instruments + [p for p in positions
                                         if p.get('instrument') not in {e.get('instrument') for e in instruments}]
        valid_ids = [e['instrument'] for e in all_instruments if e['instrument'] in matrix_cols]

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
                title='Curated Correlation Matrix',
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
                style_header={'backgroundColor': THEME['table_header'], 'color': THEME['text_sub'],
                              'fontWeight': '600', 'fontSize': '11px', 'padding': '6px 10px'},
                style_cell={'backgroundColor': THEME['bg_card'], 'color': THEME['text_main'],
                            'fontSize': '12px', 'padding': '6px 10px'},
                page_size=15,
            )

            not_in_count = len(all_instruments) - len(valid_ids)
            notice = (
                html.P(
                    f"ℹ️ {not_in_count} instrument(s) marked '—' are not yet in the matrix. "
                    "Click ↻ Recalculate Correlation below to rebuild the matrix.",
                    style={**_sub, 'marginTop': '6px'},
                ) if not_in_count > 0 else html.Div()
            )

            corr_div = html.Div([
                html.H6("Curated Correlation Matrix", style={'color': THEME['text_main'], 'marginBottom': '8px'}),
                dcc.Graph(figure=hm),
                html.H6("Lowest Correlation Pairs", style={'color': THEME['text_main'],
                        'marginTop': '14px', 'marginBottom': '8px'}),
                pairs_tbl,
                notice,
            ])
        else:
            corr_div = html.Div(
                "Click ↻ Recalculate Correlation to build the matrix for all instruments.",
                style=_sub,
            )

        return table_div, corr_div

    # -------------------------------------------------------------------------
    # SEASONAL SCREENER: cross-instrument monthly consistency table
    # -------------------------------------------------------------------------
    @app.callback(
        Output('seasonal-screener-results', 'children'),
        Input('seasonal-screener-stype',      'value'),
        Input('seasonal-screener-month',       'value'),
        Input('seasonal-screener-min-years',   'value'),
        Input('seasonal-screener-p-thresh',    'value'),
    )
    def update_seasonal_screener(stype, month, min_years, p_thresh):
        """Render the cross-instrument seasonal consistency table."""
        import pickle as _pkl
        import datetime as _dt

        if not stype or not month:
            return html.Div()

        month     = int(month)
        min_years = int(min_years or 3)
        p_thresh  = float(p_thresh or 0.10)
        month_key = f'm{month}'
        _MONTH_ABBR = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
        month_name = _MONTH_ABBR[month - 1]

        # Load seasonal-spds.pkl (with mtime cache reusing the module-level dict pattern)
        seas_path = _get_input_dir() / 'seasonal-spds.pkl'
        seasonal_data = None
        try:
            if seas_path.exists():
                with open(seas_path, 'rb') as _f:
                    seasonal_data = _pkl.load(_f)
        except Exception as exc:
            return html.Div(f"Error loading seasonal-spds.pkl: {exc}", style={'color': THEME['warning']})

        if seasonal_data is None:
            return html.Div(
                "seasonal-spds.pkl not found. Run the EOD StatGenerator to generate it.",
                style={'color': THEME['text_sub'], 'fontSize': '12px'},
            )

        sdf = seasonal_data.get(stype)
        if not isinstance(sdf, pd.DataFrame) or sdf.empty:
            return html.Div(
                f"No seasonal data for {stype}. Run EOD StatGenerator.",
                style={'color': THEME['text_sub'], 'fontSize': '12px'},
            )

        if month_key not in sdf.columns:
            return html.Div(
                f"Month {month_name} not found in seasonal data for {stype}.",
                style={'color': THEME['text_sub'], 'fontSize': '12px'},
            )

        # Build display rows — filter by min_years and p_thresh
        _arrow   = {'up': '↑', 'down': '↓', 'neutral': '—'}
        _dir_col = {'up': THEME['success'], 'down': THEME['danger'], 'neutral': THEME['text_sub']}
        rows = []
        for inst in sdf.index:
            cell = sdf.at[inst, month_key]
            if not isinstance(cell, dict):
                continue
            n_yrs   = int(cell.get('n_years', 0))
            p_val   = float(cell.get('p_value', 1.0))
            cons    = float(cell.get('consistency', 0.5))
            avg_chg = float(cell.get('avg_chg_bp', 0.0))
            direction = str(cell.get('direction', 'neutral'))
            if n_yrs < min_years:
                continue
            if p_val >= p_thresh:
                continue
            rows.append({
                'instrument': inst,
                'direction':  direction,
                'cons_pct':   cons * 100.0,
                'avg_chg':    avg_chg,
                'n_years':    n_yrs,
                'p_value':    p_val,
            })

        if not rows:
            return html.Div(
                f"No instruments pass filters for {stype} / {month_name} "
                f"(min {min_years}yr, p < {p_thresh}).",
                style={'color': THEME['text_sub'], 'fontSize': '12px'},
            )

        rows.sort(key=lambda r: (-r['cons_pct'], r['p_value']))

        header = html.Div([
            html.Span("Instrument",  style={'fontSize':'10px','color':THEME['text_sub'],'minWidth':'130px'}),
            html.Span("Dir",         style={'fontSize':'10px','color':THEME['text_sub'],'minWidth':'28px'}),
            html.Span("Cons%",       style={'fontSize':'10px','color':THEME['text_sub'],'minWidth':'46px'}),
            html.Span("AvgΔbp",      style={'fontSize':'10px','color':THEME['text_sub'],'minWidth':'52px'}),
            html.Span("Obs",         style={'fontSize':'10px','color':THEME['text_sub'],'minWidth':'30px'}),
            html.Span("p-val",       style={'fontSize':'10px','color':THEME['text_sub'],'minWidth':'42px'}),
        ], style={'display':'flex','gap':'8px','padding':'3px 8px',
                  'borderBottom':'1px solid #1a3a7a','marginBottom':'2px'})

        data_rows = []
        for r in rows:
            sig = '**' if r['p_value'] < 0.05 else ('*' if r['p_value'] < 0.10 else '')
            dc  = _dir_col[r['direction']]
            data_rows.append(html.Div([
                html.Span(r['instrument'],                  style={'fontSize':'11px','color':THEME['text_main'],'minWidth':'130px','overflow':'hidden','textOverflow':'ellipsis'}),
                html.Span(_arrow[r['direction']],           style={'fontSize':'11px','color':dc,'minWidth':'28px','fontWeight':'bold'}),
                html.Span(f"{r['cons_pct']:.0f}%{sig}",   style={'fontSize':'11px','color':THEME['text_main'],'minWidth':'46px'}),
                html.Span(f"{r['avg_chg']:+.1f}",          style={'fontSize':'11px','color': THEME['success'] if r['avg_chg'] > 0 else THEME['danger'],'minWidth':'52px'}),
                html.Span(f"n={r['n_years']}",             style={'fontSize':'11px','color':THEME['text_sub'],'minWidth':'30px'}),
                html.Span(f"{r['p_value']:.3f}",           style={'fontSize':'11px','color':THEME['text_sub'],'minWidth':'42px'}),
            ], style={'display':'flex','gap':'8px','padding':'2px 8px',
                      'borderRadius':'3px','backgroundColor':'transparent'}))

        note = html.Div(
            f"Showing {len(rows)} of {len(sdf)} instruments for {stype} / {month_name}. "
            "* p<0.10  ** p<0.05 (one-sided binomial; no FDR correction).",
            style={'fontSize':'9px','color':THEME['text_sub'],'marginTop':'6px','padding':'0 8px'},
        )

        return html.Div([header] + data_rows + [note],
                        style={'background': THEME['bg_main'], 'borderRadius': '4px',
                               'padding': '6px 0', 'maxHeight': '340px', 'overflowY': 'auto'})
