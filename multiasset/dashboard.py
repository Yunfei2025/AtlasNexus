# -*- coding: utf-8 -*-
"""
Multi-Asset Portfolio Dashboard - Refactored Entry Point

This is the main dashboard file that coordinates all components.
Helper modules handle data processing, layout, and utilities.
"""
import dash
from dash import dcc, html, dash_table, Input, Output, State
import plotly.graph_objects as go
import pandas as pd
import numpy as np
from datetime import datetime
import sys
from pathlib import Path
from dateutil.relativedelta import relativedelta

# Path setup
current_file = Path(__file__).resolve()
bin_dir = current_file.parents[1]
project_root = current_file.parents[2]
for path in [str(bin_dir), str(project_root)]:
    if path not in sys.path:
        sys.path.insert(0, path)

# Import from refactored modules
from multiasset.data import (
    load_raw_market_data, calculate_daily_returns_series,
    get_asset_type, get_universe, get_sector
)
from multiasset.layout import (
    create_layout, prepare_portfolio_table
)

# Import business logic
from multiasset.main import run_risk_parity_allocation, create_custom_portfolio
from multiasset.storage import save_asset_pool
from multiasset.risk_loader import RiskFactorLoader
from multiasset.factor_optimizer import FactorRiskParityOptimizer
from settings.paths import DIR_INPUT

# Initialize Dash app
app = dash.Dash(__name__, suppress_callback_exceptions=True)
app.title = "Multi-Asset Risk Parity Dashboard"

# Global state for allocation results
allocation_results = {
    'summary': None,
    'factor_exposures': None,
    'factor_risk': None,
    'portfolio': None,
    'timestamp': None
}

# Set layout
app.layout = create_layout

# ============================================================================
# CALLBACKS
# ============================================================================

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
    """Show/hide UI rows based on selected asset type."""
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
    """Show sector selector when universe is selected."""
    if universe:
        return {'display': 'flex', 'alignItems': 'flex-start', 'marginBottom': '12px'}
    return {'display': 'none'}


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
    """Manage asset pool: add or clear assets."""
    ctx = dash.callback_context
    if not ctx.triggered:
        return current_pool, dash.no_update, dash.no_update
    
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if button_id == 'clear-pool-btn':
        return [], [html.Div("No assets selected. Please add assets using the selection above.", 
                            style={'color': '#95a5a6', 'fontStyle': 'italic', 'padding': '10px'})], "(0)"
    
    if current_pool is None:
        current_pool = []
    
    if button_id == 'add-to-pool-btn' and asset_type == 'Rates':
        if not universe or not sectors:
            return current_pool, dash.no_update, dash.no_update
        
        universe_code_map = {
            'China Gov Bond': 'CN', 'US Gov Bond': 'US', 'DE Gov Bond': 'EU',
            'UK Gov Bond': 'UK', 'Japan Gov Bond': 'JP'
        }
        universe_code = universe_code_map.get(universe, 'XX')
        
        for sector in sectors:
            asset_name = f"{universe_code}{sector}"
            asset_info = {'name': asset_name, 'type': 'Rates', 'universe': universe, 'sector': sector}
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
        display = [html.Div("No assets selected. Please add assets using the selection above.", 
                           style={'color': '#95a5a6', 'fontStyle': 'italic', 'padding': '10px'})]
        count_text = "(0)"
    else:
        display = []
        for asset in current_pool:
            if asset['type'] == 'Commodities':
                display.append(html.Div([html.Span(f"• {asset['name']}", style={'fontWeight': 'bold'})],
                    style={'padding': '5px', 'marginBottom': '5px', 'backgroundColor': '#fff3cd', 'borderRadius': '3px'}))
            else:
                display.append(html.Div([
                    html.Span(f"• {asset['name']}", style={'fontWeight': 'bold', 'marginRight': '10px'}),
                    html.Span(f"({asset['universe']} - {asset['sector']})", style={'color': '#7f8c8d', 'fontSize': '12px'}),
                ], style={'padding': '5px', 'marginBottom': '5px', 'backgroundColor': '#e8f5e9', 'borderRadius': '3px'}))
        count_text = f"({len(current_pool)})"
    
    return current_pool, display, count_text


