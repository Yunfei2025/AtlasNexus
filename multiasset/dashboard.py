# -*- coding: utf-8 -*-
"""
Multi-Asset Portfolio Dashboard using Plotly Dash.

Interactive web dashboard for visualizing and analyzing factor-level risk parity allocations.
"""
import dash
from dash import dcc, html, dash_table, Input, Output, State
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from datetime import datetime
import sys
from pathlib import Path
from dateutil.relativedelta import relativedelta
import os

# Ensure parent directory is on sys.path
current_file = Path(__file__).resolve()
bin_dir = current_file.parents[1]       # .../MultiAsset/bin
project_root = current_file.parents[2]  # .../MultiAsset

# Add both paths to sys.path to ensure we can find 'multiasset' and 'settings'
for path in [str(bin_dir), str(project_root)]:
    if path not in sys.path:
        sys.path.insert(0, path)

from multiasset.main import run_risk_parity_allocation, create_custom_portfolio
from multiasset.storage import save_asset_pool, load_last_asset_pool
from multiasset.portfolio import RiskFactorLoader, PCARiskFactorAnalyzer
from multiasset.factor_optimizer import PCAFactorRiskParityOptimizer
from settings.paths import DIR_INPUT
from dateutil.relativedelta import relativedelta


def load_raw_market_data():
    """Load raw market data for PnL calculation."""
    # Load FX Curves (Foreign Yields)
    fx_curves = pd.read_pickle(os.path.join(DIR_INPUT, "fxcurve_ts.pkl"))
    
    # Load China Yields
    cn_data = pd.read_pickle(os.path.join(DIR_INPUT, "database-px.pkl"))["CGB"]
    
    # Load Macro Data (FX and Commodities)
    macro_data = pd.read_pickle(os.path.join(DIR_INPUT, 'macro-px.pkl'))
    
    return fx_curves, cn_data, macro_data


def get_asset_yield_series(asset_name, market_data):
    """
    Get the yield/price time series for an asset.
    Returns: (series, duration, country, is_bond)
    """
    fx_curves, cn_data, macro_data = market_data
    
    asset_type = get_asset_type(asset_name)
    universe = get_universe(asset_name)
    sector = get_sector(asset_name)
    
    if asset_type == 'Commodities':
        ticker_map = {
            'Gold': 'AU.SHF',
            'Aluminium': 'AL.SHF',
            'Copper': 'CU.SHF',
            'Crude_Oil': 'SC.INE'
        }
        ticker = ticker_map.get(asset_name)
        if ticker:
            return macro_data["commodity"][ticker], 0, None, False
        return None, 0, None, False
        
    elif asset_type == 'Rates':
        country_map = {
            'China Gov Bond': 'CN',
            'US Gov Bond': 'US',
            'DE Gov Bond': 'EU',
            'UK Gov Bond': 'UK',
            'Japan Gov Bond': 'JP'
        }
        country = country_map.get(universe)
        if not country:
            return None, 0, None, True
            
        duration = float(sector.replace('Y', ''))
        
        if country == 'CN':
            tenor_map = {
                '1Y': '中债国债到期收益率:1年',
                '2Y': '中债国债到期收益率:2年',
                '5Y': '中债国债到期收益率:5年',
                '10Y': '中债国债到期收益率:10年',
                '30Y': '中债国债到期收益率:30年'
            }
            col = tenor_map.get(sector)
            if not col or col not in cn_data.columns:
                if sector == '2Y': col = '中债国债到期收益率:1年'
                elif sector == '30Y': col = '中债国债到期收益率:10年'
                else: return None, duration, country, True
            return cn_data[col], duration, country, True
        else:
            key = f"{country}{sector}"
            if key in fx_curves[country].columns:
                return fx_curves[country][key], duration, country, True
            return None, duration, country, True
    
    return None, 0, None, False


def get_fx_series(country, market_data):
    """Get FX series for a country."""
    _, _, macro_data = market_data
    fx_map = {
        'US': 'USDCNY.IB',
        'EU': 'EURCNY.IB',
        'UK': 'GBPCNY.IB',
        'JP': 'JPYCNY.IB'
    }
    fx_ticker = fx_map.get(country)
    if fx_ticker and fx_ticker in macro_data["fx"].columns:
        return macro_data["fx"][fx_ticker]
    return None


def calculate_daily_returns_series(asset_name, market_data, start_date, end_date):
    """
    Calculate daily return series for an asset.
    Returns DataFrame with columns: ['Date', 'carry', 'capital', 'fx', 'total']
    
    For bonds:
    - Carry = daily yield / 365 (actual daily accrual)
    - Capital = -Duration * daily yield change
    - FX = daily FX return (for foreign bonds)
    
    For commodities:
    - total = daily price return
    """
    series, duration, country, is_bond = get_asset_yield_series(asset_name, market_data)
    
    if series is None:
        return pd.DataFrame()
    
    # Ensure index is DatetimeIndex for proper date comparisons
    if not isinstance(series.index, pd.DatetimeIndex):
        series.index = pd.to_datetime(series.index)
    
    # Ensure start_date and end_date are Timestamps
    start_ts = pd.to_datetime(start_date)
    end_ts = pd.to_datetime(end_date)
    
    # Filter to date range
    mask = (series.index >= start_ts) & (series.index <= end_ts)
    series = series.loc[mask].dropna()
    
    if series.empty or len(series) < 2:
        return pd.DataFrame()
    
    result = pd.DataFrame(index=series.index)
    result['Date'] = result.index
    
    if is_bond:
        # Bond returns
        # Carry: daily accrual based on that day's yield
        # Carry_t = Yield_t / 365
        result['carry'] = series / 100.0 / 365
        
        # Capital gain: -Duration * (Yield_t - Yield_{t-1})
        yield_change = series.diff() / 100.0  # Convert from % to decimal
        result['capital'] = -duration * yield_change
        
        # FX return (for foreign bonds)
        if country and country != 'CN':
            fx_series = get_fx_series(country, market_data)
            if fx_series is not None:
                # Ensure index is DatetimeIndex
                if not isinstance(fx_series.index, pd.DatetimeIndex):
                    fx_series.index = pd.to_datetime(fx_series.index)
                
                # Filter FX series by date range (create new mask for fx_series index)
                fx_mask = (fx_series.index >= start_ts) & (fx_series.index <= end_ts)
                fx_filtered = fx_series.loc[fx_mask].dropna()
                fx_ret = fx_filtered.pct_change()
                # Align with result index
                result['fx'] = fx_ret.reindex(result.index).fillna(0)
            else:
                result['fx'] = 0.0
        else:
            result['fx'] = 0.0
        
        # Total return (local + FX)
        # R_total ≈ carry + capital + fx (for small returns)
        result['total'] = result['carry'] + result['capital'] + result['fx']
        
    else:
        # Commodity returns - simple price return
        result['carry'] = 0.0
        result['capital'] = 0.0
        result['fx'] = 0.0
        result['total'] = series.pct_change()
    
    # Drop first row (NaN from diff/pct_change)
    result = result.iloc[1:]
    
    return result.reset_index(drop=True)


