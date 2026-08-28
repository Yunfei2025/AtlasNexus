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
from ..backtest import (
    run_spread_backtest, run_trend_backtest_dc,
    build_backtest_results_display,
    build_monthly_style_schedule, canonical_style, run_monthly_style_backtest,
)


def _default_style_for_spread(spread_type: str) -> str:
    """Return category default style in canonical form: mr or trend."""
    for _, info in SPREAD_CATEGORIES.items():
        if spread_type in info.get('types', []):
            return 'trend' if info.get('style', 'MeanReversion') == 'Trend' else 'mr'
    return 'mr'


def _build_monthly_style_schedule(
    spread_ts: pd.Series,
    spread_type: str,
    uncertain_policy: str = 'carry_forward',
) -> tuple[pd.DataFrame, pd.Series]:
    """Compute point-in-time monthly style assignment and a daily style strip."""
    schedule, month_to_style = build_monthly_style_schedule(
        spread_ts,
        _default_style_for_spread(spread_type),
        uncertain_policy=uncertain_policy,
    )
    if schedule.empty:
        return schedule, pd.Series(dtype=object)

    s = pd.to_numeric(spread_ts, errors='coerce').dropna()
    if not isinstance(s.index, pd.DatetimeIndex):
        s.index = pd.to_datetime(s.index, errors='coerce')
    if getattr(s.index, 'tz', None) is not None:
        s.index = s.index.tz_localize(None)
    s = s[~s.index.isna()].sort_index()

    styles = [month_to_style.get(p, 'skip') for p in s.index.to_period('M')]
    regime_strip = pd.Series(styles, index=s.index, dtype=object).map(
        {'trend': 'trending', 'mr': 'mean_reverting'}
    ).fillna('uncertain')

    return schedule, regime_strip


def _apply_monthly_style_schedule(monthly_schedule, default_style: str = 'mr',
                                  uncertain_style: str = 'manual'):
    """Return the tradeable ``{Period: style}`` map from an audit schedule.

    ``uncertain_style`` controls what a month with no tradeable classification
    becomes: a canonical style name (``mr``/``trend``/``trending``/``momentum``…)
    overrides it, ``manual`` keeps whatever the schedule already assigned, and
    ``skip`` leaves the month untradeable.
    """
    if not isinstance(monthly_schedule, pd.DataFrame) or monthly_schedule.empty:
        return {}, pd.DataFrame()

    schedule = monthly_schedule.copy()
    if 'assigned_style' not in schedule.columns:
        schedule['assigned_style'] = default_style
    schedule['regime_key'] = schedule.get('regime', '').astype(str).str.lower()

    override = canonical_style(uncertain_style)
    resolved = []
    for _, row in schedule.iterrows():
        style = canonical_style(row.get('assigned_style'))
        regime = canonical_style(row.get('regime'))
        if regime == 'skip' and override != 'skip':
            # Regime was uncertain/insufficient: apply the caller's override.
            style = override
        if style == 'skip' and str(uncertain_style).strip().lower() == 'manual':
            style = canonical_style(default_style)
        resolved.append(style)

    schedule['assigned_style'] = resolved

    month_to_style = {
        pd.Timestamp(row['review_date']).to_period('M'): row['assigned_style']
        for _, row in schedule.iterrows()
        if row['assigned_style'] in ('mr', 'trend')
    }
    return month_to_style, schedule


