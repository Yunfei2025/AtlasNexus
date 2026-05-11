# -*- coding: utf-8 -*-
"""
Dash callbacks for the Multi-Asset (Beta) Dashboard.
"""
from __future__ import annotations

import dash
from dash import dcc, html, dash_table, ALL, Patch
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
import os
import traceback
import pathlib
from datetime import datetime
from dateutil.relativedelta import relativedelta
import dash_bootstrap_components as dbc

from multiasset.data import (
    load_raw_market_data, calculate_daily_returns_series,
    get_asset_type, get_universe, get_sector
)
from multiasset.layout import prepare_portfolio_table
from multiasset.storage import load_last_asset_pool, save_asset_pool
from multiasset.main import run_risk_parity_allocation, create_custom_portfolio, compute_irdl_hedge
from multiasset.risk_loader import RiskFactorLoader
from multiasset.factor_optimizer import FactorRiskParityOptimizer
from multiasset.factor_backtest import compute_ewma_factor_vols
from multiasset.config import RiskModelConfig
from settings.paths import DIR_INPUT, DIR_MODELS, DIR_OUTPUT

try:
    from futures.backtest.data_loader import (
        discover_pkl_files, load_wind_data,
        load_local_data_processed, resample_data, get_local_file_path
    )
    from futures.backtest.strategies import (
        run_ma_strategy, run_bollinger_strategy, run_vwap_strategy,
        run_intraday_momentum_strategy, run_atr_band_strategy, run_sar_strategy,
        run_demark_strategy
    )
    from futures.backtest.metrics import calculate_metrics
    from futures.backtest.regime import RegimeDetector
    from settings.futures import FuturesConfig
    FUTURES_AVAILABLE = True
except ImportError:
    FUTURES_AVAILABLE = False

from .data import (
    THEME,
    ALLOCATION_RESULTS,
    DIVERSIFICATION_RECOMMENDATIONS,
    SELECTED_FACTOR_POOL,
    RISK_BUDGET_VOL_LOOKBACK_YEARS,
    RISK_BUDGET_EWMA_LAMBDA,
    FACTOR_TO_ASSET_MAP,
    BOND_SIGNAL_FILE_MAP,
    BOND_SIGNAL_LABELS,
    BOND_SIGNAL_BUCKETS,
    compute_factor_vol_map,
    get_assets_from_factors,
)
from .layouts import _build_bond_signal_cards

_SUMMARY_BETA_PARQUET  = str(DIR_INPUT / 'summary_beta_portfolio.parquet')
_SUMMARY_ALPHA_PARQUET = str(DIR_INPUT / 'summary_alpha_portfolio.parquet')

# Map asset-name prefix → primary risk factor (used for close-price lookup)
_ASSET_PREFIX_TO_FACTOR: dict[str, str] = {
    'CN':  'IRDL.CN',  'US':  'IRDL.US',  'EU':  'IRDL.DE',
    'JP':  'IRDL.JP',  'UK':  'IRDL.UK',
    'IRS': 'SPDL.IRS', 'CDB': 'SPDL.CDB', 'ICP': 'SPDL.ICP',
}


def _get_beta_close_prices() -> dict[str, float]:
    """Return {asset_name_prefix: last_factor_level} for Beta-Book close prices.

    Uses the most-recent row of the risk-factor level time series as a proxy.
    IR / Spread factors are reported in %; FX / Commodity not yet supported.
    """
    try:
        loader = RiskFactorLoader(DIR_INPUT)
        factor_levels = loader.load_risk_factors(use_cache=True)
        if factor_levels is None or factor_levels.empty:
            return {}
        last_row = factor_levels.iloc[-1]
        return {
            prefix: round(float(last_row[factor]), 4)
            for prefix, factor in _ASSET_PREFIX_TO_FACTOR.items()
            if factor in last_row.index and pd.notna(last_row[factor])
        }
    except Exception:
        return {}


