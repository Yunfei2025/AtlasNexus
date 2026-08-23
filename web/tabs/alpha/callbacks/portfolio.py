# -*- coding: utf-8 -*-
"""Portfolio subtab callbacks: Recalculate correlation, Scoring & Allocation."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from dash import dcc, html, dash_table, no_update
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate
import plotly.graph_objects as go

from settings.paths import DIR_INPUT as _DIR_INPUT
from ...risk.helpers import _leg_volume_ratio

from ..data import (
    THEME, SPREAD_CATEGORIES,
    load_spread_data, load_spread_timeseries, display_key,
    _get_duration_mult, resolve_legs, _load_leg_data,
)
from ..data.duration import _tenor_to_duration
from ..scoring import _compute_risk_parity_weights


_SUMMARY_ALPHA_PARQUET = str(_DIR_INPUT / 'summary_alpha_portfolio.parquet')

# Simple conservative proxy for derivative initial margin when a CCP/SIMM
# calculation is not available. These are model assumptions, not quoted
# market margin requirements; they are deliberately tenor-sensitive so a
# short-end swap spread is not charged the same flat percentage as a long-end
# spread. The notional floor preserves a minimum liquidity/operational charge.
_SWAP_MARGIN_TENOR_STRESS_BP = (
    (1.0, 10.0),
    (3.0, 20.0),
    (5.0, 35.0),
    (10.0, 50.0),
    (float('inf'), 75.0),
)
_SWAP_MARGIN_MIN_RATE = 0.0025


def _swap_leg_tenor_duration(leg: Any) -> tuple[float, float] | None:
    """Return (tenor years, duration) parsed from an IRS leg code."""
    match = re.search(r'(\d+(?:\.\d+)?)([mMyY])', str(leg or ''))
    if match is None:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower()
    tenor_years = value / 12.0 if unit == 'm' else value
    return tenor_years, max(0.01, float(_tenor_to_duration(f'{value:g}{unit}')))


def _swap_derivative_margin_mm(
    leg1: Any,
    leg2: Any,
    leg1_notional_mm: float,
    leg2_notional_mm: float,
    fallback_notional_mm: float,
    fallback_rate: float,
) -> float:
    """Estimate derivative margin from leg DV01 plus a liquidity floor.

    This is a transparent proxy for environments without CCP/SIMM margin
    files. It uses gross leg DV01 rather than net notional, then applies a
    tenor-bucket stress and a small gross-notional floor. Unknown leg codes
    retain the legacy flat-rate fallback.
    """
    leg1_info = _swap_leg_tenor_duration(leg1)
    leg2_info = _swap_leg_tenor_duration(leg2)
    if leg1_info is None or leg2_info is None:
        return abs(float(fallback_notional_mm)) * float(fallback_rate)

    max_tenor = max(leg1_info[0], leg2_info[0])
    stress_bp = next(stress for tenor, stress in _SWAP_MARGIN_TENOR_STRESS_BP if max_tenor <= tenor)
    gross_notional_mm = abs(float(leg1_notional_mm)) + abs(float(leg2_notional_mm))
    gross_dv01_k = (
        abs(float(leg1_notional_mm)) * leg1_info[1] / 10.0
        + abs(float(leg2_notional_mm)) * leg2_info[1] / 10.0
    )
    dv01_margin_mm = gross_dv01_k * stress_bp / 1000.0
    notional_floor_mm = gross_notional_mm * _SWAP_MARGIN_MIN_RATE
    return round(max(dv01_margin_mm, notional_floor_mm), 2)


def _as_positive_float(value: Any) -> float | None:
    """Return a positive finite float, or ``None`` when no usable value exists."""
    numeric = pd.to_numeric(value, errors='coerce')
    if pd.notna(numeric) and np.isfinite(numeric) and float(numeric) > 0:
        return float(numeric)
    return None


def _reserve_existing_capacity(
    positions: list[dict] | None,
    repo_margin_rate: float,
    swap_margin_rate: float,
) -> tuple[float, float, float, int]:
    """Return margin/DV01 already committed by saved Alpha-book positions.

    Only a positive manually entered ``volume_mm`` denotes an executed holding.
    The saved margin and DV01 are scaled proportionally from its prior target,
    so a live holding is never resized by a subsequent new-trade allocation.
    Blank-volume target rows are not yet committed and consume no capacity.
    """
    if not positions:
        return 0.0, 0.0, 0.0, 0

    try:
        snapshot = pd.read_parquet(_SUMMARY_ALPHA_PARQUET)
    except (FileNotFoundError, OSError, ValueError):
        snapshot = pd.DataFrame()

    snapshot_by_key: dict[tuple[str, str], dict] = {}
    if not snapshot.empty and {'spread_type', 'ID'}.issubset(snapshot.columns):
        for _, row in snapshot.drop_duplicates(['spread_type', 'ID'], keep='last').iterrows():
            snapshot_by_key[(str(row['spread_type']), str(row['ID']))] = row.to_dict()

    leg_exposure: dict[str, float] = {}
    leg_is_bond: dict[str, bool] = {}
    margin_used_mm = 0.0
    has_snapshot_margin = False
    buy_dv01_k = 0.0
    sell_dv01_k = 0.0
    held_count = 0
    for position in positions:
        spread_type = str(position.get('spread_type', '') or '')
        trade_id = str(position.get('instrument', position.get('ID', '')) or '')
        snapshot_row = snapshot_by_key.get((spread_type, trade_id), {})

        executed_volume = _as_positive_float(position.get('volume_mm'))
        if executed_volume is None:
            continue
        saved_notional = _as_positive_float(snapshot_row.get('notional_mm'))
        actual_notional = executed_volume

        scale = actual_notional / saved_notional if saved_notional else 1.0
        saved_margin_mm = _as_positive_float(snapshot_row.get('margin_mm'))
        if saved_margin_mm is not None:
            margin_used_mm += saved_margin_mm * scale
            has_snapshot_margin = True
        saved_dv01_k = _as_positive_float(snapshot_row.get('DV01_k'))
        if saved_dv01_k is None:
            # A live manually-entered holding with no usable allocation snapshot
            # must block new allocation rather than risking an over-allocated book.
            raise ValueError(
                f"Cannot reserve existing position {trade_id}: rerun its allocation or enter a complete snapshot first."
            )

        direction = str(position.get('direction') or snapshot_row.get('direction') or '').strip().upper()
        signed_notional = actual_notional * (-1.0 if direction == 'SELL' else 1.0)
        leg1 = str(snapshot_row.get('Leg1', '') or '')
        leg2 = str(snapshot_row.get('Leg2', '') or '')
        ratio = pd.to_numeric(snapshot_row.get('ratio_v2_v1'), errors='coerce')
        ratio = float(ratio) if pd.notna(ratio) and float(ratio) > 0 else 1.0
        if leg1 or leg2:
            for leg, exposure in ((leg1, signed_notional), (leg2, -signed_notional * ratio)):
                if not leg:
                    continue
                leg_exposure[leg] = leg_exposure.get(leg, 0.0) + exposure
                leg_is_bond[leg] = leg.endswith('.IB')
        else:
            # Treat an unresolved holding as an unnettable derivative exposure.
            fallback_key = f'__unresolved_{spread_type}_{trade_id}'
            leg_exposure[fallback_key] = signed_notional
            leg_is_bond[fallback_key] = False

        if direction == 'SELL':
            sell_dv01_k += saved_dv01_k * scale
        else:
            buy_dv01_k += saved_dv01_k * scale
        held_count += 1

    if has_snapshot_margin:
        return margin_used_mm, buy_dv01_k, sell_dv01_k, held_count

    # Legacy fallback for older snapshots that do not persist per-trade margin.
    net_bond_mm = sum(abs(exposure) for leg, exposure in leg_exposure.items() if leg_is_bond[leg])
    net_derivative_mm = sum(abs(exposure) for leg, exposure in leg_exposure.items() if not leg_is_bond[leg])
    capital_used = net_bond_mm * repo_margin_rate + net_derivative_mm * swap_margin_rate
    return capital_used, buy_dv01_k, sell_dv01_k, held_count


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
        duration_by_key: dict[str, float] = {}
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
                duration_by_key[col_key] = max(
                    0.01,
                    float(_get_duration_mult(str(inst), str(spread_type))),
                )

        if len(all_spreads) < 2:
            return no_update, "⚠ Need ≥ 2 instruments with time-series data."

        df_spreads = pd.DataFrame(all_spreads).tail(lookback)
        df_changes = df_spreads.diff().dropna()

        if len(df_changes) < 20:
            return no_update, "⚠ Insufficient history (< 20 days)."

        duration_s = pd.Series(duration_by_key).reindex(df_changes.columns).fillna(1.0)
        price_changes = df_changes.mul(duration_s, axis='columns')
        corr_matrix = price_changes.corr()
        ts_now = pd.Timestamp.now().strftime('%H:%M:%S')
        status = f"✓ Duration-adjusted matrix recalculated at {ts_now} ({len(all_spreads)} instruments, {len(df_changes)} days)"
        return corr_matrix.to_dict(), status

    # -------------------------------------------------------------------------
    # PORTFOLIO: Run Scoring & Allocation
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('alpha-scored-table-container', 'children'),
         Output('alpha-risk-chart-container', 'children'),
         Output('alpha-portfolio-summary', 'children'),
         Output('alpha-optimized-weights', 'data'),
         Output('alpha-portfolio-export-store', 'data'),
         Output('alpha-financing-summary', 'children')],
        Input('alpha-score-btn', 'n_clicks'),
        [State('alpha-selected-candidates', 'data'),
         State('alpha-mom-k', 'value'),
         State('alpha-mom-window', 'value'),
         State('alpha-total-capital', 'value'),
         State('alpha-alloc-method', 'value'),
         State('alpha-enforce-corr', 'value'),
         State('alpha-curated-instruments-store', 'data'),
         State('alpha-book-positions-store', 'data'),
         State('alpha-dv01-budget', 'value'),
         State('alpha-bond-margin-rate', 'value'),
         State('alpha-swap-margin-rate', 'value'),
         State('alpha-repo-leverage', 'value')],
        prevent_initial_call=True
    )
    def run_scoring(n_clicks, candidates, mom_k, mom_window, total_capital, alloc_method, enforce_corr, curated_instruments, book_positions, total_dv01_budget, bond_margin_rate, swap_margin_rate, repo_leverage):
        if not n_clicks:
            return html.Div(), html.Div(), html.Div(), [], None, html.Div()

        if not candidates:
            # Fall back to saved positions instead of blocking
            saved = list(book_positions or []) + list(curated_instruments or [])
            if not saved:
                # The candidate store is session-scoped and can be lost after a
                # refresh or tab reload even though the scan artifact still exists.
                # Rebuild the latest low-correlation set so Generate Portfolio is
                # usable without requiring the user to repeat the entire workflow.
                try:
                    from curves.refreshers.alpha import load_alpha_candidates

                    latest = load_alpha_candidates(
                        dir_input=_DIR_INPUT,
                        refresh=True,
                        zscore_threshold=2.0,
                        max_per_style=20,
                        lookback_days=252,
                        max_abs_corr=0.6,
                        top_n_low_corr=10,
                    )
                    latest_df = latest.get('selected_lowcorr')
                    if not isinstance(latest_df, pd.DataFrame) or latest_df.empty:
                        latest_df = latest.get('candidates')
                    if isinstance(latest_df, pd.DataFrame) and not latest_df.empty:
                        candidates = latest_df.to_dict('records')
                except Exception as exc:
                    print(f"[portfolio] Could not recover latest candidates: {exc}")

            # Build minimal candidate rows from saved positions so the rest of the
            # pipeline can proceed without a prior scan.
            if saved and not candidates:
                _seen: set = set()
                candidates = []
                for _e in saved:
                    _inst = _e.get('instrument', '')
                    if not _inst or _inst in _seen:
                        continue
                    _seen.add(_inst)
                    _row = {
                        'ID': _inst,
                        'spread_type': _e.get('spread_type', ''),
                        'direction': _e.get('direction', 'BUY'),
                        'style': _e.get('regime', _e.get('style', '')),
                        'score': float(_e.get('score', 0.01)),
                    }
                    _z = pd.to_numeric(_e.get('Zscore', _e.get('zscore', None)), errors='coerce')
                    if pd.notna(_z):
                        _row['Zscore'] = float(_z)
                    candidates.append(_row)

            if not candidates:
                return (
                    html.Div("No candidates or saved positions available. Run Scan Candidates first.", style={'color': THEME['warning']}),
                    html.Div(), html.Div(), [], None, html.Div()
                )

        try:
            # Total Capital and DV01 Budget are free-text inputs (to allow
            # comma/space-tolerant typing), so a cleared or non-numeric value
            # must fall back to the default rather than raising and blanking
            # the whole results panel.
            total_capital = _as_positive_float(total_capital) or 1000.0
            total_capital_mm = total_capital
            total_dv01_budget = _as_positive_float(total_dv01_budget) or 10.0
            bond_margin_rate = (_as_positive_float(bond_margin_rate) or 5.0) / 100.0
            swap_margin_rate = (_as_positive_float(swap_margin_rate) or 3.0) / 100.0
            repo_leverage = max(1.0, _as_positive_float(repo_leverage) or 15.0)
            repo_margin_rate = 1.0 / repo_leverage

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

            # Executed Alpha-book rows are immutable holdings. They remain
            # visible to correlation analysis, but only rows with an actual
            # volume are excluded from this optimization. Blank-volume target
            # rows are still candidates and may receive a new allocation.
            existing_position_keys = {
                (str(entry.get('spread_type', '') or ''), str(entry.get('instrument', entry.get('ID', '')) or ''))
                for entry in (book_positions or [])
                if _as_positive_float(entry.get('volume_mm')) is not None
            }
            existing_position_keys.discard(('', ''))

            try:
                _reserved_capital_mm, _reserved_buy_dv01_k, _reserved_sell_dv01_k, _held_count = _reserve_existing_capacity(
                    book_positions, repo_margin_rate, swap_margin_rate,
                )
            except ValueError as exc:
                return (
                    html.Div(str(exc), style={'color': THEME['warning'], 'padding': '10px'}),
                    html.Div(), html.Div(), [], None, html.Div(),
                )

            _available_capital_mm = max(0.0, total_capital_mm - _reserved_capital_mm)
            _available_dv01_k = max(0.0, total_dv01_budget * 1000 - max(_reserved_buy_dv01_k, _reserved_sell_dv01_k))

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
                        if 'Zscore' not in inst_row or pd.isna(pd.to_numeric(inst_row.get('Zscore'), errors='coerce')):
                            _entry_z = pd.to_numeric(entry.get('Zscore', entry.get('zscore', None)), errors='coerce')
                            if pd.notna(_entry_z):
                                inst_row['Zscore'] = float(_entry_z)
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

            if existing_position_keys and {'spread_type', 'ID'}.issubset(df.columns):
                _new_trade_mask = ~pd.Series(
                    list(zip(df['spread_type'].astype(str), df['ID'].astype(str))), index=df.index
                ).isin(existing_position_keys)
                df = df.loc[_new_trade_mask].copy()

            # Manually saved/book positions do not carry the scanner's score.
            # Give those rows a neutral positive score so they remain eligible
            # for allocation rather than all being filtered out below.
            if 'score' not in df.columns:
                df['score'] = 0.01
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
                    html.Div("No new candidates to allocate. Existing positions remain unchanged.", style={'color': THEME['text_sub']}),
                    html.Div(), html.Div(), [], None, html.Div()
                )

            if _available_capital_mm <= 0 or _available_dv01_k <= 0:
                _issues: list[str] = []
                if _available_capital_mm <= 0:
                    _issues.append(
                        f"capital exhausted (available {max(_available_capital_mm, 0.0):,.1f} MM; reserved {_reserved_capital_mm:,.1f} MM of {total_capital_mm:,.1f} MM)"
                    )
                if _available_dv01_k <= 0:
                    _issues.append(
                        f"single-side DV01 exhausted (available {max(_available_dv01_k, 0.0) / 1000.0:,.3f} MM/bp; reserved BUY {_reserved_buy_dv01_k / 1000.0:,.3f} MM/bp, SELL {_reserved_sell_dv01_k / 1000.0:,.3f} MM/bp, limit {total_dv01_budget:,.3f} MM/bp)"
                    )
                return (
                    html.Div(
                        "Cannot allocate new trades because " + "; ".join(_issues) + ". "
                        "Close an existing position or increase the corresponding portfolio limit.",
                        style={'color': THEME['warning'], 'padding': '10px'},
                    ),
                    html.Div(), html.Div(), [], None, html.Div(),
                )

            # All downstream capital and DV01 constraints apply only to new
            # trades; existing positions were reserved above and are immutable.
            total_capital_mm = _available_capital_mm
            total_dv01_budget = _available_dv01_k / 1000.0

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
                    df_scored['risk_contribution'] = (
                        df_scored['ID'].map(rc_map).fillna(df_scored['weight']).multiply(100.0)
                    )

                    # Override Vol(BP) with raw annualized spread volatility from
                    # the same window. Duration affects allocation covariance, not
                    # the displayed spread-volatility measure.
                    _RAW_UNIT_TYPES = {'NetBasis', 'FuturesSwap'}
                    _is_raw_unit = (
                        df_scored['spread_type'].isin(_RAW_UNIT_TYPES)
                        if 'spread_type' in df_scored.columns
                        else pd.Series(False, index=df_scored.index)
                    )
                    _new_vol = df_scored['ID'].map(vol_computed)
                    df_scored['vol'] = _new_vol.where(~_is_raw_unit, df_scored.get('vol')).fillna(df_scored.get('vol', np.nan))
                except Exception as e:
                    print(f"WARNING: Risk parity failed: {e}, falling back to equal weights")
                    df_scored['weight'] = 1 / n_trades
                    df_scored['risk_contribution'] = 100 / n_trades

            weight_sum = df_scored['weight'].sum()
            if weight_sum > 0 and abs(weight_sum - 1.0) > 1e-9:
                df_scored['weight'] = df_scored['weight'] / weight_sum

            # Direction sign: +1 for BUY, -1 for SELL
            _direction_sign = (
                df_scored['direction'].apply(lambda d: -1.0 if str(d).strip().upper() == 'SELL' else 1.0)
                if 'direction' in df_scored.columns
                else pd.Series(1.0, index=df_scored.index)
            )

            # Rounding notional to a fixed 10mm lot silently zeroes out any row
            # whose dollar allocation is under 10mm — routine once capital is
            # split across 10+ names on a modest book (e.g. 150mm / 15 trades
            # averages 10mm/row before any single row even gets there). Scale
            # the lot size down so a typical row still rounds to a non-zero,
            # displayable notional; 10mm remains the ceiling for large books.
            _lot_mm = min(10.0, max(0.1, round(total_capital_mm / max(n_trades, 1) / 5, 1)))

            # Step A: initial unsigned notional from weights
            df_scored['notional_mm'] = np.floor(df_scored['weight'] * total_capital_mm / _lot_mm) * _lot_mm

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
                        np.floor(df_scored.loc[_is_bond, 'notional_mm'] * _cap_scale / _lot_mm) * _lot_mm
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
                df_scored['notional_mm'] = np.floor(df_scored['notional_mm'] * _dv01_scale / _lot_mm) * _lot_mm
                df_scored['DV01_k'] = (df_scored['notional_mm'].abs() * df_scored['_duration'] / 10_000 * 1_000).round(1)

            # Step F: Resolve underlying instrument legs for each trade
            try:
                _leg_data = _load_leg_data()
                leg1_list = []
                leg2_list = []
                ratio_list = []
                _alpha_duration_snap_cache: Dict[str, Any] = {}
                for _, row in df_scored.iterrows():
                    stype = str(row.get('spread_type', ''))
                    tid = str(row.get('ID', ''))
                    dur = float(row.get('_duration', 0.0)) if pd.notna(row.get('_duration')) else 0.0
                    l1, l2 = resolve_legs(stype, tid, dur, _leg_data)
                    leg1_list.append(l1)
                    leg2_list.append(l2)
                    leg_ratio = _leg_volume_ratio(l1, l2, stype, tid, dur, _alpha_duration_snap_cache)
                    ratio_list.append(round(float(leg_ratio), 4) if leg_ratio is not None else np.nan)
                df_scored['Leg1'] = leg1_list
                df_scored['Leg2'] = leg2_list
                df_scored['ratio_v2_v1'] = ratio_list
            except Exception as e:
                print(f"WARNING: Leg resolution failed: {e}")
                df_scored['Leg1'] = ''
                df_scored['Leg2'] = ''
                df_scored['ratio_v2_v1'] = np.nan

            # Step G: Net Notional + Margin (capital consumption)
            # Each leg is classified as either:
            #   - Bond (leg code ends '.IB'): funded via repo/TRS with security
            #     firms through repo at 1 / `repo_leverage` of gross bond exposure.
            #   - Swap / Futures (IRS '.IR' legs, futures contract codes, or any
            #     unresolved leg as a conservative floor): funded via exchange/
            #     counterparty margin at `swap_margin_rate`.
            # Bond repo capital uses gross bond legs at the configured leverage:
            #   margin_bond = (|bond_leg1| + |bond_leg2|) / repo_leverage
            # For bond-vs-bond spreads this implies:
            #   net_notional = signed_leg1 * (1 - ratio)
            #   margin_bond = |signed_leg1| * (1 + ratio) * bond_margin_rate
            def _compute_net_and_margin(notional_mm: pd.Series) -> tuple:
                leg1_signed = notional_mm
                _ratio = pd.to_numeric(df_scored['ratio_v2_v1'], errors='coerce').fillna(1.0)
                leg2_signed = -leg1_signed * _ratio

                _leg1 = df_scored['Leg1'].astype(str)
                _leg2 = df_scored['Leg2'].astype(str)
                _leg1_is_bond = _leg1.str.endswith('.IB')
                _leg2_is_bond = _leg2.str.endswith('.IB')
                _leg1_exists = _leg1.str.len() > 0
                _leg2_exists = _leg2.str.len() > 0

                bond_gross = (
                    leg1_signed.abs().where(_leg1_is_bond, 0.0)
                    + leg2_signed.abs().where(_leg2_is_bond, 0.0)
                )

                swapfut_net = (
                    leg1_signed.where(_leg1_exists & ~_leg1_is_bond, 0.0)
                    + leg2_signed.where(_leg2_exists & ~_leg2_is_bond, 0.0)
                )
                # Conservative floor: if both legs failed to resolve, still margin
                # the trade's own notional at the swap/futures rate rather than
                # silently letting it consume zero capital.
                _both_unresolved = (~_leg1_exists) & (~_leg2_exists)
                _fallback = leg1_signed.abs().where(_both_unresolved, 0.0)

                derivative_margin = pd.Series(0.0, index=df_scored.index, dtype=float)
                for _idx in df_scored.index:
                    _is_derivative = bool(
                        (_leg1_exists.at[_idx] and not _leg1_is_bond.at[_idx])
                        or (_leg2_exists.at[_idx] and not _leg2_is_bond.at[_idx])
                    )
                    if not _is_derivative:
                        continue
                    _leg1_mm = float(leg1_signed.at[_idx])
                    _leg2_mm = float(leg2_signed.at[_idx])
                    derivative_margin.at[_idx] = _swap_derivative_margin_mm(
                        _leg1.at[_idx],
                        _leg2.at[_idx],
                        _leg1_mm,
                        _leg2_mm,
                        float(swapfut_net.at[_idx]),
                        swap_margin_rate,
                    )

                net_notional = (leg1_signed + leg2_signed).round(1)
                margin = (bond_gross * repo_margin_rate + derivative_margin + _fallback * swap_margin_rate).round(2)
                return net_notional, margin

            df_scored['net_notional_mm'], df_scored['margin_mm'] = _compute_net_and_margin(df_scored['notional_mm'])

            # Step H: net all matching leg exposures across the portfolio before
            # applying repo funding or derivative initial margin.  Total Capital
            # is therefore a limit on the actual netted financing requirement.
            def _portfolio_financing(notional_mm: pd.Series) -> tuple[float, float, float]:
                _ratio = pd.to_numeric(df_scored['ratio_v2_v1'], errors='coerce').fillna(1.0)
                _leg_exposure: dict[str, float] = {}
                _leg_is_bond: dict[str, bool] = {}

                for row_idx, leg1, leg2, ratio, leg1_notional in zip(
                    df_scored.index,
                    df_scored['Leg1'].astype(str),
                    df_scored['Leg2'].astype(str),
                    _ratio,
                    notional_mm,
                ):
                    leg1_notional = float(leg1_notional)
                    leg2_notional = -leg1_notional * float(ratio)
                    legs = ((leg1, leg1_notional), (leg2, leg2_notional))
                    resolved_leg = False
                    for leg, leg_notional in legs:
                        if not leg:
                            continue
                        resolved_leg = True
                        _leg_exposure[leg] = _leg_exposure.get(leg, 0.0) + leg_notional
                        _leg_is_bond[leg] = leg.endswith('.IB')
                    if not resolved_leg:
                        fallback_key = f'__unresolved_{row_idx}'
                        _leg_exposure[fallback_key] = leg1_notional
                        _leg_is_bond[fallback_key] = False

                net_bond_mm = sum(abs(exposure) for leg, exposure in _leg_exposure.items() if _leg_is_bond[leg])
                net_derivative_mm = sum(abs(exposure) for leg, exposure in _leg_exposure.items() if not _leg_is_bond[leg])
                capital_without_repo = net_bond_mm + net_derivative_mm * swap_margin_rate
                capital_with_repo = net_bond_mm * repo_margin_rate + net_derivative_mm * swap_margin_rate
                return net_bond_mm, capital_without_repo, capital_with_repo

            _, _, _capital_with_repo_mm = _portfolio_financing(df_scored['notional_mm'])
            if _capital_with_repo_mm > total_capital_mm and _capital_with_repo_mm > 1e-6:
                _margin_scale = total_capital_mm / _capital_with_repo_mm
                df_scored['notional_mm'] = np.floor(df_scored['notional_mm'] * _margin_scale / _lot_mm) * _lot_mm
                df_scored['DV01_k'] = (df_scored['notional_mm'].abs() * df_scored['_duration'] / 10_000 * 1_000).round(1)
                df_scored['net_notional_mm'], df_scored['margin_mm'] = _compute_net_and_margin(df_scored['notional_mm'])

            _ratio = pd.to_numeric(df_scored['ratio_v2_v1'], errors='coerce').fillna(1.0)
            _leg1_abs = df_scored['notional_mm'].abs()
            _leg2_abs = _leg1_abs * _ratio
            _leg1 = df_scored['Leg1'].astype(str)
            _leg2 = df_scored['Leg2'].astype(str)
            _leg1_bond = _leg1.str.endswith('.IB')
            _leg2_bond = _leg2.str.endswith('.IB')
            _leg1_exists = _leg1.str.len() > 0
            _leg2_exists = _leg2.str.len() > 0
            _gross_notional_mm = float((_leg1_abs + _leg2_abs).sum())
            _net_bond_mm, _capital_without_repo_mm, _capital_with_repo_mm = _portfolio_financing(df_scored['notional_mm'])
            _gross_leverage = _gross_notional_mm / _capital_with_repo_mm if _capital_with_repo_mm > 0 else 0.0

            _metric_label = {'color': THEME['text_sub'], 'fontSize': '9px', 'fontWeight': '600',
                             'textTransform': 'uppercase', 'display': 'block', 'marginBottom': '3px'}
            _metric_value = {'color': THEME['text_main'], 'fontSize': '12px', 'fontWeight': '700'}
            financing_summary = [
                html.Div([html.Span('Existing Positions', style=_metric_label), html.Span(f'{_held_count} fixed holdings', style=_metric_value)]),
                html.Div([html.Span('Reserved Capital', style=_metric_label), html.Span(f'{_reserved_capital_mm:,.1f} MM', style=_metric_value)]),
                html.Div([html.Span('Capital for New Trades', style=_metric_label), html.Span(f'{total_capital_mm:,.1f} MM', style={**_metric_value, 'color': THEME['accent']} )]),
                html.Div([html.Span('DV01 for New Trades', style=_metric_label), html.Span(f'{total_dv01_budget:,.3f} MM CNY/bp', style={**_metric_value, 'color': THEME['accent']} )]),
                html.Div([html.Span('Gross Leg Notional', style=_metric_label), html.Span(f'{_gross_notional_mm:,.1f} MM', style=_metric_value)]),
                html.Div([html.Span('Capital Without Repo (Netted)', style=_metric_label), html.Span(f'{_capital_without_repo_mm:,.1f} MM', style=_metric_value)]),
                html.Div([html.Span('Capital With Repo (Netted)', style=_metric_label), html.Span(f'{_capital_with_repo_mm:,.1f} MM', style=_metric_value)]),
                html.Div([html.Span('Gross Leverage', style=_metric_label), html.Span(f'{_gross_leverage:.1f}x', style={**_metric_value, 'color': THEME['accent']} )]),
            ]

            # Build downstream payload after leg + ratio enrichment so later
            # stages (Summary/Backtest/etc.) receive the ratio field.
            df_nonzero = df_scored[df_scored['weight'] > 0.0001].copy()
            optimized_results = df_nonzero.to_dict('records')

            display_cols = [
                'ID', 'Leg1', 'Leg2', 'ratio_v2_v1', 'style', 'direction',
                'Zscore', 'spread', 'mean', 'vol',
                'carry_roll', 'breakeven_3m', 'stop_loss', 'profit_target',
                'seasonal_edge_bps', 'score',
                'weight', 'risk_contribution', 'notional_mm', 'margin_mm', 'DV01_k',
            ]
            available_cols = [c for c in display_cols if c in df_scored.columns]
            df_display = df_scored[available_cols].copy()

            # Keep the ID column as the raw ticker only.  The raw ID is also the
            # identifier used by downstream risk, allocation, and persistence code.
            if 'ID' in df_display.columns:
                df_display['ID'] = df_scored.loc[df_display.index, 'ID'].astype(str).to_numpy()

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
                    df_display[col] = df_display[col].round(2)
                elif df_display[col].dtype in ['float64', 'float32']:
                    df_display[col] = df_display[col].round(4)

            # Display notional as absolute size; trade direction is already in DIR.
            if 'notional_mm' in df_display.columns:
                df_display['notional_mm'] = pd.to_numeric(df_display['notional_mm'], errors='coerce').abs().round(4)

            if 'carry_roll' in df_display.columns and 'direction' in df_display.columns:
                _sell = df_display['direction'].astype(str).str.strip().str.upper().eq('SELL')
                df_display.loc[_sell, 'carry_roll'] = (
                    pd.to_numeric(df_display.loc[_sell, 'carry_roll'], errors='coerce')
                    .multiply(-1).round(4)
                )

            summary_row: dict = {c: "" for c in df_display.columns}
            summary_row['ID'] = 'TOTAL'
            for col, decimals in [('weight', 4), ('risk_contribution', 2), ('notional_mm', 0), ('margin_mm', 2)]:
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
                {'if': {'column_id': 'ID'}, 'whiteSpace': 'pre-line', 'lineHeight': '1.35', 'minWidth': '170px'},
            ]

            _port_col_labels = {
                'Leg1': 'leg 1', 'Leg2': 'leg 2', 'style': 'style',
                'ratio_v2_v1': 'Ratio (V2/V1)',
                'Zscore': 'z-score', 'spread': 'spread(bp)', 'mean': 'mean(bp)',
                'vol': 'vol(bp)',
                'carry_roll': 'CR(3m)', 'breakeven_3m': 'b/e(3m)',
                'stop_loss': 'stop(bp)', 'profit_target': 'target(bp)',
                'seasonal_edge_bps': 'seas.edge', 'score': 'score',
                'weight': 'weight', 'risk_contribution': 'RC (%)',
                'notional_mm': 'NOTIONAL (MM)',
                'margin_mm': 'Margin (MM)', 'DV01_k': 'DV01(k)',
                'direction': 'DIR',
            }

            # Content-aware widths: estimate each column width from the longest
            # value (including header), then clamp to a practical range.
            _col_width_styles = []
            for _c in df_display.columns:
                _hdr = str(_port_col_labels.get(_c, _c))
                _vals = df_display[_c].fillna('').astype(str)
                _max_chars = max([len(_hdr)] + [len(v) for v in _vals.tolist()])
                _px = min(max(72, _max_chars * 8 + 24), 360)
                _col_width_styles.append({
                    'if': {'column_id': _c},
                    'minWidth': f'{_px}px',
                    'width': f'{_px}px',
                    'maxWidth': f'{_px}px',
                })

            table = dash_table.DataTable(
                id='alpha-scored-table',
                columns=[{'name': _port_col_labels.get(c, c), 'id': c} for c in df_display.columns],
                data=df_display.to_dict('records'),
                style_table={'backgroundColor': 'transparent', 'minWidth': 'max-content'},
                style_header={'backgroundColor': 'var(--surface-panel)', 'color': THEME['text_sub'],
                              'fontWeight': '600', 'textAlign': 'left', 'border': 'none',
                              'borderBottom': '1px solid var(--border-strong)', 'fontSize': '10px',
                              'textTransform': 'uppercase', 'letterSpacing': '0.05em', 'position': 'sticky', 'top': '0'},
                style_cell={'backgroundColor': 'transparent', 'color': THEME['text_main'], 'textAlign': 'left',
                            'padding': '6px 8px', 'fontSize': '11px', 'border': 'none',
                            'borderBottom': '1px solid rgba(255,255,255,0.04)',
                            'whiteSpace': 'nowrap'},
                style_data_conditional=conditional_style + _col_width_styles,
                sort_action='native', page_size=len(df_display), fill_width=False,
            )
            table = html.Div(
                table,
                style={'overflowX': 'auto', 'overflowY': 'hidden', 'width': '100%', 'maxWidth': '100%'},
            )

            summary = html.Div([
                html.Div([
                    html.Div([html.Strong("Total Trades: ", style={'color': THEME['text_sub']}), html.Span(f"{len(df_scored)}", style={'color': THEME['text_main']})], style={'marginRight': '30px'}),
                    html.Div([html.Strong("Margin Budget: ", style={'color': THEME['text_sub']}), html.Span(f"{total_capital:.1f} MM CNY", style={'color': THEME['text_main']})], style={'marginRight': '30px'}),
                    html.Div([html.Strong("DV01 Budget: ", style={'color': THEME['text_sub']}), html.Span(f"{total_dv01_budget:.1f} MM CNY", style={'color': THEME['text_main']})], style={'marginRight': '30px'}),
                    html.Div([html.Strong("Capital With Repo (Netted): ", style={'color': THEME['text_sub']}), html.Span(f"{_capital_with_repo_mm:.2f} / {total_capital:.1f} MM CNY", style={'color': THEME['text_main']})], style={'marginRight': '30px'}),
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
                df_chart = df_scored.nlargest(15, 'weight')[['ID', 'weight', 'risk_contribution']].copy()
                fig.add_trace(go.Bar(x=df_chart['ID'], y=df_chart['weight'] * 100, name='Weight (%)', marker_color=THEME['accent'], yaxis='y'))
                fig.add_trace(go.Bar(x=df_chart['ID'], y=df_chart['risk_contribution'], name='Risk Contribution (%)', marker_color=THEME['success'], yaxis='y'))
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
                        'Leg1', 'Leg2', 'ratio_v2_v1',
                        'Zscore', 'spread', 'carry_roll', 'breakeven_3m', 'vol', 'halflife',
                        'stop_loss', 'profit_target',
                        'notional_mm', 'margin_mm', '_duration', 'DV01_k', 'weight', 'risk_contribution',
                    ] if c in df_scored.columns
                ]
                _snap = df_scored[_save_cols].copy()
                _snap['_timestamp'] = datetime.now().isoformat()
                # Upsert by (spread_type, ID): keeps prior trades that aren't in this run,
                # replaces values for trades that re-appear, adds genuinely new trades.
                _id_cols = [c for c in ('spread_type', 'ID') if c in _snap.columns] or ['ID']
                merged = _upsert_snapshot(_snap, _SUMMARY_ALPHA_PARQUET, _id_cols)
                print(f"Alpha snapshot merged: {_SUMMARY_ALPHA_PARQUET} ({len(merged)} rows after upsert)")
            except Exception as _se:
                print(f"Warning: Could not save Alpha snapshot: {_se}")

            export_payload = {
                'columns': _port_col_labels,
                'records': df_display.to_dict('records'),
            }
            return table, risk_chart, summary, optimized_results, export_payload, financing_summary

        except Exception as e:
            import traceback
            error_msg = f"Error in portfolio optimization: {str(e) or type(e).__name__}"
            print(f"[ERROR] {error_msg}")
            print(traceback.format_exc())
            return (
                html.Div(error_msg, style={
                    'color': THEME['warning'], 'padding': '10px 14px', 'margin': '10px 16px',
                    'border': f"1px solid {THEME['warning']}", 'borderRadius': '4px',
                    'backgroundColor': 'rgba(224,162,60,0.08)', 'fontWeight': '600',
                }),
                html.Div(),
                html.Div(f"Details: {str(e)[:100]}", style={'color': THEME['warning'], 'fontSize': '11px'}),
                [],
                None,
                html.Div(),
            )

    @app.callback(
        Output('alpha-portfolio-download', 'data'),
        Input('alpha-download-portfolio-btn', 'n_clicks'),
        State('alpha-portfolio-export-store', 'data'),
        prevent_initial_call=True,
    )
    def download_portfolio_table(n_clicks, export_payload):
        if not n_clicks or not export_payload or not export_payload.get('records'):
            raise PreventUpdate

        df_export = pd.DataFrame(export_payload['records'])
        column_labels = export_payload.get('columns', {})
        df_export = df_export.rename(columns=column_labels)
        filename = f"alpha_portfolio_allocation_{datetime.now():%Y%m%d_%H%M%S}.csv"
        return dcc.send_data_frame(df_export.to_csv, filename, index=False)
