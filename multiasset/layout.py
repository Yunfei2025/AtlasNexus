# -*- coding: utf-8 -*-
"""
Layout components for Multi-Asset Dashboard.

Functions for creating UI layouts and table displays.
"""
from dash import dcc, html
from datetime import datetime
import pandas as pd
from multiasset.storage import load_last_asset_pool
from multiasset.data import get_asset_type, get_universe, get_sector

_CGB_TENOR_BANDS: dict = {
    "1Y": (0.9, 1.2), "2Y": (1.6, 2.5), "5Y": (4.0, 6.0),
    "10Y": (8.5, 10.0), "20Y": (15.0, 25.0), "30Y": (25.0, 30.0),
}


def get_cgb_otr_map() -> dict[str, str]:
    """Return {tenor: on-the-run bond ID} for CGB (TBond) using highest TOR per bucket.

    Uses fresh InstrumentInfo from DIR_INPUT, matching the Market Data tab's on-the-run selection.
    """
    try:
        from settings.paths import DIR_INPUT
        import numpy as np
        from pathlib import Path

        bond_info = pd.read_pickle(str(Path(DIR_INPUT) / "TBond-InstrumentInfo.pkl"))
        if not isinstance(bond_info, pd.DataFrame) or bond_info.empty:
            return {}

        bond_info = bond_info.copy()
        required_cols = ["起息日期", "到期日期", "证券全称", "成交量", "债券余额:亿"]
        if not all(col in bond_info.columns for col in required_cols):
            return {}

        today = pd.Timestamp.today().normalize()

        # Calculate turnover ratio: volume / balance (normalized by 1e4 for unit consistency)
        volume = pd.to_numeric(bond_info["成交量"], errors="coerce")
        balance = pd.to_numeric(bond_info["债券余额:亿"], errors="coerce")
        turnover = volume / balance / 1e4
        turnover = turnover.replace([np.inf, -np.inf], 0).fillna(0)

        maturity = pd.to_datetime(bond_info["到期日期"], errors="coerce")
        start_date = pd.to_datetime(bond_info["起息日期"], errors="coerce")
        terms = (maturity - today).dt.days / 365.0

        name_mask = bond_info["证券全称"].astype(str).str.contains("国债", na=False)

        result: dict[str, str] = {}
        for tenor, (lo, hi) in _CGB_TENOR_BANDS.items():
            bucket_mask = (
                terms.notna()
                & start_date.notna()
                & (start_date < today)
                & (maturity > today)
                & (terms > lo)
                & (terms <= hi)
                & name_mask
                & (balance > 0)
                & (volume > 0)
            )

            bucket_turnover = turnover[bucket_mask]
            if bucket_turnover.empty or (bucket_turnover <= 0).all():
                result[tenor] = "—"
                continue

            # On-the-run = bond with highest turnover ratio (most liquid) in the tenor band
            result[tenor] = bucket_turnover.idxmax()

        return result
    except Exception:
        return {}


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
    
    # Get all unique risk factors for sensitivity columns
    risk_factors = sorted([f for f in factor_exposures_df['Risk Factor'].values if f.startswith(('IRDL', 'IRSL', 'IRCV', 'FXDL', 'CMDL'))])

    # Filter out negligible allocations
    mask = summary_df['Allocation (CNY)'].abs() >= 1000
    filtered = summary_df[mask].copy()

    if filtered.empty:
        return pd.DataFrame()

    # Build classification columns (vectorized via .map)
    asset_col = filtered['Asset']
    otr_map = get_cgb_otr_map()
    filtered = filtered.assign(
        **{
            'Asset Type': asset_col.map(get_asset_type),
            'Universe':   asset_col.map(get_universe),
            'Sector':     asset_col.map(get_sector),
            'Asset Name': asset_col,
            'Instrument': [
                (otr_map.get(sector, f"CGB-{sector}")
                 if universe == 'China Gov Bond' and asset_type == 'Rates'
                 else asset)
                for asset, asset_type, universe, sector in zip(
                    asset_col,
                    asset_col.map(get_asset_type),
                    asset_col.map(get_universe),
                    asset_col.map(get_sector),
                )
            ],
            'Capital (CNY)': filtered['Allocation (CNY)'],
        }
    )

    # Duration: IRDL value from get_default_sensitivities (modified duration proxy)
    from multiasset.utils import get_default_sensitivities
    filtered['Duration'] = filtered['Sector'].map(
        lambda s: get_default_sensitivities(s).get('IRDL', 0.0) if isinstance(s, str) else 0.0
    )

    # DV01 (MM CNY) = capital (CNY) * duration / 1e10  ≡  capital_mm * duration / 1e4
    filtered['DV01 (MM CNY)'] = (filtered['Capital (CNY)'] * filtered['Duration'] / 1e10).round(4)

    # Build sensitivity matrix from portfolio object
    if portfolio:
        for factor in risk_factors:
            filtered[factor] = filtered['Asset'].map(
                lambda a, f=factor: (
                    portfolio.assets[a].factors.get(f, 0.0)
                    if a in portfolio.assets else 0.0
                )
            )
    else:
        for factor in risk_factors:
            filtered[factor] = 0.0

    cols = ['Asset Type', 'Universe', 'Sector', 'Asset Name', 'Instrument',
            'Duration', 'Capital (CNY)', 'DV01 (MM CNY)', 'Weight (%)'] + risk_factors
    portfolio_df = filtered[cols].sort_values(['Asset Type', 'Universe', 'Sector'])
    portfolio_df = portfolio_df.reset_index(drop=True)

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
    
    # Build weighted-sensitivity matrix from portfolio object (vectorized)
    if sensitivity_cols and portfolio_obj:
        weight_series = portfolio_df['Weight (%)'] / 100.0
        name_to_idx = {name: i for i, name in enumerate(portfolio_df['Asset Name'])}
        for factor_name in sensitivity_cols:
            sens_values = portfolio_df[factor_name].values.copy()
            for asset_name, asset in portfolio_obj.assets.items():
                if asset_name in name_to_idx and factor_name in asset.factors:
                    i = name_to_idx[asset_name]
                    sens_values[i] = weight_series.iloc[i] * asset.factors[factor_name]
            portfolio_df[factor_name] = sens_values
    
    # Add totals row
    totals = {
        'Asset Type': 'TOTAL',
        'Universe': '',
        'Sector': '',
        'Asset Name': '',
        'Instrument': '',
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
    initial_capital = 10
    initial_unit = 'billion'
    
    if last_run_data:
        if 'asset_pool' in last_run_data:
            initial_pool = last_run_data['asset_pool']
            # Note: Do NOT auto-trigger run_analysis on page load
            # User should click 'RUN ANALYSIS' manually to ensure Risk Budgets are loaded
            # initial_n_clicks remains 0
        
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
        
        # Tabs
        dcc.Tabs(id='main-tabs', value='regime-tab', children=[
            # Tab 1: Regime (Risk Factor Historical Performance)
            dcc.Tab(label='Regime', value='regime-tab', children=[
                html.Div([
                    html.H2("Risk Factor Historical Performance", style={'textAlign': 'center', 'color': '#2c3e50', 'marginTop': '20px', 'marginBottom': '20px'}),
                    
                    # Cascaded dropdown selection
                    html.Div([
                        # Row 1: Asset Class Selection
                        html.Div([
                            html.Label("Asset Class:", style={'fontWeight': 'bold', 'marginRight': '10px', 'width': '100px'}),
                            dcc.Dropdown(
                                id='factor-asset-class-selector',
                                options=[
                                    {'label': 'Rates', 'value': 'Rates'},
                                    {'label': 'Spread', 'value': 'Spread'},
                                    {'label': 'FX', 'value': 'FX'},
                                    {'label': 'Commodities', 'value': 'Commodities'},
                                ],
                                value=None,
                                placeholder="Select asset class...",
                                clearable=True,
                                style={'flex': '1'}
                            )
                        ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'}),
                        
                        # Row 2: Region/Type Selection
                        html.Div([
                            html.Label("Region/Type:", style={'fontWeight': 'bold', 'marginRight': '10px', 'width': '100px'}),
                            dcc.Dropdown(
                                id='factor-region-selector',
                                options=[],
                                value=None,
                                placeholder="Select region or type...",
                                clearable=True,
                                style={'flex': '1'}
                            )
                        ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'}),
                        
                        # Row 3: Factor Selection
                        html.Div([
                            html.Label("Factors:", style={'fontWeight': 'bold', 'marginRight': '10px', 'width': '100px'}),
                            dcc.Dropdown(
                                id='factor-type-selector',
                                options=[],
                                value=[],
                                multi=True,
                                placeholder="Select factors...",
                                style={'flex': '1'}
                            )
                        ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'}),
                    ], style={'maxWidth': '800px', 'margin': '0 auto 20px auto', 'padding': '15px', 'backgroundColor': '#f8f9fa', 'borderRadius': '5px'}),
                    
                    dcc.Graph(id='factor-history-chart')
                ], style={'backgroundColor': '#ffffff', 'padding': '20px', 'border': '1px solid #bdc3c7', 'borderRadius': '5px', 'margin': '20px'})
            ]),
            
            # Tab 2: Allocation (Configuration + Portfolio)
            dcc.Tab(label='Allocation', value='allocation-tab', children=[
                html.Div([
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
                                            {'label': ' Spread', 'value': 'Spread'},
                                            {'label': ' Commodities', 'value': 'Commodities'},
                                        ],
                                        value=None,
                                        inline=True,
                                        inputStyle={'marginRight': '5px', 'marginLeft': '10px'},
                                        style={'fontSize': '13px'}
                                    ),
                                ], style={'marginBottom': '12px', 'display': 'flex', 'alignItems': 'center'}),
                                
                                # Step 2: Universe (Rates & Spread)
                                html.Div([
                                    html.Label("Universe:", style={'fontWeight': 'bold', 'width': '70px', 'fontSize': '13px'}),
                                    dcc.Dropdown(
                                        id='universe-selector',
                                        options=[],
                                        value=None,
                                        placeholder="Select universe...",
                                        clearable=True,
                                        style={'width': '100%', 'fontSize': '13px'}
                                    ),
                                ], id='universe-selection-row', style={'display': 'none', 'marginBottom': '12px', 'alignItems': 'center'}),
                                
                                # Step 3: Sectors (Rates & Spread)
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

                        # ── Section 3: Hedge Instruments & Factor Risk Targets ─────────────
                        html.Hr(style={'margin': '0', 'borderColor': '#eee'}),
                        html.Div([
                            # Column A: Hedge Instruments
                            html.Div([
                                html.H5("5. Hedge Instruments (Optional)",
                                        style={'color': '#34495e', 'marginTop': '0', 'marginBottom': '8px', 'fontSize': '14px'}),
                                html.P("Selected instruments can take short positions to offset factor risk.",
                                       style={'fontSize': '11px', 'color': '#7f8c8d', 'marginBottom': '8px'}),
                                dcc.Checklist(
                                    id='hedge-instruments-checklist',
                                    options=[
                                        {'label': ' 1Y IRS Swap (CN)',  'value': 'HEDGE_IRS_1Y'},
                                        {'label': ' 5Y IRS Swap (CN)',  'value': 'HEDGE_IRS_5Y'},
                                        {'label': ' 10Y CGB Bond (CN)', 'value': 'HEDGE_CGB_10Y'},
                                        {'label': ' 30Y CGB Bond (CN)', 'value': 'HEDGE_CGB_30Y'},
                                    ],
                                    value=[],
                                    inline=False,
                                    inputStyle={'marginRight': '6px'},
                                    style={'fontSize': '13px', 'lineHeight': '2'},
                                ),
                            ], style={'width': '40%', 'padding': '15px 20px', 'borderRight': '1px solid #eee'}),

                            # Column B: Factor Risk Targets
                            html.Div([
                                html.H5("6. Factor Risk Targets (Optional)",
                                        style={'color': '#34495e', 'marginTop': '0', 'marginBottom': '8px', 'fontSize': '14px'}),
                                html.P("Set desired % risk contribution per CN rate factor. Leave blank for equal risk parity.",
                                       style={'fontSize': '11px', 'color': '#7f8c8d', 'marginBottom': '8px'}),
                                html.Div([
                                    html.Div([
                                        html.Label("IRDL.CN (Level):",
                                                   style={'fontSize': '12px', 'width': '130px', 'fontWeight': 'bold'}),
                                        dcc.Input(id='irdl-target', type='number', min=0, max=100,
                                                  placeholder='e.g. 60', debounce=True,
                                                  style={'width': '80px', 'padding': '3px', 'borderRadius': '4px',
                                                         'border': '1px solid #ddd', 'fontSize': '12px'}),
                                        html.Span("%", style={'marginLeft': '4px', 'fontSize': '12px', 'color': '#7f8c8d'}),
                                    ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '6px'}),
                                    html.Div([
                                        html.Label("IRSL.CN (Slope):",
                                                   style={'fontSize': '12px', 'width': '130px', 'fontWeight': 'bold'}),
                                        dcc.Input(id='irsl-target', type='number', min=0, max=100,
                                                  placeholder='e.g. 25', debounce=True,
                                                  style={'width': '80px', 'padding': '3px', 'borderRadius': '4px',
                                                         'border': '1px solid #ddd', 'fontSize': '12px'}),
                                        html.Span("%", style={'marginLeft': '4px', 'fontSize': '12px', 'color': '#7f8c8d'}),
                                    ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '6px'}),
                                    html.Div([
                                        html.Label("IRCV.CN (Curvature):",
                                                   style={'fontSize': '12px', 'width': '130px', 'fontWeight': 'bold'}),
                                        dcc.Input(id='ircv-target', type='number', min=0, max=100,
                                                  placeholder='e.g. 15', debounce=True,
                                                  style={'width': '80px', 'padding': '3px', 'borderRadius': '4px',
                                                         'border': '1px solid #ddd', 'fontSize': '12px'}),
                                        html.Span("%", style={'marginLeft': '4px', 'fontSize': '12px', 'color': '#7f8c8d'}),
                                    ], style={'display': 'flex', 'alignItems': 'center'}),
                                ]),
                            ], style={'width': '60%', 'padding': '15px 20px'}),
                        ], style={'display': 'flex', 'backgroundColor': '#fafcff'}),

                    ], style={'backgroundColor': '#ffffff', 'marginBottom': '20px', 'border': '1px solid #bdc3c7', 'borderRadius': '8px', 'boxShadow': '0 4px 6px rgba(0,0,0,0.05)'}),
                    
                    # Portfolio Table
                    html.Div([
                        html.H2("Portfolio Allocation", style={'color': '#2c3e50', 'marginBottom': '15px'}),
                        html.Div(id='portfolio-table-container')
                    ], style={'backgroundColor': '#ffffff', 'padding': '20px', 'marginBottom': '20px', 'border': '1px solid #bdc3c7', 'borderRadius': '5px'}),
                ], style={'padding': '20px'})
            ]),
            
            # Tab 3: Risk (Factor Exposures & Volatilities)
            dcc.Tab(label='Risk', value='risk-tab', children=[
                html.Div([
                    html.H2("Factor Exposures & Volatilities", style={'textAlign': 'center', 'color': '#2c3e50', 'marginTop': '20px', 'marginBottom': '20px'}),
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
                ], style={'backgroundColor': '#ffffff', 'padding': '20px', 'border': '1px solid #bdc3c7', 'borderRadius': '5px', 'margin': '20px'})
            ]),
            
            # Tab 4: Backtest (Historical Allocation Analysis)
            dcc.Tab(label='Backtest', value='backtest-tab', children=[
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
                        
                        # Method display (fixed to PCA Factor Risk Parity)
                        html.Div([
                            html.Label("Method: ", style={'fontWeight': 'bold', 'marginRight': '5px'}),
                            html.Span("PCA Factor Risk Parity", style={'color': '#27ae60', 'fontWeight': 'bold'}),
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
                ], style={'backgroundColor': '#ffffff', 'padding': '20px', 'border': '1px solid #bdc3c7', 'borderRadius': '5px', 'margin': '20px'})
            ]),
        ]),
        
        # Hidden stores
        dcc.Store(id='portfolio-data-store'),
        dcc.Store(id='asset-pool-store', data=initial_pool),
        dcc.Store(id='hedge-pool-store', data=[]),
        
    ], style={'backgroundColor': '#f5f5f5', 'padding': '20px', 'fontFamily': 'Arial, sans-serif'})