def register_multiasset_callbacks(app):
    """Register all callbacks for the Multi-Asset Dashboard components."""
    
    # 1. UI Toggles for Asset Type Selection
    @app.callback(
        [Output('universe-selection-row', 'style'),
         Output('sector-selection-row', 'style'),
         Output('commodities-confirm-row', 'style'),
         Output('universe-selector', 'options'),
         Output('universe-selector', 'value'),
         Output('sector-selector', 'value'),
         Output('commodities-selector', 'value')],
        [Input('asset-type-selector', 'value')]
    )
    def toggle_selection_rows(asset_type):
        if asset_type == 'Rates':
            universe_options = [
                {'label': 'China Gov Bond', 'value': 'China Gov Bond'},
                {'label': 'US Gov Bond', 'value': 'US Gov Bond'},
                {'label': 'DE Gov Bond', 'value': 'DE Gov Bond'},
                {'label': 'UK Gov Bond', 'value': 'UK Gov Bond'},
                {'label': 'Japan Gov Bond', 'value': 'Japan Gov Bond'},
            ]
            return (
                {'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'},
                {'display': 'none'},
                {'display': 'none'},
                universe_options, None, [], []
            )
        elif asset_type == 'Spread':
            universe_options = [
                {'label': 'Interest Rate Swap', 'value': 'Interest Rate Swap'},
                {'label': 'China Development Bond', 'value': 'China Development Bond'},
                {'label': 'Interbank Commercial Paper', 'value': 'Interbank Commercial Paper'},
            ]
            return (
                {'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'},
                {'display': 'none'},
                {'display': 'none'},
                universe_options, None, [], []
            )
        elif asset_type == 'Commodities':
            return (
                {'display': 'none'},
                {'display': 'none'},
                {'display': 'flex', 'alignItems': 'flex-start', 'marginBottom': '12px'},
                [], None, [], []
            )
        else:
            return (
                {'display': 'none'},
                {'display': 'none'},
                {'display': 'none'},
                [], None, [], []
            )

    @app.callback(
        Output('sector-selection-row', 'style', allow_duplicate=True),
        [Input('universe-selector', 'value')],
        prevent_initial_call=True
    )
    def show_sector_selection(universe):
        if universe:
            return {'display': 'flex', 'alignItems': 'flex-start', 'marginBottom': '12px'}
        return {'display': 'none'}

    # 2. Asset Pool Management
    @app.callback(
        [Output('asset-pool-store', 'data'),
         Output('asset-pool-display', 'children'),
         Output('pool-count', 'children')],
        [Input('add-to-pool-btn', 'n_clicks'),
         Input('add-commodities-btn', 'n_clicks'),
         Input('clear-pool-btn', 'n_clicks')],
        [State('asset-type-selector', 'value'),
         State('universe-selector', 'value'),
         State('sector-selector', 'value'),
         State('commodities-selector', 'value'),
         State('asset-pool-store', 'data')],
        prevent_initial_call=True
    )
    def manage_asset_pool(add_rates_clicks, add_comm_clicks, clear_clicks, asset_type, universe, sectors, commodities, current_pool):
        ctx = dash.callback_context
        if not ctx.triggered:
            return current_pool, dash.no_update, dash.no_update
        
        button_id = ctx.triggered[0]['prop_id'].split('.')[0]
        
        if button_id == 'clear-pool-btn':
            return [], [html.Div("No assets.", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'padding': '10px'})], "(0)"
        
        if current_pool is None:
            current_pool = []
        
        if button_id == 'add-to-pool-btn' and asset_type in ['Rates', 'Spread']:
            if not universe or not sectors:
                return current_pool, dash.no_update, dash.no_update
            
            universe_code_map = {
                'China Gov Bond': 'CN', 'US Gov Bond': 'US', 'DE Gov Bond': 'EU',
                'UK Gov Bond': 'UK', 'Japan Gov Bond': 'JP',
                'China Credit': 'CN-Credit', 'China Urban': 'CN-Urban'
            }
            universe_code = universe_code_map.get(universe, 'XX')
            
            for sector in sectors:
                asset_name = f"{universe_code}{sector}"
                asset_info = {'name': asset_name, 'type': asset_type, 'universe': universe, 'sector': sector}
                if not any(a['name'] == asset_name for a in current_pool):
                    current_pool.append(asset_info)
        
        elif button_id == 'add-commodities-btn' and asset_type == 'Commodities':
            if not commodities:
                return current_pool, dash.no_update, dash.no_update
            
            for comm in commodities:
                asset_info = {'name': comm, 'type': 'Commodities', 'universe': comm, 'sector': 'N/A'}
                if not any(a['name'] == comm for a in current_pool):
                    current_pool.append(asset_info)
        
        # Update display
        if not current_pool:
            display = [html.Div("No assets selected.", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'padding': '10px'})]
            count_text = "(0)"
        else:
            display = []
            for asset in current_pool:
                if asset['type'] == 'Commodities':
                   bg_col = '#b48b32'
                else:
                   bg_col = '#2c5e40'
                
                display.append(html.Div([
                    html.Span(f"• {asset['name']}", style={'fontWeight': 'bold', 'color': 'white'}),
                    html.Span(f" ({asset.get('universe','')} - {asset.get('sector','')})", style={'color': '#ddd', 'fontSize': '12px'}),
                ], style={'padding': '5px', 'marginBottom': '5px', 'backgroundColor': bg_col, 'borderRadius': '3px'}))
            count_text = f"({len(current_pool)})"
        
        # Save to persistent storage
        try:
            save_asset_pool(current_pool)
        except Exception as e:
            print(f"Error saving asset pool: {e}")

        return current_pool, display, count_text

    # 3. Factor Selection Callbacks (Regime Tab)
    @app.callback(
        [Output('factor-region-selector', 'options'),
         Output('factor-region-selector', 'value')],
        [Input('factor-asset-class-selector', 'value')]
    )
    def update_region_options(asset_class):
        if not asset_class:
            return [], None
        
        if asset_class == 'Rates':
            options = [
                {'label': 'China', 'value': 'CN'},
                {'label': 'United States', 'value': 'US'},
                {'label': 'Eurozone', 'value': 'EU'},
                {'label': 'United Kingdom', 'value': 'UK'},
                {'label': 'Japan', 'value': 'JP'},
            ]
        elif asset_class == 'Spread':
            options = [
                {'label': 'Interest Rate Swap', 'value': 'IRS'},
                {'label': 'China Development Bond', 'value': 'CDB'},
                {'label': 'Interbank Commercial Paper', 'value': 'ICP'},
            ]
        elif asset_class == 'FX':
            options = [
                {'label': 'USD/CNY', 'value': 'USDCNY'},
                {'label': 'EUR/CNY', 'value': 'EURCNY'},
                {'label': 'JPY/CNY', 'value': 'JPYCNY'},
                {'label': 'GBP/CNY', 'value': 'GBPCNY'},
            ]
        elif asset_class == 'Commodities':
            options = [
                {'label': 'Gold', 'value': 'AU'},
                {'label': 'Aluminium', 'value': 'AL'},
                {'label': 'Copper', 'value': 'CU'},
                {'label': 'Crude Oil', 'value': 'SC'},
            ]
        else:
            options = []
        
        return options, None

    @app.callback(
        [Output('factor-type-selector', 'options'),
         Output('factor-type-selector', 'value')],
        [Input('factor-asset-class-selector', 'value'),
         Input('factor-region-selector', 'value')]
    )
    def update_factor_type_options(asset_class, region):
        if not asset_class or not region:
            return [], []
        
        if asset_class == 'Rates':
            factor_codes = ['IRDL', 'IRSL', 'IRCV']
            factor_names = ['Level (IRDL)', 'Slope (IRSL)', 'Curvature (IRCV)']
            options = [{'label': f'{name} - {region}', 'value': f'{code}.{region}'} 
                    for code, name in zip(factor_codes, factor_names)]
        elif asset_class == 'Spread':
            if region == 'ICP':
                # ICP only has SPDL
                options = [{'label': f'Level (SPDL) - {region}', 'value': f'SPDL.{region}'}]
            else:
                factor_codes = ['SPDL', 'SPSL']
                factor_names = ['Level (SPDL)', 'Slope (SPSL)']
                options = [{'label': f'{name} - {region}', 'value': f'{code}.{region}'} 
                        for code, name in zip(factor_codes, factor_names)]
        elif asset_class == 'FX':
            options = [{'label': f'Level (FXDL) - {region}', 'value': f'FXDL.{region}'}]
        elif asset_class == 'Commodities':
            options = [{'label': f'Level (CMDL) - {region}', 'value': f'CMDL.{region}'}]
        else:
            options = []
        
        # Auto-select all available factors by default
        default_values = [opt['value'] for opt in options]
        return options, default_values

    @app.callback(
        Output('factor-history-chart', 'figure'),
        [Input('factor-type-selector', 'value')]
    )
    def update_factor_history_chart(selected_factors):
        if not selected_factors:
            empty_fig = go.Figure()
            empty_fig.update_layout(title="Please select factors from the dropdowns above",
                                xaxis={'visible': False}, yaxis={'visible': False}, template=THEME['chart_template'], paper_bgcolor=THEME['bg_main'], plot_bgcolor=THEME['bg_main'], font={'color': THEME['text_main']})
            return empty_fig
        
        try:
            loader = RiskFactorLoader(DIR_INPUT)
            factor_levels = loader.load_risk_factors(use_cache=True)
            
            if factor_levels is None or factor_levels.empty:
                raise ValueError("Cannot load risk factor data")

            if not isinstance(factor_levels.index, pd.DatetimeIndex):
                factor_levels.index = pd.to_datetime(factor_levels.index)
            factor_levels = factor_levels.sort_index()
            
            fig = go.Figure()
            x_min_all = None
            x_max_all = None
            for factor in selected_factors:
                if factor in factor_levels.columns:
                    series = factor_levels[factor].dropna()
                    if not series.empty:
                        fig.add_trace(go.Scatter(x=series.index, y=series.values, mode='lines', name=factor))
                        s_min = series.index.min()
                        s_max = series.index.max()
                        x_min_all = s_min if x_min_all is None else min(x_min_all, s_min)
                        x_max_all = s_max if x_max_all is None else max(x_max_all, s_max)

            default_xaxis = dict(
                rangeslider=dict(visible=False),
                rangeselector=dict(
                    buttons=[
                        dict(count=1, label="1M", step="month", stepmode="backward"),
                        dict(count=3, label="3M", step="month", stepmode="backward"),
                        dict(count=6, label="6M", step="month", stepmode="backward"),
                        dict(count=1, label="YTD", step="year", stepmode="todate"),
                        dict(count=1, label="1Y", step="year", stepmode="backward"),
                        dict(count=3, label="3Y", step="year", stepmode="backward"),
                        dict(count=5, label="5Y", step="year", stepmode="backward"),
                        dict(step="all", label="All")
                    ],
                    bgcolor=THEME['bg_card'], activecolor=THEME['accent'], font=dict(size=11, color='#000'), x=0, y=1.15
                ),
                type="date",
                gridcolor=THEME['table_header']
            )

            yaxis_config = dict(gridcolor=THEME['table_header'], autorange=True)

            # Default to 3M rather than "All" when data exists.
            if x_max_all is not None and x_min_all is not None:
                x_min_ts = pd.Timestamp(x_min_all)
                x_max_ts = pd.Timestamp(x_max_all)
                default_start = max(x_min_ts, x_max_ts - relativedelta(months=3))
                default_xaxis['range'] = [default_start, x_max_ts]

                y_min, y_max = float('inf'), float('-inf')
                for factor in selected_factors:
                    if factor in factor_levels.columns:
                        series = factor_levels[factor].dropna()
                        mask = (series.index >= default_start) & (series.index <= x_max_ts)
                        viz_series = series[mask]
                        if not viz_series.empty:
                            y_min = min(y_min, viz_series.min())
                            y_max = max(y_max, viz_series.max())
                
                if y_min != float('inf') and y_max != float('-inf'):
                    padding = (y_max - y_min) * 0.05 if y_max != y_min else abs(y_max) * 0.05 or 0.5
                    yaxis_config['range'] = [y_min - padding, y_max + padding]
                    yaxis_config['autorange'] = False

            fig.update_layout(
                xaxis_title="Date", yaxis_title="Value", hovermode='x unified',
                template=THEME['chart_template'], height=500,
                paper_bgcolor=THEME['bg_main'], plot_bgcolor=THEME['bg_main'],
                font={'color': THEME['text_main']},
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font={'color': THEME['text_main']}),
                xaxis=default_xaxis,
                yaxis=yaxis_config,
                # Avoid freezing prior zoom/range state when factor selections change.
                uirevision='factor-history-dynamic'
            )
            return fig
        except Exception as e:
            return go.Figure().update_layout(title=f"Error plotting data: {str(e)}", template=THEME['chart_template'])

    @app.callback(
        Output('factor-history-chart', 'figure', allow_duplicate=True),
        Input('factor-history-chart', 'relayoutData'),
        State('factor-history-chart', 'figure'),
        prevent_initial_call=True
    )
    def rescale_factor_history_yaxis(relayout_data, figure):
        """Rescale y-axis to visible data when x-axis range changes via rangeselector."""
        if not relayout_data or not figure:
            raise dash.exceptions.PreventUpdate

        x_start = relayout_data.get('xaxis.range[0]')
        x_end   = relayout_data.get('xaxis.range[1]')

        # Also handle autorange reset ("All" button)
        if relayout_data.get('xaxis.autorange') is True:
            patched = Patch()
            patched['layout']['yaxis']['autorange'] = True
            return patched

        if x_start is None or x_end is None:
            raise dash.exceptions.PreventUpdate

        try:
            t_start = pd.Timestamp(x_start)
            t_end   = pd.Timestamp(x_end)
        except Exception:
            raise dash.exceptions.PreventUpdate

        y_min, y_max = float('inf'), float('-inf')
        for trace in figure.get('data', []):
            xs = trace.get('x', [])
            ys = trace.get('y', [])
            for x_val, y_val in zip(xs, ys):
                if y_val is None:
                    continue
                try:
                    t = pd.Timestamp(x_val)
                except Exception:
                    continue
                if t_start <= t <= t_end:
                    if y_val < y_min:
                        y_min = y_val
                    if y_val > y_max:
                        y_max = y_val

        if y_min == float('inf') or y_max == float('-inf'):
            raise dash.exceptions.PreventUpdate

        padding = (y_max - y_min) * 0.05 if y_max != y_min else abs(y_max) * 0.05 or 0.5
        patched = Patch()
        patched['layout']['yaxis']['autorange'] = False
        patched['layout']['yaxis']['range'] = [y_min - padding, y_max + padding]
        return patched

    # 3.4 Factor Pool Counter and Store Updater
    @app.callback(
        [Output('factor-pool-count', 'children'),
         Output('factor-selection-store', 'data')],
        [Input('factor-selection-ir', 'value'),
         Input('factor-selection-sp', 'value'),
         Input('factor-selection-fx', 'value'),
         Input('factor-selection-cmd', 'value')],
        prevent_initial_call=True
    )
    def update_factor_pool_count(ir_factors, sp_factors, fx_factors, cmd_factors):
        # Store selected factors in global state for cross-tab access
        SELECTED_FACTOR_POOL['ir_factors'] = ir_factors or []
        SELECTED_FACTOR_POOL['sp_factors'] = sp_factors or []
        SELECTED_FACTOR_POOL['fx_factors'] = fx_factors or []
        SELECTED_FACTOR_POOL['cmd_factors'] = cmd_factors or []
        SELECTED_FACTOR_POOL['timestamp'] = datetime.now()
        
        # Prepare data for store
        store_data = {
            'ir': ir_factors or [],
            'sp': sp_factors or [],
            'fx': fx_factors or [],
            'cmd': cmd_factors or []
        }
        
        total = len(ir_factors or []) + len(sp_factors or []) + len(fx_factors or []) + len(cmd_factors or [])
        if total == 0:
            message = "⚠️ No factors selected. Please select at least 2 factors for correlation analysis."
        elif total == 1:
            message = f"ℹ️ {total} factor selected. Need at least 2 for correlation analysis."
        else:
            message = f"✅ {total} factors selected in pool (shared with Backtest tab)"
        
        return message, store_data
    
    # 3.6 Correlation Rank Callback
    @app.callback(
        [Output('correlation-results-container', 'children'),
         Output('low-corr-factors-store', 'data')],
        Input('rank-correlations-btn', 'n_clicks'),
        [State('correlation-period-selector', 'value'),
         State('correlation-top-pairs-selector', 'value'),
         State('factor-selection-ir', 'value'),
         State('factor-selection-sp', 'value'),
         State('factor-selection-fx', 'value'),
         State('factor-selection-cmd', 'value')],
        prevent_initial_call=True
    )
    def update_correlation_ranks(n_clicks, period, top_pairs, ir_factors, sp_factors, fx_factors, cmd_factors):
        if not n_clicks:
            return html.Div(), []
        
        # Combine all selected factors
        selected_factors = []
        if ir_factors:
            selected_factors.extend(ir_factors)
        if sp_factors:
            selected_factors.extend(sp_factors)
        if fx_factors:
            selected_factors.extend(fx_factors)
        if cmd_factors:
            selected_factors.extend(cmd_factors)
        
        if len(selected_factors) < 2:
            return html.Div("⚠️ Please select at least 2 factors for correlation analysis.", 
                          style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'}), []
        
        try:
            loader = RiskFactorLoader(DIR_INPUT)
            # Use cached load - this pulls the wide DF of all factors
            factor_levels = loader.load_risk_factors(use_cache=True)
            
            if factor_levels is None or factor_levels.empty:
                return html.Div("No factor data available.", style={'color': THEME['warning']}), []
            
            # Filter to only selected factors
            available_factors = [f for f in selected_factors if f in factor_levels.columns]
            if len(available_factors) < 2:
                return html.Div(f"⚠️ Only {len(available_factors)} of selected factors have data. Need at least 2.", 
                              style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'}), []
            
            factor_levels = factor_levels[available_factors]

            # Determine start date based on period
            end_date = factor_levels.index.max()
            if period == '3M':
                start_date = end_date - relativedelta(months=3)
            elif period == '6M':
                start_date = end_date - relativedelta(months=6)
            elif period == '1Y':
                start_date = end_date - relativedelta(years=1)
            else:
                start_date = end_date - relativedelta(months=3)

            # Filter data
            df_subset = factor_levels.loc[start_date:end_date]
            if df_subset.empty:
                 return html.Div(f"No data for period {period}", style={'color': THEME['warning']}), []
            
            # Exclude IRCV (Curvature) factors from correlation analysis
            # Curvature factors are less meaningful for diversification and can add noise
            ircv_cols = [col for col in df_subset.columns if col.startswith('IRCV')]
            df_subset = df_subset.drop(columns=ircv_cols, errors='ignore')
            
            # Calculate returns for correlation (levels might be non-stationary, but request asked for factors correlation. 
            # Usually we corr changes, but let's stick to simple Correlation of the daily prices/levels if that's what "Factors" implies, 
            # OR better, calculate correlation of daily changes (returns) which is standard for "Correlation". 
            # Let's assume daily pct_change for everything to be safe and standard.)
            # However, some factors might be rates (bp), so diff() is better than pct_change().
            # Given these are 'Risk Factors' like Yields (Rates) or Spreads, diff() is safest for stationarity.
            # But let's check if the generic 'calculate_daily_returns_series' handles this? 
            # It's an internal function. Let's just use diff() for now as it's robust for levels-based time series correlation.
            
            df_changes = df_subset.diff().dropna()
            
            if df_changes.empty:
                 return html.Div("Insufficient data points for correlation.", style={'color': THEME['warning']}), []

            corr_matrix = df_changes.corr()

            # Identify the unique factors involved in the top 10 lowest correlations
            # Stack and sort for bottom 10 table
            # Mask the upper triangle to avoid duplicates and self-correlation = 1
            mask = np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
            corr_stacked = corr_matrix.where(mask).stack().reset_index()
            corr_stacked.columns = ['Factor A', 'Factor B', 'Correlation']
            
            # Sort by absolute correlation ascending (closest to 0 first)
            corr_stacked['AbsCorrelation'] = corr_stacked['Correlation'].abs()
            top_pairs = int(top_pairs) if top_pairs else 10
            bottom_pairs = corr_stacked.sort_values('AbsCorrelation', ascending=True).head(top_pairs)

            # ── Heatmap: show ALL selected factors (not just low-corr pairs) ────
            all_factors_list = list(corr_matrix.columns)

            # Mask upper triangle for the full matrix
            corr_values = corr_matrix.values.copy()
            mask_upper = np.triu(np.ones(corr_values.shape), k=1).astype(bool)
            corr_values[mask_upper] = np.nan

            n_factors = len(all_factors_list)
            # Scale height so labels are readable regardless of how many factors
            heatmap_height = max(500, min(900, 80 + n_factors * 40))

            # --- Heatmap Plot ---
            heatmap_fig = go.Figure(data=go.Heatmap(
                z=corr_values,
                x=all_factors_list,
                y=all_factors_list,
                colorscale='RdBu',
                zmin=-1, zmax=1,
                hovertemplate='%{y} / %{x}<br>Correlation: %{z:.3f}<extra></extra>',
                xgap=1, ygap=1,
                text=[[f"{v:.2f}" if not np.isnan(v) else "" for v in row] for row in corr_values],
                texttemplate="%{text}",
            ))

            heatmap_fig.update_layout(
                title=f"Rank Correlation Matrix — {n_factors} factors · {period}",
                height=heatmap_height,
                template=THEME['chart_template'],
                paper_bgcolor=THEME['bg_card'],
                plot_bgcolor=THEME['bg_card'],
                font={'color': THEME['text_main'], 'size': 11},
                margin=dict(l=160, r=50, t=70, b=120),
                xaxis={'side': 'bottom', 'tickangle': -45},
                yaxis={'autorange': 'reversed'},
            )

            # Low-corr pairs still drive diversification recommendations
            top_factors = set(bottom_pairs['Factor A']).union(set(bottom_pairs['Factor B']))
            top_factors_list = sorted(list(top_factors))

            # Get the assets corresponding to these low-correlation factors
            diversified_assets = get_assets_from_factors(top_factors_list)
            
            # Store in global variable for cross-tab access (dcc.Store doesn't persist across tabs)
            DIVERSIFICATION_RECOMMENDATIONS['factors'] = top_factors_list
            DIVERSIFICATION_RECOMMENDATIONS['assets'] = diversified_assets
            DIVERSIFICATION_RECOMMENDATIONS['timestamp'] = datetime.now()
            
            # Build complete asset display list (grouped by type)
            asset_display_items = []
            if diversified_assets:
                # Group assets by type
                assets_by_type = {}
                for asset in diversified_assets:
                    a_type = asset.get('type', 'Other')
                    if a_type not in assets_by_type:
                        assets_by_type[a_type] = []
                    assets_by_type[a_type].append(asset)
                
                # Create display for each type
                type_colors = {
                    'Rates': '#2c5e40',
                    'Spread': '#2c5e40',
                    'Commodities': '#b48b32',
                    'FX': '#6b4b8a'
                }
                
                for a_type, assets_list in assets_by_type.items():
                    bg_col = type_colors.get(a_type, '#2c5e40')
                    asset_names = [a['name'] for a in assets_list]
                    asset_display_items.append(
                        html.Div([
                            html.Span(f"{a_type}: ", style={'fontWeight': 'bold', 'color': '#fff', 'marginRight': '5px'}),
                            html.Span(", ".join(asset_names), style={'color': '#ddd'})
                        ], style={
                            'padding': '8px 12px', 
                            'marginBottom': '5px', 
                            'backgroundColor': bg_col, 
                            'borderRadius': '4px',
                            'fontSize': '12px'
                        })
                    )
            
            # Format display
            return html.Div([
                html.Div([
                    dcc.Graph(figure=heatmap_fig)
                ], style={'marginBottom': '30px'}),

                html.H6(f"Lowest Absolute Correlations (Diversification Opportunities) - Top {top_pairs} Pairs", style={'color': THEME['text_main']}),
                dash_table.DataTable(
                    data=bottom_pairs.drop(columns=['AbsCorrelation']).to_dict('records'),
                    columns=[
                        {'name': 'Factor A', 'id': 'Factor A'},
                        {'name': 'Factor B', 'id': 'Factor B'},
                        {'name': 'Correlation', 'id': 'Correlation', 'type': 'numeric', 'format': {'specifier': '.3f'}},
                    ],
                    style_cell={
                        'textAlign': 'left', 
                        'padding': '10px', 
                        'fontFamily': 'Arial, sans-serif',
                        'backgroundColor': THEME['table_row_odd'],
                        'color': THEME['text_main'],
                        'border': 'none'
                    },
                    style_header={
                        'backgroundColor': THEME['table_header'], 
                        'color': THEME['text_main'], 
                        'fontWeight': 'bold', 
                        'textAlign': 'left',
                        'border': 'none'
                    },
                    style_data_conditional=[
                         {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']}
                    ]
                ),
                
                # Add to Asset Pool Section
                html.Div([
                    html.Hr(style={'borderColor': THEME['text_sub'], 'margin': '20px 0'}),
                    html.H6("📊 Diversified Asset Recommendation", style={'color': THEME['success'], 'marginBottom': '10px'}),
                    html.P(
                        f"Based on {len(top_factors_list)} low-correlation factors, {len(diversified_assets)} assets are recommended:",
                        style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginBottom': '10px'}
                    ),
                    # Complete asset list display
                    html.Div(
                        asset_display_items if asset_display_items else html.Div("No mappable assets found.", style={'color': THEME['warning']}),
                        style={
                            'backgroundColor': THEME['bg_input'], 
                            'padding': '10px', 
                            'borderRadius': '4px',
                            'marginBottom': '15px',
                            'maxHeight': '200px',
                            'overflowY': 'auto'
                        }
                    ),
                    html.Button(
                        f"🔄 Replace Asset Pool with {len(diversified_assets)} Recommended Assets",
                        id='add-diversified-assets-btn',
                        n_clicks=0,
                        disabled=len(diversified_assets) == 0,
                        style={
                            'backgroundColor': THEME['success'] if diversified_assets else THEME['text_sub'],
                            'color': 'white', 
                            'padding': '10px 25px', 
                            'border': 'none', 
                            'borderRadius': '5px', 
                            'cursor': 'pointer' if diversified_assets else 'not-allowed',
                            'fontWeight': 'bold',
                            'fontSize': '14px'
                        }
                    ),
                    html.Span(
                        id='add-diversified-status',
                        style={'marginLeft': '15px', 'color': THEME['text_sub'], 'fontSize': '12px'}
                    )
                ], style={'marginTop': '15px'})
            ]), top_factors_list
            
        except Exception as e:
            return html.Div(f"Error calculating correlations: {str(e)}", style={'color': THEME['danger']}), []


    # 3.55 Add Diversified Assets to Pool Callback
    # Uses global variable instead of dcc.Store because dcc.Store data doesn't persist across tab switches
    @app.callback(
        [Output('add-diversified-status', 'children'),
         Output('asset-pool-store', 'data', allow_duplicate=True),
         Output('asset-pool-display', 'children', allow_duplicate=True),
         Output('pool-count', 'children', allow_duplicate=True)],
        Input('add-diversified-assets-btn', 'n_clicks'),
        prevent_initial_call=True
    )
    def add_diversified_assets_to_pool(n_clicks):
        """
        Replace the asset pool with recommended diversified assets.
        Updates asset-pool-store directly so the Portfolio tab sees the change
        immediately without requiring a page reload.
        """
        no_change = (dash.no_update, dash.no_update, dash.no_update)
        if not n_clicks or n_clicks == 0:
            return ("",) + no_change

        # Get assets from global variable (set by correlation analysis)
        recommended_assets = DIVERSIFICATION_RECOMMENDATIONS.get('assets', [])

        if not recommended_assets:
            return ("⚠ No recommended assets available. Please run correlation analysis first.",) + no_change

        # REPLACE the entire asset pool with recommended assets
        new_pool = [asset.copy() for asset in recommended_assets]

        # Save to persistent storage
        try:
            save_asset_pool(new_pool)
        except Exception as e:
            print(f"Error saving asset pool: {e}")
            return (f"✗ Error saving: {str(e)}",) + no_change

        # Build display items (same style as manage_asset_pool)
        display = []
        for asset in new_pool:
            bg_col = '#b48b32' if asset.get('type') == 'Commodities' else '#2c5e40'
            display.append(html.Div([
                html.Span(f"• {asset['name']}", style={'fontWeight': 'bold', 'color': 'white'}),
                html.Span(
                    f" ({asset.get('universe', '')} - {asset.get('sector', '')})",
                    style={'color': '#ddd', 'fontSize': '12px'},
                ),
            ], style={'padding': '5px', 'marginBottom': '5px', 'backgroundColor': bg_col, 'borderRadius': '3px'}))

        count_text = f"({len(new_pool)})"

        # Count assets by type for status message
        type_counts: dict = {}
        for asset in new_pool:
            a_type = asset.get('type', 'Other')
            type_counts[a_type] = type_counts.get(a_type, 0) + 1
        type_summary = ", ".join([f"{count} {t}" for t, count in type_counts.items()])
        status_msg = f"✓ {len(new_pool)} assets added to pool ({type_summary})."

        return status_msg, new_pool, display, count_text

    # 3.6 Risk Factor Budget Input Generator
    @app.callback(
        Output('risk-budget-container', 'children'),
        [Input('asset-pool-store', 'data'),
         Input('rp-budget-store', 'data'),
         Input('factor-signals-snapshot-store', 'data'),
         Input('allocation-mode', 'value')],
        [State('capital-input', 'value'),
         State('capital-unit', 'value')],
    )
    def update_risk_budget_inputs(asset_pool, rp_budgets, snapshot_data, allocation_mode, capital, capital_unit):
        if not asset_pool:
             return [html.Div("Add assets to see risk factors", style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px', 'textAlign': 'center'})]

        active_factors = set()
        
        # Mappings based on MultiAsset logic
        rates_map = {'CN': 'CN', 'US': 'US', 'EU': 'DE', 'UK': 'UK', 'JP': 'JP'}
        comm_map = {'Gold': 'AU', 'Aluminium': 'AL', 'Copper': 'CU', 'Crude Oil': 'SC', 'Crude_Oil': 'SC'}

        for asset in asset_pool:
            a_type = asset.get('type')
            
            if a_type == 'Rates':
                asset_name = asset.get('name', '')
                prefix = asset_name[:2]
                rf_country = rates_map.get(prefix)
                if rf_country:
                    active_factors.add(f"IRDL.{rf_country}")
                    active_factors.add(f"IRSL.{rf_country}")
                    active_factors.add(f"IRCV.{rf_country}")
            
            elif a_type == 'Spread':
                 asset_name = asset.get('name', '')
                 if asset_name.startswith('IRS'): code = 'IRS'
                 elif asset_name.startswith('CDB'): code = 'CDB'
                 elif asset_name.startswith('ICP'): code = 'ICP'
                 else: code = None
                 if code:
                     active_factors.add(f"SPDL.{code}")
                     if code != 'ICP':
                         active_factors.add(f"SPSL.{code}")
            
            elif a_type == 'Commodities':
                 asset_name = asset.get('name', '')
                 code = comm_map.get(asset_name)
                 if code:
                     active_factors.add(f"CMDL.{code}")

        if not active_factors:
             return [html.Div("No risk factors identified.", style={'color': THEME['text_sub'], 'fontSize': '12px'})]

        sorted_factors = sorted(list(active_factors))
        n_factors = len(sorted_factors)

        # ── Compute RP Max per factor ──────────────────────────────────────────
        # Use post-run RP budgets if available; else fall back to equal capital share
        try:
            cap_val = float(capital or 100)
            cap_mult = 1e9 if (capital_unit == 'billion') else 1e6
            total_capital_m = cap_val * cap_mult / 1e6
        except (TypeError, ValueError):
            total_capital_m = 100.0
        equal_share = round(total_capital_m / n_factors, 2) if n_factors else 1.0

        # ── Factor model signal lookup (scalar + colour) ───────────────────────
        SCALAR_META = {
            -1.5: ('Strong Short', THEME.get('danger', '#e74c3c')),
            -1.0: ('Short',        '#e74c3c'),
            -0.5: ('Mild Short',   '#e67e22'),
             0.0: ('Neutral',      THEME.get('text_sub', '#aaa')),
             0.5: ('Mild Long',    '#27ae60'),
             1.0: ('Long',         THEME.get('success', '#2ecc71')),
             1.5: ('Strong Long',  '#2ecc71'),
        }
        snapshot_by_rf = {}
        if snapshot_data:
            for rec in snapshot_data:
                rf = rec.get('risk_factor')
                if rf:
                    snapshot_by_rf[rf] = rec

        def get_coeff(factor):
            rec = snapshot_by_rf.get(factor)
            if rec is not None:
                return float(rec.get('scalar', 1.0))
            return 1.0  # default: full long — placeholder until factor model is run

        # ── Factor vol lookup (live 1Y EWMA) ─────────────────────────────────
        _vol_map = compute_factor_vol_map(sorted_factors)

        # ── Inverse-vol proportional RP Max (stable base for risk_parity / factor_scaling) ─
        _inv_vols = {}
        for _f in sorted_factors:
            _v = _vol_map.get(_f)
            if _v is not None and pd.notna(_v) and _v > 0:
                _inv_vols[_f] = 1.0 / _v
        _total_inv_vol = sum(_inv_vols.values())
        if _total_inv_vol > 0:
            _inv_vol_budgets = {
                _f: round(total_capital_m * _inv_vols.get(_f, 0.0) / _total_inv_vol, 2)
                for _f in sorted_factors
            }
        else:
            _inv_vol_budgets = {_f: equal_share for _f in sorted_factors}

        def get_rp_max(factor):
            if allocation_mode == 'user_defined':
                # User Defined: preserve what the user last stored (or equal share on first load)
                return float(rp_budgets[factor]) if (rp_budgets and factor in rp_budgets) else equal_share
            # risk_parity and factor_scaling: always deterministic inverse-vol proportional
            return _inv_vol_budgets.get(factor, equal_share)

        # ── Build rows ─────────────────────────────────────────────────────────
        rows = []
        for factor in sorted_factors:
            rp_max = get_rp_max(factor)
            coeff  = get_coeff(factor)
            # factor_scaling: scale exposure by signal coeff; other modes: exposure = RP Max
            suggested = round(rp_max * coeff, 2) if allocation_mode == 'factor_scaling' else rp_max
            label, color = SCALAR_META.get(coeff, (f'{coeff:+.1f}×', THEME.get('text_main', '#fff')))
            is_default_coeff = factor not in snapshot_by_rf

            vol_val = _vol_map.get(factor)
            vol_str = f"{vol_val:.2f}%" if vol_val is not None and pd.notna(vol_val) else "–"

            rows.append(
                html.Div([
                    html.Span(factor, style={
                        'color': THEME['text_main'], 'fontSize': '12px',
                        'width': '80px', 'fontWeight': 'bold', 'flexShrink': '0',
                    }),
                    html.Span(vol_str, style={
                        'color': THEME.get('text_sub', '#aaa'), 'fontSize': '12px',
                        'width': '62px', 'textAlign': 'right', 'flexShrink': '0',
                        'fontFamily': 'monospace',
                    }),
                    html.Span(f"{rp_max:.1f}M", style={
                        'color': THEME['text_sub'], 'fontSize': '12px',
                        'width': '54px', 'textAlign': 'right', 'flexShrink': '0',
                    }),
                    html.Span(
                        f"×{coeff:+.1f}",
                        title=f"{label}{' (default)' if is_default_coeff else ''}",
                        style={
                            'color': THEME.get('text_sub', '#aaa') if is_default_coeff else color,
                            'fontSize': '12px', 'width': '44px', 'textAlign': 'center',
                            'flexShrink': '0', 'fontWeight': 'bold',
                            'fontStyle': 'italic' if is_default_coeff else 'normal',
                        }
                    ),
                    dcc.Input(
                        id={'type': 'risk-budget-input', 'index': factor},
                        type='number',
                        value=suggested,
                        step=0.1,
                        style={
                            'width': '52px', 'fontSize': '12px', 'padding': '2px 4px',
                            'backgroundColor': '#fff', 'color': '#000',
                            'border': f'1px solid {THEME["table_header"]}',
                            'borderRadius': '2px', 'textAlign': 'right',
                        }
                    ),
                    html.Span("M", style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginLeft': '2px'}),
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '4px', 'gap': '4px'})
            )
        
        return rows

    # ── 3.7  Factor Model Signals – refresh & render ──────────────────
    @app.callback(
        [Output('factor-signals-table-container', 'children'),
         Output('factor-signals-status', 'children'),
         Output('factor-signals-snapshot-store', 'data')],
        [Input('refresh-factor-signals-btn', 'n_clicks')],
        prevent_initial_call=True,
    )
    def refresh_factor_signals(n_clicks):
        """Compute signal snapshot from the factor prediction engine and
        render as a colour-coded table in the Factor tab.

        Signal sources (merged, risk-factor models take priority):
        1. Contract-level ``trained_model_*.joblib`` from ``factors/``
           → decomposed to risk factors via exposure profiles.
        2. Risk-factor-level ``factor_model_*.joblib`` from ``input/models/``
           → direct risk-factor predictions (override contract-based).
        """
        try:
            from factors.processing.exposure_mapper import (
                BucketConfig, compute_signal_snapshot,
            )
            from factors.processing.risk_factor_mapper import (
                CONTRACT_RISK_PROFILES, decompose_signal_series,
            )
            import joblib, os, glob
            from settings.paths import PATH

            rf_signals: dict = {}  # risk_factor → signal Series
            source_info: list = []  # human-readable summary

            # --- Source 1: contract-level models (factors/) --------------------
            model_dir = os.path.join(str(PATH), 'factors')
            model_files = glob.glob(os.path.join(model_dir, 'trained_model_*.joblib'))

            if model_files:
                from factors.processing.loader import getDailyTS, ensure_returns_column
                from factors.generator.factory import FactorCalculatorFactory
                from factors.engine.predictor import predict_returns

                n_contracts = 0
                for mf in model_files:
                    basename = os.path.basename(mf)
                    parts = basename.replace('trained_model_', '').replace('.joblib', '').split('_')
                    contract = parts[0] if parts else None
                    if contract not in CONTRACT_RISK_PROFILES:
                        continue
                    artifact = joblib.load(mf)
                    trained_model  = artifact.get('trained_model', {})
                    selected_factors = artifact.get('selected_factors', [])
                    ticker = artifact.get('config', {}).get('ticker', contract)
                    if not trained_model or not selected_factors:
                        continue
                    try:
                        raw_data = getDailyTS(ticker)
                        raw_data = ensure_returns_column(raw_data)
                        factory  = FactorCalculatorFactory(raw_data)
                        all_factors = factory.generate_factors()
                        predictions = predict_returns(all_factors, trained_model, selected_factors)
                        predictions = predictions.dropna()
                        predictions = predictions[predictions != 0]
                    except Exception:
                        continue
                    if predictions is None or (hasattr(predictions, 'empty') and predictions.empty):
                        continue
                    decomposed = decompose_signal_series(predictions, contract)
                    for col in decomposed.columns:
                        if col in rf_signals:
                            rf_signals[col] = rf_signals[col].add(decomposed[col], fill_value=0)
                        else:
                            rf_signals[col] = decomposed[col].copy()
                    n_contracts += 1

                if n_contracts:
                    source_info.append(f"{n_contracts} contracts")

            # --- Source 2: risk-factor-level models (input/models/) -----------
            try:
                from multiasset.factor_model import predict_factor_signals
                rf_model_signals = predict_factor_signals(DIR_INPUT, DIR_MODELS)
                if rf_model_signals:
                    for rf, series in rf_model_signals.items():
                        rf_signals[rf] = series  # override contract-derived
                    source_info.append(f"{len(rf_model_signals)} risk-factor models")
            except Exception as e:
                print(f"Warning: risk-factor model signals unavailable: {e}")

            if not rf_signals:
                return (
                    html.Div("No signal series could be computed from trained models.",
                             style={'color': THEME['text_sub']}),
                    "No signals",
                    {},
                )

            # --- bucket mapping ------------------------------------------------
            cfg = BucketConfig()
            snapshot = compute_signal_snapshot(rf_signals, cfg)

            if snapshot.empty:
                return (
                    html.Div("Signal snapshot is empty.", style={'color': THEME['text_sub']}),
                    "Empty",
                    {},
                )

            # --- render table --------------------------------------------------
            def _bucket_color(label):
                label_lower = str(label).lower()
                if 'strong long' in label_lower: return THEME['success']
                if 'long' in label_lower: return '#27ae60'
                if 'strong short' in label_lower: return THEME['danger']
                if 'short' in label_lower: return '#c0392b'
                return THEME['text_sub']

            rows = [
                html.Tr([
                    html.Td(r['risk_factor'], style={'fontWeight': 'bold'}),
                    html.Td(f"{r['signal']:.4f}"),
                    html.Td(r['bucket_label'],
                             style={'color': _bucket_color(r['bucket_label']),
                                    'fontWeight': 'bold'}),
                    html.Td(f"{r['scalar']:+.1f}×"),
                    html.Td(f"{r['risk_budget']:+.2f} M"),
                    html.Td(f"{r['confidence']:.0%}"),
                ], style={'fontSize': '12px'})
                for r in snapshot.to_dict('records')
            ]

            table = html.Table(
                [html.Thead(html.Tr([
                    html.Th(c, style={'padding': '4px 8px', 'color': THEME['text_sub'],
                                      'borderBottom': f'1px solid {THEME["table_header"]}'})
                    for c in ['Risk Factor', 'Signal', 'Bucket', 'Scalar',
                              'Risk Budget', 'Confidence']
                ]))] + [html.Tbody(rows)],
                style={'width': '100%', 'color': THEME['text_main'],
                       'fontSize': '12px', 'borderCollapse': 'collapse'},
            )

            # Store snapshot as serialisable dict for Portfolio tab
            snapshot_data = snapshot.to_dict(orient='records')

            source_str = ' + '.join(source_info) if source_info else 'unknown'

            return (
                table,
                f"Updated ({len(snapshot)} factors · {source_str})",
                snapshot_data,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return (
                html.Div(f"Error: {e}", style={'color': THEME['danger']}),
                "Error",
                {},
            )

    @app.callback(
        [Output('beta-bond-signals-container', 'children'),
         Output('beta-bond-status', 'children')],
        [Input('beta-bond-refresh-btn', 'n_clicks'),
         Input('beta-bond-type-selector', 'value')],
        prevent_initial_call=False,
    )
    def refresh_beta_bond_signals(refresh_clicks, bond_type):
        selected_bond_type = bond_type or 'TBond'
        try:
            signal_cards, bond_count = _build_bond_signal_cards(selected_bond_type)
            action = 'Loaded'
            ctx = dash.callback_context
            if ctx.triggered:
                trigger_id = ctx.triggered[0]['prop_id'].split('.')[0]
                if trigger_id == 'beta-bond-refresh-btn':
                    action = 'Refreshed'
                elif trigger_id == 'beta-bond-type-selector':
                    action = 'Switched'

            label = BOND_SIGNAL_LABELS.get(selected_bond_type, selected_bond_type)
            if bond_count is None:
                status = f"{action} {label} · no live signal rows available · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            else:
                status = f"{action} {label} · {bond_count} live rows · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            return signal_cards, status
        except Exception as e:
            traceback.print_exc()
            return (
                html.Div(f"Error loading bond signals: {e}", style={'color': THEME['danger'], 'padding': '20px'}),
                f"Load failed · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            )

    # ── 3.8  Mode status hint ─────────────────────────────────────────
    @app.callback(
        Output('factor-signals-toggle-status', 'children'),
        [Input('allocation-mode', 'value')],
        [State('factor-signals-snapshot-store', 'data'),
         State('asset-pool-store', 'data')],
    )
    def autofill_risk_budgets_status(allocation_mode, snapshot_data, asset_pool):
        """Show a one-line hint for the selected allocation mode."""
        if allocation_mode == 'risk_parity':
            return "RP Max = inv-vol weights · same result on every run"
        if allocation_mode == 'user_defined':
            return "Edit Exposure inputs directly · re-runs preserve your values"
        # factor_scaling
        if not snapshot_data:
            return "⚠ No signal snapshot — click 'Refresh Signals' in the Factor tab first."
        return f"✓ {len(snapshot_data)} factor signals scale RP Max at run time."

    # 4. Run Analysis (Portfolio Tab -> Results)
    @app.callback(
        [Output('portfolio-table-container', 'children'),
         Output('status-message', 'children'),
         Output('timestamp-display', 'children'),
         Output('portfolio-data-store', 'data'),
         Output('rp-budget-store', 'data')],
        [Input('run-button', 'n_clicks')],
        [State('capital-input', 'value'),
         State('capital-unit', 'value'),
         State('asset-pool-store', 'data'),
         State({'type': 'risk-budget-input', 'index': ALL}, 'value'),
         State({'type': 'risk-budget-input', 'index': ALL}, 'id'),
         State('allocation-mode', 'value'),
         State('factor-signals-snapshot-store', 'data')]
    )
    def run_analysis(n_clicks, total_capital, capital_unit, asset_pool,
                     budget_values, budget_ids, allocation_mode, signal_snapshot):
        if n_clicks == 0:
            return (html.Div("No data available. Click 'Run Analysis' to start.", style={'color': THEME['text_sub']}),
                    "", "", {}, {})

        try:
            # Validate asset pool
            if not asset_pool or len(asset_pool) == 0:
                error_msg = html.Span("⚠ Please add assets to the pool before running analysis", 
                                    style={'color': THEME['warning'], 'fontWeight': 'bold'})
                return (html.Div("No assets in pool.", style={'color': THEME['warning']}),
                        error_msg, "", {}, {})
            
            # Convert capital to CNY
            multiplier = 1e9 if capital_unit == 'billion' else 1e6
            total_capital_cny = float(total_capital) * multiplier
            
            # Get selected assets
            selected_asset_names = [asset['name'] for asset in asset_pool]
            
            # Build risk budgets based on allocation mode
            risk_budgets = None
            rp_budgets_out = {}
            factor_names_in_pool = [id_dict['index'] for id_dict in (budget_ids or [])]
            total_capital_m = total_capital_cny / 1e6

            if allocation_mode == 'risk_parity':
                # Pure Risk Parity: optimizer runs unconstrained ERC — always deterministic.
                # rp_budgets_out will be filled from optimizer factor vols after the run.
                risk_budgets = None

            elif allocation_mode == 'factor_scaling':
                # Factor Model Scaling: inverse-vol base budgets, scaled by signal scalar.
                _vm = compute_factor_vol_map(factor_names_in_pool) if factor_names_in_pool else {}
                _iv = {f: 1.0 / _vm[f] for f in factor_names_in_pool
                       if _vm.get(f) and pd.notna(_vm[f]) and _vm[f] > 0}
                _tot = sum(_iv.values())
                n_pool = len(factor_names_in_pool) or 1
                _base = (
                    {f: round(total_capital_m * _iv.get(f, 0.0) / _tot, 2) for f in factor_names_in_pool}
                    if _tot > 0
                    else {f: round(total_capital_m / n_pool, 2) for f in factor_names_in_pool}
                )
                if signal_snapshot:
                    _snap = {rec['risk_factor']: rec for rec in signal_snapshot if rec.get('risk_factor')}
                    risk_budgets = {}
                    scaled_count = 0
                    for f, base_val in _base.items():
                        rec = _snap.get(f)
                        if rec is not None:
                            risk_budgets[f] = round(base_val * float(rec.get('scalar', 1.0)), 2)
                            scaled_count += 1
                        else:
                            risk_budgets[f] = base_val
                    print(f"📡 Factor model scaling applied to {scaled_count} risk budgets")
                else:
                    risk_budgets = _base
                # Store unscaled base budgets — same signals → same result → idempotent
                rp_budgets_out = _base

            else:  # user_defined
                # User Defined: use input-box values exactly; write them back unchanged.
                if budget_ids and budget_values:
                    risk_budgets = {}
                    for val, id_dict in zip(budget_values, budget_ids):
                        factor_name = id_dict['index']
                        try:
                            risk_budgets[factor_name] = float(val) if val is not None else 1.0
                        except (ValueError, TypeError):
                            pass
                rp_budgets_out = dict(risk_budgets) if risk_budgets else {}

            # Run optimization
            summary, returns, vols, factor_exp, factor_risk, portfolio = run_risk_parity_allocation(
                total_capital=total_capital_cny, use_cache=True, selected_assets=selected_asset_names,
                risk_budgets=risk_budgets, use_deterministic=True
            )
            
            if summary.empty:
                error_msg = html.Span("⚠ No matching assets found in optimization results", 
                                    style={'color': THEME['warning'], 'fontWeight': 'bold'})
                return (html.Div("No matching assets found.", style={'color': THEME['warning']}),
                        error_msg, "", {}, {})
            
            # Update global state
            ALLOCATION_RESULTS.update({
                'summary': summary, 'factor_exposures': factor_exp,
                'factor_risk': factor_risk, 'portfolio': portfolio,
                'timestamp': datetime.now()
            })
            
            # Prepare portfolio table
            portfolio_df = prepare_portfolio_table(summary, factor_exp, portfolio)
            portfolio_enhanced = []
            total_rounded_capital = 0.0
            
            if not portfolio_df.empty:
                _units = np.where(
                    portfolio_df['Asset Type'].isin(('Rates', 'Spread')),
                    10_000_000.0,
                    1_000_000.0,
                )
                _rounded = np.floor(portfolio_df['Capital (CNY)'].values / _units) * _units
                total_rounded_capital = float(_rounded.sum())
                _display_df = portfolio_df.copy()
                _display_df['Capital (CNY)'] = [f"{v / 1_000_000:,.2f}" for v in _rounded]
                _display_df['Weight (%)'] = portfolio_df['Weight (%)'].map(lambda v: f"{v:.2f}%")
                portfolio_enhanced = _display_df.to_dict('records')
            
            portfolio_table_df = pd.DataFrame(portfolio_enhanced)
            
            # Add totals row
            if not portfolio_table_df.empty:
                totals = {
                    'Asset Type': 'TOTAL', 'Universe': '', 'Sector': '', 'Asset Name': '',
                    'Capital (CNY)': f"{total_rounded_capital / 1_000_000:,.2f}",
                    'Weight (%)': f"{summary['Weight (%)'].sum():.2f}%"
                }
                portfolio_table_df = pd.concat([portfolio_table_df, pd.DataFrame([totals])], ignore_index=True)
            
            # Create table
            portfolio_table = dash_table.DataTable(
                data=portfolio_table_df.to_dict('records'),
                columns=[
                    {'name': 'Asset Type', 'id': 'Asset Type'},
                    {'name': 'Universe', 'id': 'Universe'},
                    {'name': 'Sector', 'id': 'Sector'},
                    {'name': 'Asset Name', 'id': 'Asset Name'},
                    {'name': 'Capital (Million CNY)', 'id': 'Capital (CNY)'},
                    {'name': 'Weight', 'id': 'Weight (%)'},
                ],
                style_cell={
                    'textAlign': 'center', 
                    'padding': '10px', 
                    'fontFamily': 'Arial, sans-serif',
                    'backgroundColor': THEME['table_row_odd'],
                    'color': THEME['text_main'],
                    'border': 'none'
                },
                style_header={
                    'backgroundColor': THEME['table_header'], 
                    'color': THEME['text_main'], 
                    'fontWeight': 'bold', 
                    'textAlign': 'center',
                    'border': 'none'
                },
                style_data_conditional=[
                    {'if': {'filter_query': '{Asset Type} = "TOTAL"'}, 'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'], 'fontWeight': 'bold'},
                    {'if': {'row_index': 'even'}, 'backgroundColor': THEME['table_row_even']}
                ],
                style_table={'overflowX': 'auto'}
            )
            
            status_msg = html.Span("✓ Analysis completed successfully!", style={'color': THEME['success'], 'fontWeight': 'bold'})
            timestamp_msg = f"Last updated: {ALLOCATION_RESULTS['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}"

            # For Pure Risk Parity: derive RP Max from actual factor risk contributions
            # returned by the full-covariance optimizer (proper ERC attribution).
            if allocation_mode == 'risk_parity':
                factor_risk = ALLOCATION_RESULTS.get('factor_risk', pd.DataFrame())
                if (not factor_risk.empty
                        and 'Risk Factor' in factor_risk.columns
                        and 'Risk Contribution (%)' in factor_risk.columns):
                    _valid_rc = factor_risk[pd.notna(factor_risk['Risk Contribution (%)'])]
                    rc_map = dict(zip(_valid_rc['Risk Factor'], _valid_rc['Risk Contribution (%)']))
                    total_rc = sum(v for v in rc_map.values() if v > 0)
                    if total_rc > 1e-6:
                        rp_budgets_out = {
                            f: round(total_capital_m * v / total_rc, 2)
                            for f, v in rc_map.items() if v > 0
                        }
                    else:
                        # Fallback: inv-vol proportional
                        _fnames_erc = list(vols.index) if hasattr(vols, 'index') else []
                        _iv = {f: 1.0/float(vols[f]) for f in _fnames_erc
                               if pd.notna(vols.get(f)) and float(vols[f]) > 0}
                        _tot = sum(_iv.values()) or 1.0
                        rp_budgets_out = {f: round(total_capital_m * v / _tot, 2) for f, v in _iv.items()}
                else:
                    # Fallback: inv-vol proportional
                    _fnames_erc = list(vols.index) if hasattr(vols, 'index') else []
                    _iv = {f: 1.0/float(vols[f]) for f in _fnames_erc
                           if pd.notna(vols.get(f)) and float(vols[f]) > 0}
                    _tot = sum(_iv.values()) or 1.0
                    rp_budgets_out = {f: round(total_capital_m * v / _tot, 2) for f, v in _iv.items()}
            # factor_scaling and user_defined already have rp_budgets_out set above

            # ── Save Beta snapshot for Summary tab ────────────────────────────
            try:
                import pathlib
                pathlib.Path(_SUMMARY_BETA_PARQUET).parent.mkdir(parents=True, exist_ok=True)
                _snap = portfolio_df.copy()
                _snap['_timestamp'] = datetime.now().isoformat()
                _snap['_capital_cny'] = _snap['Capital (CNY)']
                # Ensure all factor-sensitivity columns are float (serialisable)
                for _c in _snap.columns:
                    if _c not in ('Asset Type', 'Universe', 'Sector', 'Asset Name',
                                  '_timestamp', '_capital_cny'):
                        _snap[_c] = pd.to_numeric(_snap[_c], errors='coerce')
                _snap.to_parquet(_SUMMARY_BETA_PARQUET, index=False)
                print(f"✓ Beta portfolio snapshot saved → {_SUMMARY_BETA_PARQUET}")
            except Exception as _se:
                print(f"Warning: Could not save Beta snapshot: {_se}")

            return (portfolio_table, status_msg, timestamp_msg, {'status': 'success'}, rp_budgets_out)
            
        except Exception as e:
            # Print full traceback for debugging
            print(f"\n{'='*80}")
            print("ERROR in run_analysis callback:")
            print(f"{'='*80}")
            traceback.print_exc()
            print(f"{'='*80}\n")
            
            error_msg = html.Span(f"✗ Error: {str(e)}", style={'color': THEME['danger'], 'fontWeight': 'bold'})
            return (html.Div(f"Error: {str(e)}", style={'color': THEME['danger']}),
                    error_msg, "", {}, {})

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

        if alloc_mode == 'factor_scaling':
            unavail_fig = go.Figure()
            unavail_fig.update_layout(
                title="Factor Model Scaling — not available yet",
                annotations=[{
                    'text': 'Factor Model Scaling requires per-factor signal backtests which are still in development.<br>'
                            'Please use Pure Risk Parity.',
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
                "Factor Model Scaling is not yet available — factor signal backtests are pending.",
                style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'},
            )

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

    # 6. Futures Backtest Callbacks
    @app.callback(
        [Output('bf-wind-inputs', 'style'), Output('bf-local-inputs', 'style')],
        [Input('bf-data-source', 'value')]
    )
    def bf_toggle_inputs(source):
        if source == 'wind':
            return {'display': 'block'}, {'display': 'none'}
        return {'display': 'none'}, {'display': 'block'}
    
    @app.callback(
        Output('bf-timeframe-container', 'style'),
        [Input('bf-trading-mode', 'value')]
    )
    def bf_toggle_timeframe(mode):
        if mode == 'daily':
            return {'display': 'none'}
        return {'display': 'block'}
    
    @app.callback(
        [Output('bf-wind-code', 'options'), Output('bf-wind-code', 'value')],
        [Input('bf-trading-mode', 'value')]
    )
    def bf_update_wind_options(mode):
        if not FUTURES_AVAILABLE: return [], None
        try:
            if mode == 'daily':
                opts = [{'label': s, 'value': s} for s in FuturesConfig.SYMBOLS]
                def_val = 'TL.CFE' if 'TL.CFE' in FuturesConfig.SYMBOLS else FuturesConfig.SYMBOLS[0]
            else:
                contract_list = FuturesConfig.get_contract_no()
                opts = [{'label': c, 'value': c} for c in contract_list]
                def_val = contract_list[0] if contract_list else None
            return opts, def_val
        except Exception:
             return [], None

    @app.callback(
        [Output('bf-local-symbol', 'options'),
         Output('bf-local-symbol', 'value')],
        [Input('bf-trading-mode', 'value')]
    )
    def bf_update_local_symbol_options(mode):
        if not FUTURES_AVAILABLE: return [], None
        try:
            if mode == 'daily':
                opts = [{'label': s, 'value': s} for s in FuturesConfig.SYMBOLS]
                def_val = 'TL.CFE' if 'TL.CFE' in FuturesConfig.SYMBOLS else FuturesConfig.SYMBOLS[0]
            else:
                contract_list = FuturesConfig.get_contract_no()
                opts = [{'label': c, 'value': c} for c in contract_list]
                def_val = contract_list[0] if contract_list else None
            return opts, def_val
        except Exception:
             return [], None

    @app.callback(
        Output('bf-results-container', 'children'),
        [Input('bf-run-button', 'n_clicks')],
        [State('bf-data-source', 'value'),
         State('bf-trading-mode', 'value'),
         State('bf-wind-code', 'value'),
         State('bf-local-symbol', 'value'),
         State('bf-date-range', 'start_date'),
         State('bf-date-range', 'end_date'),
         State('bf-timeframe', 'value'),
         State('bf-strategy-selector', 'value'),
         State('bf-ma-short', 'value'),
         State('bf-ma-long', 'value'),
         State('bf-boll-window', 'value'),
         State('bf-boll-std', 'value'),
         State('bf-boll-exit', 'value'),
         State('bf-vwap-window', 'value'),
         State('bf-mom-window', 'value'),
         State('bf-atr-ema-window', 'value'),
         State('bf-atr-window', 'value'),
         State('bf-sar-af', 'value'),
         State('bf-sar-max-af', 'value')]
    )
    def bf_update_dashboard(n_clicks, source, trading_mode, wind_code, local_symbol, start_date, end_date, tf, 
                         selected_strategies,
                         ma_s, ma_l, boll_w, boll_std, boll_exit, vwap_w, mom_w, atr_ema_w, atr_w,
                         sar_af, sar_max_af):
        if n_clicks == 0:
            return html.Div('Please configure parameters and click "Start Backtest"', style={'text-align': 'center', 'marginTop': '50px', 'color': THEME['text_sub']})
        
        if not FUTURES_AVAILABLE:
            return html.Div("Modules not loaded.", style={'color': THEME['danger']})

        selected_strategies = selected_strategies or []
        effective_tf = '1D' if trading_mode == 'daily' else tf
        
        # Load Data
        df = None
        err_msg = None
        
        try:
            if source == 'wind':
                if not wind_code: return html.Div("Please enter Wind symbol", style={'color': THEME['danger']})
                s_str = f"{start_date} 00:00:00"
                e_str = f"{end_date} 23:59:59"
                df, err_msg = load_wind_data(wind_code, s_str, e_str)
            else:
                if not local_symbol: return html.Div("Please enter symbol", style={'color': THEME['danger']})
                file_path = get_local_file_path(local_symbol, effective_tf)
                if not file_path:
                    return html.Div("Unable to construct file path", style={'color': THEME['danger']})
                
                contract_key = local_symbol if trading_mode == 'daily' else None
                df, err_msg = load_local_data_processed(file_path, contract_key)
                if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
                    s_ts = pd.to_datetime(start_date)
                    e_ts = pd.to_datetime(end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                    df = df[(df.index >= s_ts) & (df.index <= e_ts)]
                
            if err_msg:
                return html.Div(f"Data loading error: {err_msg}", style={'color': THEME['danger']})
            if df is None or (isinstance(df, pd.DataFrame) and df.empty):
                return html.Div("Data is empty (please check date range)", style={'color': THEME['danger']})

            # Resample
            if effective_tf == '1D':
                if not isinstance(df.index, pd.DatetimeIndex):
                    df.index = pd.to_datetime(df.index, errors='coerce')
                df_resampled = df.copy()
                df_resampled = df_resampled[~df_resampled.index.duplicated(keep='last')]
            else:
                df_resampled = resample_data(df, effective_tf)
                
            if df_resampled.empty:
                return html.Div("Data is empty after resampling", style={'color': THEME['danger']})
                
            # Run strategies
            results = {}
            if 'MA' in selected_strategies:
                results['MA'] = run_ma_strategy(df_resampled, ma_s, ma_l)
            if 'DeMark' in selected_strategies:
                results['DeMark'] = run_demark_strategy(df_resampled)
            if 'Boll' in selected_strategies:
                exit_at_ma = 'exit' in (boll_exit or [])
                results['Boll'] = run_bollinger_strategy(df_resampled, boll_w, boll_std, exit_at_ma)
            if 'VWAP' in selected_strategies:
                results['VWAP'] = run_vwap_strategy(df_resampled, vwap_w)
            if 'Mom' in selected_strategies:
                results['Mom'] = run_intraday_momentum_strategy(df_resampled, mom_w)
            if 'ATR' in selected_strategies:
                results['ATR'] = run_atr_band_strategy(df_resampled, atr_ema_w, atr_w)
            if 'SAR' in selected_strategies:
                results['SAR'] = run_sar_strategy(df_resampled, sar_af, sar_max_af)

            # Create Plotly Chart
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                                vertical_spacing=0.03, row_heights=[0.7, 0.3])

            # Candlestick
            fig.add_trace(go.Candlestick(
                x=df_resampled.index,
                open=df_resampled['open'], high=df_resampled['high'],
                low=df_resampled['low'], close=df_resampled['close'],
                name='Price'
            ), row=1, col=1)

            if 'DeMark' in results:
                df_demark = results['DeMark']
                for col, color, name in [
                    ('tdst_support', '#2ecc71', 'TDST Support'),
                    ('tdst_resistance', '#e74c3c', 'TDST Resistance'),
                ]:
                    series = df_demark[col].dropna()
                    if not series.empty:
                        fig.add_trace(go.Scatter(
                            x=series.index,
                            y=series.values,
                            mode='lines',
                            name=name,
                            line=dict(color=color, width=1.2, dash='dot')
                        ), row=1, col=1)

                for flag_col, name, symbol, color, price_col in [
                    ('buy_setup_complete', 'TD Buy Setup 9', 'triangle-up', '#27ae60', 'low'),
                    ('sell_setup_complete', 'TD Sell Setup 9', 'triangle-down', '#c0392b', 'high'),
                    ('buy_countdown_complete', 'TD Buy Countdown 13', 'star', '#2ecc71', 'low'),
                    ('sell_countdown_complete', 'TD Sell Countdown 13', 'star', '#e74c3c', 'high'),
                ]:
                    mask = df_demark[flag_col].eq(1)
                    if mask.any():
                        fig.add_trace(go.Scatter(
                            x=df_demark.index[mask],
                            y=df_demark.loc[mask, price_col],
                            mode='markers',
                            name=name,
                            marker=dict(symbol=symbol, color=color, size=10)
                        ), row=1, col=1)
            
            # Strategy Equity Curves
            for name, res in results.items():
                fig.add_trace(go.Scatter(
                    x=res.index, 
                    y=res['cumulative_returns'],
                    mode='lines', name=f'{name} Equity'
                ), row=2, col=1)

            fig.update_layout(
                height=600, 
                title="Backtest Results",
                template=THEME['chart_template'],
                paper_bgcolor=THEME['bg_card'],
                plot_bgcolor=THEME['bg_card'],
                font={'color': THEME['text_main']},
                margin=dict(l=50, r=50, t=50, b=50),
                legend=dict(orientation="h", y=1.02, x=0.5, xanchor="center"),
                xaxis_rangeslider_visible=False
            )
            fig.update_xaxes(gridcolor=THEME['table_header'])
            fig.update_yaxes(gridcolor=THEME['table_header'])

            # Helper for local Metric Card (redefined here or duplicated logic)
            def create_metric_card_local(title, metrics):
                return html.Div([
                    html.H6(title, style={'color': THEME['text_sub'], 'marginBottom': '5px', 'fontSize': '14px'}),
                    html.Div([
                        html.Div(f"Ret: {metrics.get('Total Return', 'N/A')}", style={'fontWeight': 'bold', 'color': THEME['success'] if str(metrics.get('Total Return')).startswith('+') else THEME['text_main']}),
                        html.Div(f"DD: {metrics.get('Max Drawdown', 'N/A')}", style={'color': THEME['danger']}),
                        html.Div(f"Sharpe: {metrics.get('Sharpe Ratio', 'N/A')}"),
                        html.Div(f"Trades: {metrics.get('Trades', 'N/A')}"),
                    ], style={'fontSize': '12px', 'lineHeight': '1.5', 'display': 'grid', 'gridTemplateColumns': '1fr 1fr', 'gap': '5px'})
                ], style={'backgroundColor': THEME['bg_input'], 'padding': '10px', 'borderRadius': '4px', 'marginBottom': '10px', 'flex': '1', 'minWidth': '150px'})

            # Card Display
            cards = []
            
            for name, res in results.items():
                m = calculate_metrics(res)
                cards.append(create_metric_card_local(name, m))
                
            return html.Div([
                html.Div(cards, style={'display': 'flex', 'flexWrap': 'wrap', 'gap': '10px', 'marginBottom': '15px'}),
                dcc.Graph(figure=fig)
            ])

        except Exception as e:
            import traceback
            traceback.print_exc()
            return html.Div(f"Error running backtest: {str(e)}", style={'color': THEME['danger']})

    # ================================================================
    # Risk Factor Backtest callbacks (BACKTEST subtab)
    # ================================================================

    @app.callback(
        [Output('rfbt-ma-params', 'style'),
         Output('rfbt-boll-params', 'style'),
         Output('rfbt-mom-params', 'style'),
         Output('rfbt-zscore-params', 'style'),
         Output('rfbt-fm-params', 'style')],
        Input('rfbt-strategy-selector', 'data'),
    )
    def toggle_rfbt_strategy_params(strategy):
        """Show/hide strategy-specific parameter inputs."""
        flex = {'display': 'flex', 'alignItems': 'center'}
        hide = {'display': 'none', 'alignItems': 'center'}
        return (hide, hide, hide, hide, flex)

    @app.callback(
        Output('rfbt-status', 'children', allow_duplicate=True),
        Input('rfbt-generate-btn', 'n_clicks'),
        prevent_initial_call=True,
    )
    def generate_factor_rates_click(n_clicks):
        """Generate (or regenerate) factor-rates.pkl."""
        if not n_clicks:
            raise dash.exceptions.PreventUpdate
        try:
            from multiasset.factor_backtest import generate_factor_rates
            df = generate_factor_rates(DIR_INPUT, save=True)
            return f"✅ factor-rates.pkl saved ({df.shape[1]} factors, {len(df)} days)"
        except Exception as e:
            return f"❌ Error: {e}"

    @app.callback(
        [Output('rfbt-results-container', 'children'),
         Output('rfbt-status', 'children')],
        Input('rfbt-run-btn', 'n_clicks'),
        [State('rfbt-factor-selector', 'value'),
         State('rfbt-strategy-selector', 'data'),
         State('rfbt-date-range', 'start_date'),
         State('rfbt-date-range', 'end_date'),
         State('rfbt-ma-short', 'value'),
         State('rfbt-ma-long', 'value'),
         State('rfbt-boll-window', 'value'),
         State('rfbt-boll-std', 'value'),
         State('rfbt-mom-window', 'value'),
         State('rfbt-zscore-window', 'value'),
         State('rfbt-zscore-entry', 'value'),
         State('rfbt-zscore-exit', 'value'),
         State('rfbt-fm-train', 'value'),
         State('rfbt-fm-ic', 'value'),
         State('rfbt-fm-topn', 'value')],
        prevent_initial_call=True,
    )
    def run_risk_factor_backtest(
        n_clicks, factors, strategy, start_date, end_date,
        ma_short, ma_long, boll_window, boll_std,
        mom_window, zscore_window, zscore_entry, zscore_exit,
        fm_train, fm_ic, fm_topn,
    ):
        if not n_clicks or not factors:
            raise dash.exceptions.PreventUpdate

        try:
            from multiasset.factor_backtest import (
                run_factor_backtest, compute_metrics, get_factor_duration,
                _is_yield_factor,
            )

            # Build strategy-specific kwargs – always FactorModel
            strategy = 'FactorModel'
            kwargs = {'train_months': int(fm_train or 12),
                      'ic_threshold': float(fm_ic or 0.05),
                      'top_n': int(fm_topn or 8)}

            results = run_factor_backtest(
                factors=factors,
                strategy=strategy,
                start_date=start_date,
                end_date=end_date,
                input_dir=DIR_INPUT,
                save=True,
                **kwargs,
            )

            if not results:
                return (
                    html.Div("No results — check that factor-rates.pkl exists and factors have data.",
                             style={'color': THEME['warning'], 'padding': '20px'}),
                    "⚠️ No factors produced results",
                )

            # ── Build summary metrics table ─────────────────────────────
            metric_rows = []
            for factor, df in results.items():
                m = compute_metrics(df)
                dur = get_factor_duration(factor)
                is_y = _is_yield_factor(factor)
                metric_rows.append({
                    'Factor': factor,
                    'Type': 'Yield' if is_y else 'Price',
                    'Scale': f'{dur:.1f}' if dur > 0 else '—',
                    'Total Ret': f"{m.get('Total Return', 0):.2%}",
                    'Ann Ret': f"{m.get('Ann. Return', 0):.2%}",
                    'Ann Vol': f"{m.get('Ann. Vol', 0):.2%}",
                    'Sharpe': f"{m.get('Sharpe', 0):.2f}",
                    'Max DD': f"{m.get('Max Drawdown', 0):.2%}",
                    'Win': f"{m.get('Win Rate', 0):.1%}",
                    'Days': int(m.get('Days', 0)),
                })

            metrics_table = dash_table.DataTable(
                data=metric_rows,
                columns=[{'name': c, 'id': c} for c in metric_rows[0].keys()],
                style_cell={'textAlign': 'center', 'padding': '6px 8px',
                            'backgroundColor': THEME['bg_input'],
                            'color': THEME['text_main'], 'border': 'none',
                            'fontSize': '11px'},
                style_header={'backgroundColor': THEME['table_header'],
                              'fontWeight': 'bold', 'color': THEME['accent'],
                              'border': 'none'},
                style_data_conditional=[
                    {'if': {'row_index': 'odd'},
                     'backgroundColor': THEME['table_row_even']},
                ],
                style_table={'overflowX': 'auto', 'marginBottom': '16px'},
            )

            # ── Build cumulative return chart ───────────────────────────
            fig = go.Figure()
            colors = ['#3498db', '#e74c3c', '#2ecc71', '#f39c12',
                      '#9b59b6', '#1abc9c', '#e67e22', '#34495e',
                      '#E91E63', '#00BCD4']
            for i, (factor, df) in enumerate(results.items()):
                cum = df['cumulative_returns'].dropna()
                fig.add_trace(go.Scatter(
                    x=cum.index, y=cum.values, mode='lines',
                    name=factor, line={'color': colors[i % len(colors)]},
                ))

            fig.update_layout(
                title=f'Cumulative Returns — {strategy} Strategy',
                xaxis_title='Date', yaxis_title='Cumulative Return',
                hovermode='x unified',
                template=THEME['chart_template'], height=420,
                paper_bgcolor=THEME['bg_main'],
                plot_bgcolor=THEME['bg_main'],
                font={'color': THEME['text_main']},
                legend=dict(orientation='h', yanchor='bottom', y=1.02,
                            xanchor='right', x=1,
                            font={'color': THEME['text_main']}),
                xaxis=dict(gridcolor=THEME['table_header']),
                yaxis=dict(gridcolor=THEME['table_header']),
            )

            # ── Build signals chart (subplots per factor) ──────────────
            n_factors = len(results)
            signal_fig = make_subplots(
                rows=n_factors, cols=1, shared_xaxes=True,
                subplot_titles=list(results.keys()),
                vertical_spacing=0.04,
            )
            for i, (factor, df) in enumerate(results.items(), start=1):
                sig = df['signal'].dropna()
                signal_fig.add_trace(
                    go.Scatter(
                        x=sig.index, y=sig.values, mode='lines',
                        name=f'{factor} sig',
                        line={'color': colors[(i - 1) % len(colors)], 'width': 1},
                    ),
                    row=i, col=1,
                )

            signal_fig.update_layout(
                title='Positions / Signals',
                height=max(200, 120 * n_factors),
                template=THEME['chart_template'],
                paper_bgcolor=THEME['bg_main'],
                plot_bgcolor=THEME['bg_main'],
                font={'color': THEME['text_main']},
                showlegend=False,
            )

            status_msg = (f"✅ Backtest complete — {strategy} on "
                          f"{len(results)} factors, saved to factor-backtest.pkl")

            return (
                html.Div([
                    metrics_table,
                    dcc.Graph(figure=fig),
                    dcc.Graph(figure=signal_fig),
                ]),
                status_msg,
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return (
                html.Div(f"Error: {e}",
                         style={'color': THEME['danger'], 'padding': '20px'}),
                f"❌ {e}",
            )

    # ── IRDL Hedge Overlay callback ───────────────────────────────────────────
    @app.callback(
        Output('irdl-hedge-ticket-container', 'children'),
        [
            Input('portfolio-data-store', 'data'),
            Input('irdl-hedge-ratio', 'value'),
            Input('irdl-hedge-instrument', 'value'),
            Input('irdl-hedge-irs-maturity', 'value'),
            Input({'type': 'irdl-dv01-override', 'index': ALL}, 'value'),
        ],
        [
            State({'type': 'irdl-dv01-override', 'index': ALL}, 'id'),
            State('capital-input', 'value'),
            State('capital-unit', 'value'),
        ],
        prevent_initial_call=True,
    )
    def update_irdl_hedge_ticket(
        store_data, hedge_ratio_pct, instrument, irs_maturity,
        dv01_values, dv01_ids, capital_value, capital_unit,
    ):
        factor_risk = ALLOCATION_RESULTS.get('factor_risk')
        if factor_risk is None or factor_risk.empty:
            return html.Div(
                "Run Analysis first to compute portfolio exposures.",
                style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px'},
            )
        if 'Net Exposure' not in factor_risk.columns:
            return html.Div(
                "Net Exposure column not available — re-run Analysis.",
                style={'color': THEME['warning'], 'fontSize': '12px'},
            )

        try:
            # Build capital
            multiplier = 1e9 if capital_unit == 'billion' else 1e6
            total_capital = float(capital_value or 10) * multiplier

            # Build DV01 overrides dict
            dv01_overrides = {}
            for val, id_dict in zip(dv01_values or [], dv01_ids or []):
                cty = id_dict['index']
                if val is not None:
                    try:
                        dv01_overrides[cty] = float(val)
                    except (ValueError, TypeError):
                        pass

            hedge_ratio = (hedge_ratio_pct or 0) / 100.0

            tickets = compute_irdl_hedge(
                factor_risk_records=factor_risk.to_dict('records'),
                total_capital=total_capital,
                hedge_ratio=hedge_ratio,
                instrument=instrument or 'futures',
                dv01_overrides=dv01_overrides if dv01_overrides else None,
                irs_maturity=irs_maturity or '10Y',
            )

            if not tickets:
                return html.Div(
                    "No IRDL factors found in current allocation.",
                    style={'color': THEME['text_sub'], 'fontStyle': 'italic', 'fontSize': '12px'},
                )

            _dir_color = {
                'SHORT':     THEME.get('danger', '#e74c3c'),
                'PAY FIXED': THEME.get('danger', '#e74c3c'),
                'LONG':      THEME.get('success', '#27ae60'),
                'RCV FIXED': THEME.get('success', '#27ae60'),
            }

            return html.Div([
                html.Div(
                    f"Hedge ratio: {hedge_ratio_pct}%  ·  Instrument: "
                    f"{'Bond Futures' if instrument == 'futures' else 'Pay-fixed IRS'}  ·  "
                    f"Capital: {float(capital_value or 10):,.0f} {capital_unit}",
                    style={'color': THEME['text_sub'], 'fontSize': '11px', 'marginBottom': '8px'},
                ),
                dash_table.DataTable(
                    data=tickets,
                    columns=[
                        {'name': 'Country',            'id': 'Country'},
                        {'name': 'Net IRDL Exp (DY)',  'id': 'Net IRDL Exp (DY)'},
                        {'name': 'Port DV01 (CNY/bp)', 'id': 'Port DV01 (CNY/bp)'},
                        {'name': 'Hedge DV01 (CNY/bp)', 'id': 'Hedge DV01 (CNY/bp)'},
                        {'name': 'Quantity',           'id': 'Quantity'},
                        {'name': 'Direction',          'id': 'Direction'},
                        {'name': 'Instrument',         'id': 'Instrument'},
                    ],
                    style_cell={
                        'textAlign': 'center', 'padding': '8px 10px',
                        'fontSize': '12px',
                        'backgroundColor': THEME['table_row_odd'],
                        'color': THEME['text_main'], 'border': 'none',
                    },
                    style_header={
                        'backgroundColor': THEME['table_header'],
                        'color': THEME['text_main'],
                        'fontWeight': 'bold', 'border': 'none',
                    },
                    style_data_conditional=[
                        {'if': {'row_index': 'even'}, 'backgroundColor': THEME['table_row_even']},
                        *[
                            {'if': {'filter_query': f'{{Direction}} = "{d}"', 'column_id': 'Direction'},
                             'color': c, 'fontWeight': 'bold'}
                            for d, c in _dir_color.items()
                        ],
                        {'if': {'filter_query': '{Net IRDL Exp (DY)} > 0', 'column_id': 'Net IRDL Exp (DY)'},
                         'color': THEME.get('success', '#27ae60')},
                        {'if': {'filter_query': '{Net IRDL Exp (DY)} < 0', 'column_id': 'Net IRDL Exp (DY)'},
                         'color': THEME.get('danger', '#e74c3c')},
                    ],
                    style_table={'overflowX': 'auto'},
                ),
            ])

        except Exception as exc:
            return html.Div(
                f"Error computing hedge: {exc}",
                style={'color': THEME['danger'], 'fontSize': '12px'},
            )

    # ── Summary tab: Beta / Alpha portfolio table callback ────────────────────
    @app.callback(
        [Output('summary-book-table-container', 'children'),
         Output('summary-refresh-status', 'children')],
        [Input('summary-book-tabs', 'value'),
         Input('summary-refresh-btn', 'n_clicks')],
    )
    def update_summary_book_table(tab_value, _n_clicks):
        """Load the saved parquet snapshot and render a styled table with
        Close Price and Market Value columns."""
        import os as _os

        def _no_data(msg: str):
            return (
                html.Div(msg, style={
                    'color': THEME['text_sub'], 'fontStyle': 'italic',
                    'padding': '30px', 'textAlign': 'center', 'fontSize': '13px',
                }),
                "",
            )

        # ── Beta tab ──────────────────────────────────────────────────────────
        if tab_value == 'beta':
            if not _os.path.exists(_SUMMARY_BETA_PARQUET):
                return _no_data(
                    "No Beta snapshot found. Click RUN ANALYSIS in the Beta Book → Portfolio tab first."
                )
            try:
                df = pd.read_parquet(_SUMMARY_BETA_PARQUET)
                ts = df['_timestamp'].iloc[0] if '_timestamp' in df.columns else "unknown"

                # Close Price: look up last factor level for each asset's primary factor
                close_prices = _get_beta_close_prices()

                def _close_price_for(asset_name: str) -> float | None:
                    """Match asset name prefix to a factor-level proxy."""
                    for prefix, price in close_prices.items():
                        if asset_name.upper().startswith(prefix.upper()):
                            return price
                    return None

                capital_col = '_capital_cny' if '_capital_cny' in df.columns else 'Capital (CNY)'
                display_rows = []
                for _, row in df.iterrows():
                    asset = str(row.get('Asset Name', ''))
                    if asset == 'TOTAL':
                        continue
                    cap_cny = float(row.get(capital_col, 0) or 0)
                    cap_mm  = round(cap_cny / 1e6, 2)
                    wt      = round(float(row.get('Weight (%)', 0) or 0), 2)
                    cp      = _close_price_for(asset)
                    mv_mm   = cap_mm   # bonds at ~par → market value ≈ notional

                    display_rows.append({
                        'Asset Type':        row.get('Asset Type', ''),
                        'Universe':          row.get('Universe', ''),
                        'Asset Name':        asset,
                        'Close Price (%)':   f"{cp:.4f}" if cp is not None else 'N/A',
                        'Capital (MM CNY)':  f"{cap_mm:,.2f}",
                        'Market Value (MM)': f"{mv_mm:,.2f}",
                        'Weight (%)':        f"{wt:.2f}%",
                    })

                if not display_rows:
                    return _no_data("Beta snapshot is empty.")

                table = dash_table.DataTable(
                    data=display_rows,
                    columns=[{'name': c, 'id': c} for c in display_rows[0].keys()],
                    style_cell={
                        'textAlign': 'center', 'padding': '8px',
                        'backgroundColor': THEME['table_row_odd'],
                        'color': THEME['text_main'], 'border': 'none',
                        'fontSize': '12px',
                    },
                    style_header={
                        'backgroundColor': THEME['table_header'],
                        'color': THEME['text_main'],
                        'fontWeight': 'bold', 'border': 'none',
                    },
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                    ],
                    style_table={'overflowX': 'auto'},
                    sort_action='native',
                    page_size=20,
                )
                status = f"Beta snapshot from {ts[:19]}"
                return table, status

            except Exception as exc:
                return _no_data(f"Error loading Beta snapshot: {exc}")

        # ── Alpha tab ─────────────────────────────────────────────────────────
        elif tab_value == 'alpha':
            if not _os.path.exists(_SUMMARY_ALPHA_PARQUET):
                return _no_data(
                    "No Alpha snapshot found. Click RUN OPTIMIZATION in the Alpha Book → Portfolio tab first."
                )
            try:
                df = pd.read_parquet(_SUMMARY_ALPHA_PARQUET)
                ts = df['_timestamp'].iloc[0] if '_timestamp' in df.columns else "unknown"

                display_rows = []
                for _, row in df.iterrows():
                    trade_id = str(row.get('ID', ''))
                    if trade_id in ('TOTAL', ''):
                        continue
                    spread_val = row.get('spread', None)
                    cp_bp      = round(float(spread_val), 4) if pd.notna(spread_val) else None
                    notional   = float(row.get('notional_mm', 0) or 0)
                    dv01_k     = float(row.get('DV01_k', 0) or 0)
                    # Mark-to-market = DV01 × current spread level
                    mv_mm = round(dv01_k * float(cp_bp) / 1000, 3) if cp_bp is not None else None

                    display_rows.append({
                        'ID':                  trade_id,
                        'Spread Type':         row.get('spread_type', ''),
                        'Style':               row.get('style', ''),
                        'Direction':           row.get('direction', ''),
                        'Z-Score':             f"{float(row.get('Zscore', 0) or 0):.2f}",
                        'Close Price (bp)':    f"{cp_bp:.4f}" if cp_bp is not None else 'N/A',
                        'Notional (MM CNY)':   f"{notional:,.1f}",
                        'DV01 (k CNY/bp)':     f"{dv01_k:.1f}",
                        'MtM Value (MM CNY)':  f"{mv_mm:,.3f}" if mv_mm is not None else 'N/A',
                        'Weight (%)':          f"{float(row.get('weight', 0) or 0) * 100:.2f}%",
                    })

                if not display_rows:
                    return _no_data("Alpha snapshot is empty.")

                dir_styles = [
                    {'if': {'filter_query': '{Direction} = "BUY"'},
                     'backgroundColor': 'rgba(0, 204, 150, 0.12)'},
                    {'if': {'filter_query': '{Direction} = "SELL"'},
                     'backgroundColor': 'rgba(239, 85, 59, 0.12)'},
                ]
                table = dash_table.DataTable(
                    data=display_rows,
                    columns=[{'name': c, 'id': c} for c in display_rows[0].keys()],
                    style_cell={
                        'textAlign': 'center', 'padding': '8px',
                        'backgroundColor': THEME['table_row_odd'],
                        'color': THEME['text_main'], 'border': 'none',
                        'fontSize': '12px',
                    },
                    style_header={
                        'backgroundColor': THEME['table_header'],
                        'color': THEME['text_main'],
                        'fontWeight': 'bold', 'border': 'none',
                    },
                    style_data_conditional=[
                        {'if': {'row_index': 'odd'}, 'backgroundColor': THEME['bg_card']},
                        *dir_styles,
                    ],
                    style_table={'overflowX': 'auto'},
                    sort_action='native',
                    page_size=20,
                )
                status = f"Alpha snapshot from {ts[:19]}"
                return table, status

            except Exception as exc:
                return _no_data(f"Error loading Alpha snapshot: {exc}")

        return _no_data("Select a tab above.")