@app.callback(
    [Output('portfolio-table-container', 'children'),
     Output('sensitivity-heatmap', 'figure'),
     Output('factor-vol-table-container', 'children'),
     Output('status-message', 'children'),
     Output('timestamp-display', 'children'),
     Output('portfolio-data-store', 'data')],
    [Input('run-button', 'n_clicks')],
    [State('capital-input', 'value'),
     State('capital-unit', 'value'),
     State('asset-pool-store', 'data')]
)
def run_analysis(n_clicks, total_capital, capital_unit, asset_pool):
    """Run portfolio analysis and update visualizations."""
    if n_clicks == 0:
        empty_fig = go.Figure()
        empty_fig.update_layout(xaxis={'visible': False}, yaxis={'visible': False},
            annotations=[{'text': 'Click "Run Analysis" to generate results', 'xref': 'paper', 'yref': 'paper',
                         'showarrow': False, 'font': {'size': 16, 'color': '#7f8c8d'}}])
        return (html.Div("No data available. Click 'Run Analysis' to start.", style={'color': '#7f8c8d'}),
                empty_fig, None, "", "", {})
        print(f"Warning: Failed to save asset pool: {e}")

    try:
        # Validate asset pool
        if not asset_pool or len(asset_pool) == 0:
            error_msg = html.Span("⚠ Please add assets to the pool before running analysis", 
                                 style={'color': '#e67e22', 'fontWeight': 'bold'})
            empty_fig = go.Figure()
            empty_fig.update_layout(xaxis={'visible': False}, yaxis={'visible': False},
                annotations=[{'text': 'Please add assets to the pool first', 'xref': 'paper', 'yref': 'paper',
                             'showarrow': False, 'font': {'size': 16, 'color': '#e67e22'}}])
            return (html.Div("No assets in pool. Please add assets first.", style={'color': '#e67e22'}),
                    empty_fig, None, error_msg, "", {})
        
        # Convert capital to CNY
        multiplier = 1e9 if capital_unit == 'billion' else 1e6
        total_capital_cny = float(total_capital) * multiplier
        
        # Get selected assets
        selected_asset_names = [asset['name'] for asset in asset_pool]
        
        # Run optimization
        summary, returns, vols, factor_exp, factor_risk, portfolio = run_risk_parity_allocation(
            total_capital=total_capital_cny, use_cache=True, selected_assets=selected_asset_names
        )
        
        if summary.empty:
            error_msg = html.Span("⚠ No matching assets found in optimization results", 
                                 style={'color': '#e67e22', 'fontWeight': 'bold'})
            empty_fig = go.Figure()
            return (html.Div("No matching assets found.", style={'color': '#e67e22'}),
                    empty_fig, None, error_msg, "", {})
        
        # Store results
        allocation_results.update({
            'summary': summary, 'factor_exposures': factor_exp,
            'factor_risk': factor_risk, 'portfolio': portfolio,
            'timestamp': datetime.now()
        })
        
        # Prepare portfolio table
        portfolio_df = prepare_portfolio_table(summary, factor_exp, portfolio)
        portfolio_enhanced = []
        total_rounded_capital = 0.0
        
        if not portfolio_df.empty:
            for idx, row in portfolio_df.iterrows():
                record = row.to_dict()
                asset_type = row['Asset Type']
                raw_capital = row['Capital (CNY)']
                
                unit = 10_000_000.0 if asset_type == 'Rates' else 1_000_000.0
                rounded_capital = np.floor(raw_capital / unit) * unit
                total_rounded_capital += rounded_capital
                
                record['Capital (CNY)'] = f"{rounded_capital / 1_000_000:,.2f}"
                record['Weight (%)'] = f"{row['Weight (%)']:.2f}%"
                portfolio_enhanced.append(record)
        
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
            style_cell={'textAlign': 'left', 'padding': '10px', 'fontFamily': 'Arial, sans-serif'},
            style_header={'backgroundColor': '#3498db', 'color': 'white', 'fontWeight': 'bold', 'textAlign': 'center'},
            style_data_conditional=[
                {'if': {'filter_query': '{Asset Type} = "TOTAL"'}, 'backgroundColor': '#2c3e50', 'color': 'white', 'fontWeight': 'bold'},
                {'if': {'row_index': 'odd'}, 'backgroundColor': '#ecf0f1'}
            ],
            style_table={'overflowX': 'auto'}
        )
        
        # Create sensitivity heatmap
        assets_with_allocation = summary[summary['Allocation (CNY)'] >= 1000].nlargest(15, 'Allocation (CNY)')
        factor_names = sorted([f for f in factor_exp['Risk Factor'].unique() if f.startswith(('IRDL', 'IRSL', 'IRCV', 'FXDL', 'CMDL'))])
        asset_names = assets_with_allocation['Asset'].tolist()
        
        sensitivity_matrix = []
        for asset_name in asset_names:
            if asset_name in portfolio.assets:
                asset = portfolio.assets[asset_name]
                row = [asset.factors.get(factor, 0.0) for factor in factor_names]
                sensitivity_matrix.append(row)
            else:
                sensitivity_matrix.append([0.0] * len(factor_names))
        
        heatmap_fig = go.Figure(data=go.Heatmap(
            z=sensitivity_matrix, x=factor_names, y=asset_names,
            colorscale='RdBu', zmid=0, text=sensitivity_matrix,
            texttemplate="%{text:.2f}", textfont={"size": 10}
        ))
        heatmap_fig.update_layout(
            title=None, height=500, margin=dict(l=100, r=50, t=30, b=50),
            xaxis_title="Risk Factor", yaxis_title="Asset"
        )
        
        # Create factor volatility table
        factor_vol_df = factor_risk[factor_risk['Risk Factor'].isin(factor_names)].copy()
        factor_vol_df = factor_vol_df[['Risk Factor', 'Volatility (% ann.)']].copy()
        factor_vol_df['Volatility (% ann.)'] = factor_vol_df['Volatility (% ann.)'].apply(lambda x: f"{x:.2f}%")
        factor_vol_df = factor_vol_df.sort_values('Risk Factor')
        
        factor_vol_table = dash_table.DataTable(
            data=factor_vol_df.to_dict('records'),
            columns=[{'name': 'Risk Factor', 'id': 'Risk Factor'}, {'name': 'Volatility (% ann.)', 'id': 'Volatility (% ann.)'}],
            style_table={'overflowX': 'auto', 'width': '100%', 'minWidth': '320px'},
            style_cell={'textAlign': 'center', 'padding': '8px', 'fontSize': '12px'},
            style_header={'backgroundColor': '#2c3e50', 'color': 'white', 'fontWeight': 'bold'},
            style_data={'backgroundColor': '#f8f9fa'},
            style_data_conditional=[{'if': {'row_index': 'odd'}, 'backgroundColor': '#ffffff'}]
        )
        
        factor_vol_container = html.Div([
            html.H4("Risk Factor Volatilities (3-Month EWMA)", 
                    style={'textAlign': 'center', 'color': '#2c3e50', 'marginBottom': '10px', 'fontSize': '14px'}),
            factor_vol_table
        ], style={'width': '100%', 'height': '500px', 'display': 'flex', 'flexDirection': 'column', 
                  'justifyContent': 'center', 'alignItems': 'center'})
        
        # Prepare factor selector
        available_factors = sorted([f for f in factor_exp['Risk Factor'].unique() 
                                   if f.startswith(('IRDL', 'IRSL', 'IRCV', 'FXDL', 'CMDL'))])
        factor_options = [{'label': f, 'value': f} for f in available_factors]
        default_factors = available_factors[:3] if len(available_factors) >= 3 else available_factors
        
        status_msg = html.Span("✓ Analysis completed successfully!", style={'color': '#27ae60', 'fontWeight': 'bold'})
        timestamp_msg = f"Last updated: {allocation_results['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}"
        
        return (portfolio_table, heatmap_fig, factor_vol_container, status_msg, timestamp_msg,
                {'status': 'success'})
        
    except Exception as e:
        error_msg = html.Span(f"✗ Error: {str(e)}", style={'color': '#e74c3c', 'fontWeight': 'bold'})
        empty_fig = go.Figure()
        empty_fig.update_layout(annotations=[{
            'text': f'Error occurred: {str(e)}', 'xref': 'paper', 'yref': 'paper',
            'showarrow': False, 'font': {'size': 14, 'color': '#e74c3c'}
        }])
        return (html.Div(f"Error: {str(e)}", style={'color': '#e74c3c'}),
                empty_fig, None, error_msg, "", {})


