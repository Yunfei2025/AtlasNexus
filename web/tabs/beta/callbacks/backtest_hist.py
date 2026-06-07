# -*- coding: utf-8 -*-
"""Historical allocation backtest callbacks (Backtest tab: factor pool display,
date info, and historical correlation-based analysis chart)."""

from __future__ import annotations

from dash import html, dash_table
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import traceback
from dateutil.relativedelta import relativedelta

from multiasset.data import load_raw_market_data, calculate_daily_returns_series
from multiasset.main import create_custom_portfolio
from multiasset.risk_loader import RiskFactorLoader
from multiasset.factor_optimizer import FactorRiskParityOptimizer
from multiasset.factor_backtest import load_factor_backtest
from multiasset.config import RiskModelConfig
from settings.paths import DIR_INPUT

from ..data import THEME, SELECTED_FACTOR_POOL, get_assets_from_factors, FACTOR_TO_ASSET_MAP


def register_backtest_hist_callbacks(app):
    """Register historical-allocation backtest callbacks."""

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
            
            # Determine correlation lookback period
            if corr_lookback == '3M':
                corr_lookback_delta = relativedelta(months=3)
            elif corr_lookback == '6M':
                corr_lookback_delta = relativedelta(months=6)
            elif corr_lookback == '1Y':
                corr_lookback_delta = relativedelta(years=1)
            else:
                corr_lookback_delta = relativedelta(months=3)
            
            # Calculate earliest valid rebalance date based on selected factor data
            earliest_valid_date = factor_data_start + corr_lookback_delta
            
            # Check if user's selected start date is before minimum supported date
            if start_date < earliest_valid_date:
                limiting_factor_info = f" (limited by {limiting_factors[0][0]})" if limiting_factors else ""
                err_fig = go.Figure().update_layout(
                    title=f"⚠️ Selected start date {start_date.strftime('%Y-%m-%d')} is before minimum supported date {earliest_valid_date.strftime('%Y-%m-%d')}{limiting_factor_info}",
                    template=THEME['chart_template'],
                    paper_bgcolor=THEME['bg_main'],
                    plot_bgcolor=THEME['bg_main'],
                    font={'color': THEME['text_main']}
                )
                return err_fig, err_fig, None, html.Div(
                    f"Please select a start date on or after {earliest_valid_date.strftime('%Y-%m-%d')}. "
                    f"The minimum date is determined by factor data availability (starts {factor_data_start.strftime('%Y-%m-%d')}) "
                    f"plus the correlation lookback period ({corr_lookback}).",
                    style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'}
                )
            
            # Generate rebalance dates (beginning of each month) - now starting from user's selected date
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
            
            for rebalance_date in rebalance_dates:
                # --- Step 1: Run Correlation Analysis on Selected Factor Pool ---
                corr_end = rebalance_date
                corr_start = rebalance_date - corr_lookback_delta
                
                df_subset = risk_factors.loc[corr_start:corr_end]
                if df_subset.empty or len(df_subset) < 20:
                    print(f"  {rebalance_date.date()}: Skipped (insufficient data)")
                    continue
                
                # Filter to only selected factors from the Factor tab
                available_factors = [f for f in selected_factors if f in df_subset.columns]
                if len(available_factors) < 2:
                    print(f"  {rebalance_date.date()}: Skipped (not enough factors in data)")
                    continue
                df_subset = df_subset[available_factors]
                
                # Calculate daily changes for correlation
                df_changes = df_subset.diff().dropna()
                if df_changes.empty:
                    continue
                
                corr_matrix = df_changes.corr()
                
                # Find lowest correlation pairs
                mask = np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
                corr_stacked = corr_matrix.where(mask).stack().reset_index()
                corr_stacked.columns = ['Factor A', 'Factor B', 'Correlation']
                corr_stacked['AbsCorrelation'] = corr_stacked['Correlation'].abs()
                bottom_pairs = corr_stacked.sort_values('AbsCorrelation', ascending=True).head(top_pairs)
                
                # Get unique factors from lowest correlation pairs
                low_corr_factors = set(bottom_pairs['Factor A']).union(set(bottom_pairs['Factor B']))
                low_corr_factors_list = sorted(list(low_corr_factors))
                
                # --- Step 2: Map Factors to Assets ---
                selected_assets = get_assets_from_factors(low_corr_factors_list)
                
                if not selected_assets:
                    print(f"  {rebalance_date.date()}: Skipped (no mappable assets)")
                    continue
                
                selected_asset_names = [a['name'] for a in selected_assets]
                all_assets_ever.update(selected_asset_names)
                
                # --- Step 3: Run factor risk parity allocation ---
                # Create portfolio for these assets
                try:
                    portfolio = create_custom_portfolio(
                        selected_asset_names,
                        use_deterministic=True,
                    )
                except Exception as e:
                    print(f"  {rebalance_date.date()}: Portfolio creation failed: {e}")
                    continue
                
                # Use shared factor risk parity optimizer with deterministic factors
                try:
                    optimizer = FactorRiskParityOptimizer(
                        portfolio=portfolio, 
                        input_dir=str(DIR_INPUT),
                        factor_model_lookback_years=1.0,
                        vol_lookback_months=RiskModelConfig.FACTOR_VOL_LOOKBACK_MONTHS,
                        ewma_lambda=RiskModelConfig.FACTOR_VOL_EWMA_LAMBDA,
                    )
                    weights_series, _ = optimizer.fit_and_calculate(pd.Timestamp(rebalance_date))
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

                # ── Factor Model Scaling: tilt each asset's risk-parity weight by
                #    the FactorModel signal of the factor(s) it maps from. The
                #    resulting weights are directional (can be negative = short)
                #    and intentionally NOT renormalised — when signals are weak the
                #    book is smaller, when strong it is fuller.
                if alloc_mode == 'factor_scaling':
                    asset_to_factors = {}
                    for f in low_corr_factors_list:
                        for a in FACTOR_TO_ASSET_MAP.get(f, []):
                            asset_to_factors.setdefault(a['name'], set()).add(f)

                    scaled = {}
                    for name, weight in weights.items():
                        sigs = [_factor_signal_asof(f, pd.Timestamp(rebalance_date))
                                for f in asset_to_factors.get(name, ())]
                        sigs = [s for s in sigs if s is not None]
                        # Default to neutral long (1.0) when no model signal exists,
                        # so un-modelled sleeves keep their risk-parity exposure.
                        coeff = float(np.mean(sigs)) if sigs else 1.0
                        scaled[name] = weight * coeff

                    # Drop assets the model flattened to ~0 exposure
                    weights = {k: v for k, v in scaled.items() if abs(v) >= 1e-6}
                    if not weights:
                        print(f"  {rebalance_date.date()}: Skipped (all factor signals flat)")
                        continue

                # Store only assets with non-negligible weights in asset pool tracking
                filtered_assets = [a for a in selected_assets if a['name'] in weights]
                asset_pools_by_date[rebalance_date] = filtered_assets
                
                # Calculate allocations
                row = {'Date': rebalance_date}
                current_allocations = {}
                for name, weight in weights.items():
                    alloc = weight * total_capital_cny
                    row[name] = alloc / 1_000_000  # Store in millions for chart
                    current_allocations[name] = alloc
                
                history_data.append(row)
                allocations_by_date[rebalance_date] = current_allocations
                
                print(f"  {rebalance_date.date()}: {len(selected_asset_names)} assets, {len(low_corr_factors_list)} factors")
            
            if not history_data:
                err_fig = go.Figure().update_layout(title="No valid rebalance periods found", template=THEME['chart_template'])
                return err_fig, err_fig, None, html.Div("No valid periods", style={'color': THEME['warning']})
            
            # Use user-selected date range for display (we already validated it's valid)
            display_start = start_date
            display_end = end_date
            
            # --- Calculate Daily PnL ---
            all_dates = sorted(risk_factors.loc[(risk_factors.index >= start_date) & (risk_factors.index <= end_date)].index)
            sorted_rebalance_dates = sorted(allocations_by_date.keys())
            
            # Pre-compute daily returns for all assets ever held
            asset_daily_returns = {}
            for name in all_assets_ever:
                try:
                    ret_df = calculate_daily_returns_series(name, market_data, start_date, end_date)
                    if not ret_df.empty:
                        ret_df = ret_df.set_index('Date')
                        asset_daily_returns[name] = ret_df
                except Exception as e:
                    print(f"  Warning: Could not load returns for {name}: {e}")
            
            daily_pnl_records = []
            cumulative_pnl = {name: 0.0 for name in all_assets_ever}
            cumulative_pnl['Total'] = 0.0
            
            for trading_day in all_dates:
                # Find applicable allocation (most recent rebalance before this day)
                applicable_alloc = None
                for rb_date in sorted_rebalance_dates:
                    if rb_date <= trading_day:
                        applicable_alloc = allocations_by_date[rb_date]
                    else:
                        break
                
                if applicable_alloc is None:
                    continue
                
                daily_record = {'Date': trading_day}
                total_daily_pnl = 0.0
                
                for name in all_assets_ever:
                    if name in applicable_alloc and name in asset_daily_returns:
                        allocation = applicable_alloc[name]
                        ret_df = asset_daily_returns[name]
                        
                        if trading_day in ret_df.index:
                            daily_ret = ret_df.loc[trading_day, 'total']
                            if pd.notna(daily_ret):
                                daily_pnl = allocation * daily_ret
                                cumulative_pnl[name] += daily_pnl
                                total_daily_pnl += daily_pnl
                    
                    daily_record[name] = cumulative_pnl[name] / 1_000_000
                
                cumulative_pnl['Total'] += total_daily_pnl
                daily_record['Total'] = cumulative_pnl['Total'] / 1_000_000
                daily_pnl_records.append(daily_record)
            
            df_history = pd.DataFrame(history_data)
            df_pnl = pd.DataFrame(daily_pnl_records)
            
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
            
            # --- Create PnL Chart ---
            fig_pnl = go.Figure()
            if not df_pnl.empty:
                # Add total line prominently
                fig_pnl.add_trace(go.Scatter(
                    x=df_pnl['Date'], 
                    y=df_pnl['Total'],
                    mode='lines', 
                    name='Total Portfolio',
                    line=dict(color='#00cc96', width=3)
                ))
            
            fig_pnl.update_layout(
                title=f"Cumulative PnL ({display_start.strftime('%Y-%m-%d')} to {display_end.strftime('%Y-%m-%d')})",
                xaxis_title="Date", 
                yaxis_title="Cumulative PnL (Million CNY)",
                hovermode='x unified', 
                template=THEME['chart_template'], 
                height=350,
                paper_bgcolor=THEME['bg_main'], 
                plot_bgcolor=THEME['bg_main'], 
                font={'color': THEME['text_main']},
                legend=dict(orientation="h", y=1.02, x=1, xanchor="right", font={'color': THEME['text_main']}),
                xaxis=dict(gridcolor=THEME['table_header']),
                yaxis=dict(gridcolor=THEME['table_header'])
            )
            
            # --- Calculate Performance Metrics ---
            metrics_table = None
            if not df_pnl.empty and len(df_pnl) > 1:
                initial_capital = total_capital_cny / 1_000_000
                portfolio_values = initial_capital + df_pnl['Total']
                daily_returns = portfolio_values.pct_change().dropna()
                
                total_days = (df_pnl['Date'].iloc[-1] - df_pnl['Date'].iloc[0]).days
                if total_days > 0:
                    total_return = (portfolio_values.iloc[-1] / portfolio_values.iloc[0]) - 1
                    annualized_return = (1 + total_return) ** (365 / total_days) - 1
                else:
                    annualized_return = 0
                
                risk_free_rate = 0.02
                if len(daily_returns) > 0 and daily_returns.std() > 0:
                    excess_return = annualized_return - risk_free_rate
                    annualized_vol = daily_returns.std() * np.sqrt(252)
                    sharpe_ratio = excess_return / annualized_vol
                else:
                    sharpe_ratio = 0
                
                rolling_max = portfolio_values.expanding().max()
                drawdowns = (portfolio_values - rolling_max) / rolling_max
                max_drawdown = drawdowns.min()
                
                metrics_table = html.Table([
                    html.Tr([
                        html.Th("Annualized Return", style={'padding': '8px 15px', 'backgroundColor': THEME['table_header'], 'color': 'white'}),
                        html.Th("Sharpe Ratio", style={'padding': '8px 15px', 'backgroundColor': THEME['table_header'], 'color': 'white'}),
                        html.Th("Max Drawdown", style={'padding': '8px 15px', 'backgroundColor': THEME['table_header'], 'color': 'white'}),
                        html.Th("# Rebalances", style={'padding': '8px 15px', 'backgroundColor': THEME['table_header'], 'color': 'white'}),
                    ]),
                    html.Tr([
                        html.Td(f"{annualized_return:.2%}", style={'padding': '8px 15px', 'textAlign': 'center', 'fontWeight': 'bold',
                                                                'color': THEME['success'] if annualized_return >= 0 else THEME['danger'], 'backgroundColor': THEME['bg_input']}),
                        html.Td(f"{sharpe_ratio:.2f}", style={'padding': '8px 15px', 'textAlign': 'center', 'fontWeight': 'bold',
                                                            'color': THEME['success'] if sharpe_ratio >= 1 else THEME['warning'] if sharpe_ratio >= 0 else THEME['danger'], 'backgroundColor': THEME['bg_input']}),
                        html.Td(f"{max_drawdown:.2%}", style={'padding': '8px 15px', 'textAlign': 'center', 'fontWeight': 'bold', 'color': THEME['danger'], 'backgroundColor': THEME['bg_input']}),
                        html.Td(f"{len(allocations_by_date)}", style={'padding': '8px 15px', 'textAlign': 'center', 'fontWeight': 'bold', 'color': THEME['text_main'], 'backgroundColor': THEME['bg_input']}),
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