def _allow_short_enabled(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value == 'allow'
    if isinstance(value, (list, tuple, set)):
        return 'allow' in value
    return False


def _run_monthly_style_switch_backtest(
    ts: pd.Series,
    spread_type: str,
    entry_z: float,
    exit_z: float,
    stop_z: float,
    min_hold: int,
    theta: float,
    vol_window: int,
    trailing_mult: float,
    carry_roll_ts: Optional[pd.Series],
    carry_roll_bp: float,
    duration_mult: float,
    borrow_cost_long_bp: float,
    borrow_cost_short_bp: float,
    allow_short: bool,
    carry_roll_sell_ts: Optional[pd.Series],
    mom_window: int = 20,
    uncertain_policy: str = 'carry_forward',
    ou_mean: Optional[float] = None,
):
    """Run one continuous backtest whose entry style is routed by the monthly review.

    The monthly regime classification decides *which* engine may open a trade in a
    given month; the position itself is carried across month boundaries by
    :func:`run_monthly_style_backtest`, so signals keep their full warm-up and a
    trade opened in one month can run until its own exit fires.

    ``ou_mean``: static ADF/OU-calibrated long-run mean for this instrument
    (``StatInfo['mean']``, only passed when ``StatInfo['stationary']=='YES'``),
    forwarded as the MR fair-value anchor so the backtest's mean-reversion
    signal uses the same mean the live Scan screener's ADF test already
    validated, instead of an independently-computed rolling(120) mean.
    """
    schedule, month_to_style = build_monthly_style_schedule(
        ts, _default_style_for_spread(spread_type), uncertain_policy=uncertain_policy,
    )
    if schedule.empty:
        return {'error': 'No valid datetime observations for monthly style backtest.'}

    results = run_monthly_style_backtest(
        ts,
        month_to_style,
        entry_z=entry_z if entry_z is not None else 2.0,
        exit_z=exit_z if exit_z is not None else 0.5,
        stop_z=stop_z if stop_z is not None else 4.0,
        min_hold=int(min_hold) if min_hold is not None else 7,
        theta_z=float(theta) if theta is not None else 1.25,
        mom_window=int(mom_window) if mom_window is not None else 20,
        vol_window=int(vol_window) if vol_window is not None else 60,
        trailing_mult=float(trailing_mult) if trailing_mult is not None else 1.5,
        allow_short=_allow_short_enabled(allow_short),
        carry_roll_ts=carry_roll_ts,
        carry_roll_bp=carry_roll_bp,
        duration_mult=duration_mult,
        borrow_cost_long_bp=borrow_cost_long_bp,
        borrow_cost_short_bp=borrow_cost_short_bp,
        spread_type=spread_type,
        carry_roll_sell_ts=carry_roll_sell_ts,
        ou_mean=ou_mean,
    )

    if isinstance(results, dict) and 'error' not in results:
        results['monthly_style_schedule'] = schedule
        style_ts = results.get('style_ts')
        if isinstance(style_ts, pd.Series) and not style_ts.empty:
            results['monthly_regime_ts'] = style_ts.map(
                {'trend': 'trending', 'mr': 'mean_reverting'}
            ).fillna('uncertain')
        else:
            results['monthly_regime_ts'] = pd.Series(dtype=object)
        results['style_mode'] = 'auto_monthly'
        results['style_effective'] = 'auto_monthly'
        results['uncertain_policy'] = uncertain_policy
    return results


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
    # BACKTEST: Display the current monthly regime for the selected instrument
    # -------------------------------------------------------------------------
    @app.callback(
        Output('bt-regime-badge', 'children'),
        [Input('bt-spread-type', 'value'),
         Input('bt-instrument', 'value')],
    )
    def update_monthly_regime_badge(spread_type, instrument):
        if not instrument or not spread_type:
            return ""

        try:
            from curves.calibration.regime import DEFAULT_REGIME_WINDOW, compute_regime_features
            regime = 'uncertain'
            score = 0.0
            regime_source = 'time-series'

            ts = None
            if isinstance(instrument, str) and instrument.startswith(MACRO_PREFIX):
                macro_name = instrument[len(MACRO_PREFIX):]
                ts = load_macro_series(macro_name)
            else:
                spread_df = load_spread_timeseries(spread_type)
                if spread_df is not None and instrument in spread_df.columns:
                    ts = spread_df[instrument].dropna()

            if ts is None or len(ts) < DEFAULT_REGIME_WINDOW + 5:
                return html.Span("Current month: insufficient history — no trade.", style={'color': THEME['warning'], 'fontSize': '12px'})

            regime_info = compute_regime_features(ts, window=DEFAULT_REGIME_WINDOW)
            regime = regime_info.get('regime', 'uncertain')
            score = regime_info.get('regime_score', 0.0)

            if np.isnan(score):
                score = 0.0

            regime_color = {'mean_reverting': THEME['success'], 'trending': THEME['accent'], 'uncertain': THEME['warning']}.get(regime, THEME['text_sub'])

            if regime == 'uncertain':
                badge_extra = html.Span(
                    f"  (score: {score:+.2f}; no trade)",
                    style={'color': THEME['warning'], 'fontSize': '11px'},
                )
            else:
                badge_extra = html.Span(
                    f"  (score: {score:+.2f}, source: {regime_source})",
                    style={'color': THEME['text_sub'], 'fontSize': '11px'},
                )
            badge = html.Div([
                html.Span("Current month: ", style={'color': THEME['text_sub'], 'fontSize': '12px'}),
                html.Span(regime.upper().replace('_', '-'), style={'color': regime_color, 'fontWeight': 'bold', 'fontSize': '13px'}),
                badge_extra,
            ])
            return badge

        except Exception as exc:
            return html.Span(f"Regime detection error: {exc}", style={'color': THEME['warning'], 'fontSize': '11px'})

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
            return 2.5, 0.25, 5.0, 10, 1.50, 30, 90, 2.0

        return 2.0, 0.5, 4.0, 7, 1.25, 20, 60, 1.5

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
        n_clicks, spread_type, instrument, entry_z, exit_z, stop_z, period, theta,
        mom_window, vol_window, trailing_mult, carry_buffer, allow_short, min_hold
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
        ou_mean: Optional[float] = None
        is_stationary = False
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
                        # ADF-confirmed stationary → use the OU long-run mean
                        # (StatInfo['mean']) as the MR fair-value anchor instead
                        # of a plain rolling(120) mean, so the backtest's entry
                        # signal is consistent with the same stationarity test
                        # that qualifies this spread for mean-reversion trading
                        # in the live Scan screener.
                        is_stationary = str(row.get('stationary', '')).strip().upper() == 'YES'
                        if is_stationary and 'mean' in row.index:
                            _m_val = row.get('mean')
                            if _m_val is not None and np.isfinite(float(_m_val)):
                                ou_mean = float(_m_val)
            except Exception:
                carry_roll_ts_instrument = None
                carry_roll_bp = 0.0
                ou_mean = None

            # YTM-based spreads: stored carry/snapshot carry is computed on the raw
            # spread value. Flip so LONG = expecting the spread to fall/narrow
            # (economically long the higher-yielding leg's price).
            if is_yield_based:
                if carry_roll_ts_instrument is not None:
                    carry_roll_ts_instrument = -carry_roll_ts_instrument
                carry_roll_bp = -carry_roll_bp
                if ou_mean is not None:
                    ou_mean = -ou_mean

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

            results = _run_monthly_style_switch_backtest(
                ts=-ts if _negate_ts else ts,
                spread_type=spread_type,
                entry_z=entry_z or 2.0,
                exit_z=exit_z or 0.5,
                stop_z=stop_z or 4.0,
                min_hold=int(min_hold) if min_hold is not None else 7,
                theta=float(theta) if theta is not None else 1.25,
                vol_window=int(vol_window) if vol_window is not None else 60,
                trailing_mult=float(trailing_mult) if trailing_mult is not None else 1.5,
                carry_roll_ts=carry_roll_ts_instrument,
                carry_roll_bp=carry_roll_bp,
                duration_mult=duration_mult,
                borrow_cost_long_bp=bc_long,
                borrow_cost_short_bp=bc_short,
                allow_short=_allow_short_enabled(allow_short),
                carry_roll_sell_ts=_cr_sell_for_backtest,
                mom_window=int(mom_window) if mom_window is not None else 20,
                ou_mean=ou_mean,
            )

            # For YTM-based spreads: restore original display signs after internal inversion.
            if _negate_ts and isinstance(results, dict):
                results['spread_ts'] = ts
                for key in ('zscore_ts', 'composite_signal_ts', 'trend_state_ts', 'norm_mom_ts'):
                    series = results.get(key)
                    if isinstance(series, pd.Series):
                        results[key] = -series
                # NOTE: direction labels ('LONG'/'SHORT') from both engines are already
                # correct after the sign inversion above — the engines see -ts, so
                # their internal LONG (position=+1) means "expects the inverted series
                # to rise", i.e. "expects the raw yield-based spread to fall/narrow",
                # which is exactly the documented LONG convention for yield-based
                # spreads. No further relabeling is needed (previously the trend path
                # incorrectly re-flipped LONG/SHORT here, mislabeling every trend
                # signal for TenorSpread/SwapSpread/etc.).
                for trade in results.get('trades', []):
                    for k in ('entry_price', 'exit_price', 'entry_z', 'exit_z'):
                        if k in trade:
                            trade[k] = -trade[k]
                open_trade = results.get('open_trade')
                if isinstance(open_trade, dict):
                    for k in ('entry_price', 'current_price', 'entry_z'):
                        if k in open_trade and open_trade[k] is not None:
                            open_trade[k] = -open_trade[k]
                _tdf = results.get('trades_df')
                if isinstance(_tdf, pd.DataFrame) and not _tdf.empty:
                    for k in ('entry_price', 'exit_price', 'entry_z', 'exit_z'):
                        if k in _tdf.columns:
                            results['trades_df'][k] = -_tdf[k]
        except Exception as exc:
            import traceback
            return html.Div(f"Backtest engine error: {exc}\n{traceback.format_exc(limit=8)}", style={'color': THEME['warning'], 'whiteSpace': 'pre-wrap', 'fontSize': '11px', 'padding': '10px'}), f"Error at {datetime.now().strftime('%H:%M:%S')}"

        # Inject SELL carry+roll timeseries for chart display
        if isinstance(results, dict) and _cr_sell_for_chart is not None:
            results['carry_roll_sell_ts'] = _cr_sell_for_chart
        if isinstance(results, dict):
            # The style schedule is produced inside the runner from the same
            # (sign-normalised) series the engines see — do not recompute it here
            # from the raw series, which would classify yield-based spreads on the
            # opposite orientation.
            results['spread_type'] = spread_type

        n_reviews = 0
        n_tradeable = 0
        _sched = results.get('monthly_style_schedule') if isinstance(results, dict) else None
        if isinstance(_sched, pd.DataFrame) and not _sched.empty:
            n_reviews = int(len(_sched))
            n_tradeable = int(_sched['assigned_style'].isin(['mr', 'trend']).sum())

        status = (
            f"Backtest completed at {datetime.now().strftime('%H:%M:%S')} "
            f"[monthly regime routing; {n_tradeable}/{n_reviews} months tradeable]"
        )
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
                _ou_mean: Optional[float] = None
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
                        # Same ADF-gated OU-mean anchor as the individual backtest
                        # path (see engine_mr.run_spread_backtest's ou_mean docstring)
                        # — only used for MR-style assets below.
                        if str(_row.get('stationary', '')).strip().upper() == 'YES' and 'mean' in _row.index:
                            _mv = _row.get('mean')
                            if _mv is not None and np.isfinite(float(_mv)):
                                _ou_mean = float(_mv)
                except Exception:
                    pass

                # YTM-based spreads: flip stored carry to match the price-series
                # inversion above (LONG = expecting the spread to fall/narrow).
                if is_yield_based:
                    if _cr_ts is not None:
                        _cr_ts = -_cr_ts
                    _cr_bp = -_cr_bp
                    if _ou_mean is not None:
                        _ou_mean = -_ou_mean

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
                            spread_type=spread_type,
                            theta=1.50 if spread_type == 'TenorSpread' else 1.25,
                            vol_window=90 if spread_type == 'TenorSpread' else 60,
                            adaptive_theta=True,
                            theta_min_mult=0.5,
                            theta_max_mult=2.5,
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
                            ou_mean=_ou_mean,
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
            chart = dcc.Graph(figure=fig, config={'displayModeBar': False})

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