# Cascaded dropdown callbacks for factor selection
@app.callback(
    [Output('factor-region-selector', 'options'),
     Output('factor-region-selector', 'value')],
    [Input('factor-asset-class-selector', 'value')]
)
def update_region_options(asset_class):
    """Update region/type options based on selected asset class."""
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
    """Update factor type options based on asset class and region."""
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
    """Update risk factor historical performance chart."""
    if not selected_factors:
        empty_fig = go.Figure()
        empty_fig.update_layout(title="Please select factors from the dropdowns above",
                               xaxis={'visible': False}, yaxis={'visible': False}, template='plotly_white')
        return empty_fig
    
    try:
        # Load risk factors directly from risk loader
        from settings.paths import DIR_INPUT
        from multiasset.risk_loader import RiskFactorLoader
        
        loader = RiskFactorLoader(DIR_INPUT)
        factor_levels = loader.load_risk_factors(use_cache=True)
        
        if factor_levels is None or factor_levels.empty:
            raise ValueError("Cannot load risk factor data")
        
        fig = go.Figure()
        for factor in selected_factors:
            if factor in factor_levels.columns:
                series = factor_levels[factor].dropna()
                if not series.empty:
                    fig.add_trace(go.Scatter(x=series.index, y=series.values, mode='lines', name=factor))
        
        fig.update_layout(
            xaxis_title="Date", yaxis_title="Value", hovermode='x unified',
            template='plotly_white', height=500,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            xaxis=dict(
                rangeslider=dict(visible=True, thickness=0.05),
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
                    bgcolor='#f8f9fa', activecolor='#3498db', font=dict(size=11), x=0, y=1.15
                ),
                type="date"
            ),
            uirevision='constant'
        )
        return fig
    except Exception as e:
        print(f"Error plotting factor history: {e}")
        return go.Figure().update_layout(title=f"Error plotting data: {str(e)}")


