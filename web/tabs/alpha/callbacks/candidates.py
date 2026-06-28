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
    load_spread_data, load_spread_timeseries, display_key,
    _get_borrow_cost_annual_bp, _get_ttm_display, _get_current_fr007_bp,
)
from ..scoring import (
    compute_spread_correlation, rank_low_correlation_pairs,
    select_diverse_instruments, compute_scan_score,
)


_ALPHA_BOOK_POSITIONS_PARQUET = _get_input_dir() / 'alpha_book_positions.parquet'
_REGIME_LOOKUP_CACHE: dict[str, dict[str, str]] = {}

# Custom colorscale matching guide/AlphaCandidates.jsx corrCell():
# navy-blue (rgb(30,80,160)) for positive, brick-red (rgb(200,60,40))
# for negative, fading to a near-transparent center at 0.
_ALPHA_CORR_COLORSCALE = [
    [0.0, 'rgb(200,60,40)'],
    [0.5, 'rgb(20,35,60)'],
    [1.0, 'rgb(30,80,160)'],
]
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

        _mr_display_cols = ['ID', 'spread_type', 'ttm_display', 'direction', 'regime', 'Zscore', 'spread', 'mean', 'vol', 'halflife', 'carry_roll', 'breakeven_3m', 'seasonal_edge_bps', 'seasonal_label', 'score', 'stop_loss', 'profit_target']
        _trend_display_cols = ['ID', 'spread_type', 'ttm_display', 'direction', 'regime', 'Zscore', 'spread', 'mean', 'vol', 'carry_roll', 'breakeven_3m', 'seasonal_edge_bps', 'seasonal_label', 'score', 'trend_state', 'stop_loss', 'profit_target']

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

        df_mr         = df_display[mr_by_regime | style_mr][_mr_avail].copy()
        df_trend      = df_display[trend_by_regime | style_trend][_trend_avail].copy()
        df_uncertain  = df_display[uncertain_unmapped][_mr_avail].copy()

        regime_counts  = regime_s.value_counts(dropna=False)
        regime_summary = ', '.join([f"{k}: {int(v)}" for k, v in regime_counts.items()])
        style_summary_div = html.Div(f"Regime: {regime_summary}", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '8px'})

        def _signal_cards(df_rows, max_z=4.0):
            """Render a compact signal-card list for one regime bucket."""
            cards = []
            for row in df_rows:
                inst      = str(row.get('ID', '') or '')
                stype     = str(row.get('spread_type', '') or '')
                label     = display_key(stype, inst)
                direction = str(row.get('direction', '') or '').upper()
                z_raw     = row.get('Zscore', None)
                try:
                    z = float(z_raw)
                except (TypeError, ValueError):
                    z = 0.0

                # Direction pill
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

                # Z-score bar: red = negative (spread below mean), green = positive (above mean)
                z_clamped = max(-max_z, min(max_z, z))
                bar_pct   = abs(z_clamped) / max_z * 50.0   # 0–50% of half-bar
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

                # Seasonal chip — driven by seasonal_label (consistency-based, no p-value gate)
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
                    # Left: pill + ID + type badge, all fixed together
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
                    # Right: z-bar + label + seasonal tag, pinned to right edge
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

        mr_rows        = df_mr.head(20).to_dict('records')        if not df_mr.empty        else []
        trend_rows     = df_trend.head(20).to_dict('records')     if not df_trend.empty     else []
        uncertain_rows = df_uncertain.head(20).to_dict('records') if not df_uncertain.empty else []

        mr_cards        = _signal_cards(mr_rows)
        trend_cards     = _signal_cards(trend_rows)
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
                # Key is "spread_type/ID" to avoid collisions when multiple spread types
                # share the same short instrument ID (e.g. NetBasis, TermBasis, FuturesSwap
                # all use T/TL/TF/TS).
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
                        col_key = display_key(spread_type, trade_id)
                        all_spreads[col_key] = ts[trade_id]

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

        # Greedy maximin diversity selection — run first so the heatmap reflects
        # the same filtered set that goes into the curated list and matrix store.
        diverse_keys = select_diverse_instruments(
            corr_matrix, all_candidates or [], n=10,
            max_abs_corr=float(max_corr) if max_corr is not None else 1.0,
        )
        heatmap_assets = [k for k in diverse_keys if k in corr_matrix.columns]

        if len(heatmap_assets) >= 2:
            sub_corr = corr_matrix.loc[heatmap_assets, heatmap_assets]
            corr_vals = sub_corr.values.copy()
            mask_upper = np.triu(np.ones(corr_vals.shape), k=0).astype(bool)
            corr_vals[mask_upper] = np.nan

            heatmap = go.Figure(data=go.Heatmap(
                z=corr_vals, x=sub_corr.columns, y=sub_corr.index,
                colorscale=_ALPHA_CORR_COLORSCALE, zmin=-1, zmax=1,
                hovertemplate='%{y} vs %{x}<br>Corr: %{z:.3f}<extra></extra>',
            ))
            _hm_height = max(350, 28 * len(heatmap_assets) + 100)
            heatmap.update_layout(
                title=f'Spread Correlation Matrix — {len(heatmap_assets)} instruments (max |corr| ≤ {max_corr})',
                height=_hm_height,
                margin=dict(l=100, r=20, t=40, b=80),
                plot_bgcolor=THEME['bg_main'], paper_bgcolor=THEME['bg_main'],
                font=dict(color=THEME['text_main'], size=10),
                xaxis=dict(tickangle=45),
            )
            heatmap_div = dcc.Graph(figure=heatmap, style={'height': f'{_hm_height}px'})
        else:
            heatmap_div = html.Div("Not enough assets passed the correlation filter.", style={'color': THEME['text_sub']})

        warning_div = html.Div()
        if len(high_corr) > 0:
            warning_div = html.Div([
                html.P(f"⚠️ {len(high_corr)} pairs exceed max correlation threshold ({max_corr}). "
                       "Consider removing correlated candidates before sizing.",
                       style={'color': THEME['warning'], 'fontSize': '12px', 'marginTop': '10px'})
            ])

        # corr_matrix columns are display_key() values; build reverse lookup.
        col_key_to_stype: dict = {}
        col_key_to_id: dict = {}
        if all_candidates:
            for c in all_candidates:
                if 'ID' in c and 'spread_type' in c:
                    ck = display_key(c['spread_type'], c['ID'])
                    col_key_to_stype[ck] = c['spread_type']
                    col_key_to_id[ck]    = c['ID']

        curated_instruments: list = []
        for col_key in diverse_keys:
            stype = col_key_to_stype.get(col_key, 'Unknown')
            inst  = col_key_to_id.get(col_key, col_key)
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

        # Trim the stored corr_matrix to only the instruments that passed the
        # max_corr gate, so the curated matrix in Portfolio Step 1 stays clean.
        if diverse_keys:
            valid_keys = [k for k in diverse_keys if k in corr_matrix.columns]
            corr_matrix_store = corr_matrix.loc[valid_keys, valid_keys]
        else:
            corr_matrix_store = corr_matrix

        return html.Div([
            heatmap_div,
            warning_div,
        ]), [], corr_matrix_store.to_dict(), curated_instruments

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

    # -------------------------------------------------------------------------
    # CANDIDATES: Update regime / direction from curated-table dropdowns
    # -------------------------------------------------------------------------
    @app.callback(
        Output('alpha-curated-instruments-store', 'data', allow_duplicate=True),
        [Input({'type': 'curated-regime',    'stype': ALL, 'inst': ALL}, 'value'),
         Input({'type': 'curated-direction', 'stype': ALL, 'inst': ALL}, 'value')],
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
        _dd_style = {'fontSize': '11px', 'minWidth': '110px'}
        _dd_warn  = {'fontSize': '11px', 'minWidth': '110px',
                     'border': f"1px solid {THEME['warning']}", 'borderRadius': '4px'}

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
            """Visually distinct colored chip for regime — teal for MR, amber for momentum."""
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
            return (html.Span("●", title="in correlation matrix",
                              style={'color': THEME['success'], 'fontSize': '9px'})
                    if in_matrix
                    else html.Span("○", title="not in matrix",
                                   style={'color': THEME['text_sub'], 'fontSize': '9px'}))

        def _z_bar(z, max_z=4.0):
            """Mini z-score bar — same style as Candidates signal cards."""
            try:
                z = float(z)
            except (TypeError, ValueError):
                z = 0.0
            z_clamped = max(-max_z, min(max_z, z))
            bar_pct   = abs(z_clamped) / max_z * 50.0
            bar_color = THEME['danger'] if z < 0 else THEME['success']
            if z < 0:
                bar_style = {'position': 'absolute', 'right': '50%',
                             'width': f'{bar_pct:.1f}%', 'height': '100%',
                             'backgroundColor': bar_color, 'opacity': '0.7',
                             'borderRadius': '2px 0 0 2px'}
            else:
                bar_style = {'position': 'absolute', 'left': '50%',
                             'width': f'{bar_pct:.1f}%', 'height': '100%',
                             'backgroundColor': bar_color, 'opacity': '0.7',
                             'borderRadius': '0 2px 2px 0'}
            return html.Div([
                html.Div(style={'position': 'relative', 'height': '5px',
                                'backgroundColor': THEME['bg_main'],
                                'borderRadius': '3px', 'overflow': 'hidden',
                                'width': '50px', 'display': 'inline-block',
                                'verticalAlign': 'middle'},
                         children=[html.Div(style=bar_style)]),
                html.Span(f'{z:+.1f}σ', style={
                    'fontSize': '10px', 'color': bar_color,
                    'fontWeight': 'bold', 'marginLeft': '3px', 'verticalAlign': 'middle',
                }),
            ], style={'display': 'inline-flex', 'alignItems': 'center'})

        def _seas_chip(label):
            label = str(label or '').strip().lower()
            if label == 'strong':
                return html.Span('S↑↑', title='Strong seasonal tailwind (consistency ≥75%)', style={
                    'backgroundColor': '#0d5c0d', 'color': '#7fff7f',
                    'fontSize': '9px', 'fontWeight': 'bold', 'padding': '1px 4px',
                    'borderRadius': '3px', 'cursor': 'default',
                })
            if label == 'weak':
                return html.Span('S↑', title='Weak seasonal tailwind (consistency ≥60%)', style={
                    'backgroundColor': '#2a4a2a', 'color': '#a0d0a0',
                    'fontSize': '9px', 'fontWeight': 'bold', 'padding': '1px 4px',
                    'borderRadius': '3px', 'cursor': 'default',
                })
            if label == 'against':
                return html.Span('S↓', title='Seasonal headwind (consistency ≥60% against)', style={
                    'backgroundColor': '#4a1a1a', 'color': '#d09090',
                    'fontSize': '9px', 'fontWeight': 'bold', 'padding': '1px 4px',
                    'borderRadius': '3px', 'cursor': 'default',
                })
            return None

        # ── Card grid: candidate instruments (from correlation check + user-added) ──
        curated_cards = []
        for entry_id, entry in enumerate(instruments):
            stype = entry.get('spread_type', '')
            inst  = entry.get('instrument', '')
            stored_regime = entry.get('regime', 'uncertain')
            regime    = (_get_upstream_regime(stype, inst) or 'uncertain'
                         if stored_regime == 'uncertain' else stored_regime)
            direction = entry.get('direction', '') or ''
            manual    = bool(entry.get('manual', False))
            z_val     = entry.get('Zscore', None)
            seas_label = entry.get('seasonal_label', '')

            regime_known = regime in {'mean-reverting', 'momentum'}
            dir_known    = direction in {'BUY', 'SELL'}
            regime_editable    = manual or not regime_known
            direction_editable = manual or not dir_known

            regime_widget = (
                dcc.Dropdown(
                    id={'type': 'curated-regime', 'stype': stype, 'inst': inst},
                    options=_REGIME_OPTIONS,
                    value=regime if regime_known else None,
                    placeholder='regime…', clearable=False,
                    style=_dd_style if regime_known else _dd_warn,
                ) if regime_editable
                else _regime_chip(regime)
            )
            dir_widget = (
                dcc.Dropdown(
                    id={'type': 'curated-direction', 'stype': stype, 'inst': inst},
                    options=_DIR_OPTIONS,
                    value=direction if dir_known else None,
                    placeholder='dir…', clearable=False,
                    style=_dd_style if dir_known else _dd_warn,
                ) if direction_editable
                else _dir_pill(direction)
            )

            curated_cards.append(html.Div([
                # Row 1: instrument label + matrix dot + delete button
                html.Div([
                    html.Span(display_key(stype, inst), style={
                        'color': THEME['text_main'], 'fontSize': '11px', 'fontWeight': '600',
                        'flex': '1', 'overflow': 'hidden', 'textOverflow': 'ellipsis', 'whiteSpace': 'nowrap',
                    }),
                    _matrix_dot(inst, stype),
                    html.Button("×", id={'type': 'curated-del', 'stype': stype, 'inst': inst}, n_clicks=0,
                                style={'background': 'none', 'border': f"1px solid {THEME['danger']}",
                                       'color': THEME['danger'], 'borderRadius': '3px',
                                       'cursor': 'pointer', 'padding': '0px 4px',
                                       'fontSize': '11px', 'lineHeight': '1.3',
                                       'marginLeft': '4px', 'flexShrink': '0'}),
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '4px'}),
                # Row 2: type badge + z-score bar + seasonal chip
                html.Div([
                    html.Span(stype, style={
                        'backgroundColor': THEME['table_header'], 'color': THEME['text_sub'],
                        'fontSize': '9px', 'padding': '1px 4px', 'borderRadius': '2px',
                        'marginRight': '5px', 'flexShrink': '0',
                    }),
                    _z_bar(z_val) if z_val is not None else html.Span('z=—', style={'color': THEME['text_sub'], 'fontSize': '10px'}),
                    *([html.Div(_seas_chip(seas_label), style={'marginLeft': '5px', 'flexShrink': '0'})] if _seas_chip(seas_label) else []),
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '5px'}),
                # Row 3: regime chip/dropdown + direction pill/dropdown
                html.Div([
                    html.Div(regime_widget, style={'marginRight': '5px', 'flexShrink': '0'}),
                    html.Div(dir_widget,    style={'flexShrink': '0'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),
            ], style={
                'padding': '7px 8px',
                'borderRadius': '4px',
                'backgroundColor': THEME['bg_card'],
                'borderLeft': f"3px solid {_dir_border(direction)}",
            }))

        if curated_cards:
            grid_a = html.Div(curated_cards, style={
                'display': 'grid',
                'gridTemplateColumns': 'repeat(3, 1fr)',
                'gap': '5px',
                'maxHeight': '300px',
                'overflowY': 'auto',
                'paddingRight': '2px',
            })
        else:
            grid_a = html.Div(
                "Run Check Correlation in the Candidates subtab to populate this list.",
                style=_sub,
            )

        # ── Card grid: saved positions (alpha_book_positions.parquet, read-only) ──
        pos_cards = []
        for entry in positions:
            stype = entry.get('spread_type', '')
            inst  = entry.get('instrument', '')
            stored_regime = entry.get('regime', 'uncertain')
            regime    = (_get_upstream_regime(stype, inst) or 'uncertain'
                         if stored_regime == 'uncertain' else stored_regime)
            direction  = entry.get('direction', '') or ''
            z_val      = entry.get('Zscore', None)
            seas_label = entry.get('seasonal_label', '')
            pos_cards.append(html.Div([
                html.Div([
                    html.Span(display_key(stype, inst), style={
                        'color': THEME['text_main'], 'fontSize': '11px', 'fontWeight': '600',
                        'flex': '1', 'overflow': 'hidden', 'textOverflow': 'ellipsis', 'whiteSpace': 'nowrap',
                    }),
                    _matrix_dot(inst, stype),
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '4px'}),
                html.Div([
                    html.Span(stype, style={
                        'backgroundColor': THEME['table_header'], 'color': THEME['text_sub'],
                        'fontSize': '9px', 'padding': '1px 4px', 'borderRadius': '2px',
                        'marginRight': '5px', 'flexShrink': '0',
                    }),
                    _z_bar(z_val) if z_val is not None else html.Span('z=—', style={'color': THEME['text_sub'], 'fontSize': '10px'}),
                    *([html.Div(_seas_chip(seas_label), style={'marginLeft': '5px', 'flexShrink': '0'})] if _seas_chip(seas_label) else []),
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '5px'}),
                html.Div([
                    _regime_chip(regime),
                    html.Div(style={'flex': '1'}),
                    _dir_pill(direction),
                ], style={'display': 'flex', 'alignItems': 'center', 'gap': '5px'}),
            ], style={
                'padding': '7px 8px',
                'borderRadius': '4px',
                'backgroundColor': THEME['bg_card'],
                'borderLeft': f"3px solid {_dir_border(direction)}",
                'opacity': '0.85',
            }))

        if pos_cards:
            grid_b = html.Div(pos_cards, style={
                'display': 'grid',
                'gridTemplateColumns': 'repeat(3, 1fr)',
                'gap': '5px',
                'maxHeight': '200px',
                'overflowY': 'auto',
                'paddingRight': '2px',
            })
        else:
            grid_b = html.Div("No saved positions found in alpha_book_positions.parquet.", style=_sub)

        table_div = html.Div([
            html.Div([
                html.Div([
                    html.Span('▌', style={'color': THEME['accent'], 'fontSize': '14px', 'marginRight': '6px', 'verticalAlign': 'middle'}),
                    html.Span("Candidate Instruments", style={'color': THEME['text_main'], 'fontSize': '12px', 'fontWeight': '700', 'verticalAlign': 'middle'}),
                    html.Span(f"  {len(instruments)} trades", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '6px', 'verticalAlign': 'middle'}),
                ], style={'marginBottom': '8px', 'paddingBottom': '5px',
                          'borderBottom': f"1px solid {THEME['accent']}33"}),
                grid_a,
            ]),

            html.Div([
                html.Div([
                    html.Span('▌', style={'color': THEME['warning'], 'fontSize': '14px', 'marginRight': '6px', 'verticalAlign': 'middle'}),
                    html.Span("Saved Positions", style={'color': THEME['text_main'], 'fontSize': '12px', 'fontWeight': '700', 'verticalAlign': 'middle'}),
                    html.Span(f"  {len(positions)} trades", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '6px', 'verticalAlign': 'middle'}),
                    html.Span(" · read-only", style={'color': THEME['text_sub'], 'fontSize': '10px', 'marginLeft': '4px', 'fontStyle': 'italic'}),
                ], style={'marginBottom': '8px', 'paddingBottom': '5px',
                          'borderBottom': f"1px solid {THEME['warning']}33"}),
                grid_b,
            ]),
        ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '12px'})

        # ── Combined correlation matrix (all instruments from both tables) ──
        all_instruments = instruments + [p for p in positions
                                         if p.get('instrument') not in {e.get('instrument') for e in instruments}]
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

            hm = go.Figure(data=go.Heatmap(
                z=corr_vals, x=sub_matrix.columns.tolist(), y=sub_matrix.index.tolist(),
                colorscale=_ALPHA_CORR_COLORSCALE, zmin=-1, zmax=1,
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

            not_in_count = len(all_instruments) - len(valid_ids)
            notice = (
                html.P(
                    f"ℹ️ {not_in_count} instrument(s) marked '○' are not yet in the matrix. "
                    "Click ↻ Recalculate Correlation below to rebuild the matrix.",
                    style={**_sub, 'marginTop': '6px'},
                ) if not_in_count > 0 else html.Div()
            )

            corr_div = html.Div([
                html.H6("Curated Correlation Matrix", style={'color': THEME['text_main'], 'marginBottom': '8px'}),
                dcc.Graph(figure=hm),
                notice,
            ])
        else:
            corr_div = html.Div(
                "Click ↻ Recalculate Correlation to build the matrix for all instruments.",
                style=_sub,
            )

        return table_div, corr_div
