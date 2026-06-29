# -*- coding: utf-8 -*-
"""Backtest subtab callbacks: mode selector, instrument dropdown, regime auto-detect,
parameter panel toggle, individual backtest, portfolio data preview, portfolio backtest."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from dash import dcc, html, dash_table
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go

from ..data import (
    THEME, SPREAD_CATEGORIES, MACRO_PREFIX, YIELD_BASED_SPREAD_TYPES,
    load_spread_data, load_spread_timeseries, load_carry_roll_timeseries,
    load_macro_series, _get_duration_mult, _get_borrow_cost_annual_bp,
)
from .portfolio import _SUMMARY_ALPHA_PARQUET
from ..layouts import build_individual_backtest_panel, build_portfolio_backtest_panel
from ..backtest import run_spread_backtest, run_trend_backtest_dc, build_backtest_results_display


def register_backtest_callbacks(app) -> None:
    """Register all Backtest subtab callbacks."""

    def _load_portfolio_snapshot(optimized_data):
        """Prefer the persisted Alpha snapshot so Backtest matches Summary."""
        try:
            import os

            if os.path.exists(_SUMMARY_ALPHA_PARQUET):
                df_snap = pd.read_parquet(_SUMMARY_ALPHA_PARQUET)
                if isinstance(df_snap, pd.DataFrame) and not df_snap.empty:
                    if 'ID' in df_snap.columns:
                        df_snap = df_snap[df_snap['ID'].astype(str).ne('TOTAL')].copy()
                    if '_timestamp' in df_snap.columns:
                        df_snap = df_snap.sort_values('_timestamp')
                    return df_snap.to_dict('records')
        except Exception:
            pass

        return optimized_data or []

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
        {'label': ' Trend (Directional-Change)', 'value': 'trend'},
    ]
    _BT_DISABLED_OPTIONS = [
        {'label': ' Mean-Reversion', 'value': 'mr', 'disabled': True},
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
                # Uncertain regime: use the sign of the 3m edge as a tiebreaker.
                # Positive edge rewards waiting for reversion → MR.
                # Negative/zero edge means follow Trend.
                auto_options = _BT_BASE_OPTIONS
                edge_val = np.nan
                try:
                    snap_df = load_spread_data(spread_type)
                    if isinstance(snap_df, pd.DataFrame) and not snap_df.empty:
                        _row = None
                        if instrument in snap_df.index:
                            _row = snap_df.loc[instrument]
                        elif 'ID' in snap_df.columns:
                            _m = snap_df[snap_df['ID'].astype(str) == str(instrument)]
                            if not _m.empty:
                                _row = _m.iloc[0]
                        if _row is not None:
                            for _c in ['carry_roll', 'carry_3m_bp', 'Carry(3m,bp)', 'carry']:
                                _v = _row.get(_c, np.nan)
                                if _v is not None and np.isfinite(float(_v)):
                                    edge_val = float(_v)
                                    break
                except Exception:
                    pass
                if not np.isnan(edge_val):
                    style_key = 'mr' if edge_val > 0 else 'trend'
                    edge_hint = f"edge={edge_val:+.1f}bp → {'MR' if edge_val > 0 else 'Trend'} suggested"
                else:
                    style_key = 'mr'
                    edge_hint = "edge unavailable → MR suggested"

            if regime == 'uncertain':
                badge_extra = html.Span(
                    f"  (score: {score:+.2f})  {edge_hint}",
                    style={'color': THEME['warning'], 'fontSize': '11px'},
                )
            else:
                badge_extra = html.Span(
                    f"  (score: {score:+.2f}, source: {regime_source})",
                    style={'color': THEME['text_sub'], 'fontSize': '11px'},
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
        base_mr = {
            'background': 'var(--surface-panel)', 'border': '1px solid var(--border-strong)',
            'borderRadius': '6px', 'padding': '14px 16px', 'marginBottom': '14px',
        }
        base_trend = {'background': 'var(--surface-panel)', 'border': '1px solid var(--border-strong)',
                      'borderRadius': '6px', 'padding': '14px 16px', 'flex': '1'}
        if style == 'trend':
            base_mr['display'] = 'none'
        else:
            base_trend['display'] = 'none'
        return base_mr, base_trend

    # -------------------------------------------------------------------------
    # BACKTEST: Spread-type parameter presets
    # -------------------------------------------------------------------------
    @app.callback(
        [Output('bt-entry-z', 'value'),
         Output('bt-exit-z', 'value'),
         Output('bt-stop-z', 'value'),
         Output('bt-min-hold', 'value'),
         Output('bt-theta', 'value'),
         Output('bt-mom-window', 'value'),
         Output('bt-vol-window', 'value'),
         Output('bt-trailing-mult', 'value')],
        Input('bt-spread-type', 'value'),
    )
    def preset_backtest_params(spread_type):
        if spread_type == 'TenorSpread':
            return 2.5, 0.25, 5.0, 10, 0.03, 30, 90, 2.0

        return 2.0, 0.5, 4.0, 7, 0.02, 20, 60, 1.5

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
         State('bt-period', 'value'),
         State('bt-trade-style', 'value'),
         State('bt-theta', 'value'),
         State('bt-mom-window', 'value'),
         State('bt-vol-window', 'value'),
         State('bt-trailing-mult', 'value'),
         State('bt-carry-buffer', 'value'),
         State('bt-allow-short', 'value'),
         State('bt-min-hold', 'value')],
        prevent_initial_call=True
    )
    def run_individual_backtest(
        n_clicks, spread_type, instrument, entry_z, exit_z, stop_z, period, style,
        theta, mom_window, vol_window, trailing_mult, carry_buffer, allow_short, min_hold
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

        is_yield_based = spread_type in YIELD_BASED_SPREAD_TYPES

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

            # YTM-based spreads: stored carry/snapshot carry is computed on the raw
            # spread value. Flip so LONG = expecting the spread to fall/narrow
            # (economically long the higher-yielding leg's price).
            if is_yield_based:
                if carry_roll_ts_instrument is not None:
                    carry_roll_ts_instrument = -carry_roll_ts_instrument
                carry_roll_bp = -carry_roll_bp

        style = style or 'mr'
        try:
            duration_mult = _get_duration_mult(instrument, spread_type)
            bc_long, bc_short = _get_borrow_cost_annual_bp(spread_type, instrument)

            # For TenorSpread, adjust carry_roll_ts to include financing and borrow costs
            _cr_sell_for_chart = None    # negated carry_roll for SELL chart display
            _cr_sell_for_backtest = None  # unnegated carry_roll for SELL _carry_accrual
            if spread_type == 'TenorSpread' and carry_roll_ts_instrument is not None:
                try:
                    from ..data import _get_tenor_yields_for_spread, _get_current_fr007_bp
                    y_short, y_long = _get_tenor_yields_for_spread(instrument)
                    fr007_bp = _get_current_fr007_bp() or 137.0
                    tenor_ratio = 0.5  # 2:1 DV01-hedged ratio

                    if y_short is not None and y_long is not None:
                        y_short_pct = y_short
                        y_long_pct = y_long
                        fr007_pct = fr007_bp / 100.0

                        fin_adj_annual_pct = (1.0 - tenor_ratio) * (y_long_pct - fr007_pct)
                        fin_adj_3m_pct = fin_adj_annual_pct * (90.0 / 360.0)

                        bc_long_3m_pct = (bc_long * tenor_ratio) * (90.0 / 360.0) / 100.0
                        bc_short_3m_pct = (bc_short) * (90.0 / 360.0) / 100.0

                        # BUY (position=+1): cr_buy passed directly → carry = sum(cr_buy)/90
                        # SELL (position=-1): +bc_short here so (-1)*(+bc_short) = -bc_short (cost)
                        cr_buy = carry_roll_ts_instrument + fin_adj_3m_pct - bc_long_3m_pct
                        cr_sell = carry_roll_ts_instrument + fin_adj_3m_pct + bc_short_3m_pct
                        _cr_sell_for_chart = -cr_sell
                        _cr_sell_for_backtest = cr_sell

                        carry_roll_ts_instrument = cr_buy
                except Exception:
                    pass

            # For BondCurve and BondSwap, adjust for direction-dependent borrow costs
            if spread_type in ['TBondCurve', 'CBondCurve', 'TBondSwap', 'CBondSwap'] and carry_roll_ts_instrument is not None:
                try:
                    if spread_type in ['TBondCurve', 'CBondCurve']:
                        bc_long_3m_pct = bc_long * (90.0 / 360.0) / 100.0
                        carry_roll_ts_instrument = carry_roll_ts_instrument - bc_long_3m_pct

                    # BondSwap: direction-asymmetric carry+roll.
                    # BUY (long bond, pay fixed swap): no borrow cost
                    # SELL (short bond, receive fixed swap): deduct borrow cost
                    if spread_type in ['TBondSwap', 'CBondSwap']:
                        bc_short_3m_pct = bc_short * (90.0 / 360.0) / 100.0
                        cr_buy = carry_roll_ts_instrument
                        cr_sell = carry_roll_ts_instrument + bc_short_3m_pct

                        carry_roll_ts_instrument = cr_buy
                        _cr_sell_for_backtest = cr_sell
                        _cr_sell_for_chart = -cr_sell
                except Exception:
                    pass

            _negate_ts = is_yield_based

            if style == 'trend':
                results = run_trend_backtest_dc(
                    spread_ts=-ts if _negate_ts else ts,
                    theta=float(theta) if theta is not None else 0.02,
                    mom_window=int(mom_window) if mom_window is not None else 20,
                    vol_window=int(vol_window) if vol_window is not None else 60,
                    trailing_mult=float(trailing_mult) if trailing_mult is not None else 1.5,
                    carry_buffer=float(carry_buffer) if carry_buffer is not None else 0.0,
                    allow_short=bool(allow_short and 'allow' in allow_short),
                    carry_roll_ts=carry_roll_ts_instrument,
                    carry_roll_bp=carry_roll_bp,
                    duration_mult=duration_mult,
                    borrow_cost_long_bp=bc_long,
                    borrow_cost_short_bp=bc_short,
                    spread_type=spread_type,
                    tenor_ratio=0.5 if spread_type == 'TenorSpread' else 1.0,
                    carry_roll_sell_ts=_cr_sell_for_backtest,
                    min_hold=int(min_hold) if min_hold is not None else 7,
                )
            else:
                results = run_spread_backtest(
                    spread_ts=-ts if _negate_ts else ts,
                    entry_z=entry_z or 2.0,
                    exit_z=exit_z or 0.5,
                    stop_z=stop_z or 4.0,
                    min_hold=int(min_hold) if min_hold is not None else 7,
                    trade_style=style,
                    carry_roll_ts=carry_roll_ts_instrument,
                    carry_roll_bp=carry_roll_bp,
                    duration_mult=duration_mult,
                    borrow_cost_long_bp=bc_long,
                    borrow_cost_short_bp=bc_short,
                    spread_type=spread_type,
                    tenor_ratio=0.5 if spread_type == 'TenorSpread' else 1.0,
                    carry_roll_sell_ts=_cr_sell_for_backtest,
                )

            # For YTM-based spreads: restore original display signs after internal inversion.
            if _negate_ts and isinstance(results, dict):
                results['spread_ts'] = ts
                for key in ('zscore_ts', 'composite_signal_ts', 'norm_mom_ts', 'trend_state_ts'):
                    series = results.get(key)
                    if isinstance(series, pd.Series):
                        results[key] = -series
                for trade in results.get('trades', []):
                    for k in ('entry_price', 'exit_price', 'entry_z', 'exit_z'):
                        if k in trade:
                            trade[k] = -trade[k]
                    if style == 'trend' and 'direction' in trade:
                        trade['direction'] = 'LONG' if trade['direction'] == 'SHORT' else ('SHORT' if trade['direction'] == 'LONG' else trade['direction'])
                open_trade = results.get('open_trade')
                if isinstance(open_trade, dict):
                    for k in ('entry_price', 'current_price', 'entry_z'):
                        if k in open_trade and open_trade[k] is not None:
                            open_trade[k] = -open_trade[k]
                    if style == 'trend' and 'direction' in open_trade:
                        open_trade['direction'] = 'LONG' if open_trade['direction'] == 'SHORT' else ('SHORT' if open_trade['direction'] == 'LONG' else open_trade['direction'])
                _tdf = results.get('trades_df')
                if isinstance(_tdf, pd.DataFrame) and not _tdf.empty:
                    for k in ('entry_price', 'exit_price', 'entry_z', 'exit_z'):
                        if k in _tdf.columns:
                            results['trades_df'][k] = -_tdf[k]
                    if style == 'trend' and 'direction' in _tdf.columns:
                        results['trades_df']['direction'] = _tdf['direction'].replace({'LONG': 'SHORT', 'SHORT': 'LONG'})
        except Exception as exc:
            import traceback
            return html.Div(f"Backtest engine error: {exc}\n{traceback.format_exc(limit=8)}", style={'color': THEME['warning'], 'whiteSpace': 'pre-wrap', 'fontSize': '11px', 'padding': '10px'}), f"Error at {datetime.now().strftime('%H:%M:%S')}"

        # Inject SELL carry+roll timeseries for chart display
        if isinstance(results, dict) and _cr_sell_for_chart is not None:
            results['carry_roll_sell_ts'] = _cr_sell_for_chart
        if isinstance(results, dict):
            results['spread_type'] = spread_type

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
        portfolio_data = _load_portfolio_snapshot(optimized_data)

        if not portfolio_data:
            return html.P("No portfolio data loaded. Please go to the 'Portfolio' tab and run 'Calculate Score & Allocation' first.", style={'color': 'var(--accent-amber)', 'fontStyle': 'italic', 'fontSize': '12px'})

        try:
            n_assets = len(portfolio_data)
            total_weight = sum(float(item.get('weight', 0) or 0) for item in portfolio_data)
            n_buy  = sum(1 for item in portfolio_data if item.get('direction') == 'BUY')
            n_sell = sum(1 for item in portfolio_data if item.get('direction') == 'SELL')

            style_counts: dict = {}
            for item in portfolio_data:
                style = item.get('style', 'Unknown')
                style_counts[style] = style_counts.get(style, 0) + 1

            sorted_assets = sorted(portfolio_data, key=lambda x: float(x.get('weight', 0) or 0), reverse=True)
            asset_rows = []
            for item in sorted_assets:
                w = float(item.get('weight', 0) or 0)
                _dir = item.get('direction', 'N/A')
                _dir_color = 'var(--accent-green)' if _dir == 'BUY' else ('var(--negative)' if _dir == 'SELL' else 'var(--text-muted)')
                asset_rows.append(html.Div([
                    html.Span('•', style={'color': 'var(--text-muted)', 'marginRight': '6px'}),
                    html.Span(f"{item.get('ID', 'Unknown')} — {w*100:.1f}%", style={'color': 'var(--text-secondary)'}),
                    html.Span(f" ({_dir})", style={'color': _dir_color, 'fontWeight': '600', 'marginLeft': '4px'}),
                ], style={'fontSize': '11px', 'padding': '3px 0', 'fontFamily': 'var(--font-mono, monospace)'}))

            _stat_lbl = {'fontSize': '9px', 'fontWeight': '600', 'letterSpacing': '0.05em',
                         'textTransform': 'uppercase', 'color': 'var(--text-muted)', 'marginBottom': '2px'}

            return html.Div([
                html.Div([
                    html.Div([html.Div("Total Assets", style=_stat_lbl), html.Div(f"{n_assets}", style={'color': 'var(--accent-amber)', 'fontSize': '13px', 'fontWeight': '600'})]),
                    html.Div([html.Div("Weight Sum", style=_stat_lbl), html.Div(f"{total_weight*100:.1f}%", style={'color': 'var(--text-primary)', 'fontSize': '13px'})]),
                    html.Div([html.Div("Direction", style=_stat_lbl), html.Div(f"BUY: {n_buy} / SELL: {n_sell}", style={'color': 'var(--text-primary)', 'fontSize': '12px'})]),
                    html.Div([html.Div("Styles", style=_stat_lbl), html.Div(' | '.join([f"{k}: {v}" for k, v in style_counts.items()]), style={'color': 'var(--text-primary)', 'fontSize': '11px'})]),
                ], style={'display': 'grid', 'gridTemplateColumns': '1fr 1fr', 'gap': '8px', 'marginBottom': '12px'}),
                html.Div("Active Portfolio Assets (Backtest Universe):", style={'fontSize': '11px', 'color': 'var(--text-muted)', 'marginBottom': '6px'}),
                html.Div(asset_rows, style={'maxHeight': '180px', 'overflowY': 'auto', 'border': '1px solid var(--border-default)',
                                            'borderRadius': '4px', 'padding': '6px 10px', 'background': 'var(--surface-input)'}),
            ])
        except Exception as e:
            return html.P(f"Error parsing portfolio data: {str(e)}", style={'color': 'var(--negative)'})

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
         State('bt-port-period', 'value'),
         State('bt-entry-z', 'value'),
         State('bt-exit-z', 'value'),
         State('bt-stop-z', 'value'),
         State('bt-min-hold', 'value')],
        prevent_initial_call=True
    )
    def run_portfolio_backtest(n_clicks, optimized_data, capital, txn_cost, period,
                               entry_z, exit_z, stop_z, min_hold):
        if not n_clicks:
            return html.Div(), ""

        optimized_data = _load_portfolio_snapshot(optimized_data)

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
                is_yield_based = spread_type in YIELD_BASED_SPREAD_TYPES
                ts_bt = -ts if is_yield_based else ts

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

                # YTM-based spreads: flip stored carry to match the price-series
                # inversion above (LONG = expecting the spread to fall/narrow).
                if is_yield_based:
                    if _cr_ts is not None:
                        _cr_ts = -_cr_ts
                    _cr_bp = -_cr_bp

                dur = _get_duration_mult(asset, spread_type)
                _bc_long, _bc_short = _get_borrow_cost_annual_bp(spread_type, asset)

                _entry_z  = float(entry_z)  if entry_z  is not None else 2.0
                _exit_z   = float(exit_z)   if exit_z   is not None else 0.5
                _stop_z   = float(stop_z)   if stop_z   is not None else 4.0
                _min_hold = int(min_hold) if min_hold is not None else 7

                try:
                    if run_trend:
                        res = run_trend_backtest_dc(
                            spread_ts=ts_bt, carry_roll_ts=_cr_ts,
                            carry_roll_bp=_cr_bp, duration_mult=dur,
                            allow_short=True,
                            min_hold=_min_hold,
                        )
                    else:
                        res = run_spread_backtest(
                            spread_ts=ts_bt, carry_roll_ts=_cr_ts,
                            carry_roll_bp=_cr_bp, duration_mult=dur,
                            borrow_cost_long_bp=_bc_long,
                            borrow_cost_short_bp=_bc_short,
                            spread_type=spread_type,
                            entry_z=_entry_z,
                            exit_z=_exit_z,
                            stop_z=_stop_z,
                            min_hold=_min_hold,
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