def calculate_asset_monthly_return(asset_name, start_date, end_date, market_data):
    """
    Calculate monthly return components for an asset.
    Returns: (total_return, carry_return, price_return, fx_return)
    """
    fx_curves, cn_data, macro_data = market_data
    
    # 1. Determine Asset Type and Parameters
    asset_type = get_asset_type(asset_name)
    universe = get_universe(asset_name)
    sector = get_sector(asset_name) # Tenor for bonds
    
    if asset_type == 'Commodities':
        # Commodity Logic
        ticker_map = {
            'Gold': 'AU.SHF',
            'Aluminium': 'AL.SHF',
            'Copper': 'CU.SHF',
            'Crude_Oil': 'SC.INE'
        }
        ticker = ticker_map.get(asset_name)
        if not ticker:
            return 0.0, 0.0, 0.0, 0.0
            
        price_series = macro_data["commodity"][ticker]
        
        # Get prices
        try:
            p_start = price_series.asof(start_date)
            p_end = price_series.asof(end_date)
            
            if pd.isna(p_start) or pd.isna(p_end):
                return 0.0, 0.0, 0.0, 0.0
                
            total_ret = (p_end - p_start) / p_start
            return total_ret, 0.0, total_ret, 0.0
            
        except Exception:
            return 0.0, 0.0, 0.0, 0.0
            
    elif asset_type == 'Rates':
        # Bond Logic
        # Map universe to country code
        country_map = {
            'China Gov Bond': 'CN',
            'US Gov Bond': 'US',
            'DE Gov Bond': 'EU', # Using EU for DE
            'UK Gov Bond': 'UK',
            'Japan Gov Bond': 'JP'
        }
        country = country_map.get(universe)
        if not country:
            return 0.0, 0.0, 0.0, 0.0
            
        # Get Yield Data
        try:
            if country == 'CN':
                # Map tenor to column name
                tenor_map = {
                    '1Y': '中债国债到期收益率:1年',
                    '2Y': '中债国债到期收益率:2年', # Assuming exists, need to check or fallback
                    '5Y': '中债国债到期收益率:5年',
                    '10Y': '中债国债到期收益率:10年',
                    '30Y': '中债国债到期收益率:30年'
                }
                col = tenor_map.get(sector)
                if not col or col not in cn_data.columns:
                    # Fallback or skip
                    if sector == '2Y': col = '中债国债到期收益率:1年' # Approx
                    elif sector == '30Y': col = '中债国债到期收益率:10年' # Approx
                    else: return 0.0, 0.0, 0.0, 0.0
                
                yield_series = cn_data[col]
            else:
                # Foreign curves
                key = f"{country}{sector}"
                if key not in fx_curves[country].columns:
                    return 0.0, 0.0, 0.0, 0.0
                yield_series = fx_curves[country][key]
            
            # Get Yields (in %)
            y_start = yield_series.asof(start_date)
            y_end = yield_series.asof(end_date)
            
            if pd.isna(y_start) or pd.isna(y_end):
                return 0.0, 0.0, 0.0, 0.0
            
            # Duration Approximation
            duration = float(sector.replace('Y', ''))
            
            # 1. Carry Return (Coupon Income)
            # Approx: Yield * Time Fraction
            # Time fraction = 1/12 for monthly
            carry_ret = (y_start / 100.0) * (1/12)
            
            # 2. Capital Gain (Price Change due to Yield Change)
            # Approx: -Duration * Delta Yield
            capital_ret = -duration * (y_end - y_start) / 100.0
            
            # 3. FX Return (for foreign bonds)
            fx_ret = 0.0
            if country != 'CN':
                fx_map = {
                    'US': 'USDCNY.IB',
                    'EU': 'EURCNY.IB',
                    'UK': 'GBPCNY.IB',
                    'JP': 'JPYCNY.IB'
                }
                fx_ticker = fx_map.get(country)
                if fx_ticker:
                    fx_series = macro_data["fx"][fx_ticker]
                    fx_start = fx_series.asof(start_date)
                    fx_end = fx_series.asof(end_date)
                    if not pd.isna(fx_start) and not pd.isna(fx_end):
                        fx_ret = (fx_end - fx_start) / fx_start
            
            # Total Return (Approx)
            # R_total = (1 + R_local) * (1 + R_fx) - 1
            # R_local = Carry + Capital
            r_local = carry_ret + capital_ret
            total_ret = (1 + r_local) * (1 + fx_ret) - 1
            
            return total_ret, carry_ret, capital_ret, fx_ret
            
        except Exception as e:
            # print(f"Error calc return for {asset_name}: {e}")
            return 0.0, 0.0, 0.0, 0.0
            
    return 0.0, 0.0, 0.0, 0.0


# Initialize the Dash app
app = dash.Dash(__name__, suppress_callback_exceptions=True)
app.title = "Multi-Asset Risk Parity Dashboard"

# Global variable to store results
allocation_results = {
    'summary': None,
    'factor_exposures': None,
    'factor_risk': None,
    'portfolio': None,
    'timestamp': None
}


def get_asset_type(asset_name):
    """Categorize asset by type."""
    if asset_name in ['Gold', 'Aluminium', 'Copper', 'Crude_Oil']:
        return 'Commodities'
    elif any(x in asset_name for x in ['US', 'EU', 'UK', 'JP', 'CN']):
        return 'Rates'
    else:
        return 'Equities'


def get_universe(asset_name):
    """Get the universe/country for the asset."""
    if 'US' in asset_name:
        return 'US Gov Bond'
    elif 'EU' in asset_name:
        return 'DE Gov Bond'
    elif 'UK' in asset_name:
        return 'UK Gov Bond'
    elif 'JP' in asset_name:
        return 'Japan Gov Bond'
    elif 'CN' in asset_name:
        return 'China Gov Bond'
    elif asset_name == 'Gold':
        return 'AU'
    elif asset_name == 'Aluminium':
        return 'AL'
    elif asset_name == 'Copper':
        return 'CU'
    elif asset_name == 'Crude_Oil':
        return 'SC'
    else:
        return 'N/A'


def get_sector(asset_name):
    """Get the sector/tenor for the asset."""
    for tenor in ['1Y', '2Y', '5Y', '10Y', '30Y']:
        if tenor in asset_name:
            return tenor
    return 'N/A'


def prepare_portfolio_table(summary_df, factor_exposures_df, portfolio=None):
    """
    Prepare the portfolio table with asset type, universe, sector, allocation, and sensitivities.
    
    Args:
        summary_df: Summary DataFrame from optimization
        factor_exposures_df: Factor exposures DataFrame
        portfolio: Portfolio object containing asset details
        
    Returns:
        DataFrame formatted for display
    """
    if summary_df is None or summary_df.empty:
        return pd.DataFrame()
    
    # Create a copy of summary
    portfolio_data = []
    
    # Get all unique risk factors for sensitivity columns
    risk_factors = sorted([f for f in factor_exposures_df['Risk Factor'].values if f.startswith(('IRDL', 'IRSL', 'IRCV', 'FXDL', 'CMDL'))])
    
    for idx, row in summary_df.iterrows():
        asset_name = row['Asset']
        
        # Skip assets with zero allocation
        if row['Allocation (CNY)'] < 1000:  # Less than 1000 CNY
            continue
        
        record = {
            'Asset Type': get_asset_type(asset_name),
            'Universe': get_universe(asset_name),
            'Sector': get_sector(asset_name),
            'Asset Name': asset_name,
            'Capital (CNY)': row['Allocation (CNY)'],
            'Weight (%)': row['Weight (%)'],
        }
        
        # Add sensitivity columns
        if portfolio and asset_name in portfolio.assets:
            asset = portfolio.assets[asset_name]
            for factor in risk_factors:
                record[factor] = asset.factors.get(factor, 0.0)
        else:
            for factor in risk_factors:
                record[factor] = 0.0
        
        portfolio_data.append(record)
    
    portfolio_df = pd.DataFrame(portfolio_data)
    
    # Sort by Asset Type, Universe, and Sector
    if not portfolio_df.empty:
        portfolio_df = portfolio_df.sort_values(['Asset Type', 'Universe', 'Sector'])
    
    return portfolio_df


def create_portfolio_table_with_sensitivities(portfolio_df, portfolio_obj):
    """
    Add sensitivity values to the portfolio table.
    
    Args:
        portfolio_df: Portfolio DataFrame
        portfolio_obj: Portfolio object from main.py
        
    Returns:
        Enhanced DataFrame with sensitivity values
    """
    if portfolio_df.empty:
        return portfolio_df
    
    # Get sensitivity columns
    sensitivity_cols = [col for col in portfolio_df.columns if col.startswith(('IRDL', 'IRSL', 'IRCV', 'FXDL', 'CMDL'))]
    
    for idx, row in portfolio_df.iterrows():
        asset_name = row['Asset Name']
        weight = row['Weight (%)'] / 100.0
        
        # Get asset from portfolio
        if asset_name in portfolio_obj.assets:
            asset = portfolio_obj.assets[asset_name]
            
            # Fill in sensitivities
            for factor_name, sensitivity in asset.factors.items():
                if factor_name in sensitivity_cols:
                    # Weighted sensitivity
                    portfolio_df.at[idx, factor_name] = weight * sensitivity
    
    # Add totals row
    totals = {
        'Asset Type': 'TOTAL',
        'Universe': '',
        'Sector': '',
        'Asset Name': '',
        'Capital (CNY)': portfolio_df['Capital (CNY)'].sum(),
        'Weight (%)': portfolio_df['Weight (%)'].sum(),
    }
    
    for col in sensitivity_cols:
        totals[col] = portfolio_df[col].sum()
    
    portfolio_df = pd.concat([portfolio_df, pd.DataFrame([totals])], ignore_index=True)
    
    return portfolio_df


