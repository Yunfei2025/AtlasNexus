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
# Theme / Style constants — mirrors web/assets/colors.css design tokens.
# Volatility accent is cyan (--accent-cyan), consistent with the Market book.
# ---------------------------------------------------------------------------
THEME = {
    'bg_main': '#0e1d3a',     # --navy-800
    'bg_card': '#122a4c',     # --navy-700 / --surface-panel
    'bg_input': '#17345c',    # --navy-600 / --surface-input
    'text_main': '#e9eef8',   # --text-primary
    'text_sub': '#a4b6d2',    # --text-secondary
    'border': '#2a517f',      # --border-strong
    'border_sub': '#1e3a5f',  # --border-default
    'accent': '#45b6e6',      # --accent-cyan (Volatility accent)
    'success': '#2f9d6b',     # --accent-green
    'warning': '#e0a23c',     # --accent-amber
    'danger': '#d56b6b',      # --negative
    'table_header': '#17345c',
    'table_row_even': '#122a4c',
    'table_row_odd': '#0e1d3a',
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

def _vol_card_header(title: str, badge_text: str | None = None) -> html.Div:
    """Card header row — title + optional meta badge. Matches the Alpha Book card pattern."""
    children_left = [
        html.Span(title, style={'fontSize': '13px', 'fontWeight': '600', 'color': 'var(--text-primary)'}),
    ]
    if badge_text:
        children_left.append(html.Span(badge_text, style={
            'fontSize': '9px', 'color': 'var(--text-muted)', 'background': 'var(--surface-input)',
            'padding': '2px 7px', 'borderRadius': '3px', 'border': '1px solid var(--border-default)',
        }))
    return html.Div(
        children_left,
        style={'display': 'flex', 'alignItems': 'center', 'gap': '10px',
               'padding': '11px 16px', 'background': 'var(--surface-panel)',
               'borderBottom': '1px solid var(--border-strong)'},
    )


_VOL_EMPTY_MSG = html.Div(
    "Click \"Run\" to start...",
    style={'color': 'var(--text-muted)', 'fontSize': '11px', 'fontStyle': 'italic', 'padding': '20px 16px'},
)


def build_volatility_layout() -> html.Div:
    """Build the main Volatility Analysis layout."""
    _label_style = {
        'color': THEME['text_sub'], 'fontSize': '9px', 'fontWeight': '600',
        'textTransform': 'uppercase', 'letterSpacing': '0.06em',
        'marginBottom': '4px', 'display': 'block',
    }
    _input_style = {
        'backgroundColor': THEME['bg_input'], 'color': THEME['text_main'],
        'border': f"1px solid {THEME['border']}", 'borderRadius': '4px',
        'padding': '6px 8px', 'width': '100%', 'textAlign': 'right', 'fontSize': '11px',
        'boxSizing': 'border-box',
    }

    return html.Div([
        html.Div([
            html.H1("Volatility Analysis", style={
                'margin': '0 0 3px', 'fontSize': '20px', 'fontWeight': '600',
                'color': 'var(--text-primary)',
            }),
            html.Div(
                "IV term structure, Bollinger bands strategy, and performance",
                style={'fontSize': '11px', 'color': 'var(--text-muted)'},
            ),
        ], style={'marginBottom': '4px'}),

        # ── Main layout: Controls (left) + Charts (right) ──────────────────────
        html.Div([
            # Controls card — narrow, fixed width
            html.Div([
                _vol_card_header("Controls"),
                html.Div([
                    html.Div([
                        html.Label("Ticker", style=_label_style),
                        dcc.Dropdown(
                            id='vol-ticker-dropdown',
                            options=VOL_TICKER_OPTIONS,
                            value=DEFAULT_TICKER,
                            clearable=False,
                            style={'fontSize': '11px'},
                        ),
                    ]),
                    html.Div([
                        html.Label("Lookback", style=_label_style),
                        dcc.Input(
                            id='vol-lookback-input', type='number', value=DEFAULT_LOOKBACK,
                            min=5, max=60, step=1, style=_input_style,
                        ),
                    ]),
                    html.Div([
                        html.Label("Std Dev ×", style=_label_style),
                        dcc.Input(
                            id='vol-numstd-input', type='number', value=DEFAULT_NUM_STD,
                            min=1.0, max=3.0, step=0.1, style=_input_style,
                        ),
                    ]),
                    html.Button(
                        "▶ Run", id='vol-run-analysis-btn', n_clicks=0,
                        style={'padding': '6px 12px', 'background': 'var(--positive)', 'color': 'var(--navy-950)',
                               'border': 'none', 'borderRadius': '4px', 'fontSize': '10px', 'fontWeight': '700',
                               'cursor': 'pointer', 'width': '100%'},
                    ),
                    html.Button(
                        "↻ Refresh", id='vol-refresh-data-btn', n_clicks=0,
                        style={'padding': '6px 12px', 'background': 'transparent', 'color': 'var(--text-muted)',
                               'border': '1px solid var(--border-default)', 'borderRadius': '4px', 'fontSize': '10px',
                               'cursor': 'pointer', 'width': '100%'},
                    ),
                    html.Div(id='vol-status-line', children="Ready",
                             style={'color': THEME['text_sub'], 'fontSize': '8px'}),

                    # ── Performance (moved to bottom of controls) ────────────────
                    html.Div([
                        html.Div("Performance", style={'fontSize': '10px', 'fontWeight': '600', 'color': THEME['text_sub'], 'marginBottom': '8px'}),
                        dcc.Loading(
                            id='vol-loading',
                            type='circle',
                            color=THEME['accent'],
                            style={'minHeight': '60px'},
                            children=html.Div(id='vol-performance-container', children=_VOL_EMPTY_MSG),
                        ),
                    ], style={'padding': '10px', 'background': THEME['bg_input'], 'borderRadius': '4px',
                              'border': f"1px solid {THEME['border_sub']}", 'fontSize': '9px'}),
                ], style={'padding': '12px 14px', 'display': 'flex', 'flexDirection': 'column', 'gap': '12px'}),
            ], style={'width': '220px', 'flexShrink': '0', 'border': '1px solid var(--border-strong)',
                      'borderRadius': '8px', 'overflow': 'hidden'}),

            # ── Chart cards (populated after Run) — right side ────────────────
            html.Div(id='vol-results-container', children=[], style={'flex': '1', 'minWidth': '0'}),
        ], style={'display': 'flex', 'gap': '12px', 'alignItems': 'flex-start'}),

        # Store for data
        dcc.Store(id='vol-data-store', data=None),

    ], style={'padding': '10px', 'display': 'flex', 'flexDirection': 'column', 'gap': '10px'})


def _vol_chart_card(title: str, graph: dcc.Graph, legend_items: list[tuple[str, str]] | None = None) -> html.Div:
    """Wrap a Plotly graph in the Alpha Book card pattern, with an optional colour-key legend row."""
    children = [_vol_card_header(title)]
    if legend_items:
        children.append(html.Div(
            [
                html.Span([
                    html.Span(style={'width': '12px', 'height': '2px', 'background': color,
                                      'display': 'inline-block', 'borderRadius': '1px'}),
                    label,
                ], style={'display': 'flex', 'alignItems': 'center', 'gap': '4px'})
                for color, label in legend_items
            ],
            style={'display': 'flex', 'gap': '12px', 'padding': '8px 16px 0', 'fontSize': '8px',
                   'color': 'var(--text-muted)', 'borderBottom': '1px solid var(--border-strong)'},
        ))
    children.append(html.Div(graph, style={'padding': '12px 16px'}))
    return html.Div(children, style={'border': '1px solid var(--border-strong)', 'borderRadius': '8px',
                                      'overflow': 'hidden'})


def build_vol_results_display(
    df: pd.DataFrame,
    signals: pd.Series,
    backtest_results: Dict[str, Any],
    ticker: str
) -> tuple[html.Div, html.Div]:
    """Build the Performance table and the chart cards.

    Returns:
        (performance_table, charts_div) — performance_table renders inside the
        Controls-row "Performance" card; charts_div is the full-width chart stack.
    """
    metrics = backtest_results['metrics']
    cumulative_return = backtest_results['cumulative_return']

    latest = df.iloc[-1]
    latest_signal = int(signals.iloc[-1]) if len(signals) > 0 else 0
    if latest_signal == 1:
        signal_text, signal_color = "Long Vol", THEME['success']
    elif latest_signal == -1:
        signal_text, signal_color = "Short Vol", THEME['danger']
    else:
        signal_text, signal_color = "Neutral", THEME['text_sub']

    _kpi_rows = [('Ticker', ticker, None)]
    for col in ['IV_1M', 'IV_2M', 'IV_3M']:
        if col in latest.index:
            _kpi_rows.append((col.replace('IV_', '') + ' IV', f"{latest[col]:.4f}", None))
    _kpi_rows.append(('Signal', signal_text, signal_color))
    _kpi_rows += [
        ('Total Return', f"{metrics['total_return']:.2%}", THEME['success']),
        ('Annualized Return', f"{metrics['annualized_return']:.2%}", THEME['success']),
        ('Volatility', f"{metrics['volatility']:.2%}", None),
        ('Sharpe Ratio', f"{metrics['sharpe_ratio']:.2f}", None),
        ('Win Rate', f"{metrics['win_rate']:.2%}", THEME['success']),
        ('Max Drawdown', f"{metrics['max_drawdown']:.2%}", THEME['danger']),
        ('Total Trades', str(metrics['num_trades']), None),
    ]

    performance_table = html.Div(
        html.Table(
            html.Tbody([
                html.Tr([
                    html.Td(label, style={'padding': '6px 12px', 'color': 'var(--text-secondary)', 'fontSize': '10px'}),
                    html.Td(value, style={'padding': '6px 12px', 'textAlign': 'right', 'fontSize': '10px',
                                           'fontWeight': '600',
                                           'color': color or 'var(--text-secondary)'}),
                ], style={'borderBottom': '1px solid rgba(255,255,255,0.04)',
                          'background': 'transparent' if i % 2 == 0 else 'rgba(255,255,255,0.015)'})
                for i, (label, value, color) in enumerate(_kpi_rows)
            ]),
            style={'width': '100%', 'borderCollapse': 'collapse'},
        ),
        style={'overflowX': 'auto'},
    )

    # Chart 1: Term Structure
    fig_ts = go.Figure()
    fig_ts.add_trace(go.Scatter(x=df.index, y=df['IV_1M'], name='1M IV', mode='lines', line=dict(color='#3498db', width=2)))
    fig_ts.add_trace(go.Scatter(x=df.index, y=df['IV_2M'], name='2M IV', mode='lines', line=dict(color='#f39c12', width=2)))
    fig_ts.add_trace(go.Scatter(x=df.index, y=df['IV_3M'], name='3M IV', mode='lines', line=dict(color='#e74c3c', width=2)))
    
    fig_ts.update_layout(
        height=300,
        margin=dict(l=50, r=20, t=20, b=40),
        plot_bgcolor=THEME['bg_main'],
        paper_bgcolor=THEME['bg_main'],
        font=dict(color=THEME['text_main']),
        xaxis=dict(gridcolor=THEME['bg_card']),
        yaxis=dict(title='IV', gridcolor=THEME['bg_card']),
        showlegend=False,
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
        height=350,
        margin=dict(l=50, r=20, t=20, b=40),
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
        height=250,
        margin=dict(l=50, r=20, t=20, b=40),
        plot_bgcolor=THEME['bg_main'],
        paper_bgcolor=THEME['bg_main'],
        font=dict(color=THEME['text_main']),
        xaxis=dict(gridcolor=THEME['bg_card']),
        yaxis=dict(title='Cumulative Return', gridcolor=THEME['bg_card']),
        showlegend=False,
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
        height=200,
        margin=dict(l=50, r=20, t=20, b=40),
        plot_bgcolor=THEME['bg_main'],
        paper_bgcolor=THEME['bg_main'],
        font=dict(color=THEME['text_main']),
        xaxis=dict(gridcolor=THEME['bg_card']),
        yaxis=dict(title='Z-Score', gridcolor=THEME['bg_card']),
        showlegend=False,
    )

    charts_div = html.Div([
        _vol_chart_card(
            "Implied Volatility Term Structure",
            dcc.Graph(figure=fig_ts, style={'height': '300px'}),
            legend_items=[('#3498db', '1M IV'), ('#f39c12', '2M IV'), ('#e74c3c', '3M IV')],
        ),
        _vol_chart_card(
            "Mean Reversion: Bollinger Bands",
            dcc.Graph(figure=fig_bb, style={'height': '350px'}),
        ),
        _vol_chart_card(
            "Strategy Cumulative Return",
            dcc.Graph(figure=fig_cum, style={'height': '250px'}),
        ),
        _vol_chart_card(
            "Term Structure Slope Z-Score (1M-3M)",
            dcc.Graph(figure=fig_slope, style={'height': '200px'}),
        ),
    ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '10px'})

    return performance_table, charts_div


# ---------------------------------------------------------------------------
# Callback Registration
# ---------------------------------------------------------------------------

def register_volatility_callbacks(app) -> None:
    """Register all callbacks for the Volatility tab."""
    
    @app.callback(
        [Output('vol-performance-container', 'children'),
         Output('vol-results-container', 'children'),
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
            return _VOL_EMPTY_MSG, [], "Ready"

        triggered_id = ctx.triggered[0]['prop_id'].split('.')[0]

        # Handle refresh data button
        if triggered_id == 'vol-refresh-data-btn':
            try:
                success = retrieve_vol_data()
                if success:
                    return (
                        _VOL_EMPTY_MSG, [],
                        f"Data updated @ {datetime.now().strftime('%H:%M:%S')} — click Run"
                    )
                else:
                    return (
                        html.Div("Data update failed, please check network connection",
                                 style={'color': THEME['danger'], 'fontSize': '11px', 'padding': '20px 16px'}),
                        [], "Data update failed"
                    )
            except Exception as e:
                return (
                    html.Div(f"Data update error: {str(e)}",
                             style={'color': THEME['danger'], 'fontSize': '11px', 'padding': '20px 16px'}),
                    [], f"Error: {str(e)[:50]}"
                )

        # Handle run analysis button
        if triggered_id == 'vol-run-analysis-btn':
            try:
                # Load data
                df = load_vol_data(ticker)
                if df is None:
                    return (
                        html.Div([
                            html.P(f"Unable to load data for {ticker}", style={'color': THEME['danger'], 'fontSize': '11px'}),
                            html.P("Please click \"Refresh\" to get the latest data first", style={'color': THEME['text_sub'], 'fontSize': '11px'}),
                        ], style={'padding': '20px 16px'}),
                        [], f"Data loading failed - {ticker}"
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
                performance_table, charts_div = build_vol_results_display(df, signals, backtest_results, ticker)

                status = f"Done @ {datetime.now().strftime('%H:%M:%S')} | {ticker} | LB {lookback}d | {num_std}σ"

                return performance_table, charts_div, status

            except Exception as e:
                import traceback
                traceback.print_exc()
                return (
                    html.Div(f"Analysis error: {str(e)}",
                             style={'color': THEME['danger'], 'fontSize': '11px', 'padding': '20px 16px'}),
                    [], f"Error: {str(e)[:50]}"
                )

        return _VOL_EMPTY_MSG, [], "Ready"
