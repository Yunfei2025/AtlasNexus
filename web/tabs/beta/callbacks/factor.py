# -*- coding: utf-8 -*-
"""Factor (Regime) tab callbacks: factor pool selection, cascade dropdowns,
factor history chart, and correlation ranking."""

from __future__ import annotations

import dash
from dash import dcc, html, dash_table, Patch
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from datetime import datetime
from dateutil.relativedelta import relativedelta

from multiasset.risk_loader import RiskFactorLoader
from settings.paths import DIR_INPUT

from ..data import (
    THEME,
    DIVERSIFICATION_RECOMMENDATIONS,
    SELECTED_FACTOR_POOL,
    get_assets_from_factors,
)


def register_factor_callbacks(app):
    """Register Factor (Regime) tab callbacks."""

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
        elif asset_class == 'Credit':
            options = [
                {'label': 'China', 'value': 'CN'},
                {'label': 'United States', 'value': 'US'},
                {'label': 'Eurozone', 'value': 'EU'},
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
                {'label': 'Gold',        'value': 'AU'},
                {'label': 'Silver',      'value': 'AG'},
                {'label': 'Aluminium',   'value': 'AL'},
                {'label': 'Copper',      'value': 'CU'},
                {'label': 'Zinc',        'value': 'ZN'},
                {'label': 'Crude Oil',   'value': 'SC'},
                {'label': 'Rebar',       'value': 'RB'},
                {'label': 'Live Hog',    'value': 'LC'},
                {'label': 'Soda Ash',    'value': 'SA'},
                {'label': 'Coking Coal', 'value': 'JM'},
                {'label': 'Containerized Freight Index',    'value': 'EC'},
            ]
        elif asset_class == 'Equities':
            options = [
                {'label': 'CSI 300 (IF)',  'value': 'IF'},
                {'label': 'CSI 500 (IC)',  'value': 'IC'},
                {'label': 'SSE 50 (IH)',   'value': 'IH'},
                {'label': 'CSI 1000 (IM)', 'value': 'IM'},
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
        elif asset_class == 'Credit':
            factor_codes = ['CRDL', 'CRSL', 'CRCV']
            factor_names = ['Level (CRDL)', 'Slope (CRSL)', 'Curvature (CRCV)']
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
        elif asset_class == 'Equities':
            options = [{'label': f'Level (EQDL) - {region}', 'value': f'EQDL.{region}'}]
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
                    bgcolor=THEME['bg_card'], activecolor=THEME['accent'], font=dict(size=11, color='#000'), x=0, y=1.02
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
                template=THEME['chart_template'], height=520,
                paper_bgcolor=THEME['bg_main'], plot_bgcolor=THEME['bg_main'],
                font={'color': THEME['text_main']},
                margin=dict(t=60, b=50, l=60, r=30),
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

        # Handle autorange reset ("All" button)
        if relayout_data.get('xaxis.autorange') is True:
            patched = Patch()
            patched['layout']['yaxis']['autorange'] = True
            return patched

        # Get x-axis range from layout (set by rangeselector or manual drag)
        x_start = relayout_data.get('xaxis.range[0]')
        x_end   = relayout_data.get('xaxis.range[1]')

        # Fallback: if figure layout has xaxis.range, use that (for initial 3M range)
        if x_start is None or x_end is None:
            fig_layout = figure.get('layout', {})
            fig_xaxis = fig_layout.get('xaxis', {})
            x_range = fig_xaxis.get('range', [])
            if x_range and len(x_range) == 2:
                x_start, x_end = x_range
            else:
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
        [Input('factor-selection-ir-cn', 'value'),
         Input('factor-selection-ir-us', 'value'),
         Input('factor-selection-ir-eu', 'value'),
         Input('factor-selection-ir-jp', 'value'),
         Input('factor-selection-ir-uk', 'value'),
         Input('factor-selection-cr-cdb', 'value'),
         Input('factor-selection-cr-lgb', 'value'),
         Input('factor-selection-cr-mtn', 'value'),
         Input('factor-selection-cr-icp', 'value'),
         Input('factor-selection-fx', 'value'),
         Input('factor-selection-eq', 'value'),
         Input('factor-selection-cmd', 'value')],
        prevent_initial_call=True
    )
    def update_factor_pool_count(ir_cn, ir_us, ir_eu, ir_jp, ir_uk, cr_cdb, cr_lgb, cr_mtn, cr_icp,
                                  fx_factors, eq_factors, cmd_factors):
        # Merge all domicile IR selections into one list
        ir_factors = (ir_cn or []) + (ir_us or []) + (ir_eu or []) + (ir_jp or []) + (ir_uk or [])
        # Merge all credit universe selections into one list
        cr_factors = (cr_cdb or []) + (cr_lgb or []) + (cr_mtn or []) + (cr_icp or [])

        SELECTED_FACTOR_POOL['ir_factors'] = ir_factors
        SELECTED_FACTOR_POOL['cr_factors'] = cr_factors
        SELECTED_FACTOR_POOL['fx_factors'] = fx_factors or []
        SELECTED_FACTOR_POOL['eq_factors'] = eq_factors or []
        SELECTED_FACTOR_POOL['cmd_factors'] = cmd_factors or []
        SELECTED_FACTOR_POOL['timestamp'] = datetime.now()

        store_data = {
            'ir': ir_factors,
            'cr': cr_factors,
            'fx': fx_factors or [],
            'eq': eq_factors or [],
            'cmd': cmd_factors or [],
        }

        total = (len(ir_factors) + len(cr_factors) + len(fx_factors or [])
                 + len(eq_factors or []) + len(cmd_factors or []))
        if total == 0:
            message = "⚠️ No factors selected. Please select at least 2 factors for correlation analysis."
        elif total == 1:
            message = f"ℹ️ {total} factor selected. Need at least 2 for correlation analysis."
        else:
            message = f"✅ {total} factors selected in pool (shared with Backtest tab)"

        return message, store_data
    
    # 3.6 Correlation Rank Callback
    @app.callback(
        [Output('correlation-heatmap-container', 'children'),
         Output('correlation-table-container', 'children'),
         Output('diversified-recommendation-container', 'children'),
         Output('low-corr-factors-store', 'data')],
        Input('rank-correlations-btn', 'n_clicks'),
        [State('correlation-period-selector', 'value'),
         State('correlation-top-pairs-selector', 'value'),
         State('factor-selection-ir-cn', 'value'),
         State('factor-selection-ir-us', 'value'),
         State('factor-selection-ir-eu', 'value'),
         State('factor-selection-ir-jp', 'value'),
         State('factor-selection-ir-uk', 'value'),
         State('factor-selection-cr-cdb', 'value'),
         State('factor-selection-cr-lgb', 'value'),
         State('factor-selection-cr-mtn', 'value'),
         State('factor-selection-cr-icp', 'value'),
         State('factor-selection-fx', 'value'),
         State('factor-selection-eq', 'value'),
         State('factor-selection-cmd', 'value')],
        prevent_initial_call=True
    )
    def update_correlation_ranks(n_clicks, period, top_pairs,
                                 ir_cn, ir_us, ir_eu, ir_jp, ir_uk,
                                 cr_cdb, cr_lgb, cr_mtn, cr_icp,
                                 fx_factors, eq_factors, cmd_factors):
        if not n_clicks:
            return html.Div(), html.Div(), []

        # Merge domicile IR selections and combine with Credit/FX/EQ/CMD
        ir_factors = (ir_cn or []) + (ir_us or []) + (ir_eu or []) + (ir_jp or []) + (ir_uk or [])
        cr_factors = (cr_cdb or []) + (cr_lgb or []) + (cr_mtn or []) + (cr_icp or [])
        selected_factors = []
        if ir_factors:
            selected_factors.extend(ir_factors)
        if cr_factors:
            selected_factors.extend(cr_factors)
        if fx_factors:
            selected_factors.extend(fx_factors)
        if eq_factors:
            selected_factors.extend(eq_factors)
        if cmd_factors:
            selected_factors.extend(cmd_factors)
        
        if len(selected_factors) < 2:
            return html.Div(), html.Div("⚠️ Please select at least 2 factors for correlation analysis.",
                          style={'color': THEME['warning'], 'padding': '20px', 'textAlign': 'center'}), []

        try:
            loader = RiskFactorLoader(DIR_INPUT)
            # Use cached load - this pulls the wide DF of all factors
            factor_levels = loader.load_risk_factors(use_cache=True)

            if factor_levels is None or factor_levels.empty:
                return html.Div(), html.Div("No factor data available.", style={'color': THEME['warning']}), []

            # Filter to only selected factors
            available_factors = [f for f in selected_factors if f in factor_levels.columns]
            if len(available_factors) < 2:
                return html.Div(), html.Div(f"⚠️ Only {len(available_factors)} of selected factors have data. Need at least 2.",
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
                 return html.Div(), html.Div(f"No data for period {period}", style={'color': THEME['warning']}), []
            
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
                 return html.Div(), html.Div("Insufficient data points for correlation.", style={'color': THEME['warning']}), []

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

            # Classify each factor into an asset class so we can guarantee
            # cross-asset coverage in the selected top-N pairs.
            def _asset_class(f: str) -> str:
                p = f.split('.')[0]
                if p in ('IRDL', 'IRSL', 'IRCV'):
                    return 'Rates'
                if p in ('SPDL', 'SPSL', 'SPCV'):
                    return 'Spread'
                if p.startswith('FX'):
                    return 'FX'
                if p.startswith('EQ'):
                    return 'Equity'
                if p.startswith('CMD'):
                    return 'Commodity'
                return 'Other'

            corr_sorted = corr_stacked.sort_values('AbsCorrelation', ascending=True)

            # Step 1 — one cheapest cross-asset pair per asset class present
            classes_present = set(
                _asset_class(f) for f in available_factors
            )
            selected_idx: set = set()
            selected_pairs: list = []
            for cls in sorted(classes_present):
                for _, row in corr_sorted.iterrows():
                    if row.name in selected_idx:
                        continue
                    if cls in (_asset_class(row['Factor A']), _asset_class(row['Factor B'])):
                        selected_idx.add(row.name)
                        selected_pairs.append(row)
                        break

            # Step 2 — fill remaining slots with globally lowest-corr pairs
            for _, row in corr_sorted.iterrows():
                if len(selected_pairs) >= top_pairs:
                    break
                if row.name not in selected_idx:
                    selected_idx.add(row.name)
                    selected_pairs.append(row)

            bottom_pairs = pd.DataFrame(selected_pairs).head(top_pairs)

            # ── Heatmap: show ALL selected factors (not just low-corr pairs) ────
            all_factors_list = list(corr_matrix.columns)

            # Mask upper triangle AND diagonal (self-correlation = 1.00 is not
            # shown, matching the guide's lower-triangle-only matrix).
            corr_values = corr_matrix.values.copy()
            mask_upper = np.triu(np.ones(corr_values.shape), k=0).astype(bool)
            corr_values[mask_upper] = np.nan

            n_factors = len(all_factors_list)
            # Scale height so labels are readable regardless of how many factors
            heatmap_height = max(500, min(900, 80 + n_factors * 40))

            # --- Heatmap Plot ---
            # Custom colorscale matching guide/BetaCandidates.jsx betaCorrBg():
            # navy-blue (rgba(30,80,160)) for positive, brick-red (rgba(200,60,40))
            # for negative, fading to a near-transparent center at 0.
            _BETA_CORR_COLORSCALE = [
                [0.0, 'rgb(200,60,40)'],
                [0.5, 'rgb(20,35,60)'],
                [1.0, 'rgb(30,80,160)'],
            ]
            heatmap_fig = go.Figure(data=go.Heatmap(
                z=corr_values,
                x=all_factors_list,
                y=all_factors_list,
                colorscale=_BETA_CORR_COLORSCALE,
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
                paper_bgcolor='rgba(0,0,0,0)',
                plot_bgcolor='rgba(0,0,0,0)',
                font={'color': '#e9eef8', 'size': 11},
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
                    'Rates': '#1f5c45',
                    'Spread': '#1f5c45',
                    'Commodities': '#8a661f',
                    'FX': '#5a3d80',
                    'Equities': '#1a4d75',
                }

                for a_type, assets_list in assets_by_type.items():
                    bg_col = type_colors.get(a_type, '#1f5c45')
                    asset_names = [a['name'] for a in assets_list]
                    asset_display_items.append(
                        html.Div([
                            html.Span(f"{a_type}: ", style={'fontWeight': '700', 'color': '#fff', 'marginRight': '5px'}),
                            html.Span(", ".join(asset_names), style={'color': 'rgba(255,255,255,0.85)'})
                        ], style={
                            'padding': '7px 12px',
                            'marginBottom': '5px',
                            'background': bg_col,
                            'borderRadius': '4px',
                            'fontSize': '11px',
                        })
                    )

            # Format display — heatmap goes to the right column, table +
            # diversification recommendation go to the left column under the
            # signal cards (matches the guide's side-by-side layout).
            heatmap_div = html.Div(dcc.Graph(figure=heatmap_fig))

            table_div = html.Div([
                html.Div(f"Lowest Absolute Correlations (Diversification Opportunities) — Top {top_pairs} Pairs",
                         style={'fontSize': '12px', 'fontWeight': '600', 'color': 'var(--text-primary)',
                                'marginBottom': '8px'}),
                dash_table.DataTable(
                    data=bottom_pairs.drop(columns=['AbsCorrelation']).to_dict('records'),
                    columns=[
                        {'name': 'Factor A', 'id': 'Factor A'},
                        {'name': 'Factor B', 'id': 'Factor B'},
                        {'name': 'Correlation', 'id': 'Correlation', 'type': 'numeric', 'format': {'specifier': '.3f'}},
                    ],
                    style_cell={
                        'textAlign': 'left',
                        'padding': '8px 10px',
                        'fontFamily': 'inherit',
                        'fontSize': '11px',
                        'backgroundColor': '#122a4c',
                        'color': '#e9eef8',
                        'border': 'none',
                    },
                    style_header={
                        'backgroundColor': '#0e1d3a',
                        'color': '#a4b6d2',
                        'fontWeight': '600',
                        'fontSize': '9px',
                        'textTransform': 'uppercase',
                        'letterSpacing': '0.05em',
                        'textAlign': 'left',
                        'border': 'none',
                    },
                    style_data_conditional=[
                         {'if': {'row_index': 'odd'}, 'backgroundColor': 'rgba(255,255,255,0.015)'}
                    ]
                ),
            ])

            # Add to Asset Pool Section — relocated to its own full-width row
            # below the table/matrix (matches the guide's layout).
            recommendation_div = html.Div([
                html.Div("Diversified Asset Recommendation",
                         style={'fontSize': '13px', 'fontWeight': '600', 'color': '#34d399', 'marginBottom': '8px'}),
                html.Div(
                    f"Based on {len(top_factors_list)} low-correlation factors, {len(diversified_assets)} assets are recommended:",
                    style={'color': 'var(--text-muted)', 'fontSize': '11px', 'marginBottom': '10px'}
                ),
                # Complete asset list display
                html.Div(
                    asset_display_items if asset_display_items else html.Div(
                        "No mappable assets found.", style={'color': 'var(--accent-amber)', 'fontSize': '11px'}),
                    style={
                        'background': 'var(--surface-input)',
                        'padding': '10px',
                        'borderRadius': '4px',
                        'marginBottom': '12px',
                        'maxHeight': '200px',
                        'overflowY': 'auto',
                    }
                ),
                html.Button(
                    f"Replace Asset Pool with {len(diversified_assets)} Recommended Assets",
                    id='add-diversified-assets-btn',
                    n_clicks=0,
                    disabled=len(diversified_assets) == 0,
                    style={
                        'background': '#34d399' if diversified_assets else 'var(--text-muted)',
                        'color': '#06281c',
                        'padding': '8px 18px',
                        'border': 'none',
                        'borderRadius': '5px',
                        'cursor': 'pointer' if diversified_assets else 'not-allowed',
                        'fontWeight': '700',
                        'fontSize': '11px',
                    }
                ),
                html.Span(
                    id='add-diversified-status',
                    style={'marginLeft': '12px', 'color': 'var(--text-muted)', 'fontSize': '11px'}
                )
            ])

            return heatmap_div, table_div, recommendation_div, top_factors_list

        except Exception as e:
            return (html.Div(), html.Div(f"Error calculating correlations: {str(e)}",
                                          style={'color': THEME['danger']}), html.Div(), [])