def create_layout():
    """Create the dashboard layout."""
    
    # Load last saved state
    last_run_data = load_last_asset_pool()
    initial_pool = []
    initial_n_clicks = 0
    initial_capital = 100
    initial_unit = 'million'
    
    if last_run_data:
        if 'asset_pool' in last_run_data:
            initial_pool = last_run_data['asset_pool']
            if initial_pool:
                initial_n_clicks = 1
        
        if 'metadata' in last_run_data:
            meta = last_run_data['metadata']
            if 'capital' in meta:
                initial_capital = meta['capital']
            if 'unit' in meta:
                initial_unit = meta['unit']

    # Generate initial pool display
    if not initial_pool:
        pool_display = [html.Div("No assets selected. Please add assets using the selection above.", 
                           style={'color': '#95a5a6', 'fontStyle': 'italic', 'fontSize': '12px', 'textAlign': 'center', 'padding': '15px'})]
        pool_count_text = "(0)"
    else:
        pool_display = []
        for asset in initial_pool:
            if asset['type'] == 'Commodities':
                pool_display.append(
                    html.Div([
                        html.Span(f"• {asset['name']}", style={'fontWeight': 'bold'}),
                    ], style={'padding': '5px', 'marginBottom': '5px', 'backgroundColor': '#fff3cd', 'borderRadius': '3px'})
                )
            else:
                pool_display.append(
                    html.Div([
                        html.Span(f"• {asset['name']}", style={'fontWeight': 'bold', 'marginRight': '10px'}),
                        html.Span(f"({asset['universe']} - {asset['sector']})", style={'color': '#7f8c8d', 'fontSize': '12px'}),
                    ], style={'padding': '5px', 'marginBottom': '5px', 'backgroundColor': '#e8f5e9', 'borderRadius': '3px'})
                )
        pool_count_text = f"({len(initial_pool)})"

    return html.Div([
        # Header
        html.Div([
            html.H1("Multi-Asset Risk Parity Portfolio Dashboard",
                   style={'textAlign': 'center', 'color': '#2c3e50', 'marginBottom': '10px'}),
            html.H3("Factor-Level Risk Parity Allocation",
                   style={'textAlign': 'center', 'color': '#7f8c8d', 'marginTop': '0px'}),
        ], style={'backgroundColor': '#ecf0f1', 'padding': '20px', 'marginBottom': '20px'}),
        
        # Control Panel
        html.Div([
            # Section 1: Configuration Header & Capital
            html.Div([
                html.Div([
                    html.H4("1. Configuration", style={'margin': '0', 'color': '#2c3e50', 'fontSize': '16px'}),
                ], style={'flex': '1'}),
                
                html.Div([
                    html.Label("Total Capital:", style={'fontWeight': 'bold', 'marginRight': '10px', 'fontSize': '14px'}),
                    dcc.Input(
                        id='capital-input',
                        type='number',
                        value=initial_capital,
                        style={'width': '100px', 'marginRight': '5px', 'padding': '5px', 'borderRadius': '4px', 'border': '1px solid #ddd'}
                    ),
                    dcc.Dropdown(
                        id='capital-unit',
                        options=[
                            {"label": "Million", "value": "million"},
                            {"label": "Billion", "value": "billion"},
                        ],
                        value=initial_unit,
                        clearable=False,
                        style={'width': '100px', 'marginRight': '5px', 'fontSize': '13px'}
                    ),
                    html.Span("CNY", style={'color': '#7f8c8d', 'fontSize': '14px'}),
                ], style={'display': 'flex', 'alignItems': 'center'}),
            ], style={'display': 'flex', 'alignItems': 'center', 'padding': '15px 20px', 'backgroundColor': '#f8f9fa', 'borderBottom': '1px solid #eee', 'borderRadius': '8px 8px 0 0'}),
            
            # Section 2: Main Content (Selection + Pool + Action)
            html.Div([
                # Column 1: Asset Selection
                html.Div([
                    html.H5("2. Asset Selection", style={'color': '#34495e', 'marginTop': '0', 'marginBottom': '15px', 'fontSize': '15px'}),
                    
                    # Step 1: Type
                    html.Div([
                        html.Label("Type:", style={'fontWeight': 'bold', 'width': '70px', 'fontSize': '13px'}),
                        dcc.RadioItems(
                            id='asset-type-selector',
                            options=[
                                {'label': ' Rates', 'value': 'Rates'},
                                {'label': ' Commodities', 'value': 'Commodities'},
                            ],
                            value=None,
                            inline=True,
                            inputStyle={'marginRight': '5px', 'marginLeft': '10px'},
                            style={'fontSize': '13px'}
                        ),
                    ], style={'marginBottom': '12px', 'display': 'flex', 'alignItems': 'center'}),
                    
                    # Step 2: Universe (Rates)
                    html.Div([
                        html.Label("Universe:", style={'fontWeight': 'bold', 'width': '70px', 'fontSize': '13px'}),
                        dcc.Dropdown(
                            id='universe-selector',
                            options=[
                                {'label': 'China Gov Bond', 'value': 'China Gov Bond'},
                                {'label': 'US Gov Bond', 'value': 'US Gov Bond'},
                                {'label': 'DE Gov Bond', 'value': 'DE Gov Bond'},
                                {'label': 'UK Gov Bond', 'value': 'UK Gov Bond'},
                                {'label': 'Japan Gov Bond', 'value': 'Japan Gov Bond'},
                            ],
                            value=None,
                            placeholder="Select universe...",
                            clearable=True,
                            style={'width': '100%', 'fontSize': '13px'}
                        ),
                    ], id='universe-selection-row', style={'display': 'none', 'marginBottom': '12px', 'alignItems': 'center'}),
                    
                    # Step 3: Sectors (Rates)
                    html.Div([
                        html.Label("Sector:", style={'fontWeight': 'bold', 'width': '70px', 'fontSize': '13px', 'alignSelf': 'flex-start', 'marginTop': '5px'}),
                        html.Div([
                            dcc.Checklist(
                                id='sector-selector',
                                options=[
                                    {'label': ' 1Y', 'value': '1Y'},
                                    {'label': ' 2Y', 'value': '2Y'},
                                    {'label': ' 5Y', 'value': '5Y'},
                                    {'label': ' 10Y', 'value': '10Y'},
                                    {'label': ' 30Y', 'value': '30Y'},
                                ],
                                value=[],
                                inline=True,
                                inputStyle={'marginRight': '3px', 'marginLeft': '8px'},
                                style={'fontSize': '13px', 'marginBottom': '8px'}
                            ),
                            html.Button(
                                'Add to Pool',
                                id='add-to-pool-btn',
                                n_clicks=0,
                                style={'backgroundColor': '#2ecc71', 'color': 'white', 'padding': '4px 12px', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer', 'fontSize': '12px'}
                            ),
                        ], style={'flex': '1'})
                    ], id='sector-selection-row', style={'display': 'none', 'marginBottom': '12px', 'alignItems': 'flex-start'}),
                    
                    # Step 2: Commodities
                    html.Div([
                        html.Label("Items:", style={'fontWeight': 'bold', 'width': '70px', 'fontSize': '13px', 'alignSelf': 'flex-start', 'marginTop': '5px'}),
                        html.Div([
                            dcc.Checklist(
                                id='commodities-selector',
                                options=[
                                    {'label': ' Gold', 'value': 'Gold'},
                                    {'label': ' Aluminium', 'value': 'Aluminium'},
                                    {'label': ' Copper', 'value': 'Copper'},
                                    {'label': ' Crude Oil', 'value': 'Crude_Oil'},
                                ],
                                value=[],
                                inline=True,
                                inputStyle={'marginRight': '3px', 'marginLeft': '8px'},
                                style={'fontSize': '13px', 'marginBottom': '8px'}
                            ),
                            html.Button(
                                'Add to Pool',
                                id='add-commodities-btn',
                                n_clicks=0,
                                style={'backgroundColor': '#f39c12', 'color': 'white', 'padding': '4px 12px', 'border': 'none', 'borderRadius': '4px', 'cursor': 'pointer', 'fontSize': '12px'}
                            ),
                        ], style={'flex': '1'})
                    ], id='commodities-confirm-row', style={'display': 'none', 'marginBottom': '12px', 'alignItems': 'flex-start'}),
                    
                ], style={'width': '40%', 'padding': '20px', 'borderRight': '1px solid #eee'}),
                
                # Column 2: Asset Pool
                html.Div([
                    html.Div([
                        html.H5("3. Asset Pool", style={'color': '#34495e', 'marginTop': '0', 'marginBottom': '0', 'fontSize': '15px'}),
                        html.Span(id='pool-count', children=pool_count_text, style={'color': '#7f8c8d', 'fontSize': '13px', 'marginLeft': '5px'}),
                        html.Button(
                            'Clear',
                            id='clear-pool-btn',
                            n_clicks=0,
                            style={'backgroundColor': '#e74c3c', 'color': 'white', 'padding': '2px 8px', 'border': 'none', 'borderRadius': '3px', 'cursor': 'pointer', 'fontSize': '11px', 'marginLeft': 'auto'}
                        )
                    ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '10px'}),
                    
                    html.Div(
                        id='asset-pool-display',
                        children=pool_display,
                        style={'height': '150px', 'overflowY': 'auto', 'border': '1px solid #eee', 'borderRadius': '4px', 'padding': '8px', 'backgroundColor': '#fafafa'}
                    ),
                ], style={'width': '30%', 'padding': '20px', 'borderRight': '1px solid #eee'}),
                
                # Column 3: Action
                html.Div([
                    html.H5("4. Analysis", style={'color': '#34495e', 'marginTop': '0', 'marginBottom': '15px', 'fontSize': '15px'}),
                    html.Div([
                        html.Button(
                            'RUN ANALYSIS',
                            id='run-button',
                            n_clicks=initial_n_clicks,
                            style={'backgroundColor': '#3498db', 'color': 'white', 'padding': '12px', 'width': '100%', 'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer', 'fontSize': '14px', 'fontWeight': 'bold', 'boxShadow': '0 2px 5px rgba(52, 152, 219, 0.3)'}
                        ),
                        html.Div(id='status-message', style={'marginTop': '15px', 'fontSize': '13px', 'textAlign': 'center', 'minHeight': '20px'}),
                        html.Div(id='timestamp-display', style={'color': '#7f8c8d', 'fontSize': '11px', 'textAlign': 'center', 'marginTop': '10px'})
                    ], style={'display': 'flex', 'flexDirection': 'column', 'justifyContent': 'center', 'height': '80%'})
                ], style={'width': '30%', 'padding': '20px', 'backgroundColor': '#f8f9fa', 'borderRadius': '0 0 8px 0'}),
            ], style={'display': 'flex'}),
            
        ], style={'backgroundColor': '#ffffff', 'marginBottom': '20px', 'border': '1px solid #bdc3c7', 'borderRadius': '8px', 'boxShadow': '0 4px 6px rgba(0,0,0,0.05)'}),
        
        # Portfolio Table
        html.Div([
            html.H2("Portfolio Allocation", style={'color': '#2c3e50', 'marginBottom': '15px'}),
            html.Div(id='portfolio-table-container')
        ], style={'backgroundColor': '#ffffff', 'padding': '20px', 'marginBottom': '20px', 'border': '1px solid #bdc3c7', 'borderRadius': '5px'}),
        
        # Factor Exposures Heatmap (moved after Portfolio Allocation)
        html.Div([
            html.Div([
                html.H3("Factor Exposures & Volatilities", style={'textAlign': 'center', 'color': '#2c3e50', 'marginTop': '20px', 'marginBottom': '20px'}),
                # Side-by-side layout container
                html.Div([
                    # Left column: Heatmap
                    html.Div([
                        html.H4("Asset Sensitivity to Risk Factors", style={'textAlign': 'center', 'color': '#2c3e50', 'marginBottom': '15px', 'fontSize': '14px'}),
                        dcc.Graph(id='sensitivity-heatmap', style={'height': '500px', 'margin': '0'})
                    ], style={'flex': '1', 'minWidth': '0', 'paddingRight': '10px'}),
                    
                    # Right column: Factor Volatility Table
                    html.Div([
                        html.Div(id='factor-vol-table-container')
                    ], style={'flex': '1', 'minWidth': '0', 'paddingLeft': '10px'})
                ], style={'display': 'flex', 'gap': '10px', 'justifyContent': 'space-between'})
            ]),

            html.Div([
                html.H3("Risk Factor Historical Performance", style={'textAlign': 'center', 'color': '#2c3e50', 'marginTop': '40px'}),
                html.Div([
                    html.Label("Select Factors:", style={'fontWeight': 'bold', 'marginRight': '10px'}),
                    dcc.Dropdown(
                        id='factor-selector',
                        options=[],
                        value=[],
                        multi=True,
                        placeholder="Select risk factors to visualize...",
                        style={'flex': '1'}
                    )
                ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '15px', 'maxWidth': '800px', 'margin': '0 auto 15px auto'}),
                dcc.Graph(id='factor-history-chart')
            ])
        ], style={'backgroundColor': '#ffffff', 'padding': '20px', 'marginBottom': '20px', 'border': '1px solid #bdc3c7', 'borderRadius': '5px'}),

        # Historical Allocation Analysis
        html.Div([
            html.H2("Historical Allocation Analysis", style={'color': '#2c3e50', 'marginBottom': '15px'}),
            
            # Date Range Selection and Performance Metrics
            html.Div([
                html.Div([
                    html.Label("Backtest Period:", style={'fontWeight': 'bold', 'marginRight': '10px'}),
                    dcc.DatePickerRange(
                        id='history-date-range',
                        min_date_allowed=datetime(2015, 1, 1),
                        max_date_allowed=datetime.now(),
                        start_date=datetime(datetime.now().year, 1, 1).date(),
                        end_date=datetime.now().date(),
                        display_format='YYYY-MM-DD'
                    ),
                ], style={'display': 'flex', 'alignItems': 'center'}),
                
                # PCA Factor Risk Parity Option
                html.Div([
                    html.Label("Optimization Method:", style={'fontWeight': 'bold', 'marginRight': '10px'}),
                    dcc.RadioItems(
                        id='optimization-method',
                        options=[
                            {'label': 'Asset Risk Parity (1/Vol)', 'value': 'asset_rp'},
                            {'label': 'PCA Factor Risk Parity', 'value': 'pca_factor_rp'}
                        ],
                        value='asset_rp',
                        inline=True,
                        style={'fontSize': '13px'}
                    ),
                ], style={'display': 'flex', 'alignItems': 'center', 'marginLeft': '30px'}),
                
                # Performance Metrics Table
                html.Div(id='performance-metrics-container', style={'marginLeft': '30px'}),
            ], style={'marginBottom': '15px', 'display': 'flex', 'alignItems': 'center', 'flexWrap': 'wrap', 'gap': '10px'}),

            html.Div([
                html.Button(
                    "Run Historical Analysis", 
                    id='run-history-button',
                    n_clicks=0,
                    style={'backgroundColor': '#27ae60', 'color': 'white', 'padding': '10px 20px', 'border': 'none', 'borderRadius': '5px', 'cursor': 'pointer', 'fontSize': '14px', 'fontWeight': 'bold', 'marginBottom': '15px'}
                ),
                dcc.Loading(
                    id="loading-history",
                    type="default",
                    children=[
                        dcc.Graph(id='historical-allocation-chart'),
                        html.Div(style={'height': '30px'}),
                        dcc.Graph(id='pnl-attribution-chart')
                    ]
                )
            ])
        ], style={'backgroundColor': '#ffffff', 'padding': '20px', 'marginBottom': '20px', 'border': '1px solid #bdc3c7', 'borderRadius': '5px'}),
        
        # Hidden div to store portfolio object reference
        dcc.Store(id='portfolio-data-store'),
        dcc.Store(id='asset-pool-store', data=initial_pool)
        
    ], style={'backgroundColor': '#f5f5f5', 'padding': '20px', 'fontFamily': 'Arial, sans-serif'})


# Callback 1: 根据 Asset Type 显示/隐藏对应的选择区域
@app.callback(
    [Output('universe-selection-row', 'style'),
     Output('sector-selection-row', 'style'),
     Output('commodities-confirm-row', 'style'),
     Output('universe-selector', 'value'),
     Output('sector-selector', 'value'),
     Output('commodities-selector', 'value')],
    [Input('asset-type-selector', 'value')]
)
def toggle_selection_rows(asset_type):
    """根据选择的资产类型显示相应的选择行"""
    if asset_type == 'Rates':
        return (
            {'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'},
            {'display': 'none'},  # Sector 行先隐藏，等选了 Universe 再显示
            {'display': 'none'},
            None,  # 重置 universe selector
            [],    # 重置 sector selector
            []     # 重置 commodities selector
        )
    elif asset_type == 'Commodities':
        return (
            {'display': 'none'},
            {'display': 'none'},
            {'display': 'flex', 'alignItems': 'flex-start', 'marginBottom': '12px'},
            None,
            [],
            []
        )
    else:
        return (
            {'display': 'none'},
            {'display': 'none'},
            {'display': 'none'},
            None,
            [],
            []
        )


# Callback 2: 选择了 Universe 后显示 Sector 选择
@app.callback(
    Output('sector-selection-row', 'style', allow_duplicate=True),
    [Input('universe-selector', 'value')],
    prevent_initial_call=True
)
def show_sector_selection(universe):
    """选择 Universe 后显示 Sector 选择"""
    if universe:
        return {'display': 'flex', 'alignItems': 'flex-start', 'marginBottom': '12px'}
    else:
        return {'display': 'none'}


# Callback 3: 管理资产池
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
    """管理资产池：添加或清空"""
    ctx = dash.callback_context
    if not ctx.triggered:
        return current_pool, dash.no_update, dash.no_update
    
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if button_id == 'clear-pool-btn':
        # 清空资产池
        return [], [html.Div("No assets selected. Please add assets using the selection above.", 
                            style={'color': '#95a5a6', 'fontStyle': 'italic', 'padding': '10px'})], "(0 assets)"
    
    # 初始化 pool
    if current_pool is None:
        current_pool = []
    
    if button_id == 'add-to-pool-btn' and asset_type == 'Rates':
        # 添加 Rates 资产
        if not universe or not sectors:
            return current_pool, dash.no_update, dash.no_update
        
        # 为每个选中的 sector 生成资产名称
        new_assets = []
        universe_code_map = {
            'China Gov Bond': 'CN',
            'US Gov Bond': 'US',
            'DE Gov Bond': 'EU',
            'UK Gov Bond': 'UK',
            'Japan Gov Bond': 'JP'
        }
        
        universe_code = universe_code_map.get(universe, 'XX')
        
        for sector in sectors:
            asset_name = f"{universe_code}{sector}"
            asset_info = {
                'name': asset_name,
                'type': 'Rates',
                'universe': universe,
                'sector': sector
            }
            # 避免重复添加
            if not any(a['name'] == asset_name for a in current_pool):
                new_assets.append(asset_info)
        
        current_pool.extend(new_assets)
    
    elif button_id == 'add-commodities-btn' and asset_type == 'Commodities':
        # 添加选中的 Commodities
        if not commodities:
            return current_pool, dash.no_update, dash.no_update
        
        for comm in commodities:
            asset_info = {
                'name': comm,
                'type': 'Commodities',
                'universe': comm,
                'sector': 'N/A'
            }
            if not any(a['name'] == comm for a in current_pool):
                current_pool.append(asset_info)
    
    # 更新显示
    if not current_pool:
        display = [html.Div("No assets selected. Please add assets using the selection above.", 
                           style={'color': '#95a5a6', 'fontStyle': 'italic', 'padding': '10px'})]
        count_text = "(0 assets)"
    else:
        display = []
        for asset in current_pool:
            # 对于 Commodities，不显示括号信息；对于 Rates，显示 universe 和 sector
            if asset['type'] == 'Commodities':
                display.append(
                    html.Div([
                        html.Span(f"• {asset['name']}", style={'fontWeight': 'bold'}),
                    ], style={'padding': '5px', 'marginBottom': '5px', 'backgroundColor': '#fff3cd', 'borderRadius': '3px'})
                )
            else:
                display.append(
                    html.Div([
                        html.Span(f"• {asset['name']}", style={'fontWeight': 'bold', 'marginRight': '10px'}),
                        html.Span(f"({asset['universe']} - {asset['sector']})", style={'color': '#7f8c8d', 'fontSize': '12px'}),
                    ], style={'padding': '5px', 'marginBottom': '5px', 'backgroundColor': '#e8f5e9', 'borderRadius': '3px'})
                )
        count_text = f"({len(current_pool)} assets)"
    
    return current_pool, display, count_text


@app.callback(
    [Output('portfolio-table-container', 'children'),
     Output('sensitivity-heatmap', 'figure'),
     Output('factor-vol-table-container', 'children'),
     Output('status-message', 'children'),
     Output('timestamp-display', 'children'),
     Output('portfolio-data-store', 'data'),
     Output('factor-selector', 'options'),
     Output('factor-selector', 'value')],
    [Input('run-button', 'n_clicks')],
    [State('capital-input', 'value'),
     State('capital-unit', 'value'),
     State('asset-pool-store', 'data')]
)
def run_analysis(n_clicks, total_capital, capital_unit, asset_pool):
    """Run the portfolio analysis and update all visualizations."""
    if n_clicks == 0:
        # Initial empty state
        empty_fig = go.Figure()
        empty_fig.update_layout(
            xaxis={'visible': False},
            yaxis={'visible': False},
            annotations=[{
                'text': 'Click "Run Analysis" to generate results',
                'xref': 'paper',
                'yref': 'paper',
                'showarrow': False,
                'font': {'size': 16, 'color': '#7f8c8d'}
            }]
        )
        return (
            html.Div("No data available. Click 'Run Analysis' to start.", style={'color': '#7f8c8d'}),
            empty_fig,  # sensitivity-heatmap
            None,  # factor-vol-table-container
            "",
            "",
            {},
            [],
            []
        )
    
    # Save current configuration
    if asset_pool:
        try:
            save_asset_pool(
                asset_pool, 
                metadata={
                    'capital': total_capital,
                    'unit': capital_unit
                }
            )
        except Exception as e:
            print(f"Warning: Failed to save asset pool: {e}")

    try:
        # Check if asset pool is empty
        if not asset_pool or len(asset_pool) == 0:
            error_msg = html.Span("⚠ Please add assets to the pool before running analysis", style={'color': '#e67e22', 'fontWeight': 'bold'})
            empty_fig = go.Figure()
            empty_fig.update_layout(
                xaxis={'visible': False},
                yaxis={'visible': False},
                annotations=[{
                    'text': 'Please add assets to the pool first',
                    'xref': 'paper',
                    'yref': 'paper',
                    'showarrow': False,
                    'font': {'size': 16, 'color': '#e67e22'}
                }]
            )
            return (
                html.Div("No assets in pool. Please add assets first.", style={'color': '#e67e22'}),
                empty_fig,  # sensitivity-heatmap
                None,  # factor-vol-table-container
                error_msg,
                "",
                {},
                [],
                []
            )
        
        # Run the analysis
        status_msg = html.Span("Running analysis...", style={'color': '#f39c12'})
        
        # Convert user input to absolute CNY based on selected unit
        if capital_unit == 'billion':
            multiplier = 1e9
        else:  # 'million'
            multiplier = 1e6

        total_capital_cny = float(total_capital) * multiplier

        # Get list of selected asset names
        selected_asset_names = [asset['name'] for asset in asset_pool]

        summary, returns, vols, factor_exp, factor_risk, portfolio = run_risk_parity_allocation(
            total_capital=total_capital_cny,
            use_cache=True,
            selected_assets=selected_asset_names
        )
        
        # Filter summary based on asset pool
        # selected_asset_names = [asset['name'] for asset in asset_pool]
        # filtered_summary = summary[summary['Asset'].isin(selected_asset_names)].copy()
        filtered_summary = summary
        
        # Check if filtered summary is empty
        if filtered_summary.empty:
            error_msg = html.Span("⚠ No matching assets found in optimization results", style={'color': '#e67e22', 'fontWeight': 'bold'})
            empty_fig = go.Figure()
            empty_fig.update_layout(
                annotations=[{
                    'text': 'Selected assets not found in optimization results',
                    'xref': 'paper',
                    'yref': 'paper',
                    'showarrow': False,
                    'font': {'size': 14, 'color': '#e67e22'}
                }]
            )
            return (
                html.Div("No matching assets found.", style={'color': '#e67e22'}),
                empty_fig,  # sensitivity-heatmap
                None,  # factor-vol-table-container
                error_msg,
                "",
                {},
                [],
                []
            )
        
        # Store results
        allocation_results['summary'] = filtered_summary
        allocation_results['factor_exposures'] = factor_exp
        allocation_results['factor_risk'] = factor_risk
        allocation_results['portfolio'] = portfolio
        allocation_results['timestamp'] = datetime.now()
        
        # Prepare portfolio table
        portfolio_df = prepare_portfolio_table(filtered_summary, factor_exp, portfolio)
        
        # Format for display
        portfolio_enhanced = []
        total_rounded_capital = 0.0
        if not portfolio_df.empty:
            for idx, row in portfolio_df.iterrows():
                record = row.to_dict()
                
                # Apply rounding rules
                asset_type = row['Asset Type']
                raw_capital = row['Capital (CNY)']
                
                if asset_type == 'Commodities':
                    unit = 1_000_000.0
                elif asset_type == 'Rates':
                    unit = 10_000_000.0
                else:
                    unit = 1.0
                
                rounded_capital = np.floor(raw_capital / unit) * unit
                total_rounded_capital += rounded_capital

                # Format numbers
                record['Capital (CNY)'] = f"{rounded_capital / 1_000_000:,.2f}"
                record['Capital (B)'] = rounded_capital / 1e9
                record['Weight (%)'] = f"{row['Weight (%)']:.2f}%"
                portfolio_enhanced.append(record)
        
        portfolio_table_df = pd.DataFrame(portfolio_enhanced)

        # Prepare span information for merging Asset Type cells visually
        # Dash DataTable doesn't support true rowspan, but we can emulate it
        # by only showing the Asset Type value on the first row of each group
        # and clearing it for subsequent rows with the same type.
        span_info = []
        last_type = None
        for idx, row in portfolio_table_df.iterrows():
            current_type = row['Asset Type']
            if current_type == last_type:
                span_info.append({
                    'Asset Type_display': '',
                    'Asset Type_is_first': False,
                })
            else:
                span_info.append({
                    'Asset Type_display': current_type,
                    'Asset Type_is_first': True,
                })
                last_type = current_type

        if span_info:
            span_df = pd.DataFrame(span_info)
            portfolio_table_df = pd.concat([portfolio_table_df, span_df], axis=1)
        
        # Add totals row
        if not portfolio_table_df.empty:
            total_capital_value = total_rounded_capital
            totals = {
                'Asset Type': 'TOTAL',
                'Asset Type_display': 'TOTAL',
                'Universe': '',
                'Sector': '',
                'Asset Name': '',
                'Capital (CNY)': f"{total_capital_value / 1_000_000:,.2f}",
                'Capital (B)': total_capital_value / 1e9,
                'Weight (%)': f"{filtered_summary['Weight (%)'].sum():.2f}%",
            }
            portfolio_table_df = pd.concat([portfolio_table_df, pd.DataFrame([totals])], ignore_index=True)
        
        # Create portfolio table
        portfolio_table = dash_table.DataTable(
            data=portfolio_table_df.to_dict('records'),
            columns=[
                {'name': 'Asset Type', 'id': 'Asset Type_display', 'presentation': 'markdown'},
                {'name': 'Universe', 'id': 'Universe'},
                {'name': 'Sector', 'id': 'Sector'},
                {'name': 'Asset Name', 'id': 'Asset Name'},
                {'name': 'Capital (Million CNY)', 'id': 'Capital (CNY)'},
                {'name': 'Weight', 'id': 'Weight (%)'},
            ],
            style_cell={
                'textAlign': 'left',
                'padding': '10px',
                'fontFamily': 'Arial, sans-serif'
            },
            style_header={
                'backgroundColor': '#3498db',
                'color': 'white',
                'fontWeight': 'bold',
                'textAlign': 'center'
            },
            style_data_conditional=[
                {
                    'if': {'filter_query': '{Asset Type} = "TOTAL"'},
                    'backgroundColor': '#2c3e50',
                    'color': 'white',
                    'fontWeight': 'bold'
                },
                {
                    'if': {'row_index': 'odd'},
                    'backgroundColor': '#ecf0f1'
                }
            ],
            style_table={'overflowX': 'auto'}
        )
        
        # (Removed allocation pie chart and factor risk chart - not displayed)
        
        # Create sensitivity heatmap
        # Build sensitivity matrix
        assets_with_allocation = filtered_summary[filtered_summary['Allocation (CNY)'] >= 1000].copy()
        assets_with_allocation = assets_with_allocation.nlargest(15, 'Allocation (CNY)')
        
        sensitivity_matrix = []
        # Get factors that are actually used (non-zero exposure in portfolio)
        factor_names = sorted([f for f in factor_exp['Risk Factor'].unique() if f.startswith(('IRDL', 'IRSL', 'IRCV', 'FXDL', 'CMDL'))])
        asset_names = assets_with_allocation['Asset'].tolist()
        
        for asset_name in asset_names:
            if asset_name in portfolio.assets:
                asset = portfolio.assets[asset_name]
                row = []
                for factor in factor_names:
                    row.append(asset.factors.get(factor, 0.0))
                sensitivity_matrix.append(row)
            else:
                sensitivity_matrix.append([0.0] * len(factor_names))
        
        heatmap_fig = go.Figure(data=go.Heatmap(
            z=sensitivity_matrix,
            x=factor_names,
            y=asset_names,
            colorscale='RdBu',
            zmid=0,
            text=sensitivity_matrix,
            texttemplate="%{text:.2f}",
            textfont={"size": 10}
        ))
        heatmap_fig.update_layout(
            title=None,
            height=500,
            margin=dict(l=100, r=50, t=30, b=50),
            xaxis_title="Risk Factor",
            yaxis_title="Asset"
        )
        
        # Create Factor Volatility Table
        # Filter factor_risk to only show factors displayed in heatmap
        factor_vol_df = factor_risk[factor_risk['Risk Factor'].isin(factor_names)].copy()
        factor_vol_df = factor_vol_df[['Risk Factor', 'Volatility (% ann.)']].copy()
        factor_vol_df['Volatility (% ann.)'] = factor_vol_df['Volatility (% ann.)'].apply(lambda x: f"{x:.2f}%")
        factor_vol_df = factor_vol_df.sort_values('Risk Factor')
        
        factor_vol_table = dash_table.DataTable(
            data=factor_vol_df.to_dict('records'),
            columns=[
                {'name': 'Risk Factor', 'id': 'Risk Factor'},
                {'name': 'Volatility (% ann.)', 'id': 'Volatility (% ann.)'}
            ],
            style_table={
                'overflowX': 'auto',
                'width': '100%',
                'minWidth': '320px'
            },
            style_cell={
                'textAlign': 'center',
                'padding': '8px',
                'fontSize': '12px'
            },
            style_cell_conditional=[
                {'if': {'column_id': 'Risk Factor'}, 'width': '45%'},
                {'if': {'column_id': 'Volatility (% ann.)'}, 'width': '55%'}
            ],
            style_header={
                'backgroundColor': '#2c3e50',
                'color': 'white',
                'fontWeight': 'bold',
                'textAlign': 'center'
            },
            style_data={
                'backgroundColor': '#f8f9fa'
            },
            style_data_conditional=[
                {'if': {'row_index': 'odd'}, 'backgroundColor': '#ffffff'}
            ]
        )
        
        factor_vol_container = html.Div([
            html.H4("Risk Factor Volatilities (3-Month EWMA)", 
                    style={'textAlign': 'center', 'color': '#2c3e50', 'marginBottom': '10px', 'fontSize': '14px'}),
            factor_vol_table
        ], style={'width': '100%', 'height': '500px', 'display': 'flex', 'flexDirection': 'column', 'justifyContent': 'center', 'alignItems': 'center'})
        
        # Prepare Factor Selector options
        # IRDL/IRSL/IRCV are now PCA-based (Level/Slope/Curvature from full-history PCA)
        available_factors = sorted([
            f for f in factor_exp['Risk Factor'].unique() 
            if f.startswith(('IRDL', 'IRSL', 'IRCV', 'FXDL', 'CMDL'))
        ])
        factor_options = [{'label': f, 'value': f} for f in available_factors]
        default_factors = available_factors[:3] if len(available_factors) >= 3 else available_factors

        status_msg = html.Span("✓ Analysis completed successfully!", style={'color': '#27ae60', 'fontWeight': 'bold'})
        timestamp_msg = f"Last updated: {allocation_results['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}"
        
        return (
            portfolio_table,
            heatmap_fig,
            factor_vol_container,
            status_msg,
            timestamp_msg,
            {'status': 'success'},
            factor_options,
            default_factors
        )
        
    except Exception as e:
        error_msg = html.Span(f"✗ Error: {str(e)}", style={'color': '#e74c3c', 'fontWeight': 'bold'})
        empty_fig = go.Figure()
        empty_fig.update_layout(
            annotations=[{
                'text': f'Error occurred: {str(e)}',
                'xref': 'paper',
                'yref': 'paper',
                'showarrow': False,
                'font': {'size': 14, 'color': '#e74c3c'}
            }]
        )
        
        return (
            html.Div(f"Error: {str(e)}", style={'color': '#e74c3c'}),
            empty_fig,  # sensitivity-heatmap
            None,  # factor-vol-table-container
            error_msg,
            "",
            {},
            [],
            []
        )


# Callback 5: Update Risk Factor Historical Performance Chart
@app.callback(
    Output('factor-history-chart', 'figure'),
    [Input('factor-selector', 'value')]
)
def update_factor_history_chart(selected_factors):
    """Update the risk factor historical performance chart based on selection."""
    if not selected_factors or allocation_results['portfolio'] is None:
        empty_fig = go.Figure()
        empty_fig.update_layout(
            title="No factors selected or analysis not run",
            xaxis={'visible': False},
            yaxis={'visible': False},
            template='plotly_white'
        )
        return empty_fig
    
    try:
        portfolio = allocation_results['portfolio']
        # Get factor returns data
        # Use get_risk_factors() method from Portfolio class
        # This returns the raw factor levels/prices
        factor_levels = portfolio.get_risk_factors(use_cache=True)
        
        if factor_levels is None or factor_levels.empty:
            raise ValueError("Cannot load risk factor data")

        fig = go.Figure()
        
        # Plot all selected factors
        for factor in selected_factors:
            if factor in factor_levels.columns:
                # Get the raw series and drop NaN values for this specific factor
                series = factor_levels[factor].dropna()
                
                if series.empty:
                    continue
                
                # Handle different factor types
                # IRDL/IRSL/IRCV are PCA scores (Level/Slope/Curvature from full-history PCA)
                # FXDL/CMDL are prices, plot raw levels
                
                if factor.startswith(('IRDL', 'IRSL', 'IRCV')):
                    # IR factors are cumulative PCA scores
                    fig.add_trace(go.Scatter(
                        x=series.index,
                        y=series.values,
                        mode='lines',
                        name=factor
                    ))
                else:
                    # For prices (FX, Commodities), plot raw levels
                    fig.add_trace(go.Scatter(
                        x=series.index,
                        y=series.values,
                        mode='lines',
                        name=factor
                    ))
        
        fig.update_layout(
            #title="Risk Factor Historical Performance",
            xaxis_title="Date",
            yaxis_title="Value",
            hovermode='x unified',
            template='plotly_white',
            height=500,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            # Add range slider and range selector for time navigation
            xaxis=dict(
                rangeslider=dict(
                    visible=True,
                    thickness=0.05
                ),
                rangeselector=dict(
                    buttons=list([
                        dict(count=1, label="1M", step="month", stepmode="backward"),
                        dict(count=3, label="3M", step="month", stepmode="backward"),
                        dict(count=6, label="6M", step="month", stepmode="backward"),
                        dict(count=1, label="YTD", step="year", stepmode="todate"),
                        dict(count=1, label="1Y", step="year", stepmode="backward"),
                        dict(count=3, label="3Y", step="year", stepmode="backward"),
                        dict(count=5, label="5Y", step="year", stepmode="backward"),
                        dict(step="all", label="All")
                    ]),
                    bgcolor='#f8f9fa',
                    activecolor='#3498db',
                    font=dict(size=11),
                    x=0,
                    y=1.15
                ),
                type="date"
            ),
            yaxis=dict(
                autorange=True,
                fixedrange=False
            ),
            # Use uirevision to maintain zoom state but allow autorange
            uirevision='constant'
        )
        return fig
        
    except Exception as e:
        print(f"Error plotting factor history: {e}")
        return go.Figure().update_layout(title=f"Error plotting data: {str(e)}")


# Callback for Historical Allocation Analysis
@app.callback(
    [Output('historical-allocation-chart', 'figure'),
     Output('pnl-attribution-chart', 'figure'),
     Output('performance-metrics-container', 'children')],
    [Input('run-history-button', 'n_clicks')],
    [State('asset-pool-store', 'data'),
     State('capital-input', 'value'),
     State('capital-unit', 'value'),
     State('history-date-range', 'start_date'),
     State('history-date-range', 'end_date'),
     State('optimization-method', 'value')]
)
def update_historical_allocation(n_clicks, asset_pool, total_capital, capital_unit, start_date, end_date, optimization_method):
    if n_clicks == 0 or not asset_pool:
        return go.Figure(), go.Figure(), None
    
    try:
        # Parse dates from DatePickerRange
        if start_date:
            start_date = pd.to_datetime(start_date)
        if end_date:
            end_date = pd.to_datetime(end_date)

        # 1. Load all risk factors
        loader = RiskFactorLoader(DIR_INPUT)
        risk_factors = loader.load_risk_factors(use_cache=True)
        
        # Ensure index is DatetimeIndex for proper date comparisons
        if not isinstance(risk_factors.index, pd.DatetimeIndex):
            risk_factors.index = pd.to_datetime(risk_factors.index)
        
        # Load raw market data for PnL
        market_data = load_raw_market_data()
        
        if risk_factors.empty:
            return go.Figure().update_layout(title="No risk factor data available"), go.Figure(), None
            
        # 2. Use selected date range, fallback to last 2 years if not provided
        if not end_date:
            end_date = risk_factors.index.max()
        if not start_date:
            start_date = end_date - relativedelta(years=2)
        
        # Generate list of 1st of each month in the range (for rebalancing)
        rebalance_dates = []
        current_date = start_date.replace(day=1)
        while current_date <= end_date:
            if current_date >= risk_factors.index.min():
                rebalance_dates.append(current_date)
            current_date += relativedelta(months=1)
            
        # 3. Create portfolio with selected assets
        selected_asset_names = [asset['name'] for asset in asset_pool]
        portfolio = create_custom_portfolio(selected_asset_names)
        
        # 4. Calculate allocation for each rebalance date
        history_data = []
        allocations_by_date = {}  # Store allocations for each rebalance period
        
        # Ensure total_capital is float
        if total_capital is None:
            total_capital = 10_000_000_000
        else:
            total_capital = float(total_capital)
            
        # Adjust for unit
        if capital_unit == 'billion':
            total_capital *= 1_000  # Convert to Million CNY
        
        # Initialize PCA optimizer if needed
        pca_optimizer = None
        if optimization_method == 'pca_factor_rp':
            pca_optimizer = PCAFactorRiskParityOptimizer(
                portfolio=portfolio,
                input_dir=DIR_INPUT,
                pca_lookback_years=1.0,
                vol_lookback_months=3,
                ewma_lambda=0.94
            )
        
        for i, date in enumerate(rebalance_dates):
            if optimization_method == 'pca_factor_rp' and pca_optimizer is not None:
                # Use PCA Factor Risk Parity
                try:
                    weights_series, _ = pca_optimizer.fit_and_calculate(pd.Timestamp(date))
                    weights = weights_series.to_dict()
                except Exception as e:
                    print(f"PCA optimization failed at {date}: {e}")
                    continue
            else:
                # Use traditional asset-level Risk Parity (1/vol)
                lookback_start = date - relativedelta(months=3)
                mask = (risk_factors.index <= date) & (risk_factors.index >= lookback_start)
                filtered_factors = risk_factors.loc[mask]
                
                if len(filtered_factors) < 40:
                    continue
                    
                # Calculate volatilities manually for each asset
                volatilities = {}
                for name, asset in portfolio.assets.items():
                    vol = asset.get_volatility(filtered_factors, use_cache=False)
                    volatilities[name] = vol
                
                # Calculate weights (Risk Parity: w ~ 1/vol)
                inv_vols = {k: 1.0/v if v > 0 else 0 for k, v in volatilities.items()}
                sum_inv_vol = sum(inv_vols.values())
                
                if sum_inv_vol == 0:
                    continue
                    
                weights = {k: v/sum_inv_vol for k, v in inv_vols.items()}
            
            # Calculate capital allocation
            row = {'Date': date}
            current_allocations = {}
            
            for name, weight in weights.items():
                # Allocation in Million CNY
                alloc = weight * total_capital
                row[name] = alloc
                current_allocations[name] = alloc * 1_000_000 # Absolute amount for PnL calc
            
            history_data.append(row)
            allocations_by_date[date] = current_allocations
        
        if not history_data:
            return go.Figure().update_layout(title="Insufficient data for historical analysis"), go.Figure(), None
        
        # 5. Calculate DAILY PnL based on monthly allocations
        # For each day, find which rebalance period it belongs to, use that allocation
        
        # Get all trading days in the range
        all_dates = sorted(risk_factors.loc[(risk_factors.index >= start_date) & (risk_factors.index <= end_date)].index)
        
        # Build a mapping: for each trading day, which allocation to use
        sorted_rebalance_dates = sorted(allocations_by_date.keys())
        
        # Initialize daily PnL tracking
        daily_pnl_records = []
        cumulative_pnl = {name: 0.0 for name in selected_asset_names}
        cumulative_pnl['Total'] = 0.0
        
        # Pre-compute daily returns for each asset
        asset_daily_returns = {}
        for name in selected_asset_names:
            ret_df = calculate_daily_returns_series(name, market_data, start_date, end_date)
            if not ret_df.empty:
                ret_df = ret_df.set_index('Date')
                asset_daily_returns[name] = ret_df
        
        # Calculate daily PnL
        for trading_day in all_dates:
            # Find the applicable allocation (most recent rebalance before this day)
            applicable_alloc = None
            for rb_date in sorted_rebalance_dates:
                if rb_date <= trading_day:
                    applicable_alloc = allocations_by_date[rb_date]
                else:
                    break
            
            if applicable_alloc is None:
                continue
            
            # Calculate PnL for this day
            daily_record = {'Date': trading_day}
            total_daily_pnl = 0.0
            
            for name in selected_asset_names:
                if name in applicable_alloc and name in asset_daily_returns:
                    allocation = applicable_alloc[name]
                    ret_df = asset_daily_returns[name]
                    
                    # Get daily return for this trading day
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
        
        # 6. Plot Allocation (monthly rebalancing points)
        fig_alloc = go.Figure()
        
        for asset_name in selected_asset_names:
            if asset_name in df_history.columns:
                fig_alloc.add_trace(go.Scatter(
                    x=df_history['Date'],
                    y=df_history[asset_name],
                    mode='lines+markers',
                    name=asset_name,
                    stackgroup='one' # Stacked area chart for allocation
                ))
        
        fig_alloc.update_layout(
            title="Historical Portfolio Allocation (Monthly Rebalancing)",
            xaxis_title="Date",
            yaxis_title="Allocation",
            hovermode='x unified',
            template='plotly_white',
            height=450,
            legend=dict(orientation="h", y=1.02, x=1, xanchor="right")
        )
        
        # 7. Plot DAILY PnL Attribution
        fig_pnl = go.Figure()
        
        if not df_pnl.empty:
            # Plot Individual Asset PnL (Stacked)
            for asset_name in selected_asset_names:
                if asset_name in df_pnl.columns:
                    fig_pnl.add_trace(go.Scatter(
                        x=df_pnl['Date'],
                        y=df_pnl[asset_name],
                        mode='lines',
                        name=asset_name,
                        stackgroup='one' # Stacked area chart for PnL
                    ))
            
            # Plot Total PnL (Line on top)
            fig_pnl.add_trace(go.Scatter(
                x=df_pnl['Date'],
                y=df_pnl['Total'],
                mode='lines',
                name='Total Portfolio PnL',
                line=dict(color='black', width=2, dash='dash')
            ))
                    
        fig_pnl.update_layout(
            title="Daily Cumulative Profit & Loss Attribution (Million CNY)",
            xaxis_title="Date",
            yaxis_title="Cumulative PnL",
            hovermode='x unified',
            template='plotly_white',
            height=450,
            legend=dict(orientation="h", y=1.02, x=1, xanchor="right")
        )
        
        # 8. Calculate Performance Metrics
        metrics_table = None
        if not df_pnl.empty and len(df_pnl) > 1:
            # Portfolio value = Initial Capital + Cumulative PnL
            initial_capital = total_capital  # Already in Million CNY
            portfolio_values = initial_capital + df_pnl['Total']
            
            # Daily returns
            daily_returns = portfolio_values.pct_change().dropna()
            
            # Annualized Return
            total_days = (df_pnl['Date'].iloc[-1] - df_pnl['Date'].iloc[0]).days
            if total_days > 0:
                total_return = (portfolio_values.iloc[-1] / portfolio_values.iloc[0]) - 1
                annualized_return = (1 + total_return) ** (365 / total_days) - 1
            else:
                annualized_return = 0
            
            # Sharpe Ratio (assuming risk-free rate = 2%)
            risk_free_rate = 0.02
            if len(daily_returns) > 0 and daily_returns.std() > 0:
                excess_return = annualized_return - risk_free_rate
                annualized_vol = daily_returns.std() * np.sqrt(252)
                sharpe_ratio = excess_return / annualized_vol
            else:
                sharpe_ratio = 0
            
            # Max Drawdown
            rolling_max = portfolio_values.expanding().max()
            drawdowns = (portfolio_values - rolling_max) / rolling_max
            max_drawdown = drawdowns.min()
            
            # Create metrics table
            metrics_table = html.Table([
                html.Tr([
                    html.Th("Annualized Return", style={'padding': '8px 15px', 'backgroundColor': '#3498db', 'color': 'white', 'borderRadius': '4px 0 0 4px'}),
                    html.Th("Sharpe Ratio", style={'padding': '8px 15px', 'backgroundColor': '#3498db', 'color': 'white'}),
                    html.Th("Max Drawdown", style={'padding': '8px 15px', 'backgroundColor': '#3498db', 'color': 'white', 'borderRadius': '0 4px 4px 0'}),
                ]),
                html.Tr([
                    html.Td(f"{annualized_return:.2%}", style={'padding': '8px 15px', 'textAlign': 'center', 'backgroundColor': '#ecf0f1', 'fontWeight': 'bold', 'color': '#27ae60' if annualized_return >= 0 else '#e74c3c'}),
                    html.Td(f"{sharpe_ratio:.2f}", style={'padding': '8px 15px', 'textAlign': 'center', 'backgroundColor': '#ecf0f1', 'fontWeight': 'bold', 'color': '#27ae60' if sharpe_ratio >= 1 else '#f39c12' if sharpe_ratio >= 0 else '#e74c3c'}),
                    html.Td(f"{max_drawdown:.2%}", style={'padding': '8px 15px', 'textAlign': 'center', 'backgroundColor': '#ecf0f1', 'fontWeight': 'bold', 'color': '#e74c3c'}),
                ]),
            ], style={'borderCollapse': 'collapse', 'fontSize': '14px'})
        
        return fig_alloc, fig_pnl, metrics_table
        
    except Exception as e:
        print(f"Error in historical analysis: {e}")
        import traceback
        traceback.print_exc()
        err_fig = go.Figure().update_layout(title=f"Error: {str(e)}")
        return err_fig, err_fig, None


# Set the layout
app.layout = create_layout


def run_dashboard(host='127.0.0.1', port=5003, debug=True):
    """
    Run the dashboard server.
    
    Args:
        host: Host IP address
        port: Port number
        debug: Enable debug mode
    """
    print("\n" + "="*80)
    print("Starting Multi-Asset Portfolio Dashboard")
    print("="*80)
    print(f"Dashboard URL: http://{host}:{port}")
    print("Press Ctrl+C to stop the server")
    print("="*80 + "\n")
    
    app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    run_dashboard()
