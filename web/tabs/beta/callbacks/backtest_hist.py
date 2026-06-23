# -*- coding: utf-8 -*-
"""Historical allocation backtest callbacks (Backtest tab: factor pool display,
date info, and historical correlation-based analysis chart)."""

from __future__ import annotations

from dash import html, dash_table
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import os
import traceback
from dateutil.relativedelta import relativedelta

from multiasset.data import load_raw_market_data, calculate_daily_returns_series, get_asset_type
from multiasset.main import create_custom_portfolio
from multiasset.risk_loader import RiskFactorLoader
from multiasset.factor_optimizer import FactorRiskParityOptimizer
from multiasset.factor_backtest import load_factor_backtest, compute_portfolio_metrics
from multiasset.config import RiskModelConfig
from multiasset.backtest_cache import (
    RPCacheParams, FactorTiltCacheParams,
    load_rp, save_rp, load_factor_tilt, save_factor_tilt,
    scalar_to_coeff, rp_hash,
)
from settings.paths import DIR_INPUT

from ..data import THEME, SELECTED_FACTOR_POOL, get_assets_from_factors, FACTOR_TO_ASSET_MAP


def register_backtest_hist_callbacks(app):
    """Register historical-allocation backtest callbacks."""

    # 4.3 Toggle visibility between Preset Lookback and Custom Period
    @app.callback(
        [Output('backtest-lookback-container', 'style'),
         Output('backtest-period-container', 'style')],
        [Input('backtest-date-mode', 'value')],
        prevent_initial_call=False
    )
    def toggle_date_mode_visibility(date_mode):
        """Show/hide lookback dropdown or date range picker based on date mode."""
        print(f"[Backtest Date Mode] Switched to: {date_mode}")
        if date_mode == 'preset':
            print("  → Showing Preset Lookback dropdown, hiding Custom Period picker")
            return (
                {'marginRight': '25px', 'display': 'block'},  # lookback container visible
                {'marginRight': '25px', 'display': 'none'},   # period container hidden
            )
        else:  # custom
            print("  → Showing Custom Period picker, hiding Preset Lookback dropdown")
            return (
                {'marginRight': '25px', 'display': 'none'},   # lookback container hidden
                {'marginRight': '25px', 'display': 'block'},  # period container visible
            )

    # 4.4 Update date range based on lookback preset dropdown
    @app.callback(
        [Output('history-date-range', 'start_date'),
         Output('history-date-range', 'end_date')],
        [Input('backtest-lookback-preset', 'value')],
        prevent_initial_call=True
    )
    def update_date_range_from_lookback(lookback_preset):
        """Update the date range based on the selected lookback period."""
        from datetime import datetime, timedelta

        end_date = datetime.now().date()

        if lookback_preset == '1Y':
            start_date = end_date - relativedelta(years=1)
        elif lookback_preset == '2Y':
            start_date = end_date - relativedelta(years=2)
        elif lookback_preset == '5Y':
            start_date = end_date - relativedelta(years=5)
        elif lookback_preset == '10Y':
            start_date = end_date - relativedelta(years=10)
        else:
            start_date = end_date - relativedelta(years=2)  # default to 2Y

        return start_date, end_date

    # 4.5 Backtest Factor Pool Display and Min Date Info
    @app.callback(
        [Output('backtest-factor-pool-display', 'children'),
         Output('backtest-min-date-info', 'children')],
        [Input('run-history-button', 'n_clicks')],
        [State('backtest-corr-lookback', 'value')],
        prevent_initial_call=False
    )
    def update_backtest_factor_pool_display(n_clicks, corr_lookback):
        """Display the current factor pool from Factor tab and calculate minimum supported date."""
        all_factors = []
        all_factors.extend(SELECTED_FACTOR_POOL.get('ir_factors', []))
        all_factors.extend(SELECTED_FACTOR_POOL.get('sp_factors', []))
        all_factors.extend(SELECTED_FACTOR_POOL.get('fx_factors', []))
        all_factors.extend(SELECTED_FACTOR_POOL.get('cmd_factors', []))
        
        if not all_factors:
            return ("⚠️ No factors selected. Go to Factor tab to select factors.",
                    "ℹ️ Select factors first to see minimum supported date.")
        
        # Calculate minimum supported date based on selected factors
        try:
            loader = RiskFactorLoader(DIR_INPUT)
            risk_factors = loader.load_risk_factors(use_cache=True)
            risk_factors.index = pd.to_datetime(risk_factors.index)
            
            available_factors = [f for f in all_factors if f in risk_factors.columns]
            if len(available_factors) >= 2:
                # Find the latest start date among selected factors
                factor_data = risk_factors[available_factors].dropna(how='any')
                factor_data_start = factor_data.index.min()
                factor_data_end = factor_data.index.max()
                
                # Determine lookback period
                if corr_lookback == '6M':
                    lookback_delta = relativedelta(months=6)
                elif corr_lookback == '1Y':
                    lookback_delta = relativedelta(years=1)
                else:
                    lookback_delta = relativedelta(months=3)
                
                earliest_valid_date = factor_data_start + lookback_delta
                
                # Find the limiting factor (the one with latest start date)
                latest_factor = None
                latest_start = None
                for f in available_factors:
                    f_start = risk_factors[f].dropna().index.min()
                    if latest_start is None or f_start > latest_start:
                        latest_start = f_start
                        latest_factor = f
                
                min_date_info = (f"ℹ️ Min supported date: {earliest_valid_date.strftime('%Y-%m-%d')} "
                               f"(Data: {factor_data_start.strftime('%Y-%m-%d')} ~ {factor_data_end.strftime('%Y-%m-%d')}, "
                               f"limited by {latest_factor})")
            else:
                min_date_info = "⚠️ Not enough factors available in data."
        except Exception as e:
            min_date_info = f"⚠️ Error calculating date range: {str(e)}"
        
        factor_display = f"{len(all_factors)} factors: {', '.join(all_factors)}"
        return factor_display, min_date_info

    # 5. Historical Analysis (Backtest Tab) - Correlation-Based Strategy
    @app.callback(
        [Output('historical-allocation-chart', 'figure'),
         Output('pnl-attribution-chart', 'figure'),
         Output('performance-metrics-container', 'children'),
         Output('asset-changes-container', 'children')],
        [Input('run-history-button', 'n_clicks')],
        [State('backtest-capital-input', 'value'),
         State('backtest-capital-unit', 'value'),
         State('history-date-range', 'start_date'),
         State('history-date-range', 'end_date'),
         State('backtest-corr-lookback', 'value'),
         State('backtest-top-pairs', 'value'),
         State('backtest-alloc-mode', 'value')]
    )
    def update_historical_allocation(n_clicks, total_capital, capital_unit, start_date, end_date, corr_lookback, top_pairs, alloc_mode):
        """
        Correlation-Based Historical Allocation Strategy:
        1. At each month start, run correlation analysis on risk factors
        2. Select assets with lowest correlations for diversification
        3. Run Risk Parity (1/Vol) allocation on the selected assets
        4. Track asset pool changes over time
        """
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="Click 'Run Historical Analysis' to start",
            template=THEME['chart_template'],
            paper_bgcolor=THEME['bg_main'],
            plot_bgcolor=THEME['bg_main'],
            font={'color': THEME['text_main']}
        )
        
        if n_clicks == 0:
            return empty_fig, empty_fig, None, None

        # Refresh factor-rates.pkl incrementally before backtesting so that
        # any data gap since the last "Predict" run is filled automatically.
        try:
            from multiasset.factor_backtest import update_factor_rates
            _, n_new = update_factor_rates(DIR_INPUT)
            if n_new:
                print(f"Portfolio backtest: factor-rates.pkl +{n_new} new day(s) appended")
        except Exception as _ufr_exc:
            print(f"Warning: factor-rates incremental update failed: {_ufr_exc}")

        alloc_mode = alloc_mode or 'risk_parity'

        # ── Factor Model Scaling: load saved per-factor signal series ──────────
        # When factor scaling is requested, each asset's risk-parity weight is
        # tilted by the FactorModel signal (`position` in ~[-1, 1]) of the
        # factor(s) it maps from, as of each rebalance date. Signals come from
        # the walk-forward factor backtest persisted in factor-backtest.pkl.
        factor_signal_series = {}
        if alloc_mode == 'factor_scaling':
            try:
                fm_results = load_factor_backtest(DIR_INPUT).get('FactorModel', {})
                for f_code, f_df in fm_results.items():
                    if 'position' in f_df.columns:
                        s = f_df['position'].dropna()
                        if not isinstance(s.index, pd.DatetimeIndex):
                            s.index = pd.to_datetime(s.index)
                        factor_signal_series[f_code] = s.sort_index()
            except Exception as e:
                print(f"  Warning: Could not load factor model signals: {e}")

            if not factor_signal_series:
                unavail_fig = go.Figure()
                unavail_fig.update_layout(
                    title="Factor Model Scaling — no signals available",
                    annotations=[{
                        'text': 'No FactorModel signals found in factor-backtest.pkl.<br>'
                                'Run the Individual Factors backtest first to generate signals.',
                        'xref': 'paper', 'yref': 'paper', 'x': 0.5, 'y': 0.5,
                        'showarrow': False, 'font': {'size': 14, 'color': THEME['warning']},
                        'align': 'center',
                    }],
                    template=THEME['chart_template'],
                    paper_bgcolor=THEME['bg_main'],
                    plot_bgcolor=THEME['bg_main'],
                    font={'color': THEME['text_main']},
                )
                return unavail_fig, unavail_fig, None, html.Div(
                    "Factor Model Scaling needs factor signals — run the Individual Factors "
                    "backtest to populate factor-backtest.pkl, then retry.",
                    style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'},
                )

        def _factor_signal_asof(factor_code, asof_date):
            """Most-recent FactorModel position for `factor_code` on/before `asof_date`."""
            s = factor_signal_series.get(factor_code)
            if s is None:
                return None
            s = s.loc[s.index <= asof_date]
            return float(s.iloc[-1]) if len(s) else None

        try:
            # Parse dates
            start_date = pd.to_datetime(start_date) if start_date else None
            end_date = pd.to_datetime(end_date) if end_date else None
            top_pairs = int(top_pairs) if top_pairs else 10
            
            # Load risk factor data
            loader = RiskFactorLoader(DIR_INPUT)
            risk_factors = loader.load_risk_factors(use_cache=True)
            risk_factors.index = pd.to_datetime(risk_factors.index)
            market_data = load_raw_market_data()
            
            if risk_factors.empty:
                err_fig = go.Figure().update_layout(title="No risk factor data available", template=THEME['chart_template'])
                return err_fig, err_fig, None, html.Div("No data", style={'color': THEME['warning']})
            
            # Get selected factors from global factor pool (set in Factor tab)
            selected_factors = []
            selected_factors.extend(SELECTED_FACTOR_POOL.get('ir_factors', []))
            selected_factors.extend(SELECTED_FACTOR_POOL.get('sp_factors', []))
            selected_factors.extend(SELECTED_FACTOR_POOL.get('fx_factors', []))
            selected_factors.extend(SELECTED_FACTOR_POOL.get('cmd_factors', []))
            
            if len(selected_factors) < 2:
                err_fig = go.Figure().update_layout(
                    title="⚠️ Please select at least 2 factors in the Factor tab first",
                    template=THEME['chart_template'],
                    paper_bgcolor=THEME['bg_main'],
                    plot_bgcolor=THEME['bg_main'],
                    font={'color': THEME['text_main']}
                )
                return err_fig, err_fig, None, html.Div(
                    "Go to Factor tab and select factors for the analysis pool.", 
                    style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'}
                )
            
            print(f"Using factor pool from Factor tab: {selected_factors}")
            
            # Filter risk_factors to only include selected factors that exist in data
            available_factors = [f for f in selected_factors if f in risk_factors.columns]
            if len(available_factors) < 2:
                err_fig = go.Figure().update_layout(
                    title=f"⚠️ Only {len(available_factors)} of selected factors found in data",
                    template=THEME['chart_template'],
                    paper_bgcolor=THEME['bg_main'],
                    plot_bgcolor=THEME['bg_main'],
                    font={'color': THEME['text_main']}
                )
                missing = [f for f in selected_factors if f not in risk_factors.columns]
                return err_fig, err_fig, None, html.Div(
                    f"Missing factors: {missing}", 
                    style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'}
                )
            
            # Get the actual data range for selected factors
            # Use dropna(how='any') to ensure ALL selected factors have data
            selected_factor_data = risk_factors[available_factors].dropna(how='any')
            factor_data_start = selected_factor_data.index.min()
            factor_data_end = selected_factor_data.index.max()
            
            # Find which factor limits the start date (latest starting factor)
            limiting_factors = []
            for f in available_factors:
                f_start = risk_factors[f].dropna().index.min()
                if f_start is not None and f_start >= factor_data_start - pd.Timedelta(days=30):
                    limiting_factors.append((f, f_start.date()))
            limiting_factors.sort(key=lambda x: x[1], reverse=True)
            
            print(f"Available factors in data: {available_factors}")
            print(f"Selected factor data range (ALL factors): {factor_data_start.date()} to {factor_data_end.date()}")
            if limiting_factors:
                print(f"Limiting factors (latest start): {limiting_factors[:3]}")
            
            # Set date range
            if not end_date:
                end_date = factor_data_end
            if not start_date:
                start_date = end_date - relativedelta(years=1)
            
            # Determine correlation lookback period and factor vol lookback
            if corr_lookback == '3M':
                corr_lookback_delta = relativedelta(months=3)
                vol_lookback_months = 3
            elif corr_lookback == '6M':
                corr_lookback_delta = relativedelta(months=6)
                vol_lookback_months = 6
            elif corr_lookback == '1Y':
                corr_lookback_delta = relativedelta(years=1)
                vol_lookback_months = 12
            else:
                corr_lookback_delta = relativedelta(months=3)
                vol_lookback_months = 3
            
            # Calculate earliest valid rebalance date based on selected factor data
            earliest_valid_date = factor_data_start + corr_lookback_delta

            # Auto-adjust start date if it's before the minimum supported date
            if start_date < earliest_valid_date:
                print(f"⚠️  Start date {start_date.date()} is before earliest valid date {earliest_valid_date.date()}")
                print(f"   Using earliest valid date: {earliest_valid_date.date()}")
                start_date = earliest_valid_date

            # Generate rebalance dates (beginning of each month) - starting from earliest valid date
            rebalance_dates = []
            current_date = start_date.replace(day=1)
            while current_date <= end_date:
                rebalance_dates.append(current_date)
                current_date += relativedelta(months=1)
            
            if not rebalance_dates:
                err_fig = go.Figure().update_layout(title="Not enough historical data for the selected period", template=THEME['chart_template'])
                return err_fig, err_fig, None, html.Div("Insufficient data", style={'color': THEME['warning']})
            
            # Convert capital
            total_capital_value = float(total_capital) if total_capital else 100
            if capital_unit == 'billion':
                total_capital_value *= 1_000
            total_capital_cny = total_capital_value * 1_000_000  # Convert to CNY
            
            # Track allocations and asset changes
            history_data = []
            allocations_by_date = {}
            asset_pools_by_date = {}  # Track asset pool changes
            all_assets_ever = set()

            print(f"\n{'='*60}")
            print(f"Running Correlation-Based Backtest: {start_date.date()} to {end_date.date()}")
            print(f"Rebalance dates: {len(rebalance_dates)}")
            print(f"First rebalance: {rebalance_dates[0].date() if rebalance_dates else 'N/A'}")
            print(f"Last rebalance: {rebalance_dates[-1].date() if rebalance_dates else 'N/A'}")
            print(f"{'='*60}")

            # ── Step A: pure risk-parity (RP) weights — cached, independent of
            #    factor-scaling selection. Adding/removing a factor from the
            #    scaling pool never forces this to recompute.
            rp_params = RPCacheParams(
                rebalance_dates=tuple(sorted(d.strftime('%Y-%m-%d') for d in rebalance_dates)),
                corr_lookback=corr_lookback or '3M',
                top_pairs=top_pairs,
                factor_pool=tuple(sorted(available_factors)),
                factor_model_lookback_years=1.0,
                ewma_lambda=RiskModelConfig.FACTOR_VOL_EWMA_LAMBDA,
                use_vol_sqrt_budgets=True,
                use_dv01_shape=True,
                bounds_version="RiskModelConfig.v1",
            )
            rp_h = None
            cached_rp = load_rp(DIR_INPUT, rp_params)
            if cached_rp is not None:
                rp_weights_by_date = cached_rp['weights_by_date']
                asset_pools_by_date = cached_rp['asset_pools_by_date']
                screened_factors_by_date = cached_rp['screened_factors_by_date']
                rp_h = rp_hash(rp_params)
                print(f"  RP base: cache hit ({rp_h})")
            else:
                rp_weights_by_date = {}  # rebalance_date -> {asset_name: weight}
                asset_pools_by_date = {}
                screened_factors_by_date = {}  # rebalance_date -> [factor_code, ...]

                # Cache of portfolio+optimizer keyed by frozenset of asset names.
                # Re-using objects avoids redundant construction for recurring asset sets
                # while still allowing the asset set to change month-to-month.
                _optimizer_cache: dict = {}

                for rebalance_date in rebalance_dates:
                    # --- Step 1: Rolling correlation screen on the lookback window ---
                    corr_end = rebalance_date
                    corr_start = rebalance_date - corr_lookback_delta

                    df_subset = risk_factors.loc[corr_start:corr_end,
                                                 [f for f in available_factors if f in risk_factors.columns]]
                    if df_subset.empty or len(df_subset) < 20:
                        print(f"  {rebalance_date.date()}: Skipped (insufficient data)")
                        continue

                    df_changes = df_subset.diff().dropna()
                    if df_changes.empty:
                        continue

                    corr_matrix = df_changes.corr()

                    # Find the `top_pairs` lowest-correlation factor pairs in this window
                    mask = np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
                    corr_stacked = corr_matrix.where(mask).stack().reset_index()
                    corr_stacked.columns = ['Factor A', 'Factor B', 'Correlation']
                    corr_stacked['AbsCorrelation'] = corr_stacked['Correlation'].abs()
                    bottom_pairs = corr_stacked.sort_values('AbsCorrelation').head(top_pairs)

                    low_corr_factors = (
                        set(bottom_pairs['Factor A']) | set(bottom_pairs['Factor B'])
                    )
                    low_corr_factors_list = sorted(low_corr_factors)

                    # --- Step 2: Map screened factors → assets ---
                    selected_assets = get_assets_from_factors(low_corr_factors_list)

                    if not selected_assets:
                        print(f"  {rebalance_date.date()}: Skipped (no mappable assets)")
                        continue

                    selected_asset_names = [a['name'] for a in selected_assets]

                    # --- Step 3: Optimise with time-varying EWMA covariance ---
                    # Re-use a cached portfolio/optimizer when the asset set is the same
                    # as a previous month; the rolling vol window still changes because
                    # fit_and_calculate() slices by rebalance_date.
                    _key = frozenset(selected_asset_names)
                    if _key not in _optimizer_cache:
                        try:
                            _port = create_custom_portfolio(selected_asset_names, use_deterministic=True)
                            _opt  = FactorRiskParityOptimizer(
                                portfolio=_port,
                                input_dir=str(DIR_INPUT),
                                factor_model_lookback_years=1.0,
                                vol_lookback_months=vol_lookback_months,
                                ewma_lambda=RiskModelConfig.FACTOR_VOL_EWMA_LAMBDA,
                            )
                            _optimizer_cache[_key] = _opt
                        except Exception as e:
                            print(f"  {rebalance_date.date()}: Portfolio creation failed: {e}")
                            continue

                    try:
                        weights_series, _ = _optimizer_cache[_key].fit_and_calculate(
                            pd.Timestamp(rebalance_date),
                            use_vol_sqrt_budgets=True,
                            # use_dv01_shape=True (default): two-stage — ERC across factors
                            # (stage 1, rolling covariance) then DV01 split within each
                            # factor group (stage 2, analytic inverse-duration).
                        )
                        weights = weights_series.to_dict()
                    except Exception as e:
                        print(f"  {rebalance_date.date()}: Factor risk optimization failed: {e}")
                        continue

                    if not weights or sum(weights.values()) == 0:
                        print(f"  {rebalance_date.date()}: Skipped (invalid weights)")
                        continue

                    # Filter out negligible weights (floating point precision artifacts)
                    weights = {k: v for k, v in weights.items() if abs(v) >= 1e-6}

                    # Renormalize weights after filtering
                    weight_sum = sum(weights.values())
                    if weight_sum > 0:
                        weights = {k: v / weight_sum for k, v in weights.items()}
                    else:
                        continue

                    rp_weights_by_date[rebalance_date] = weights
                    filtered_assets = [a for a in selected_assets if a['name'] in weights]
                    asset_pools_by_date[rebalance_date] = filtered_assets
                    screened_factors_by_date[rebalance_date] = low_corr_factors_list

                    print(f"  {rebalance_date.date()}: {len(selected_asset_names)} assets, {len(low_corr_factors_list)} screened factors (of {len(available_factors)} total)")

                rp_h = save_rp(DIR_INPUT, rp_params, rp_weights_by_date, asset_pools_by_date, screened_factors_by_date)
                print(f"  RP base: computed and cached ({rp_h})")

            # ── Step B: factor-scaling tilts — cached per factor, each keyed on
            #    the RP base it was tilted from. Adding factor N+1 only computes
            #    factor N+1's tilt; previously-cached factors are reused as-is.
            factor_tilts_by_factor: dict = {}
            if alloc_mode == 'factor_scaling':
                try:
                    _signal_pkl_mtime = os.path.getmtime(os.path.join(str(DIR_INPUT), 'factor-backtest.pkl'))
                except OSError:
                    _signal_pkl_mtime = 0.0

                for f_code in sorted(factor_signal_series.keys()):
                    tilt_params = FactorTiltCacheParams(
                        factor_code=f_code,
                        scalar_to_coeff_version="v1",
                        factor_to_asset_map_version="v1",
                        signal_pkl_mtime=_signal_pkl_mtime,
                        class_caps_version="RiskModelConfig.v1",
                    )
                    cached_tilt = load_factor_tilt(DIR_INPUT, rp_h, tilt_params)
                    if cached_tilt is not None:
                        factor_tilts_by_factor[f_code] = cached_tilt['tilt_weights_by_date']
                        print(f"  Factor {f_code}: cache hit")
                        continue

                    tilt_rows = {}
                    for rebalance_date, weights in rp_weights_by_date.items():
                        # Only tilt with this factor on dates where it was actually
                        # screened in (low_corr_factors_list) — matches the original
                        # per-date asset_to_factors gating exactly.
                        if f_code not in screened_factors_by_date.get(rebalance_date, ()):
                            continue
                        mapped_assets = {a['name'] for a in FACTOR_TO_ASSET_MAP.get(f_code, [])}
                        sig = _factor_signal_asof(f_code, pd.Timestamp(rebalance_date))
                        if sig is None:
                            continue
                        coeff = scalar_to_coeff(sig, f_code)
                        tilt_rows[rebalance_date] = {
                            name: weight * coeff for name, weight in weights.items()
                            if name in mapped_assets
                        }
                    tilt_df = pd.DataFrame(tilt_rows).T
                    factor_tilts_by_factor[f_code] = tilt_df
                    save_factor_tilt(DIR_INPUT, rp_h, tilt_params, tilt_df)
                    print(f"  Factor {f_code}: computed and cached")

            # ── Step C: blend per-date — average each asset's tilted weight
            #    across the factors that touch it, falling back to the RP
            #    weight for assets touched by zero factors, then renormalise,
            #    apply class caps, and finally apply capital ONCE to the
            #    blended vector (never per-factor, so summing contributions
            #    from N factors cannot inflate total deployed capital).
            _CLASS_CAPS = RiskModelConfig.CLASS_CAPS

            for rebalance_date, weights in rp_weights_by_date.items():
                if alloc_mode == 'factor_scaling' and factor_tilts_by_factor:
                    blended = {}
                    for name, rp_weight in weights.items():
                        tilted_vals = []
                        for f_code, tilt_df in factor_tilts_by_factor.items():
                            if rebalance_date in tilt_df.index and name in tilt_df.columns:
                                v = tilt_df.loc[rebalance_date, name]
                                if pd.notna(v):
                                    tilted_vals.append(float(v))
                        blended[name] = float(np.mean(tilted_vals)) if tilted_vals else rp_weight

                    total_scaled = sum(blended.values())
                    if total_scaled > 1e-9:
                        weights = {k: v / total_scaled for k, v in blended.items()}
                        # Apply per-class caps then renormalise (iterate to spread
                        # any excess evenly across uncapped assets).
                        for _ in range(3):
                            capped = {k: max(0, min(v, _CLASS_CAPS.get(get_asset_type(k), RiskModelConfig.CLASS_CAP_DEFAULT)))
                                      for k, v in weights.items()}
                            cap_total = sum(capped.values())
                            if cap_total > 1e-9:
                                weights = {k: v / cap_total for k, v in capped.items()}
                    else:
                        print(f"  {rebalance_date.date()}: All signals zero, using RP weights")
                        # weights already set from RP optimizer above, leave unchanged

                all_assets_ever.update(weights.keys())

                # Calculate allocations — capital applied once, on the final
                # (blended + capped, or pure-RP) weight vector.
                row = {'Date': rebalance_date}
                current_allocations = {}
                for name, weight in weights.items():
                    alloc = weight * total_capital_cny
                    row[name] = alloc / 1_000_000  # Store in millions for chart
                    current_allocations[name] = alloc

                history_data.append(row)
                allocations_by_date[rebalance_date] = current_allocations
            
            if not history_data:
                err_fig = go.Figure().update_layout(title="No valid rebalance periods found", template=THEME['chart_template'])
                return err_fig, err_fig, None, html.Div("No valid periods", style={'color': THEME['warning']})
            
            # Use user-selected date range for display (we already validated it's valid)
            display_start = start_date
            display_end = end_date
            
            # --- Calculate Daily PnL ---
            all_dates = sorted(risk_factors.loc[(risk_factors.index >= start_date) & (risk_factors.index <= end_date)].index)
            sorted_rebalance_dates = sorted(allocations_by_date.keys())
            
            # --- Vectorised daily PnL ---
            # Step 1: build returns matrix (index=date, columns=assets)
            _daily_idx = pd.DatetimeIndex(all_dates)
            _ret_series: dict[str, pd.Series] = {}
            for name in all_assets_ever:
                try:
                    ret_df = calculate_daily_returns_series(name, market_data, start_date, end_date)
                    if not ret_df.empty:
                        s = ret_df.set_index('Date')['total']
                        if not isinstance(s.index, pd.DatetimeIndex):
                            s.index = pd.to_datetime(s.index)
                        _ret_series[name] = s
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning("Could not load returns for %s: %s", name, e)

            rets_matrix = pd.DataFrame(_ret_series, index=_daily_idx)

            # Step 2: allocation matrix — one row per rebalance date, forward-filled daily
            _alloc_rows = {
                pd.Timestamp(rd): alloc
                for rd, alloc in allocations_by_date.items()
            }
            alloc_raw = pd.DataFrame(_alloc_rows).T  # shape: (n_rebalances, n_assets)
            alloc_raw.index = pd.DatetimeIndex(alloc_raw.index)
            alloc_daily = (
                alloc_raw
                .reindex(alloc_raw.index.union(_daily_idx))
                .ffill()
                .reindex(_daily_idx)
                .reindex(columns=rets_matrix.columns)
                .fillna(0.0)
            )

            # Step 3: daily PnL in millions CNY, then cumulative sum
            daily_pnl_m = (alloc_daily * rets_matrix).fillna(0.0) / 1_000_000

            # ── Turnover & transaction costs (Item 21b) ───────────────────────
            # Turnover at each rebalance = Σ|Δweight| (one-way, so round-trip = 2×).
            # Tx cost: 0.5 bp notional per unit of one-way turnover (conservative
            # estimate for bond futures / IRS; apply symmetrically to round-trips).
            _TX_COST_BP: float = 0.5          # basis points per unit one-way turnover
            _tx_cost_rate = _TX_COST_BP / 1e4

            weight_rows = {}
            for rd, alloc in allocations_by_date.items():
                _tot = sum(abs(v) for v in alloc.values()) or 1.0
                weight_rows[pd.Timestamp(rd)] = {k: v / _tot for k, v in alloc.items()}

            _wt_df = pd.DataFrame(weight_rows).T.sort_index().reindex(
                columns=list(rets_matrix.columns), fill_value=0.0
            )
            _wt_df_prev = _wt_df.shift(1).fillna(0.0)
            turnover_by_date = (_wt_df - _wt_df_prev).abs().sum(axis=1)  # one-way per rebalance

            # Deduct tx cost from portfolio PnL on each rebalance day
            # cost_m = turnover × tx_cost_rate × total_capital (in millions)
            _cap_m = total_capital_cny / 1_000_000
            tx_cost_m = pd.Series(0.0, index=_daily_idx)
            for rd, to in turnover_by_date.items():
                _match = _daily_idx[_daily_idx >= rd]
                if len(_match):
                    tx_cost_m[_match[0]] += float(to) * _tx_cost_rate * _cap_m

            # Total annualised turnover (sum of monthly one-way turnovers / years)
            _n_years = max((end_date - start_date).days / 365.25, 1e-3)
            _ann_turnover = float(turnover_by_date.sum()) / _n_years
            _total_tx_cost_m = float(tx_cost_m.sum())

            _gross_daily = daily_pnl_m.sum(axis=1)
            cumulative_m = daily_pnl_m.cumsum()
            cumulative_m.insert(0, 'Date', _daily_idx)
            cumulative_m['Total'] = _gross_daily.cumsum()
            cumulative_m['Total (net)'] = (_gross_daily - tx_cost_m.values).cumsum()

            df_history = pd.DataFrame(history_data)
            df_pnl = cumulative_m.reset_index(drop=True)

            # Round time series to integers (million CNY)
            for col in df_history.columns:
                if col != 'Date':
                    df_history[col] = df_history[col].round().astype('Int64')
            for col in df_pnl.columns:
                if col != 'Date':
                    df_pnl[col] = df_pnl[col].round().astype('Int64')

            # --- Create Allocation Chart ---
            fig_alloc = go.Figure()
            for asset_name in sorted(all_assets_ever):
                if asset_name in df_history.columns:
                    fig_alloc.add_trace(go.Scatter(
                        x=df_history['Date'],
                        y=df_history[asset_name].fillna(0),
                        mode='lines+markers',
                        name=asset_name,
                        stackgroup='one'
                    ))
            
            fig_alloc.update_layout(
                title=f"Historical Portfolio Allocation ({display_start.strftime('%Y-%m-%d')} to {display_end.strftime('%Y-%m-%d')})",
                xaxis_title="Date", 
                yaxis_title="Allocation (Million CNY)",
                hovermode='x unified', 
                template=THEME['chart_template'], 
                height=400,
                paper_bgcolor=THEME['bg_main'], 
                plot_bgcolor=THEME['bg_main'], 
                font={'color': THEME['text_main']},
                legend=dict(orientation="h", y=1.02, x=1, xanchor="right", font={'color': THEME['text_main'], 'size': 10}),
                xaxis=dict(gridcolor=THEME['table_header']),
                yaxis=dict(gridcolor=THEME['table_header'])
            )
            
            # --- Create Stacked Area PnL Chart ---
            fig_pnl = go.Figure()
            if not df_pnl.empty:
                # Add stacked area traces for each asset
                for asset_name in sorted(all_assets_ever):
                    if asset_name in df_pnl.columns:
                        fig_pnl.add_trace(go.Scatter(
                            x=df_pnl['Date'],
                            y=df_pnl[asset_name].fillna(0),
                            mode='none',
                            name=asset_name,
                            stackgroup='pnl',
                            fillcolor=None,
                            hovertemplate=f'<b>{asset_name}</b><br>Date: %{{x|%Y-%m-%d}}<br>PnL: %{{y}} Million CNY<extra></extra>'
                        ))

                # Add a line trace at the top to show total boundary
                fig_pnl.add_trace(go.Scatter(
                    x=df_pnl['Date'],
                    y=df_pnl['Total'],
                    mode='lines',
                    name='Total',
                    showlegend=False,
                    line=dict(color='rgba(255,255,255,0.3)', width=2),
                    hovertemplate='<b>Total PnL</b><br>Date: %{x|%Y-%m-%d}<br>PnL: %{y} Million CNY<extra></extra>'
                ))

            fig_pnl.update_layout(
                title=f"Cumulative PnL by Asset ({display_start.strftime('%Y-%m-%d')} to {display_end.strftime('%Y-%m-%d')})",
                xaxis_title="Date",
                yaxis_title="Cumulative PnL (Million CNY)",
                hovermode='x unified',
                template=THEME['chart_template'],
                height=450,
                paper_bgcolor=THEME['bg_main'],
                plot_bgcolor=THEME['bg_main'],
                font={'color': THEME['text_main']},
                showlegend=False,
                xaxis=dict(gridcolor=THEME['table_header']),
                yaxis=dict(gridcolor=THEME['table_header'])
            )
            
            # --- NAV index (base 1000) and Performance Metrics ---
            metrics_table = None
            if not df_pnl.empty and len(df_pnl) > 1:
                initial_capital = total_capital_cny / 1_000_000
                portfolio_values = initial_capital + df_pnl['Total']
                net_portfolio_values = initial_capital + df_pnl['Total (net)']
                nav_series = (portfolio_values / portfolio_values.iloc[0]) * 1000
                nav_net_series = (net_portfolio_values / net_portfolio_values.iloc[0]) * 1000
                fig_pnl.add_trace(go.Scatter(
                    x=df_pnl['Date'],
                    y=nav_series.round(2),
                    mode='lines',
                    name='NAV gross (base 1000)',
                    yaxis='y2',
                    line=dict(color='#FFD700', width=2.5, dash='solid'),
                    hovertemplate='<b>NAV (gross)</b>: %{y:.1f}<extra></extra>',
                ))
                fig_pnl.add_trace(go.Scatter(
                    x=df_pnl['Date'],
                    y=nav_net_series.round(2),
                    mode='lines',
                    name='NAV net of tx costs (base 1000)',
                    yaxis='y2',
                    line=dict(color='#FFD700', width=1.5, dash='dot'),
                    hovertemplate='<b>NAV (net)</b>: %{y:.1f}<extra></extra>',
                ))
                fig_pnl.update_layout(
                    yaxis2=dict(
                        title='NAV (base 1000)',
                        overlaying='y',
                        side='right',
                        showgrid=False,
                        tickfont=dict(color='#FFD700'),
                        title_font=dict(color='#FFD700'),
                    ),
                    showlegend=True,
                )
                _perf = compute_portfolio_metrics(
                    portfolio_values,
                    risk_free_rate=RiskModelConfig.RISK_FREE_RATE,
                )
                _perf_net = compute_portfolio_metrics(
                    net_portfolio_values,
                    risk_free_rate=RiskModelConfig.RISK_FREE_RATE,
                )
                annualized_return = _perf.get('Ann. Return', 0.0)
                sharpe_ratio      = _perf.get('Sharpe', 0.0) or 0.0
                max_drawdown      = _perf.get('Max Drawdown', 0.0)
                sharpe_net        = _perf_net.get('Sharpe', 0.0) or 0.0

                _th = {'padding': '8px 12px', 'backgroundColor': THEME['table_header'], 'color': 'white', 'fontSize': '12px'}
                _td_base = {'padding': '8px 12px', 'textAlign': 'center', 'fontWeight': 'bold', 'backgroundColor': THEME['bg_input'], 'fontSize': '12px'}
                metrics_table = html.Table([
                    html.Tr([
                        html.Th("Ann. Return", style=_th),
                        html.Th("Sharpe (gross)", style=_th),
                        html.Th("Sharpe (net tx)", style=_th),
                        html.Th("Max Drawdown", style=_th),
                        html.Th("# Rebalances", style=_th),
                        html.Th("Ann. Turnover", style=_th),
                        html.Th("Total Tx Cost (MM)", style=_th),
                    ]),
                    html.Tr([
                        html.Td(f"{annualized_return:.2%}", style={**_td_base, 'color': THEME['success'] if annualized_return >= 0 else THEME['danger']}),
                        html.Td(f"{sharpe_ratio:.2f}", style={**_td_base, 'color': THEME['success'] if sharpe_ratio >= 1 else THEME['warning'] if sharpe_ratio >= 0 else THEME['danger']}),
                        html.Td(f"{sharpe_net:.2f}", style={**_td_base, 'color': THEME['success'] if sharpe_net >= 1 else THEME['warning'] if sharpe_net >= 0 else THEME['danger']}),
                        html.Td(f"{max_drawdown:.2%}", style={**_td_base, 'color': THEME['danger']}),
                        html.Td(f"{len(allocations_by_date)}", style={**_td_base, 'color': THEME['text_main']}),
                        html.Td(f"{_ann_turnover:.0%}", style={**_td_base, 'color': THEME['text_main']}),
                        html.Td(f"{_total_tx_cost_m:.2f}", style={**_td_base, 'color': THEME['text_sub']}),
                    ]),
                ], style={'borderCollapse': 'collapse', 'fontSize': '14px'})
            
            # --- Build Monthly Holdings Table ---
            asset_holdings_rows = []
            
            for rb_date in sorted_rebalance_dates:
                assets = asset_pools_by_date.get(rb_date, [])
                current_assets = sorted([a['name'] for a in assets])
                
                asset_holdings_rows.append({
                    'Date': rb_date.strftime('%Y-%m'),
                    'Asset Count': len(current_assets),
                    'Holdings': ", ".join(current_assets) if current_assets else "-"
                })
            
            asset_holdings_df = pd.DataFrame(asset_holdings_rows)
            
            asset_changes_table = html.Div([
                html.H5("📅 Monthly Asset Holdings", style={'color': THEME['text_main'], 'marginBottom': '10px', 'marginTop': '20px'}),
                dash_table.DataTable(
                    data=asset_holdings_df.to_dict('records'),
                    columns=[
                        {'name': 'Month', 'id': 'Date'},
                        {'name': '# Assets', 'id': 'Asset Count'},
                        {'name': 'Holdings', 'id': 'Holdings'},
                    ],
                    style_cell={
                        'textAlign': 'left', 
                        'padding': '8px 10px', 
                        'fontFamily': 'Arial, sans-serif',
                        'backgroundColor': THEME['table_row_odd'],
                        'color': THEME['text_main'],
                        'border': 'none',
                        'fontSize': '12px',
                        'whiteSpace': 'normal',
                        'height': 'auto',
                    },
                    style_cell_conditional=[
                        {'if': {'column_id': 'Date'}, 'width': '80px'},
                        {'if': {'column_id': 'Asset Count'}, 'width': '80px', 'textAlign': 'center'},
                        {'if': {'column_id': 'Holdings'}, 'minWidth': '300px'},
                    ],
                    style_header={
                        'backgroundColor': THEME['table_header'], 
                        'color': THEME['text_main'], 
                        'fontWeight': 'bold', 
                        'textAlign': 'left',
                        'border': 'none'
                    },
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                    ],
                    style_table={'overflowX': 'auto', 'maxHeight': '400px', 'overflowY': 'auto'}
                )
            ], style={'backgroundColor': THEME['bg_card'], 'padding': '15px', 'borderRadius': '5px'})
            
            return fig_alloc, fig_pnl, metrics_table, asset_changes_table
            
        except Exception as e:
            traceback.print_exc()
            err_fig = go.Figure().update_layout(title=f"Error: {str(e)}", template=THEME['chart_template'])
            return err_fig, err_fig, None, html.Div(f"Error: {str(e)}", style={'color': THEME['danger']})