@app.callback(
    [Output('historical-allocation-chart', 'figure'),
     Output('pnl-attribution-chart', 'figure'),
     Output('performance-metrics-container', 'children')],
    [Input('run-history-button', 'n_clicks')],
    [State('asset-pool-store', 'data'),
     State('capital-input', 'value'),
     State('capital-unit', 'value'),
     State('history-date-range', 'start_date'),
     State('history-date-range', 'end_date')]
)
def update_historical_allocation(n_clicks, asset_pool, total_capital, capital_unit, start_date, end_date):
    """Update historical allocation analysis."""
    if n_clicks == 0 or not asset_pool:
        return go.Figure(), go.Figure(), None
    
    try:
        # Parse dates
        start_date = pd.to_datetime(start_date) if start_date else None
        end_date = pd.to_datetime(end_date) if end_date else None
        
        # Load data
        loader = RiskFactorLoader(DIR_INPUT)
        risk_factors = loader.load_risk_factors(use_cache=True)
        risk_factors.index = pd.to_datetime(risk_factors.index)
        market_data = load_raw_market_data()
        
        if risk_factors.empty:
            return go.Figure().update_layout(title="No risk factor data available"), go.Figure(), None
        
        # Set date range
        if not end_date:
            end_date = risk_factors.index.max()
        if not start_date:
            start_date = end_date - relativedelta(years=2)
        
        # Generate rebalance dates (monthly)
        rebalance_dates = []
        current_date = start_date.replace(day=1)
        while current_date <= end_date:
            if current_date >= risk_factors.index.min():
                rebalance_dates.append(current_date)
            current_date += relativedelta(months=1)
        
        # Create portfolio
        selected_asset_names = [asset['name'] for asset in asset_pool]
        portfolio = create_custom_portfolio(selected_asset_names)
        
        # Convert capital
        total_capital = float(total_capital) if total_capital else 10_000_000_000
        if capital_unit == 'billion':
            total_capital *= 1_000
        
        # Initialize optimizer if needed
        optimizer = FactorRiskParityOptimizer(
            portfolio=portfolio, input_dir=str(DIR_INPUT),
            factor_model_lookback_years=1.0, vol_lookback_months=3, ewma_lambda=0.94
        )
        
        # Calculate allocations for each rebalance date
        history_data = []
        allocations_by_date = {}
        
        for date in rebalance_dates:
            try:
                weights_series, _ = optimizer.fit_and_calculate(pd.Timestamp(date))
                weights = weights_series.to_dict()
            except Exception as e:
                print(f"Factor risk optimization failed at {date}: {e}")
                continue
            
            # Filter out negligible weights (floating point precision artifacts)
            weights = {k: v for k, v in weights.items() if abs(v) >= 1e-6}
            
            # Renormalize weights after filtering
            weight_sum = sum(weights.values())
            if weight_sum > 0:
                weights = {k: v / weight_sum for k, v in weights.items()}
            else:
                continue
            
            # Calculate allocations
            row = {'Date': date}
            current_allocations = {}
            for name, weight in weights.items():
                alloc = weight * total_capital
                row[name] = alloc
                current_allocations[name] = alloc * 1_000_000
            
            history_data.append(row)
            allocations_by_date[date] = current_allocations
        
        if not history_data:
            return go.Figure().update_layout(title="Insufficient data for historical analysis"), go.Figure(), None
        
        # Calculate daily PnL
        all_dates = sorted(risk_factors.loc[(risk_factors.index >= start_date) & (risk_factors.index <= end_date)].index)
        sorted_rebalance_dates = sorted(allocations_by_date.keys())
        
        daily_pnl_records = []
        cumulative_pnl = {name: 0.0 for name in selected_asset_names}
        cumulative_pnl['Total'] = 0.0
        
        # Pre-compute daily returns
        asset_daily_returns = {}
        for name in selected_asset_names:
            ret_df = calculate_daily_returns_series(name, market_data, start_date, end_date)
            if not ret_df.empty:
                ret_df = ret_df.set_index('Date')
                asset_daily_returns[name] = ret_df
        
        # Calculate daily PnL
        for trading_day in all_dates:
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
            
            for name in selected_asset_names:
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
        
        # Create allocation chart
        fig_alloc = go.Figure()
        for asset_name in selected_asset_names:
            if asset_name in df_history.columns:
                fig_alloc.add_trace(go.Scatter(
                    x=df_history['Date'], y=df_history[asset_name],
                    mode='lines+markers', name=asset_name, stackgroup='one'
                ))
        
        fig_alloc.update_layout(
            title="Historical Portfolio Allocation (Monthly Rebalancing)",
            xaxis_title="Date", yaxis_title="Allocation",
            hovermode='x unified', template='plotly_white', height=450,
            legend=dict(orientation="h", y=1.02, x=1, xanchor="right")
        )
        
        # Create PnL chart
        fig_pnl = go.Figure()
        if not df_pnl.empty:
            for asset_name in selected_asset_names:
                if asset_name in df_pnl.columns:
                    fig_pnl.add_trace(go.Scatter(
                        x=df_pnl['Date'], y=df_pnl[asset_name],
                        mode='lines', name=asset_name, stackgroup='one'
                    ))
            
            fig_pnl.add_trace(go.Scatter(
                x=df_pnl['Date'], y=df_pnl['Total'],
                mode='lines', name='Total Portfolio PnL',
                line=dict(color='black', width=2, dash='dash')
            ))
        
        fig_pnl.update_layout(
            title="Daily Cumulative Profit & Loss Attribution (Million CNY)",
            xaxis_title="Date", yaxis_title="Cumulative PnL",
            hovermode='x unified', template='plotly_white', height=450,
            legend=dict(orientation="h", y=1.02, x=1, xanchor="right")
        )
        
        # Calculate performance metrics
        metrics_table = None
        if not df_pnl.empty and len(df_pnl) > 1:
            initial_capital = total_capital
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
                    html.Th("Annualized Return", style={'padding': '8px 15px', 'backgroundColor': '#3498db', 'color': 'white'}),
                    html.Th("Sharpe Ratio", style={'padding': '8px 15px', 'backgroundColor': '#3498db', 'color': 'white'}),
                    html.Th("Max Drawdown", style={'padding': '8px 15px', 'backgroundColor': '#3498db', 'color': 'white'}),
                ]),
                html.Tr([
                    html.Td(f"{annualized_return:.2%}", style={'padding': '8px 15px', 'textAlign': 'center', 'fontWeight': 'bold',
                                                               'color': '#27ae60' if annualized_return >= 0 else '#e74c3c'}),
                    html.Td(f"{sharpe_ratio:.2f}", style={'padding': '8px 15px', 'textAlign': 'center', 'fontWeight': 'bold',
                                                          'color': '#27ae60' if sharpe_ratio >= 1 else '#f39c12' if sharpe_ratio >= 0 else '#e74c3c'}),
                    html.Td(f"{max_drawdown:.2%}", style={'padding': '8px 15px', 'textAlign': 'center', 'fontWeight': 'bold', 'color': '#e74c3c'}),
                ]),
            ], style={'borderCollapse': 'collapse', 'fontSize': '14px'})
        
        return fig_alloc, fig_pnl, metrics_table
        
    except Exception as e:
        print(f"Error in historical analysis: {e}")
        import traceback
        traceback.print_exc()
        err_fig = go.Figure().update_layout(title=f"Error: {str(e)}")
        return err_fig, err_fig, None


# ============================================================================
# RUN DASHBOARD
# ============================================================================

def run_dashboard(host='127.0.0.1', port=5010, debug=True):
    """Run the dashboard server."""
    print("\n" + "="*80)
    print("Starting Multi-Asset Portfolio Dashboard (Refactored)")
    print("="*80)
    print(f"Dashboard URL: http://{host}:{port}")
    print("Press Ctrl+C to stop the server")
    print("="*80 + "\n")
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    run_dashboard()
