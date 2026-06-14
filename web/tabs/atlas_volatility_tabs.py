# -*- coding: utf-8 -*-
"""Volatility trading strategy tab layouts and callbacks for AtlasNexus Daily Console.

Migrated from derivatives/vol/dashboard.py to integrate into the unified AlphaBook interface.

Implements:
- Mean Reversion strategy analysis using Bollinger Bands
- Futures implied volatility term structure visualization
- Strategy backtesting and performance metrics
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any

import numpy as np
import pandas as pd

from dash import dcc, html, dash_table, callback_context
from dash.dependencies import Input, Output, State
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Theme / Style constants (consistent with atlas_alpha_tabs.py)
# ---------------------------------------------------------------------------
THEME = {
    'bg_main': '#082255',
    'bg_card': '#0c2b64',
    'bg_input': '#112e66',
    'text_main': '#ffffff',
    'text_sub': '#aab0c0',
    'accent': '#3498db',
    'success': '#00cc96',
    'warning': '#f39c12',
    'danger': '#ef553b',
    'table_header': '#1a3a7a',
    'table_row_even': '#0c2b64',
    'table_row_odd': '#082255',
}

# ---------------------------------------------------------------------------
# Ticker Options for Volatility Analysis
# ---------------------------------------------------------------------------
VOL_TICKER_OPTIONS = [
    {'label': 'SSE 50 (000016.SH)', 'value': '000016.SH'},
    {'label': 'CSI 300 (000300.SH)', 'value': '000300.SH'},
    {'label': 'CSI 1000 (000852.SH)', 'value': '000852.SH'},
    {'label': 'Gold (AU.SHF)', 'value': 'AU.SHF'},
    {'label': 'Silver (AG.SHF)', 'value': 'AG.SHF'},
    {'label': 'Copper (CU.SHF)', 'value': 'CU.SHF'},
    {'label': 'Soda Ash (SA.CZC)', 'value': 'SA.CZC'},
    {'label': 'Crude Oil (SC.INE)', 'value': 'SC.INE'},
    {'label': 'Lithium Carbonate (LC.GFE)', 'value': 'LC.GFE'},
    {'label': 'Rebar (RB.SHF)', 'value': 'RB.SHF'},
]

DEFAULT_TICKER = 'AU.SHF'

# Strategy parameters
DEFAULT_LOOKBACK = 10
DEFAULT_NUM_STD = 2.0


# ---------------------------------------------------------------------------
# Data Loading Utilities
# ---------------------------------------------------------------------------

def _get_input_dir() -> Path:
    """Get the input directory path."""
    try:
        from settings.paths import DIR_INPUT
        return Path(DIR_INPUT)
    except ImportError:
        return Path(__file__).parent.parent / 'input'


def load_vol_data(ticker: str = DEFAULT_TICKER) -> Optional[pd.DataFrame]:
    """Load volatility time series data for the given ticker.
    
    Returns DataFrame with columns: IV_1M, IV_2M, IV_3M
    """
    dir_input = _get_input_dir()
    vol_file = dir_input / 'futures-volpx.pkl'
    
    if not vol_file.exists():
        print(f"Vol file not found: {vol_file}")
        return None
    
    try:
        all_data = pd.read_pickle(vol_file)
        if ticker not in all_data:
            print(f"Ticker {ticker} not found in data. Available tickers: {list(all_data.keys())}")
            return None
        
        df = all_data[ticker].copy()
        
        # Debug: print original columns
        print(f"Original columns for {ticker}: {df.columns.tolist()}")
        
        # Standardize column names - handle different possible formats
        # Common formats: iv_1m1000_n, IV_1M, etc.
        col_mapping = {}
        for col in df.columns:
            col_str = str(col).upper()
            if '1M' in col_str or 'IV_1M1000' in col_str:
                col_mapping[col] = 'IV_1M'
            elif '2M' in col_str or 'IV_2M1000' in col_str:
                col_mapping[col] = 'IV_2M'
            elif '3M' in col_str or 'IV_3M1000' in col_str:
                col_mapping[col] = 'IV_3M'
        
        if col_mapping:
            df = df.rename(columns=col_mapping)
            print(f"Renamed columns to: {df.columns.tolist()}")
        elif len(df.columns) == 3:
            # Fallback: assume columns are in order 1M, 2M, 3M
            df.columns = ['IV_1M', 'IV_2M', 'IV_3M']
            print(f"Applied default column names: {df.columns.tolist()}")
        
        # Verify we have the required columns
        required_cols = ['IV_1M', 'IV_2M', 'IV_3M']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            print(f"Missing required columns: {missing_cols}")
            return None
        
        # Drop any extra columns and keep only required ones
        df = df[required_cols]
        
        # Convert to numeric and drop NaNs
        for col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        print(f"Loaded {len(df)} rows of volatility data for {ticker}")
        return df
        
    except Exception as e:
        print(f"Error loading volatility data: {e}")
        import traceback
        traceback.print_exc()
        return None


def retrieve_vol_data() -> bool:
    """Retrieve/update futures volatility data from Wind."""
    try:
        from derivatives.vol.retrieve import retrieveFuturesVol
        retrieveFuturesVol()
        return True
    except Exception as e:
        print(f"Error retrieving volatility data: {e}")
        return False


# ---------------------------------------------------------------------------
# Strategy Computation
# ---------------------------------------------------------------------------

def compute_mean_reversion_features(
    df: pd.DataFrame, 
    lookback: int = DEFAULT_LOOKBACK, 
    num_std: float = DEFAULT_NUM_STD
) -> pd.DataFrame:
    """Compute Bollinger Bands for mean reversion strategy."""
    result = df.copy()
    
    # Moving average and standard deviation
    result['IV_1M_MA'] = df['IV_1M'].rolling(window=lookback).mean()
    result['IV_1M_Std'] = df['IV_1M'].rolling(window=lookback).std()
    
    # Bollinger Bands
    result['IV_1M_Upper'] = result['IV_1M_MA'] + num_std * result['IV_1M_Std']
    result['IV_1M_Lower'] = result['IV_1M_MA'] - num_std * result['IV_1M_Std']
    
    # Term structure slopes
    result['Slope_1M2M'] = df['IV_2M'] - df['IV_1M']
    result['Slope_2M3M'] = df['IV_3M'] - df['IV_2M']
    result['Slope_1M3M'] = df['IV_3M'] - df['IV_1M']
    
    # Z-scores for term structure
    for col in ['Slope_1M3M']:
        mean = result[col].mean()
        std = result[col].std()
        if std > 0:
            result[f'{col}_Zscore'] = (result[col] - mean) / std
    
    return result


def generate_mean_reversion_signals(df: pd.DataFrame) -> pd.Series:
    """Generate trading signals based on Bollinger Band breakouts.
    
    Signal: 1 = Long volatility (IV below lower band)
           -1 = Short volatility (IV above upper band)
            0 = Neutral
    """
    signals = pd.Series(0, index=df.index)
    
    if 'IV_1M_Upper' in df.columns and 'IV_1M_Lower' in df.columns:
        # Short volatility: IV breaks above upper band
        signals[df['IV_1M'] > df['IV_1M_Upper']] = -1
        # Long volatility: IV breaks below lower band
        signals[df['IV_1M'] < df['IV_1M_Lower']] = 1
    
    return signals


def backtest_strategy(df: pd.DataFrame, signals: pd.Series, transaction_cost: float = 0.0) -> Dict[str, Any]:
    """Run simple backtest and compute metrics."""
    # Market return (using IV changes as proxy)
    market_return = df['IV_1M'].pct_change()
    
    # Strategy return = signal × market return
    strategy_return = signals.shift(1) * market_return
    
    # Apply transaction costs
    signal_changes = (signals.diff() != 0).astype(int)
    strategy_return = strategy_return - (signal_changes * transaction_cost)
    strategy_return = strategy_return.fillna(0)
    
    # Cumulative returns
    cumulative_return = (1 + strategy_return).cumprod()
    
    # Compute metrics
    total_return = cumulative_return.iloc[-1] - 1 if len(cumulative_return) > 0 else 0
    num_periods = len(strategy_return.dropna())
    years = num_periods / 252 if num_periods > 0 else 1
    
    annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
    volatility = strategy_return.std() * np.sqrt(252)
    sharpe_ratio = (strategy_return.mean() / strategy_return.std() * np.sqrt(252)) if strategy_return.std() > 0 else 0
    
    # Win rate
    winning_days = (strategy_return > 0).sum()
    total_days = (strategy_return != 0).sum()
    win_rate = winning_days / total_days if total_days > 0 else 0
    
    # Max drawdown
    rolling_max = cumulative_return.expanding().max()
    drawdown = (cumulative_return / rolling_max - 1)
    max_drawdown = drawdown.min()
    
    # Number of trades
    num_trades = signal_changes.sum()
    
    return {
        'strategy_return': strategy_return,
        'cumulative_return': cumulative_return,
        'market_return': market_return,
        'signals': signals,
        'metrics': {
            'total_return': total_return,
            'annualized_return': annualized_return,
            'volatility': volatility,
            'sharpe_ratio': sharpe_ratio,
            'win_rate': win_rate,
            'max_drawdown': max_drawdown,
            'num_trades': int(num_trades),
        }
    }


# ---------------------------------------------------------------------------
# Layout Builders
# ---------------------------------------------------------------------------

def build_volatility_layout() -> html.Div:
    """Build the main Volatility Analysis layout."""
    return html.Div([
        # Header with controls
        html.Div([
            html.H6("📊 Volatility Trading Strategy Analysis", 
                    style={'color': THEME['text_main'], 'marginBottom': '15px'}),
            
            # Control panel
            html.Div([
                # Ticker selector
                html.Div([
                    html.Label("Ticker:", style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginBottom': '5px'}),
                    dcc.Dropdown(
                        id='vol-ticker-dropdown',
                        options=VOL_TICKER_OPTIONS,
                        value=DEFAULT_TICKER,
                        style={'backgroundColor': THEME['bg_input'], 'color': THEME['text_main']},
                        clearable=False,
                    ),
                ], style={'width': '200px', 'marginRight': '20px'}),
                
                # Lookback period
                html.Div([
                    html.Label("Lookback Period:", style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginBottom': '5px'}),
                    dcc.Input(
                        id='vol-lookback-input',
                        type='number',
                        value=DEFAULT_LOOKBACK,
                        min=5,
                        max=60,
                        step=1,
                        style={
                            'backgroundColor': THEME['bg_input'],
                            'color': THEME['text_main'],
                            'border': f'1px solid {THEME["bg_card"]}',
                            'borderRadius': '4px',
                            'padding': '6px',
                            'width': '80px',
                        },
                    ),
                ], style={'marginRight': '20px'}),
                
                # Bollinger Band multiplier
                html.Div([
                    html.Label("Std Deviation Multiplier:", style={'color': THEME['text_sub'], 'fontSize': '12px', 'marginBottom': '5px'}),
                    dcc.Input(
                        id='vol-numstd-input',
                        type='number',
                        value=DEFAULT_NUM_STD,
                        min=1.0,
                        max=3.0,
                        step=0.1,
                        style={
                            'backgroundColor': THEME['bg_input'],
                            'color': THEME['text_main'],
                            'border': f'1px solid {THEME["bg_card"]}',
                            'borderRadius': '4px',
                            'padding': '6px',
                            'width': '80px',
                        },
                    ),
                ], style={'marginRight': '20px'}),
                
                # Run analysis button
                html.Div([
                    html.Label(" ", style={'color': 'transparent', 'fontSize': '12px', 'marginBottom': '5px'}),
                    html.Button(
                        "▶ Run Analysis",
                        id='vol-run-analysis-btn',
                        n_clicks=0,
                        style={
                            'backgroundColor': THEME['accent'],
                            'color': THEME['text_main'],
                            'border': 'none',
                            'borderRadius': '4px',
                            'padding': '8px 16px',
                            'cursor': 'pointer',
                            'fontWeight': 'bold',
                        },
                    ),
                ], style={'marginRight': '20px'}),
                
                # Refresh data button
                html.Div([
                    html.Label(" ", style={'color': 'transparent', 'fontSize': '12px', 'marginBottom': '5px'}),
                    html.Button(
                        "🔄 Refresh Data",
                        id='vol-refresh-data-btn',
                        n_clicks=0,
                        style={
                            'backgroundColor': THEME['bg_card'],
                            'color': THEME['text_main'],
                            'border': f'1px solid {THEME["accent"]}',
                            'borderRadius': '4px',
                            'padding': '8px 16px',
                            'cursor': 'pointer',
                        },
                    ),
                ]),
            ], style={'display': 'flex', 'alignItems': 'flex-end', 'flexWrap': 'wrap', 'gap': '10px'}),
            
            # Status line
            html.Div(id='vol-status-line', children="Ready",
                     style={'color': THEME['text_sub'], 'marginTop': '10px', 'fontSize': '12px', 'fontStyle': 'italic'}),
            
        ], style={
            'backgroundColor': THEME['bg_card'],
            'padding': '15px',
            'borderRadius': '5px',
            'marginBottom': '15px',
        }),
        
        # Loading indicator
        dcc.Loading(
            id='vol-loading',
            type='circle',
            color=THEME['accent'],
            style={'minHeight': '80px'},
            children=[
                # Results container
                html.Div(id='vol-results-container', children=[
                    html.Div("Click \"Run Analysis\" to start...",
                             style={'color': THEME['text_sub'], 'textAlign': 'center', 'padding': '50px'})
                ]),
            ],
        ),
        
        # Store for data
        dcc.Store(id='vol-data-store', data=None),
        
    ], style={'padding': '10px'})


def build_vol_results_display(
    df: pd.DataFrame,
    signals: pd.Series,
    backtest_results: Dict[str, Any],
    ticker: str
) -> html.Div:
    """Build the results display with charts and metrics."""
    metrics = backtest_results['metrics']
    cumulative_return = backtest_results['cumulative_return']
    
    # Info panel - latest values
    latest = df.iloc[-1]
    info_items = []
    
    info_items.append(html.Div([
        html.Span("Ticker:", style={'color': THEME['text_sub'], 'fontSize': '11px'}),
        html.Br(),
        html.Span(ticker, style={'color': THEME['text_main'], 'fontWeight': 'bold', 'fontSize': '16px'}),
    ], style={'padding': '10px', 'backgroundColor': THEME['bg_card'], 'borderRadius': '5px', 'marginRight': '10px'}))
    
    for col in ['IV_1M', 'IV_2M', 'IV_3M']:
        if col in latest.index:
            info_items.append(html.Div([
                html.Span(col.replace('IV_', '') + ' IV:', style={'color': THEME['text_sub'], 'fontSize': '11px'}),
                html.Br(),
                html.Span(f"{latest[col]:.4f}", style={'color': THEME['text_main'], 'fontWeight': 'bold', 'fontSize': '16px'}),
            ], style={'padding': '10px', 'backgroundColor': THEME['bg_card'], 'borderRadius': '5px', 'marginRight': '10px'}))
    
    # Signal interpretation
    latest_signal = int(signals.iloc[-1]) if len(signals) > 0 else 0
    if latest_signal == 1:
        signal_text = "🟢 Long Volatility"
        signal_color = THEME['success']
    elif latest_signal == -1:
        signal_text = "🔴 Short Volatility"
        signal_color = THEME['danger']
    else:
        signal_text = "⚪ Neutral"
        signal_color = THEME['text_sub']
    
    info_items.append(html.Div([
        html.Span("Current Signal:", style={'color': THEME['text_sub'], 'fontSize': '11px'}),
        html.Br(),
        html.Span(signal_text, style={'color': signal_color, 'fontWeight': 'bold', 'fontSize': '14px'}),
    ], style={'padding': '10px', 'backgroundColor': THEME['bg_card'], 'borderRadius': '5px'}))
    
    info_panel = html.Div(info_items, style={'display': 'flex', 'marginBottom': '15px', 'flexWrap': 'wrap'})
    
    # Metrics panel
    metrics_items = [
        ('Total Return', f"{metrics['total_return']:.2%}"),
        ('Annualized Return', f"{metrics['annualized_return']:.2%}"),
        ('Volatility', f"{metrics['volatility']:.2%}"),
        ('Sharpe Ratio', f"{metrics['sharpe_ratio']:.2f}"),
        ('Win Rate', f"{metrics['win_rate']:.2%}"),
        ('Max Drawdown', f"{metrics['max_drawdown']:.2%}"),
        ('Num Trades', str(metrics['num_trades'])),
    ]
    
    metrics_panel = html.Div([
        html.Div([
            html.Span(name + ":", style={'color': THEME['text_sub'], 'fontSize': '11px'}),
            html.Br(),
            html.Span(value, style={
                'color': THEME['success'] if 'Return' in name and not value.startswith('-') else 
                        (THEME['danger'] if value.startswith('-') else THEME['text_main']),
                'fontWeight': 'bold', 
                'fontSize': '14px'
            }),
        ], style={'padding': '10px', 'backgroundColor': THEME['bg_card'], 'borderRadius': '5px', 'marginRight': '10px', 'marginBottom': '10px'})
        for name, value in metrics_items
    ], style={'display': 'flex', 'flexWrap': 'wrap', 'marginBottom': '15px'})
    
    # Chart 1: Term Structure
    fig_ts = go.Figure()
    fig_ts.add_trace(go.Scatter(x=df.index, y=df['IV_1M'], name='1M IV', mode='lines', line=dict(color='#3498db', width=2)))
    fig_ts.add_trace(go.Scatter(x=df.index, y=df['IV_2M'], name='2M IV', mode='lines', line=dict(color='#f39c12', width=2)))
    fig_ts.add_trace(go.Scatter(x=df.index, y=df['IV_3M'], name='3M IV', mode='lines', line=dict(color='#e74c3c', width=2)))
    
    fig_ts.update_layout(
        title='Implied Volatility Term Structure',
        height=300,
        margin=dict(l=50, r=20, t=40, b=40),
        plot_bgcolor=THEME['bg_main'],
        paper_bgcolor=THEME['bg_main'],
        font=dict(color=THEME['text_main']),
        xaxis=dict(gridcolor=THEME['bg_card']),
        yaxis=dict(title='IV', gridcolor=THEME['bg_card']),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        hovermode='x unified',
    )
    
    # Chart 2: Bollinger Bands
    fig_bb = go.Figure()
    fig_bb.add_trace(go.Scatter(x=df.index, y=df['IV_1M'], name='1M IV', mode='lines', line=dict(color='#3498db', width=2)))
    
    if 'IV_1M_MA' in df.columns:
        fig_bb.add_trace(go.Scatter(x=df.index, y=df['IV_1M_MA'], name='Moving Average', mode='lines', line=dict(color='#f39c12', width=1.5, dash='dash')))
    
    if 'IV_1M_Upper' in df.columns and 'IV_1M_Lower' in df.columns:
        fig_bb.add_trace(go.Scatter(x=df.index, y=df['IV_1M_Upper'], name='Upper Band', mode='lines', line=dict(color='gray', width=1), showlegend=False))
        fig_bb.add_trace(go.Scatter(x=df.index, y=df['IV_1M_Lower'], name='Bollinger Bands', mode='lines', line=dict(color='gray', width=1), fill='tonexty', fillcolor='rgba(128,128,128,0.2)'))
    
    # Add signal markers
    buy_signals = df[signals == 1]
    sell_signals = df[signals == -1]
    
    if len(buy_signals) > 0:
        fig_bb.add_trace(go.Scatter(
            x=buy_signals.index, y=buy_signals['IV_1M'],
            mode='markers', name='Long Signal',
            marker=dict(color=THEME['success'], size=8, symbol='triangle-up'),
        ))
    
    if len(sell_signals) > 0:
        fig_bb.add_trace(go.Scatter(
            x=sell_signals.index, y=sell_signals['IV_1M'],
            mode='markers', name='Short Signal',
            marker=dict(color=THEME['danger'], size=8, symbol='triangle-down'),
        ))
    
    fig_bb.update_layout(
        title='Mean Reversion Strategy - Bollinger Bands',
        height=350,
        margin=dict(l=50, r=20, t=40, b=40),
        plot_bgcolor=THEME['bg_main'],
        paper_bgcolor=THEME['bg_main'],
        font=dict(color=THEME['text_main']),
        xaxis=dict(gridcolor=THEME['bg_card']),
        yaxis=dict(title='1M IV', gridcolor=THEME['bg_card']),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        hovermode='x unified',
    )
    
    # Chart 3: Cumulative Return
    fig_cum = go.Figure()
    fig_cum.add_trace(go.Scatter(
        x=cumulative_return.index, y=cumulative_return.values,
        name='Strategy Cumulative Return', mode='lines', line=dict(color=THEME['accent'], width=2),
        fill='tozeroy', fillcolor=f'rgba(52, 152, 219, 0.2)',
    ))
    fig_cum.add_hline(y=1, line_dash='dash', line_color=THEME['text_sub'])
    
    fig_cum.update_layout(
        title='Strategy Cumulative Return Curve',
        height=250,
        margin=dict(l=50, r=20, t=40, b=40),
        plot_bgcolor=THEME['bg_main'],
        paper_bgcolor=THEME['bg_main'],
        font=dict(color=THEME['text_main']),
        xaxis=dict(gridcolor=THEME['bg_card']),
        yaxis=dict(title='累计收益', gridcolor=THEME['bg_card']),
        hovermode='x unified',
    )
    
    # Chart 4: Term Structure Slope Z-Score
    fig_slope = go.Figure()
    if 'Slope_1M3M_Zscore' in df.columns:
        zscore = df['Slope_1M3M_Zscore'].dropna()
        colors = [THEME['danger'] if z > 1.5 else (THEME['success'] if z < -1.5 else THEME['accent']) for z in zscore.values]
        
        fig_slope.add_trace(go.Scatter(
            x=zscore.index, y=zscore.values,
            name='Term Structure Z-Score', mode='lines', line=dict(color=THEME['accent'], width=1.5),
        ))
        fig_slope.add_hline(y=1.5, line_dash='dash', line_color=THEME['danger'], annotation_text='+1.5σ')
        fig_slope.add_hline(y=-1.5, line_dash='dash', line_color=THEME['success'], annotation_text='-1.5σ')
        fig_slope.add_hline(y=0, line_dash='dot', line_color=THEME['text_sub'])
    
    fig_slope.update_layout(
        title='Term Structure Slope Z-Score (1M-3M)',
        height=200,
        margin=dict(l=50, r=20, t=40, b=40),
        plot_bgcolor=THEME['bg_main'],
        paper_bgcolor=THEME['bg_main'],
        font=dict(color=THEME['text_main']),
        xaxis=dict(gridcolor=THEME['bg_card']),
        yaxis=dict(title='Z-Score', gridcolor=THEME['bg_card']),
        showlegend=False,
    )
    
    return html.Div([
        info_panel,
        metrics_panel,
        html.Div([dcc.Graph(figure=fig_ts, style={'height': '300px'})], style={'marginBottom': '15px'}),
        html.Div([dcc.Graph(figure=fig_bb, style={'height': '350px'})], style={'marginBottom': '15px'}),
        html.Div([dcc.Graph(figure=fig_cum, style={'height': '250px'})], style={'marginBottom': '15px'}),
        html.Div([dcc.Graph(figure=fig_slope, style={'height': '200px'})], style={'marginBottom': '15px'}),
    ])


# ---------------------------------------------------------------------------
# Callback Registration
# ---------------------------------------------------------------------------

def register_volatility_callbacks(app) -> None:
    """Register all callbacks for the Volatility tab."""
    
    @app.callback(
        [Output('vol-results-container', 'children'),
         Output('vol-status-line', 'children')],
        [Input('vol-run-analysis-btn', 'n_clicks'),
         Input('vol-refresh-data-btn', 'n_clicks')],
        [State('vol-ticker-dropdown', 'value'),
         State('vol-lookback-input', 'value'),
         State('vol-numstd-input', 'value')],
        prevent_initial_call=True
    )
    def run_vol_analysis(run_clicks, refresh_clicks, ticker, lookback, num_std):
        """Run volatility analysis or refresh data."""
        ctx = callback_context
        if not ctx.triggered:
            return html.Div("Click \"Run Analysis\" to start...", 
                           style={'color': THEME['text_sub'], 'textAlign': 'center', 'padding': '50px'}), "Ready"
        
        triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]
        
        # Handle refresh data button
        if triggered_id == 'vol-refresh-data-btn':
            try:
                success = retrieve_vol_data()
                if success:
                    return (
                        html.Div("Data updated, please click \"Run Analysis\" to see results", 
                                style={'color': THEME['success'], 'textAlign': 'center', 'padding': '50px'}),
                        f"Data update completed @ {datetime.now().strftime('%H:%M:%S')}"
                    )
                else:
                    return (
                        html.Div("Data update failed, please check network connection", 
                                style={'color': THEME['danger'], 'textAlign': 'center', 'padding': '50px'}),
                        "Data update failed"
                    )
            except Exception as e:
                return (
                    html.Div(f"Data update error: {str(e)}", 
                            style={'color': THEME['danger'], 'textAlign': 'center', 'padding': '50px'}),
                    f"Error: {str(e)[:50]}"
                )
        
        # Handle run analysis button
        if triggered_id == 'vol-run-analysis-btn':
            try:
                # Load data
                df = load_vol_data(ticker)
                if df is None:
                    return (
                        html.Div([
                            html.P(f"Unable to load data for {ticker}", style={'color': THEME['danger']}),
                            html.P("Please click \"Refresh Data\" to get the latest data first", style={'color': THEME['text_sub']}),
                        ], style={'textAlign': 'center', 'padding': '50px'}),
                        f"Data loading failed - {ticker}"
                    )
                
                # Validate parameters
                lookback = int(lookback) if lookback else DEFAULT_LOOKBACK
                num_std = float(num_std) if num_std else DEFAULT_NUM_STD
                
                # Compute features
                df = compute_mean_reversion_features(df, lookback=lookback, num_std=num_std)
                
                # Generate signals
                signals = generate_mean_reversion_signals(df)
                
                # Run backtest
                backtest_results = backtest_strategy(df, signals)
                
                # Build results display
                results_div = build_vol_results_display(df, signals, backtest_results, ticker)
                
                status = f"Analysis completed @ {datetime.now().strftime('%H:%M:%S')} | {ticker} | Lookback: {lookback} days | σ multiplier: {num_std}"
                
                return results_div, status
                
            except Exception as e:
                import traceback
                traceback.print_exc()
                return (
                    html.Div(f"Analysis error: {str(e)}", 
                            style={'color': THEME['danger'], 'textAlign': 'center', 'padding': '50px'}),
                    f"Error: {str(e)[:50]}"
                )
        
        return (
            html.Div("Click \"Run Analysis\" to start...", 
                    style={'color': THEME['text_sub'], 'textAlign': 'center', 'padding': '50px'}),
            "Ready"
        )
