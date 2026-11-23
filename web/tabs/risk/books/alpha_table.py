# -*- coding: utf-8 -*-
"""Alpha allocation-table renderer for Summary > Books."""

from __future__ import annotations

from datetime import datetime

import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import numpy as np
import pandas as pd

from settings.paths import DIR_INPUT
from .swap_close import freshest_daily_closes, swap_spread_close_bp, zscore_from_close
from web.tabs.alpha.data.legs import fly_leg_dv01_ratios
from web.tabs.alpha.data import load_spread_data as _load_alpha_spread_data
from web.tabs.alpha.data.duration import get_breakeven_3m_bp, get_carry_roll_3m_bp
from web.tabs.beta.data import THEME
from web.tabs.beta.callbacks._common import _SUMMARY_ALPHA_PARQUET, _SUMMARY_ALPHA_DISPLAY_PARQUET, _ALPHA_POSITIONS_PARQUET, _load_cr_ts, _price_progress_bar, _dir_badge, _style_badge, _signed_value_style, _zscore_cell_style, _sortable_header, _apply_sort
_SUMMARY_ALPHA_PARQUAT = _SUMMARY_ALPHA_PARQUET
from .close_reminder import alpha_close_ticket, format_ticket
from ..helpers import _compute_alpha_carry_mtm, _persist_alpha_summary_rows, _alpha_progress_direction, _alpha_spread_pnl_bp, _coerce_float, _load_leg_data, _resolve_legs, _leg_volume_ratio, _row_key, normalize_risk_ticker


_BAR_STOP = '#ef4444'
_BAR_TARGET = '#34d399'
_BAR_NOW = 'var(--accent-amber)'


def _stop_target_bar(entry: float, cur: float, stop: float, target: float, direction: str) -> html.Div:
    """Progress bar in profit terms, the same for BUY and SELL: red STOP tick on the left, green TARGET
    tick on the right, amber NOW tick in between. Position = favourable move since entry (bp), so the amber
    tick is left of the middle when losing, right when winning, and sits OUTSIDE the red / green ticks when
    the spread is already past the stop / target (the bar widens to fit it). The fill runs from the entry
    (zero) to now: green = profit, red = loss. ``direction`` is the progress direction
    (``_alpha_progress_direction``): 'BUY' gains when the spread rises, 'SELL' when it falls."""
    sign = 1.0 if direction == 'BUY' else -1.0
    pnl = sign * (cur - entry)                    # favourable move in bp, 0 = entry
    stop_x = -abs(entry - stop)                   # stop and target as favourable distances from entry
    tgt_x = abs(target - entry)
    lo, hi = min(stop_x, pnl, 0.0), max(tgt_x, pnl, 0.0)
    pad = ((hi - lo) or 1.0) * 0.07               # keep the end ticks inside the bar
    lo, hi = lo - pad, hi + pad
    pos = lambda x: (x - lo) / (hi - lo) * 100.0
    fill_color = 'rgba(52,211,153,0.5)' if pnl >= 0 else 'rgba(239,68,68,0.5)'
    tick = lambda x, color, w, grow: html.Div(style={
        'position': 'absolute', 'top': f'-{grow}px', 'bottom': f'-{grow}px', 'left': f'{pos(x):.1f}%',
        'width': f'{w}px', 'background': color, 'borderRadius': '1px', 'transform': 'translateX(-50%)'})
    return html.Div(style={
        'position': 'relative', 'height': '6px', 'background': 'var(--surface-input)',
        'borderRadius': '3px', 'minWidth': '110px',
    }, title=f"stop {stop_x:+.1f} bp · now {pnl:+.1f} bp · target {tgt_x:+.1f} bp  (vs entry, in profit terms)", children=[
        html.Div(style={'position': 'absolute', 'top': '0', 'bottom': '0', 'left': f'{pos(min(0.0, pnl)):.1f}%',
                        'width': f'{abs(pos(pnl) - pos(0.0)):.1f}%', 'background': fill_color, 'borderRadius': '3px'}),
        tick(stop_x, _BAR_STOP, 2, 2),
        tick(tgt_x, _BAR_TARGET, 2, 2),
        tick(pnl, _BAR_NOW, 3, 3),
    ])


def _progress_legend() -> html.Div:
    """Two-line key for the Progress column and the row colours, shown above the Alpha table."""
    sub = {'color': THEME['text_sub'], 'fontSize': '11px'}

    def tick(color, label):
        return html.Span([
            html.Span(style={'display': 'inline-block', 'width': '3px', 'height': '11px', 'background': color,
                             'borderRadius': '1px', 'margin': '0 5px -2px 0'}), label,
        ], style={'marginRight': '16px', 'whiteSpace': 'nowrap'})

    def swatch(bg, label):
        return html.Span([
            html.Span(style={'display': 'inline-block', 'width': '12px', 'height': '10px', 'background': bg,
                             'borderRadius': '2px', 'margin': '0 5px -1px 0'}), label,
        ], style={'marginRight': '16px', 'whiteSpace': 'nowrap'})

    return html.Div([
        html.Div([
            html.Span("Progress", style={'color': THEME['text_main'], 'fontWeight': '600', 'marginRight': '10px'}),
            tick(_BAR_STOP, 'stop (left)'),
            tick(_BAR_TARGET, 'target (right)'),
            tick(_BAR_NOW, 'now'),
            swatch('rgba(52,211,153,0.5)', 'profit since entry'),
            swatch('rgba(239,68,68,0.5)', 'loss'),
            html.Span("now outside the ticks = past stop / target", style={'whiteSpace': 'nowrap'}),
        ], style={**sub, 'marginBottom': '4px'}),
        html.Div([
            html.Span("Row", style={'color': THEME['text_main'], 'fontWeight': '600', 'marginRight': '10px'}),
            swatch('rgba(239,85,59,0.45)', 'stop hit'),
            swatch('rgba(0,204,150,0.45)', 'target reached'),
            swatch('rgba(255,165,0,0.35)', 'review: held 21d+ or signal says close'),
        ], style={**sub, 'marginBottom': '4px'}),
        html.Div([
            html.Span("Stop / Target", style={'color': THEME['text_main'], 'fontWeight': '600', 'marginRight': '10px'}),
            html.Span("levels in bp, like Open / Close:  BUY → stop above, target below   ·   SELL → stop below, target above"),
        ], style=sub),
    ], style={'padding': '6px 2px', 'marginBottom': '8px'})


def register_alpha_book_table_callbacks(app):
    """Register the Alpha allocation-table renderer."""
    @app.callback(
        [Output('summary-alpha-table-container', 'children'),
         Output('summary-refresh-status', 'children', allow_duplicate=True),
         Output('summary-alpha-rows-store', 'data')],
        [Input('summary-refresh-btn', 'n_clicks'),
         Input('summary-col-visibility', 'data'),
         Input('summary-alpha-sort', 'data')],
        State('summary-alpha-active-date-row', 'data'),
        prevent_initial_call='initial_duplicate',
    )
    def update_summary_alpha_table(_n_clicks, col_vis, sort_state, active_date_row):
        """Render Alpha Book allocation table."""
        import os as _os
        sort_state = sort_state or {'col': None, 'dir': 'asc'}
        col_vis = col_vis or {}
    
        def _fmt_file_ts(path: str) -> str:
            try:
                return datetime.fromtimestamp(_os.path.getmtime(path)).isoformat()
            except Exception:
                return 'unknown'
    
        def _load_persisted_alpha_display() -> tuple[list[dict], str, str]:
            """Load saved Alpha display snapshot rows, excluding helper columns.
    
            Priority:
            1) summary_alpha_display.parquet (render-ready snapshot)
            2) none -> caller falls back to canonical alpha snapshot rebuild
            """
            if _os.path.exists(_SUMMARY_ALPHA_DISPLAY_PARQUET):
                try:
                    adf = pd.read_parquet(_SUMMARY_ALPHA_DISPLAY_PARQUET)
                    if not adf.empty:
                        ts = 'unknown'
                        if '_timestamp' in adf.columns and adf['_timestamp'].notna().any():
                            ts = str(adf['_timestamp'].dropna().astype(str).iloc[-1])
                        else:
                            ts = _fmt_file_ts(_SUMMARY_ALPHA_DISPLAY_PARQUET)
                        records = adf.to_dict('records')
                        records = [{k: v for k, v in r.items() if not str(k).startswith('_')} for r in records]
                        return records, ts, 'saved alpha display snapshot'
                except Exception:
                    pass
            return [], 'unknown', ''
    
        def _no_data(msg: str):
            return (
                html.Div(msg, style={
                    'color': THEME['text_sub'], 'fontStyle': 'italic',
                    'padding': '30px', 'textAlign': 'center', 'fontSize': '13px',
                }),
                "",
                [],
            )
    
        def _load_positions() -> dict:
            if _os.path.exists(_ALPHA_POSITIONS_PARQUET):
                try:
                    pos = pd.read_parquet(_ALPHA_POSITIONS_PARQUET)
                    result = {}
                    for _, r in pos.iterrows():
                        key = (str(r.get('spread_type', '')), str(r.get('ID', '')))
                        result[key] = {
                            'open_price_bp': r.get('open_price_bp', ''),
                            'volume_mm':     r.get('volume_mm', ''),
                            'open_date':     str(r.get('open_date', '')),
                        }
                    return result
                except Exception:
                    pass
            return {}
    
        _alpha_spread_cache: dict[str, pd.DataFrame | None] = {}
        _irs_close_yield_df: pd.DataFrame | None = None
        _db_px: dict | None = None
        _swap_close_date: dict[str, pd.Timestamp] = {}   # trade_id -> date of the daily close used

        def _database_px() -> dict:
            """database-px.pkl (the market data feed), read once per refresh."""
            nonlocal _db_px
            if _db_px is None:
                try:
                    _loaded = pd.read_pickle(str(DIR_INPUT / 'database-px.pkl'))
                    _db_px = _loaded if isinstance(_loaded, dict) else {}
                except Exception:
                    _db_px = {}
            return _db_px

        def _realtime_irs_date() -> pd.Timestamp | None:
            try:
                return pd.Timestamp(_os.path.getmtime(str(DIR_INPUT / 'IRS-spdsrt.pkl')), unit='s').normalize()
            except OSError:
                return None
    
        def _resolve_alpha_metric(
            spread_type: str,
            trade_id: str,
            metric: str,
            fallback: float | None = None,
            *,
            scale_to_bp: bool = False,
        ) -> float | None:
            if not spread_type or not trade_id:
                return fallback
            if spread_type not in _alpha_spread_cache:
                try:
                    _alpha_spread_cache[spread_type] = _load_alpha_spread_data(spread_type)
                except Exception:
                    _alpha_spread_cache[spread_type] = None
            df = _alpha_spread_cache.get(spread_type)
            if df is None or trade_id not in df.index:
                return fallback
            try:
                if metric not in df.columns:
                    return fallback
                raw_value = df.loc[trade_id, metric]
                if raw_value is None or pd.isna(raw_value):
                    return fallback
                value = float(raw_value)
                if scale_to_bp and spread_type in {
                    'TBondCurve', 'CBondCurve', 'SwapSpread', 'TenorSpread', 'TermBasis'
                }:
                    value *= 100.0
                return round(value, 4)
            except (TypeError, ValueError, KeyError):
                return fallback
    
        _cvpx_act_cache: dict = {}

        def _bond_close_spread_bp(spread_type: str, leg1: str, leg2: str) -> float | None:
            """(y1 - y2) in bp on the latest day both legs have a close yield (within the last 5 rows)."""
            prefix = 'TBond' if spread_type == 'TBondCurve' else 'CBond'
            if prefix not in _cvpx_act_cache:
                try:
                    _a = pd.read_pickle(str(DIR_INPUT / f'{prefix}-cvpx.pkl'))['ytm_act'].apply(pd.to_numeric, errors='coerce')
                    _cvpx_act_cache[prefix] = _a.iloc[-5:]
                except Exception:
                    _cvpx_act_cache[prefix] = None
            _a = _cvpx_act_cache[prefix]
            if _a is None or leg1 not in _a.columns or leg2 not in _a.columns:
                return None
            _both = _a[[leg1, leg2]].dropna()
            if _both.empty:
                return None
            return round(float(_both.iloc[-1][leg1] - _both.iloc[-1][leg2]) * 100.0, 4)

        def _resolve_alpha_close_price_bp(
            spread_type: str,
            trade_id: str,
            leg1: str,
            leg2: str,
            fallback: float | None,
            leg3: str = '',
        ) -> float | None:
            nonlocal _irs_close_yield_df
    
            # BondCurve close price = leg1 - leg2 on the latest CLOSE yields (ytm_act in {T,C}Bond-cvpx.pkl),
            # not the live bid/offer mids; the snapshot's 'CloseYield' column below is only the fallback.
            if spread_type in {'TBondCurve', 'CBondCurve'} and leg1 and leg2:
                _close_bp = _bond_close_spread_bp(spread_type, leg1, leg2)
                if _close_bp is not None:
                    return _close_bp
                if spread_type not in _alpha_spread_cache:
                    try:
                        _alpha_spread_cache[spread_type] = _load_alpha_spread_data(spread_type)
                    except Exception:
                        _alpha_spread_cache[spread_type] = None
                _df = _alpha_spread_cache.get(spread_type)
                if isinstance(_df, pd.DataFrame) and 'CloseYield' in _df.columns and leg1 in _df.index and leg2 in _df.index:
                    try:
                        y1 = float(_df.loc[leg1, 'CloseYield'])
                        y2 = float(_df.loc[leg2, 'CloseYield'])
                        return round((y1 - y2) * 100.0, 4)
                    except (TypeError, ValueError, KeyError):
                        pass
    
            # Repo swap spreads: latest daily close across ALL legs (a fly is
            # 2*belly - wings). Freshest source wins -- the data feed
            # (database-px.pkl) is topped up with IRS-pxspds.pkl, which can lag it
            # by days. The real-time quote (`fallback`) is used instead only when
            # that file is newer than the latest daily close.
            if spread_type == 'SwapSpread' and leg1.endswith('.IR') and leg2.endswith('.IR'):
                if _irs_close_yield_df is None:
                    try:
                        _irs_px = pd.read_pickle(str(DIR_INPUT / 'IRS-pxspds.pkl'))
                        _cy = _irs_px.get('CloseYield') if isinstance(_irs_px, dict) else None
                    except Exception:
                        _cy = None
                    _irs_close_yield_df = freshest_daily_closes(_database_px().get('IRS'), _cy)
                _pt = swap_spread_close_bp(_irs_close_yield_df, [leg1, leg2, leg3])
                if _pt is not None:
                    _rt = _realtime_irs_date()
                    if _rt is not None and _rt > _pt[1] and fallback is not None:
                        return fallback
                    _swap_close_date[trade_id] = _pt[1]
                    return _pt[0]

            return fallback
    
        # Load leg data once for all spread types (used by _resolve_legs below)
        _ld = None
    
        def _resolve_bondcurve_legs(spread_type: str, trade_id: str, duration: float) -> tuple[str, str]:
            """Resolve leg1/leg2 for all spread types using the canonical leg resolver."""
            nonlocal _ld
            if _ld is None:
                try:
                    _ld = _load_leg_data()
                except Exception:
                    _ld = {}
            return _resolve_legs(spread_type, trade_id, duration, _ld)
    
        _alpha_duration_snap_cache: dict[str, pd.DataFrame | None] = {}
    
        try:
            # The canonical allocation snapshot is updated by Alpha Portfolio's
            # Run Optimization action.  A display export is intentionally only
            # a fallback: using it first makes Summary keep rendering an older
            # table after a newly added allocation has been saved.
            if _os.path.exists(_SUMMARY_ALPHA_PARQUAT):
                _saved_rows = []
                df = pd.read_parquet(_SUMMARY_ALPHA_PARQUAT)
                ts = df['_timestamp'].iloc[-1] if '_timestamp' in df.columns else "unknown"
                source_label = 'saved alpha snapshot'
                pos = _load_positions()
            else:
                _saved_rows, ts_saved, source_saved = _load_persisted_alpha_display()
                if not _saved_rows:
                    return _no_data(
                        "No Alpha snapshot found. Click RUN OPTIMIZATION in the Alpha Book -> Portfolio tab first."
                    )
                display_rows = [dict(r) for r in _saved_rows]
                ts = ts_saved
                source_label = source_saved
    
            def _fmt1(v):
                try:
                    f = float(v)
                    return f"{f:.1f}" if pd.notna(f) else ''
                except (TypeError, ValueError):
                    return ''

            def _first_numeric(_row: dict, keys: tuple[str, ...]) -> float | None:
                for key in keys:
                    raw = _row.get(key)
                    if raw in (None, '', 'N/A'):
                        continue
                    try:
                        _f = float(str(raw).replace(',', '').replace('%', ''))
                    except (TypeError, ValueError):
                        continue
                    if _f != _f:  # NaN (parquet null) counts as missing so the fallback runs
                        continue
                    return _f
                return None
    
            if not _saved_rows:
                display_rows = []
                _seeded = False
                for _row_idx, (_, row) in enumerate(df.iterrows()):
                    trade_id = str(row.get('ID', ''))
                    if trade_id in ('TOTAL', ''):
                        continue
                    spread_type    = str(row.get('spread_type', ''))
                    key            = (spread_type, trade_id)
                    saved          = pos.get(key, {})
                    open_price_str = str(saved.get('open_price_bp', ''))
                    volume_str     = str(saved.get('volume_mm', ''))
                    open_date_str  = str(saved.get('open_date', ''))
    
                    spread_val = row.get('spread', None)
                    zscore_val = _resolve_alpha_metric(spread_type, trade_id, 'Zscore', fallback=_coerce_float(row.get('Zscore')))
                    carry_roll_val = _resolve_alpha_metric(spread_type, trade_id, 'carry_roll', fallback=_coerce_float(row.get('carry_roll')))
                    # The snapshot has no breakeven column and saved rows rarely carry one (only the
                    # Candidates scan computes it), so derive it from the snapshot's carry+roll.
                    breakeven_val = get_breakeven_3m_bp(spread_type, trade_id, str(row.get('direction', '') or ''))
                    if breakeven_val is None:
                        breakeven_val = _resolve_alpha_metric(spread_type, trade_id, 'breakeven_3m', fallback=_coerce_float(row.get('breakeven_3m')))
                    # Size is the magnitude; the sign comes from DIRECTION (BUY +,
                    # SELL -), never from the stored notional_mm -- older snapshots
                    # stored it flipped for the whole book. Leg 2 is the opposite
                    # side of leg 1, so Target Volume Leg2 takes the opposite sign.
                    notional   = abs(float(row.get('notional_mm', 0) or 0))
                    _dir_sign  = -1.0 if str(row.get('direction', '')).strip().upper() in ('SELL', 'SHORT') else 1.0
                    margin_mm  = _coerce_float(row.get('margin_mm'))
                    dv01_k     = float(row.get('DV01_k', 0) or 0)
                    risk_contribution = _coerce_float(row.get('risk_contribution'))
                    _dur_raw   = row.get('_duration', None)
                    if _dur_raw is not None and pd.notna(_dur_raw):
                        duration = float(_dur_raw)
                    elif notional > 0:
                        duration = round(dv01_k * 10.0 / notional, 2)
                    else:
                        duration = 0.0
    
                    # Prefer the leg info saved by Alpha Portfolio's Run Optimization
                    # (row['Leg1']/['Leg2']) — it reflects what was actually traded.
                    # Only fall back to the OTR/duration heuristic resolver when the
                    # saved snapshot doesn't have leg info (e.g. older saved rows).
                    saved_leg1 = row.get('Leg1', None)
                    saved_leg2 = row.get('Leg2', None)
                    if saved_leg1 not in (None, '') and pd.notna(saved_leg1) and \
                       saved_leg2 not in (None, '') and pd.notna(saved_leg2):
                        leg1, leg2 = str(saved_leg1), str(saved_leg2)
                    else:
                        leg1, leg2 = _resolve_bondcurve_legs(spread_type, trade_id, duration)
                    leg1_display = normalize_risk_ticker(leg1)
                    leg2_display = normalize_risk_ticker(leg2)
                    # Leg 3 only exists for 3-leg flies; blank for every other spread.
                    saved_leg3 = row.get('Leg3', None)
                    leg3 = '' if saved_leg3 in (None, '') or pd.isna(saved_leg3) else str(saved_leg3)
                    leg_ratio_val = _leg_volume_ratio(leg1, leg2, spread_type, trade_id, duration, _alpha_duration_snap_cache)
                    # 3-tenor fly: each wing takes half the belly's DV01 (the ratios the
                    # optimizer sized with and Risk nets with). The 2-leg ratio above
                    # hedged the belly's full DV01 with one wing -- 2x too big -- and was
                    # blank when a wing's bond had not been resolved.
                    _fly_ratios = fly_leg_dv01_ratios(spread_type, trade_id, legs=(leg1, leg2, leg3))
                    if _fly_ratios is not None:
                        leg_ratio_val = _fly_ratios[0]
                    leg_ratio = f"{leg_ratio_val:.3f}" if leg_ratio_val is not None else ''
                    leg_ratio3 = f"{_fly_ratios[1]:.3f}" if _fly_ratios is not None else ''
                    leg2_target_volume = (
                        -_dir_sign * round(notional * leg_ratio_val / 10.0) * 10.0 if leg_ratio_val is not None else None
                    )
                    # Long wing of a fly: the other half of the belly's DV01, same side as leg 2.
                    leg3_target_volume = (
                        -_dir_sign * round(notional * _fly_ratios[1] / 10.0) * 10.0 if _fly_ratios is not None else None
                    )
    
                    cp_fallback_bp = _resolve_alpha_metric(
                        spread_type, trade_id, 'spread',
                        fallback=round(float(spread_val), 4) if pd.notna(spread_val) else None,
                        scale_to_bp=True,
                    )
                    cp_bp = _resolve_alpha_close_price_bp(
                        spread_type,
                        trade_id,
                        leg1,
                        leg2,
                        cp_fallback_bp,
                        leg3,
                    )
                    # Swap rows priced off a daily close: Z-Score from that same close
                    # (snapshot mean / EWMA vol), not the older real-time quote's.
                    if spread_type == 'SwapSpread' and trade_id in _swap_close_date and cp_bp is not None:
                        _sdf = _alpha_spread_cache.get(spread_type)
                        if isinstance(_sdf, pd.DataFrame) and trade_id in _sdf.index:
                            _vol = _sdf.at[trade_id, 'ewm_vol'] if 'ewm_vol' in _sdf.columns else np.nan
                            if pd.isna(_vol) and 'vol' in _sdf.columns:
                                _vol = _sdf.at[trade_id, 'vol']
                            _z = zscore_from_close(cp_bp, _sdf.at[trade_id, 'mean'] if 'mean' in _sdf.columns else None, _vol)
                            if _z is not None:
                                zscore_val = _z
    
                    # Carry+Roll is shown as a 3m value in the table.
                    # Use the live spread-based annual proxy when available and convert annual -> quarterly.
                    # This keeps borrow-cost drag out of the displayed carry for bond shorts.
                    # What the POSITION earns over 3 months, from the snapshot's carry+roll (the
                    # same figure the Candidates cards use). The old spread-level/4 proxy had the
                    # wrong sign for slopes (CGB-10s30s showed +11.5 when BUY earns -5.3).
                    carry_roll_3m_val = get_carry_roll_3m_bp(spread_type, trade_id, str(row.get('direction', '') or ''))
                    if carry_roll_3m_val is None:      # no snapshot row: legacy proxy, BUY-side then flipped for SELL
                        _base_annual_bp = cp_bp if cp_bp is not None else carry_roll_val
                        if _base_annual_bp is not None:
                            carry_roll_3m_val = _base_annual_bp / 4.0
                            if str(row.get('direction', '')).strip().upper() == 'SELL':
                                carry_roll_3m_val = -carry_roll_3m_val
    
                    # No open price yet (newly added, or added before this existed): default it to
                    # the latest close and today's date. Saved below, so it stays fixed; the user
                    # can overwrite it.
                    if not open_price_str.strip() and cp_bp is not None:
                        open_price_str = f"{cp_bp:.4f}"
                        open_date_str = open_date_str.strip() or pd.Timestamp.today().strftime('%Y-%m-%d')
                        _seeded = True

                    mtm_price_mm = mtm_spd_bp = mtm_carry_mm = mtm_total_mm = None
                    open_price_bp = None
                    try:
                        open_price_bp = float(open_price_str) if open_price_str else None
                        # An allocation has a target notional before it becomes an
                        # executed position.  Use that target for indicative MTM
                        # until the operator enters an actual volume.
                        volume_mm_f = float(volume_str) if volume_str else abs(notional)
                        direction     = row.get('direction', '').upper()
                        mtm_spd_bp = _alpha_spread_pnl_bp(
                            spread_type, direction, open_price_bp, cp_bp,
                        )
                        if mtm_spd_bp is not None and volume_mm_f is not None:
                            mtm_price_mm = round(mtm_spd_bp * duration * volume_mm_f / 10000.0, 4)
                        if volume_mm_f is not None:
                            mtm_carry_mm = _compute_alpha_carry_mtm(spread_type, trade_id, open_date_str, volume_mm_f, direction)
                        if mtm_price_mm is not None or mtm_carry_mm is not None:
                            mtm_total_mm = round((mtm_price_mm or 0.0) + (mtm_carry_mm or 0.0), 4)
                    except (ValueError, TypeError):
                        pass
    
                    # Stop/Target are stored as bp *distances* from entry, signed by
                    # direction (BUY: stop below entry, target above; SELL: reversed).
                    _direction_u = str(row.get('direction', '')).strip().upper()
                    _stop_mag = _first_numeric(row, (
                        'stop_loss', 'stop', 'stop_bp', 'stopLoss', '_stop_dist', 'Stop (bp)'
                    ))
                    _target_mag = _first_numeric(row, (
                        'profit_target', 'target', 'target_bp', 'profitTarget', '_target_dist', 'Target (bp)'
                    ))

                    # Stop/Target are shown exactly as saved by Alpha > Portfolio (Run Optimization);
                    # there is deliberately no second formula here. A blank means that run saved none.
                    # Trend / momentum rows: if the saved snapshot has no stop/target (or only one), fill
                    # from live sigma exactly as the Portfolio run does (2 sigma stop, 2 sigma mirror target).
                    # Depends only on sigma, so it does not go stale like a mean-reverting level.
                    if (_stop_mag is None or _target_mag is None) and str(row.get('style', '') or '').strip().lower() not in {
                            'meanreversion', 'mean-reverting', 'mean_reverting'}:
                        _sg_live = _resolve_alpha_metric(spread_type, trade_id, 'ewm_vol', scale_to_bp=True)
                        if not _sg_live:
                            _sg_live = _resolve_alpha_metric(spread_type, trade_id, 'vol', scale_to_bp=True)
                        if _sg_live:
                            if _stop_mag is None:
                                _stop_mag = 2.0 * abs(float(_sg_live))
                            if _target_mag is None:
                                _target_mag = 2.0 * abs(float(_sg_live))
                    stop_level = target_level = None
                    # Open price is seeded with the spread when the trade was added to the
                    # portfolio; older rows without one fall back to the current close.
                    _entry_bp = open_price_bp if open_price_bp is not None else cp_bp
                    if _entry_bp is None and spread_val is not None and pd.notna(spread_val):
                        _entry_bp = float(spread_val)
                    try:
                        _sl_mag = float(_stop_mag) if _stop_mag is not None else None
                        _tp_mag = float(_target_mag) if _target_mag is not None else None
                        _progress_direction = _alpha_progress_direction(spread_type, _direction_u)
                        if _entry_bp is not None:
                            if _sl_mag is not None:
                                stop_level = _entry_bp - _sl_mag if _progress_direction == 'BUY' else _entry_bp + _sl_mag
                            if _tp_mag is not None:
                                target_level = _entry_bp + _tp_mag if _progress_direction == 'BUY' else _entry_bp - _tp_mag
                    except (ValueError, TypeError):
                        pass

                    # Mean-reverting rows: target and stop are z-levels around TODAY's mean and sigma
                    # (as the backtest exits: |z| <= exit_z / |z| >= stop_z), so they follow the drift.
                    # The stop may only tighten: never looser than entry +/- its saved distance.
                    # _stop_mag/_target_mag are rewritten as distances from entry for the exit alerts.
                    if str(row.get('style', '') or '').strip().lower() in {'meanreversion', 'mean-reverting', 'mean_reverting'}:
                        _mean_bp = _resolve_alpha_metric(spread_type, trade_id, 'mean', scale_to_bp=True)
                        _sig_bp = _resolve_alpha_metric(spread_type, trade_id, 'ewm_vol', scale_to_bp=True)
                        if not _sig_bp:
                            _sig_bp = _resolve_alpha_metric(spread_type, trade_id, 'vol', scale_to_bp=True)
                        if _mean_bp is not None and _sig_bp and _entry_bp is not None:
                            from web.tabs.alpha.callbacks.backtest_state import mr_exit_stop_z
                            _ez, _sz = mr_exit_stop_z(spread_type, trade_id)
                            _sg = abs(float(_sig_bp))
                            _buy = _alpha_progress_direction(spread_type, _direction_u) == 'SELL'   # BUY profits as spread falls
                            target_level = _mean_bp + _ez * _sg if _buy else _mean_bp - _ez * _sg
                            _dyn_stop = _mean_bp + _sz * _sg if _buy else _mean_bp - _sz * _sg
                            if stop_level is not None:      # saved entry stop: dynamic stop can only tighten it
                                stop_level = min(stop_level, _dyn_stop) if _buy else max(stop_level, _dyn_stop)
                            else:
                                stop_level = _dyn_stop
                            _target_mag = max((_entry_bp - target_level) if _buy else (target_level - _entry_bp), 0.0)
                            _stop_mag = max((stop_level - _entry_bp) if _buy else (_entry_bp - stop_level), 0.0)

                    # Trend / momentum rows: the backtest's exit is a trailing stop off the best price since
                    # entry (trailing_mult x daily-change vol) and a trend-state flip -- no price target.
                    # Show that stop; leave Target blank. The 2-sigma fill above stays only as a fallback.
                    elif True:
                        from web.tabs.alpha.callbacks.backtest_state import trend_trailing_stop_bp
                        _tr = trend_trailing_stop_bp(spread_type, trade_id, _direction_u, open_date_str)
                        if _tr is not None:
                            stop_level = _tr['level']
                            target_level = None
                            _stop_mag = _target_mag = None   # levels only: alerts read the shown Stop level

                    display_rows.append({
                        '__row_key':              str(_row_idx),
                        'ID':                     trade_id,
                        'Leg 1':                  leg1_display,
                        'Leg 2':                  leg2_display,
                        'Leg 3':                  leg3,
                        'Ratio (V2/V1)':          leg_ratio,
                        'Ratio (V3/V1)':          leg_ratio3,
                        'Target Volume Leg2 (MM CNY)': f"{leg2_target_volume:,.1f}" if leg2_target_volume is not None else '',
                        'Target Volume Leg3 (MM CNY)': f"{leg3_target_volume:,.1f}" if leg3_target_volume is not None else '',
                        'Margin (MM)':            f"{margin_mm:,.2f}" if margin_mm is not None else '',
                        'Spread Type':            spread_type,
                        'Style':                  row.get('style', ''),
                        'Direction':              row.get('direction', ''),
                        'Duration':               f"{duration:.2f}" if duration else 'N/A',
                        'Open price (bp)':        open_price_str,
                        'Volume (mm)':            volume_str,
                        'Open date':              open_date_str,
                        'Z-Score':                f"{zscore_val:.2f}" if zscore_val is not None else '',
                        'Close Price (bp)':       f"{cp_bp:.2f}" if cp_bp is not None else 'N/A',
                        'Progress':               '',
                        'Capital (MM CNY)':       f"{_dir_sign * notional:,.1f}",
                        'DV01 (k CNY/bp)':        f"{dv01_k:.1f}",
                        'Carry+Roll (3m,bp)':     _fmt1(carry_roll_3m_val),
                        'Breakeven (3m,bp)':      _fmt1(breakeven_val),
                        # Stop / Target are LEVELS in the same units as Open / Close: a BUY profits when the
                        # spread falls (stop above entry, target below), a SELL the reverse. The saved
                        # distances stay in _stop_dist / _target_dist for the exit alerts.
                        'Stop (bp)':              _fmt1(stop_level) if stop_level is not None else _fmt1(_stop_mag),
                        'Target (bp)':            _fmt1(target_level) if target_level is not None else _fmt1(_target_mag),
                        '_stop_dist':             _fmt1(_stop_mag),
                        '_target_dist':           _fmt1(_target_mag),
                        'MTM spd (bp)':           f"{mtm_spd_bp:,.4f}" if mtm_spd_bp is not None else '',
                        'MtM Carry (MM CNY)':     f"{mtm_carry_mm:,.4f}" if mtm_carry_mm is not None else '',
                        'MtM Value (MM CNY)':     f"{mtm_total_mm:,.4f}" if mtm_total_mm is not None else '',
                        'Target Weight (%)':      f"{float(row.get('weight', 0) or 0) * 100:.2f}%",
                        # risk_contribution is already in percent (see Alpha Portfolio);
                        # renormalized to the rows shown below.
                        'RC (%)':                 f"{risk_contribution:.6f}%" if risk_contribution is not None else '',
                        'Weight (%)':             '',
                        '_entry_level':           f"{_entry_bp:.4f}" if _entry_bp is not None else '',
                        '_current_level':         f"{cp_bp:.4f}" if cp_bp is not None else '',
                        '_stop_level':            f"{stop_level:.4f}" if stop_level is not None else '',
                        '_target_level':          f"{target_level:.4f}" if target_level is not None else '',
                    })

                if _seeded:
                    try:
                        _persist_alpha_summary_rows(display_rows, prune=False)
                    except Exception as _e:
                        print(f"WARNING: could not save default open prices: {_e}")
    
            for r in display_rows:
                if r.get('ID') == 'TOTAL':
                    continue
                try:
                    row_volume = float(str(r.get('Volume (mm)', '') or '').replace(',', '').strip()) if str(r.get('Volume (mm)', '') or '').strip() else None
                except (ValueError, TypeError):
                    row_volume = None
                try:
                    target_volume = float(str(r.get('Capital (MM CNY)', '') or '').replace(',', '').strip()) if str(r.get('Capital (MM CNY)', '') or '').strip() else None
                except (ValueError, TypeError):
                    target_volume = None
                if row_volume is not None and row_volume > 0 and target_volume not in (None, 0):
                    scale = row_volume / abs(target_volume)
                    margin_val = _coerce_float(r.get('Margin (MM)'))
                    if margin_val is not None:
                        r['Margin (MM)'] = f"{margin_val * scale:,.2f}"

            total_vol = 0.0
            for r in display_rows:
                try:
                    total_vol += float(r['Volume (mm)']) if r['Volume (mm)'] else 0.0
                except (ValueError, TypeError):
                    pass
            for r in display_rows:
                try:
                    v = float(r['Volume (mm)']) if r['Volume (mm)'] else None
                    r['Weight (%)'] = f"{v / total_vol * 100:.2f}%" if (v is not None and total_vol > 0) else ''
                except (ValueError, TypeError):
                    r['Weight (%)'] = ''
    
            if not display_rows:
                return _no_data("Alpha snapshot is empty.")

            # The snapshot can hold only some of the optimised trades (or rows whose
            # RC was missing), so rescale RC to sum to 100% across the rows shown.
            _rc_vals = {}
            for _i, r in enumerate(display_rows):
                try:
                    _rc_vals[_i] = float(str(r.get('RC (%)', '')).replace('%', '').strip())
                except (ValueError, TypeError):
                    pass
            _rc_sum = sum(_rc_vals.values())
            if _rc_sum > 0:
                for _i, _v in _rc_vals.items():
                    display_rows[_i]['RC (%)'] = f"{_v / _rc_sum * 100:.2f}%"
    
            _BOND_OUTRIGHT_TYPES = {'TBondCurve', 'CBondCurve', 'TBondSwap', 'CBondSwap'}
    
            def _sum_col(col, filter_types=None):
                total, has_any = 0.0, False
                for r in display_rows:
                    if filter_types and r.get('Spread Type', '') not in filter_types:
                        continue
                    v = str(r.get(col, '')).replace(',', '').replace('%', '').strip()
                    if v:
                        try:
                            total += float(v); has_any = True
                        except (ValueError, TypeError):
                            pass
                return total if has_any else None
    
            _s_tvol   = _sum_col('Capital (MM CNY)', _BOND_OUTRIGHT_TYPES)
            _s_margin = _sum_col('Margin (MM)')
            _s_dv01   = _sum_col('DV01 (k CNY/bp)')
            _s_carry  = _sum_col('MtM Carry (MM CNY)')
            _s_mtm    = _sum_col('MtM Value (MM CNY)')
            _s_tgt_wt = _sum_col('Target Weight (%)')
            _s_rc     = _sum_col('RC (%)')
            _s_wt     = _sum_col('Weight (%)')
    
            total_row = {c: '' for c in display_rows[0].keys()}
            total_row['ID']                     = 'TOTAL'
            total_row['Capital (MM CNY)'] = f"{_s_tvol:,.1f}"   if _s_tvol   is not None else ''
            total_row['Margin (MM)']            = f"{_s_margin:,.2f}" if _s_margin is not None else ''
            total_row['DV01 (k CNY/bp)']        = f"{_s_dv01:.1f}"    if _s_dv01   is not None else ''
            total_row['MtM Carry (MM CNY)']     = f"{_s_carry:,.4f}"  if _s_carry  is not None else ''
            total_row['MtM Value (MM CNY)']     = f"{_s_mtm:,.4f}"    if _s_mtm    is not None else ''
            total_row['Target Weight (%)']      = f"{_s_tgt_wt:.2f}%" if _s_tgt_wt is not None else ''
            total_row['RC (%)']                 = f"{_s_rc:.2f}%"     if _s_rc     is not None else ''
            total_row['Weight (%)']             = f"{_s_wt:.2f}%"     if _s_wt     is not None else ''
            display_rows.append(total_row)
    
            _today = pd.Timestamp.today().normalize()
            _alert_rows: list = []
            _alert_ids: dict = {'stop': set(), 'target': set(), 'hold': set()}
            for r in display_rows:
                if r.get('ID') == 'TOTAL':
                    continue
                _tid  = r.get('ID', '')
                _direction_actual = str(r.get('Direction', '')).strip().upper()
                _op_s = str(r.get('Open price (bp)', '') or '').strip()
                _cp_s = str(r.get('Close Price (bp)', '') or '').strip()
                _stop_level_s = str(r.get('_stop_level', '') or r.get('Stop (bp)', '') or '').strip()
                _target_level_s = str(r.get('_target_level', '') or r.get('Target (bp)', '') or '').strip()
                _stop_dist_s = str(r.get('_stop_dist', '') or '').strip()
                _target_dist_s = str(r.get('_target_dist', '') or '').strip()
                _od_s = str(r.get('Open date', '') or '').strip()
                try:
                    _op = float(_op_s) if _op_s else None
                    _cp = float(_cp_s) if _cp_s else None
                    _stop_dist = float(_stop_dist_s) if _stop_dist_s else None
                    _target_dist = float(_target_dist_s) if _target_dist_s else None
                    _saved_stop_level = float(_stop_level_s) if _stop_level_s else None
                    _saved_target_level = float(_target_level_s) if _target_level_s else None
                except (TypeError, ValueError):
                    _op = _cp = _stop_dist = _target_dist = None
                    _saved_stop_level = _saved_target_level = None

                # Recompute absolute levels from the entry and distance fields.
                # This deliberately ignores stale hidden *_level values in display
                # snapshots; 6.8 can be a profit-distance, not an absolute spread level.
                _stop_level = None
                _target_level = None
                if _op is not None:
                    if _stop_dist is not None:
                        _stop_level = (_op + abs(_stop_dist) if _direction_actual == 'BUY'
                                       else _op - abs(_stop_dist))
                    elif _saved_stop_level is not None:
                        _stop_level = _saved_stop_level

                    if _target_dist is not None:
                        _target_level = (_op - abs(_target_dist) if _direction_actual == 'BUY'
                                         else _op + abs(_target_dist))
                    elif _saved_target_level is not None:
                        _target_level = _saved_target_level
                _days = None
                if _od_s:
                    try:
                        _od = pd.to_datetime(_od_s, errors='coerce')
                        if pd.notna(_od):
                            _days = (_today - _od.normalize()).days
                    except Exception:
                        pass
                if _op is not None and _cp is not None:
                    _spd_chg = _cp - _op
                    _pnl_dir = -_spd_chg if _direction_actual == 'BUY' else _spd_chg

                    _stop_hit = (
                        _stop_level is not None
                        and ((_direction_actual == 'BUY' and _cp >= _stop_level)
                             or (_direction_actual == 'SELL' and _cp <= _stop_level))
                    )
                    _target_hit = (
                        _target_level is not None
                        and ((_direction_actual == 'BUY' and _cp <= _target_level)
                             or (_direction_actual == 'SELL' and _cp >= _target_level))
                    )
                    if _stop_hit:
                        _alert_rows.append((_tid, f"Stop loss hit (Δ={_pnl_dir:+.1f} bp, stop level={_stop_level:+.1f} bp)", 'stop'))
                        _alert_ids['stop'].add(_tid)
                    elif _target_hit:
                        _alert_rows.append((_tid, f"Target reached (Δ={_pnl_dir:+.1f} bp, target level={_target_level:+.1f} bp)", 'target'))
                        _alert_ids['target'].add(_tid)
                # Signal-based exit for Core names with saved params: the backtest
                # (same params the signal uses) has closed a trade opened on/after
                # this position's open date -> the signal says close.
                if (str(r.get('Spread Type', '')) == 'TenorSpread' and _od_s
                        and _tid not in _alert_ids['stop'] and _tid not in _alert_ids['target']):
                    try:
                        from web.tabs.alpha.data import has_saved_state as _has_saved
                        from web.tabs.alpha.callbacks.core_positions import backtest_exit_signal as _bt_exit
                        _sig = _bt_exit(_tid, _od_s) if _has_saved('TenorSpread', _tid) else None
                    except Exception:
                        _sig = None
                    if _sig is not None:
                        _why, _bdir, _bex = _sig
                        _sev = 'stop' if _why == 'stop_loss' else 'target' if _why == 'target' else 'hold'
                        _alert_rows.append((_tid, f"Signal says CLOSE: backtest exited on {_bex:%Y-%m-%d} ({_why or 'exit'})", _sev))
                        _alert_ids[_sev].add(_tid)
                if _days is not None and _days >= 21 and _tid not in _alert_ids['stop'] and _tid not in _alert_ids['target']:
                    _alert_rows.append((_tid, f"Long hold: {_days}d — review if signal or carry has changed", 'hold'))
                    _alert_ids['hold'].add(_tid)
    
            _alert_severity = {}
            for _tid in _alert_ids['stop']:
                _alert_severity[_tid] = 'stop'
            for _tid in _alert_ids['target']:
                _alert_severity[_tid] = 'target'
            for _tid in _alert_ids['hold']:
                _alert_severity[_tid] = 'hold'
            _row_alert_bg = {
                'stop':   'rgba(239,85,59,0.22)',
                'target': 'rgba(0,204,150,0.22)',
                'hold':   'rgba(255,165,0,0.14)',
            }
    
            body_rows  = [r for r in display_rows if r.get('ID') != 'TOTAL']
            total_rows = [r for r in display_rows if r.get('ID') == 'TOTAL']
            _numeric_cols = {
                'Duration', 'Open price (bp)', 'Volume (mm)', 'Z-Score', 'Close Price (bp)',
                'Capital (MM CNY)', 'Target Volume Leg2 (MM CNY)', 'Target Volume Leg3 (MM CNY)', 'Margin (MM)',
                'DV01 (k CNY/bp)', 'Carry+Roll (3m,bp)',
                'Breakeven (3m,bp)', 'Stop (bp)', 'Target (bp)', 'MTM spd (bp)',
                'MtM Carry (MM CNY)', 'MtM Value (MM CNY)', 'Target Weight (%)', 'RC (%)', 'Weight (%)',
            }
            body_rows = _apply_sort(body_rows, sort_state, _numeric_cols)
    
            _ALL_COLS = [
                ('ID', 'left'), ('Leg 1', 'left'), ('Leg 2', 'left'), ('Leg 3', 'left'), ('Ratio (V2/V1)', 'right'), ('Ratio (V3/V1)', 'right'),
                ('Style', 'left'), ('Direction', 'center'), ('Duration', 'right'),
                ('Close Price (bp)', 'right'), ('Stop (bp)', 'right'), ('Target (bp)', 'right'),
                ('Z-Score', 'right'), ('Progress', 'left'),
                ('Capital (MM CNY)', 'right'), ('Target Volume Leg2 (MM CNY)', 'right'),
                ('Target Volume Leg3 (MM CNY)', 'right'), ('Margin (MM)', 'right'),
                ('DV01 (k CNY/bp)', 'right'),
                ('Carry+Roll (3m,bp)', 'right'), ('Breakeven (3m,bp)', 'right'),
                ('Target Weight (%)', 'right'), ('RC (%)', 'right'),
            ]
            _cols = [('__delete', 'center')] + list(_ALL_COLS)
    
            header_row = html.Tr([
                (html.Th('', style={'padding': '7px 6px', 'width': '24px'}) if c == '__delete'
                 else _sortable_header(c, c, 'alpha', sort_state, align=a))
                for c, a in _cols
            ], style={'background': THEME['table_header'], 'borderBottom': f"1px solid {THEME['accent']}"})
    
            def _editable_cell(row_idx: int, col: str, value: str, kind: str = 'text'):
                input_id = {'type': 'alpha-cell-input', 'row': row_idx, 'col': col}
                if kind == 'date':
                    return html.Td([
                        html.Button(
                            value or '—',
                            id={'type': 'alpha-date-trigger', 'row': row_idx},
                            n_clicks=0,
                            className='an-date-trigger-btn',
                            style={
                                'background': 'rgba(99,179,237,0.08)',
                                'border': f'1px solid {THEME["accent"]}', 'borderRadius': '3px',
                                'color': THEME['text_main'], 'fontSize': '13px', 'padding': '5px 8px',
                                'cursor': 'pointer', 'width': '100%', 'minWidth': '92px',
                                'whiteSpace': 'nowrap',
                            },
                        ),
                    ], style={'padding': '5px 10px', 'textAlign': 'right', 'minWidth': '92px'})
                return html.Td(
                    dcc.Input(
                        id=input_id, type='text', value=value, debounce=True,
                        style={
                            'background': 'rgba(99,179,237,0.08)', 'border': f'1px solid {THEME["accent"]}',
                            'borderRadius': '3px', 'color': THEME['text_main'], 'fontSize': '9px',
                            'padding': '3px 6px', 'width': '64px', 'textAlign': 'right',
                        },
                    ),
                    style={'padding': '5px 10px', 'textAlign': 'right'},
                )
    
            def _cell(row_idx: int, col: str, row: dict, align: str):
                val = row.get(col, '')
                base_style = {'padding': '5px 10px', 'textAlign': align, 'color': THEME['text_main']}
                if col == 'ID':
                    return html.Td(val, style={**base_style, 'fontWeight': '600', 'whiteSpace': 'nowrap'})
                if col in ('Leg 1', 'Leg 2', 'Leg 3'):
                    return html.Td(val, style={**base_style, 'color': THEME['text_sub'], 'fontSize': '9px'})
                if col == 'Style':
                    return html.Td(_style_badge(val) if val else '', style=base_style)
                if col == 'Direction':
                    return html.Td(_dir_badge(val) if val else '', style=base_style)
                if col == 'Open price (bp)':
                    return _editable_cell(row_idx, col, val, 'text')
                if col == 'Volume (mm)':
                    return _editable_cell(row_idx, col, val, 'text')
                if col == 'Open date':
                    return _editable_cell(row_idx, col, val, 'date')
                if col == 'Z-Score':
                    try:
                        z = float(val) if val not in ('', 'N/A') else None
                    except (TypeError, ValueError):
                        z = None
                    return html.Td(val, style={**base_style, **_zscore_cell_style(z)})
                if col in ('MTM spd (bp)', 'MtM Value (MM CNY)'):
                    try:
                        signed = float(str(val).replace(',', '')) if val else None
                    except (TypeError, ValueError):
                        signed = None
                    return html.Td(val, style={**base_style, **_signed_value_style(signed)})
                if col == 'Target (bp)':
                    try:
                        _td = row['_target_dist'] if '_target_dist' in row else val
                        _at_target = _td not in ('', None) and float(str(_td).replace(',', '')) <= 0
                    except (TypeError, ValueError):
                        _at_target = False
                    if _at_target:   # 0 bp to go: already at the exit level, not a missing target
                        return html.Td('at target', title='Spread already inside the exit band (0 bp to go)',
                                       style={**base_style, 'color': '#34d399', 'fontStyle': 'italic'})
                    return html.Td(val, style={**base_style, 'color': '#34d399'})
                if col == 'Stop (bp)':
                    return html.Td(val, style={**base_style, 'color': '#f87171'})
                if col == 'Progress':
                    try:
                        entry  = float(row.get('_entry_level', '') or '')
                        cur    = float(row.get('_current_level', '') or '')
                        target = float(row.get('_target_level', '') or '')
                        stop   = float(row.get('_stop_level', '') or '')
                    except (TypeError, ValueError):
                        return html.Td('', style=base_style)
                    direction = _alpha_progress_direction(row.get('Spread Type', ''), row.get('Direction', ''))
                    return html.Td(_stop_target_bar(entry, cur, stop, target, direction),
                                    style={**base_style, 'minWidth': '110px'})
                if col == '__delete':
                    return html.Td(
                        html.Button('×', id={'type': 'alpha-row-delete', 'row': row_idx}, n_clicks=0, style={
                            'background': 'none', 'border': 'none', 'color': THEME['text_sub'],
                            'cursor': 'pointer', 'fontSize': '14px', 'padding': '0 4px',
                        }),
                        style={'padding': '5px 6px', 'textAlign': 'center'},
                    )
                return html.Td(val, style=base_style)
    
            body_trs = []
            for i, row in enumerate(body_rows):
                tid = row.get('ID', '')
                sev = _alert_severity.get(tid)
                row_bg = _row_alert_bg.get(sev) if sev else (
                    THEME['bg_card'] if i % 2 == 1 else 'transparent')
                row_idx = _row_key(row, i)
                body_trs.append(html.Tr(
                    [_cell(row_idx, c, row, a) for c, a in _cols],
                    style={'background': row_bg, 'borderBottom': '1px solid rgba(255,255,255,0.04)'},
                ))
            for trow in total_rows:
                body_trs.append(html.Tr(
                    [html.Td(trow.get(c, '') if c != '__delete' else '', style={
                        'padding': '5px 10px', 'textAlign': a, 'fontWeight': 'bold',
                        'color': THEME['text_main'],
                    }) for c, a in _cols],
                    style={'background': THEME['table_header'], 'borderTop': f"1px solid {THEME['accent']}"},
                ))
    
            table = html.Div(
                html.Table([
                    html.Thead(header_row),
                    html.Tbody(body_trs),
                ], style={'width': '100%', 'borderCollapse': 'collapse', 'fontSize': '9px'}),
                style={'overflowX': 'auto'},
            )
    
            _reminder_banner = None
            if _alert_rows:
                _sev_style = {
                    'stop':   {'color': THEME['danger'],  'icon': '🛑'},
                    'target': {'color': THEME['success'], 'icon': '✅'},
                    'hold':   {'color': THEME['warning'], 'icon': '⏰'},
                }
                _items = []
                _rows_by_id = {r.get('ID'): r for r in display_rows}
                for _tid, _msg, _sev in _alert_rows:
                    _st = _sev_style[_sev]
                    _children = [
                        html.Span(f"{_st['icon']} ", style={'fontSize': '13px'}),
                        html.Span(_tid, style={'fontWeight': 'bold', 'color': _st['color'], 'marginRight': '6px'}),
                        html.Span(_msg, style={'color': THEME['text_main']}),
                    ]
                    # A close alert (stop / target / signal) comes with the legs to trade. Long-hold is a
                    # review prompt, not a close.
                    if _sev in ('stop', 'target') or _msg.startswith('Signal says CLOSE'):
                        _tk = alpha_close_ticket(_rows_by_id.get(_tid, {}))
                        if _tk:
                            _booked = all(t['booked'] for t in _tk)
                            _children.append(html.Div(
                                f"Close: {format_ticket(_tk)}" + ('' if _booked else '  (indicative: Volume not entered, using target size)'),
                                style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '22px', 'marginTop': '2px'}))
                    _items.append(html.Div(_children, style={'marginBottom': '6px', 'fontSize': '12px'}))
                _reminder_banner = html.Div([
                    html.Div("Exit Reminders", style={
                        'fontWeight': 'bold', 'color': THEME['text_main'], 'fontSize': '13px',
                        'marginBottom': '6px', 'borderBottom': f"1px solid {THEME['table_header']}",
                        'paddingBottom': '4px',
                    }),
                    *_items,
                ], style={'backgroundColor': 'rgba(239,85,59,0.08)', 'border': f"1px solid {THEME['danger']}",
                          'borderRadius': '5px', 'padding': '10px 14px', 'marginBottom': '12px'})
    
            _active_target = next((r for r in display_rows if _row_key(r, -1) == active_date_row), None) \
                if active_date_row is not None else None
            if _active_target is not None:
                _parsed_active = pd.to_datetime(_active_target.get('Open date', ''), errors='coerce')
                _picker_date = _parsed_active.date().isoformat() if pd.notna(_parsed_active) else None
                _picker_disabled = False
                _picker_label = f"Editing {_active_target.get('ID', '')}"
            else:
                _picker_date = None
                _picker_disabled = True
                _picker_label = 'Click an Open date cell to edit with the calendar.'
    
            content = html.Div([
                html.Div([
                    html.Span('Open date calendar:', style={'color': THEME['text_sub'], 'fontSize': '11px'}),
                    dcc.DatePickerSingle(
                        id='summary-alpha-open-date-picker',
                        date=_picker_date, display_format='YYYY-MM-DD', clearable=True,
                        disabled=_picker_disabled,
                        placeholder='Select an Open date cell',
                        style={'backgroundColor': THEME['bg_input']},
                    ),
                    html.Span(
                        id='summary-alpha-open-date-target',
                        children=_picker_label,
                        style={'color': THEME['text_sub'], 'fontSize': '11px', 'fontStyle': 'italic'},
                    ),
                ], style={'display': 'flex', 'alignItems': 'center', 'gap': '10px',
                          'marginBottom': '10px', 'flexWrap': 'wrap', 'position': 'relative', 'zIndex': '1001'}),
                *([_reminder_banner] if _reminder_banner else []),
                _progress_legend(),
                table,
            ], id='summary-alpha-table-wrapper')
            status = f"Alpha snapshot from {ts[:19]} ({source_label})"
            try:
                _cgb = _database_px().get('CGB')
                _asof = pd.Timestamp(_cgb.index.max()).date() if isinstance(_cgb, pd.DataFrame) and len(_cgb) else None
                if _asof is not None:
                    status += f" · Z-Score / Close as of {_asof}"
                _snap = DIR_INPUT / 'Alpha-spreadsrt.pkl'
                if _snap.exists() and (DIR_INPUT / 'database-px.pkl').exists() \
                        and _snap.stat().st_mtime < (DIR_INPUT / 'database-px.pkl').stat().st_mtime:
                    status += " · WARNING: spread snapshot is older than market data (rebuild failed?)"
            except Exception:
                pass
            return content, status, display_rows
    
        except Exception as exc:
            return _no_data(f"Error loading Alpha snapshot: {exc}")
    
    # ── Alpha Book: header sort clicks ─────────────────────────────────────────
