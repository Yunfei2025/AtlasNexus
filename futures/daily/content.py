# -*- coding: utf-8 -*-
"""
Created on Thu Dec 11 21:46:00 2025

@author: CMBC
"""

import sys
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict

import dash
from dash import dcc, html, Input, Output, State
import plotly.graph_objects as go
import dash_bootstrap_components as dbc

# Add project path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from futures.daily import (
    FuturesPortfolioSelector,
    TrendFollowingStrategy,
    MeanReversionStrategy,
    StrategyBacktester,
)

class FuturesPortfolioDashboard:
    """Dashboard for futures portfolio strategy analysis."""
    
    def __init__(self, data: Dict[str, pd.DataFrame]):
        """
        Initialize dashboard.
        
        Args:
            data: Dict mapping ticker to OHLC DataFrame
        """
        self.data = data
        self.app = dash.Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])
        
        # Initialize components
        self.selector = FuturesPortfolioSelector(data, lookback_months=12)
        self.trend_strategy = TrendFollowingStrategy(
            fast_period=5, slow_period=15, hysteresis_factor=0.3, vol_target=0.005
        )
        self.mr_strategy = MeanReversionStrategy(
            period=10, num_std=1.5, max_hold=10, vol_target=0.005
        )
        
        # Get reference date (last day of previous month)
        sample_ticker = list(data.keys())[0]
        last_date = data[sample_ticker].index.max()
        self.reference_date = last_date.replace(day=1) - timedelta(days=1)
        
        self._setup_layout()
        self._setup_callbacks()
    
    def calculate_risk_parity_weights(self, tickers: list) -> Dict[str, float]:
        """
        Calculate risk parity weights using EWMA volatility.
        
        Args:
            tickers: List of tickers
            
        Returns:
            Dict of weights
        """
        end_date = self.reference_date
        start_date = (end_date - pd.DateOffset(years=1)).date()
        
        # Calculate EWMA volatility for each ticker
        vols = {}
        for ticker in tickers:
            if ticker not in self.data:
                continue
            
            df = self.data[ticker]
            df_window = df[(df.index >= start_date) & (df.index <= end_date)]
            
            if len(df_window) < 20:
                continue
            
            returns = df_window['Close'].pct_change().dropna()
            
            # EWMA with span=60 (approximately 3 months)
            ewma_var = returns.ewm(span=60).var().iloc[-1]
            ewma_vol = np.sqrt(ewma_var * 252)  # Annualized
            
            vols[ticker] = ewma_vol
        
        # Risk parity: weight inversely proportional to volatility
        inv_vols = {k: 1/v for k, v in vols.items()}
        total_inv_vol = sum(inv_vols.values())
        weights = {k: v/total_inv_vol for k, v in inv_vols.items()}
        
        return weights
    
    def get_current_signals(self, ticker: str) -> Dict[str, int]:
        """
        Get current signals for a ticker.
        
        Args:
            ticker: Ticker symbol
            
        Returns:
            Dict with 'trend' and 'mr' signals (1=long, -1=short, 0=neutral)
        """
        if ticker not in self.data:
            return {'trend': 0, 'mr': 0}
        
        df = self.data[ticker]
        df_to_date = df[df.index <= self.reference_date].copy()
        
        if len(df_to_date) < 100:
            return {'trend': 0, 'mr': 0}
        
        # Get signals
        trend_signals = self.trend_strategy.generate_signals(df_to_date)
        mr_signals = self.mr_strategy.generate_signals(df_to_date)
        
        return {
            'trend': int(trend_signals.iloc[-1]) if len(trend_signals) > 0 else 0,
            'mr': int(mr_signals.iloc[-1]) if len(mr_signals) > 0 else 0
        }
    
    def backtest_ticker(self, ticker: str, start_date=None, end_date=None, years: int = 5) -> Dict:
        """
        Run backtest for a ticker.
        
        Args:
            ticker: Ticker symbol
            start_date: Backtest start date (optional)
            end_date: Backtest end date (optional)
            years: Backtest period in years (used if start_date/end_date not provided)
            
        Returns:
            Dict with backtest results
        """
        if ticker not in self.data:
            return None
        
        df = self.data[ticker].copy()
        
        # Use provided dates or calculate from years
        if start_date is None or end_date is None:
            end_date = df.index.max()
            start_date = (end_date - pd.DateOffset(years=years)).date()
        
        # Filter data by date range
        df = df[(df.index >= start_date) & (df.index <= end_date)]
        
        if len(df) < 60:  # Require at least 60 days for strategy to work
            return None
        
        # Calculate returns for both strategies (with transaction costs built-in)
        trend_returns = self.trend_strategy.calculate_returns(df)
        mr_returns = self.mr_strategy.calculate_returns(df)
        
        # Get positions (for display purposes)
        trend_positions = self.trend_strategy.generate_signals(df).shift(1).fillna(0)
        mr_positions = self.mr_strategy.generate_signals(df).shift(1).fillna(0)
        
        # Calculate cumulative PnL
        trend_cum_pnl = (1 + trend_returns).cumprod()
        mr_cum_pnl = (1 + mr_returns).cumprod()
        
        # Use StrategyBlender for optimal weight calculation
        from futures.daily.blender import StrategyBlender
        
        blender = StrategyBlender({
            'TrendFollowing': trend_returns,
            'MeanReversion': mr_returns
        })
        
        # Optimize weights with minimum 20% allocation for diversification
        # This forces blending even when one strategy has negative Sharpe
        optimal_weights = blender.optimize_weights(
            objective='sharpe',
            min_weight=0.2,
            max_weight=0.8
        )
        
        # Get rolling optimal weights (6-month lookback)
        try:
            weights_df = blender.optimize_rolling_weights(lookback_window=126, objective='sharpe')
            trend_weight = weights_df['TrendFollowing'].reindex(trend_returns.index, method='ffill').fillna(0.5)
            mr_weight = weights_df['MeanReversion'].reindex(mr_returns.index, method='ffill').fillna(0.5)
        except:
            # Fallback to static optimal weights if rolling optimization fails
            trend_weight = pd.Series(optimal_weights['TrendFollowing'], index=trend_returns.index)
            mr_weight = pd.Series(optimal_weights['MeanReversion'], index=mr_returns.index)
        
        # Combined strategy with optimal weights
        combined_returns = trend_weight * trend_returns + mr_weight * mr_returns
        combined_cum_pnl = (1 + combined_returns).cumprod()
        combined_positions = trend_weight * trend_positions + mr_weight * mr_positions
        
        # Calculate metrics
        backtester = StrategyBacktester(df)
        trend_metrics = backtester.run_backtest(trend_returns)
        mr_metrics = backtester.run_backtest(mr_returns)
        combined_metrics = backtester.run_backtest(combined_returns)
        
        # Add diversification analysis
        div_analysis = blender.analyze_diversification_benefit()
        
        return {
            'dates': df.index,
            'trend_positions': trend_positions,
            'trend_cum_pnl': trend_cum_pnl,
            'trend_metrics': trend_metrics,
            'mr_positions': mr_positions,
            'mr_cum_pnl': mr_cum_pnl,
            'mr_metrics': mr_metrics,
            'combined_positions': combined_positions,
            'combined_cum_pnl': combined_cum_pnl,
            'combined_metrics': combined_metrics,
            'optimal_weights': optimal_weights,
            'correlation': div_analysis.get('correlation', 0),
            'trend_weight': trend_weight,
            'mr_weight': mr_weight
        }
    
    def _setup_layout(self):
        """Setup dashboard layout."""
        
        # Get initial portfolio
        selected_tickers = self.selector.select_diversified_portfolio(
            rebalance_date=self.reference_date,
            n_assets=5
        )
        
        self.app.layout = dbc.Container([
            dbc.Row([
                dbc.Col([
                    html.H1("Futures Portfolio Strategy Dashboard", 
                           className="text-center mb-4 mt-3",
                           style={'color': '#2c3e50'})
                ])
            ]),
            
            # Block 1: Capital Allocation
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader(html.H4("📊 Capital Allocation (Risk Parity)", 
                                              className="text-white"),
                                      style={'backgroundColor': '#3498db'}),
                        dbc.CardBody([
                            html.P(f"Reference Date: {self.reference_date.strftime('%Y-%m-%d')}", 
                                  className="text-muted"),
                            html.P(f"Lookback Window: 1 Year (EWMA Vol)", 
                                  className="text-muted mb-3"),
                            dbc.Row([
                                dbc.Col([
                                    dbc.Label("Total Capital (Million CNY):", className="fw-bold"),
                                    dbc.Input(
                                        id='capital-input',
                                        type='number',
                                        value=1,
                                        min=0.1,
                                        step=0.1,
                                        className="mb-2"
                                    )
                                ], width=3),
                                dbc.Col([
                                    dbc.Label("\u00A0", className="fw-bold"),  # Spacer
                                    dbc.Button(
                                        "Construct Portfolio",
                                        id='construct-button',
                                        color='primary',
                                        className="w-100",
                                        n_clicks=0
                                    )
                                ], width=3),
                                dbc.Col([
                                    html.Div(id='allocation-status', className="mt-4")
                                ], width=6)
                            ], className="mb-3"),
                            dcc.Graph(id='allocation-chart'),
                            dbc.Row([
                                dbc.Col([
                                    html.Div(id='allocation-table', className="mt-3")
                                ], width=7),
                                dbc.Col([
                                    html.Div(id='correlation-table', className="mt-3")
                                ], width=5)
                            ])
                        ])
                    ], className="mb-4")
                ])
            ]),
            
            # Block 2: Direction Signals
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader(html.H4("🎯 Current Direction Signals", 
                                              className="text-white"),
                                      style={'backgroundColor': '#2ecc71'}),
                        dbc.CardBody([
                            html.Div(id='signals-display')
                        ])
                    ], className="mb-4")
                ])
            ]),
            
            # Block 3: Backtest
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            dbc.Row([
                                dbc.Col(html.H4("📈 Strategy Backtest", 
                                              className="text-white mb-0"),
                                       width=3),
                                dbc.Col([
                                    dcc.Dropdown(
                                        id='ticker-dropdown',
                                        options=[{'label': t, 'value': t} 
                                                for t in sorted(self.data.keys())],
                                        value=selected_tickers[0] if selected_tickers else list(self.data.keys())[0],
                                        clearable=False,
                                        style={'backgroundColor': 'white'}
                                    )
                                ], width=2),
                                dbc.Col([
                                    dcc.DatePickerRange(
                                        id='backtest-date-range',
                                        start_date=(datetime.now() - timedelta(days=365)).date(),
                                        end_date=datetime.now().date(),
                                        display_format='YYYY-MM-DD',
                                        style={'fontSize': '12px'}
                                    )
                                ], width=4),
                                dbc.Col([
                                    dbc.Button(
                                        "Run Analysis",
                                        id='run-backtest-button',
                                        color='success',
                                        className="w-100",
                                        n_clicks=0
                                    )
                                ], width=2),
                                dbc.Col([
                                    html.Div(id='backtest-status')
                                ], width=1)
                            ], align='center')
                        ], style={'backgroundColor': '#e74c3c'}),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-backtest",
                                type="default",
                                children=[
                                    dbc.Row([
                                        # Trend Following
                                        dbc.Col([
                                            html.H5("Trend Following Strategy", 
                                                   className="text-center mb-3",
                                                   style={'color': '#3498db'}),
                                            dcc.Graph(id='trend-position-chart', style={'height': '250px'}),
                                            html.Div(id='trend-metrics', className="mb-3"),
                                            dcc.Graph(id='trend-pnl-chart', style={'height': '250px'})
                                        ], width=6),
                                        
                                        # Mean Reversion
                                        dbc.Col([
                                            html.H5("Mean Reversion Strategy", 
                                                   className="text-center mb-3",
                                                   style={'color': '#9b59b6'}),
                                            dcc.Graph(id='mr-position-chart', style={'height': '250px'}),
                                            html.Div(id='mr-metrics', className="mb-3"),
                                            dcc.Graph(id='mr-pnl-chart', style={'height': '250px'})
                                        ], width=6)
                                    ])
                                ]
                            )
                        ])
                    ], className="mb-4")
                ])
            ]),
            
            # Block 4: Combined Strategy
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader(html.H4("🎲 Combined Strategy (Optimal Blending)", 
                                              className="text-white"),
                                      style={'backgroundColor': '#f39c12'}),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-combined",
                                type="default",
                                children=[
                                    dbc.Row([
                                        dbc.Col([
                                            dcc.Graph(id='combined-position-chart', style={'height': '300px'})
                                        ], width=6),
                                        dbc.Col([
                                            html.Div(id='combined-metrics', className="mb-3"),
                                            dcc.Graph(id='combined-pnl-chart', style={'height': '250px'})
                                        ], width=6)
                                    ])
                                ]
                            )
                        ])
                    ])
                ])
            ]),
            
            # Store for portfolio data
            dcc.Store(id='portfolio-data', data=selected_tickers)
        ], fluid=True)
    
    def _setup_callbacks(self):
        """Setup dashboard callbacks."""
        
        @self.app.callback(
            [Output('allocation-chart', 'figure'),
             Output('allocation-table', 'children'),
             Output('correlation-table', 'children'),
             Output('signals-display', 'children'),
             Output('allocation-status', 'children'),
             Output('portfolio-data', 'data')],
            [Input('construct-button', 'n_clicks')],
            [State('capital-input', 'value'),
             State('portfolio-data', 'data')]
        )
        def update_allocation_and_signals(n_clicks, capital_million, current_portfolio):
            """Update capital allocation and signals."""
            
            # Trigger selection only when button is clicked
            if n_clicks > 0:
                selected_tickers = self.selector.select_diversified_portfolio(
                    rebalance_date=self.reference_date,
                    n_assets=5
                )
            else:
                selected_tickers = current_portfolio if current_portfolio else []
            
            if not selected_tickers:
                empty_fig = go.Figure()
                status = dbc.Alert("No portfolio selected", color="warning", className="mb-0 py-2")
                return empty_fig, html.Div("No data"), html.Div("No data"), html.Div("No data"), status, selected_tickers
            
            # Calculate risk parity weights
            weights = self.calculate_risk_parity_weights(selected_tickers)
            
            # Allocation chart
            fig_alloc = go.Figure(data=[
                go.Pie(
                    labels=list(weights.keys()),
                    values=list(weights.values()),
                    hole=0.4,
                    marker=dict(colors=['#3498db', '#2ecc71', '#f39c12', '#e74c3c', '#9b59b6']),
                    textinfo='label+percent',
                    textfont=dict(size=14)
                )
            ])
            
            fig_alloc.update_layout(
                title="Portfolio Allocation",
                height=400,
                margin=dict(l=20, r=20, t=40, b=20)
            )
            
            # Allocation table with No. of Contracts
            total_capital = (capital_million if capital_million else 1) * 1000000
            
            # Get recent prices for contract calculation
            recent_prices = {}
            for ticker in weights.keys():
                if ticker in self.data:
                    df = self.data[ticker]
                    df_to_date = df[df.index <= self.reference_date]
                    if len(df_to_date) > 0:
                        recent_prices[ticker] = df_to_date['Close'].iloc[-1]
            
            table_rows = [
                html.Thead(html.Tr([
                    html.Th("Ticker"),
                    html.Th("Weight", style={'textAlign': 'right'}),
                    html.Th("Capital (CNY)", style={'textAlign': 'right'}),
                    html.Th("No. of Contracts", style={'textAlign': 'right'})
                ]))
            ]
            table_body = []
            for ticker, weight in sorted(weights.items(), key=lambda x: -x[1]):
                capital_allocated = weight * total_capital
                num_contracts = 0
                if ticker in recent_prices:
                    num_contracts = int(round(capital_allocated / recent_prices[ticker]))
                
                table_body.append(
                    html.Tr([
                        html.Td(ticker, style={'fontWeight': 'bold'}),
                        html.Td(f"{weight:.2%}", style={'textAlign': 'right'}),
                        html.Td(f"¥{capital_allocated:,.0f}", style={'textAlign': 'right'}),
                        html.Td(f"{num_contracts:,}", style={'textAlign': 'right'})
                    ])
                )
            table_rows.append(html.Tbody(table_body))
            
            allocation_table = dbc.Table(
                table_rows,
                bordered=True,
                hover=True,
                responsive=True,
                striped=True,
                style={'fontSize': '14px'}
            )
            
            # Correlation matrix
            end_date = self.reference_date
            start_date = (end_date - pd.DateOffset(years=1)).date()
            
            # Calculate returns for correlation
            returns_dict = {}
            for ticker in selected_tickers:
                if ticker not in self.data:
                    continue
                df = self.data[ticker]
                df_window = df[(df.index >= start_date) & (df.index <= end_date)]
                if len(df_window) > 20:
                    returns_dict[ticker] = df_window['Close'].pct_change().dropna()
            
            # Create correlation matrix
            if len(returns_dict) > 0:
                returns_df = pd.DataFrame(returns_dict)
                corr_matrix = returns_df.corr()
                
                # Build correlation table
                corr_table_rows = [html.Thead(html.Tr(
                    [html.Th("", style={'textAlign': 'center'})] + 
                    [html.Th(ticker, style={'textAlign': 'center', 'fontSize': '12px'}) 
                     for ticker in corr_matrix.columns]
                ))]
                
                corr_body = []
                for idx, row_ticker in enumerate(corr_matrix.index):
                    row_cells = [html.Td(row_ticker, style={'fontWeight': 'bold', 'fontSize': '12px'})]
                    for col_ticker in corr_matrix.columns:
                        corr_val = corr_matrix.loc[row_ticker, col_ticker]
                        # Color coding: red for high correlation, green for low/negative
                        if row_ticker == col_ticker:
                            bg_color = '#f8f9fa'
                        elif corr_val > 0.5:
                            bg_color = '#ffcccc'
                        elif corr_val < 0:
                            bg_color = '#ccffcc'
                        else:
                            bg_color = 'white'
                        
                        row_cells.append(html.Td(
                            f"{corr_val:.2f}",
                            style={'textAlign': 'center', 'fontSize': '11px', 
                                   'backgroundColor': bg_color}
                        ))
                    corr_body.append(html.Tr(row_cells))
                
                corr_table_rows.append(html.Tbody(corr_body))
                
                correlation_table = html.Div([
                    html.H6("Correlation Matrix (1Y)", className="mb-2 text-center", 
                           style={'fontWeight': 'bold'}),
                    dbc.Table(
                        corr_table_rows,
                        bordered=True,
                        hover=True,
                        responsive=True,
                        size='sm',
                        style={'fontSize': '11px'}
                    )
                ])
            else:
                correlation_table = html.Div("Insufficient data for correlation")
            
            # Status message
            if n_clicks > 0:
                status = dbc.Alert(
                    [html.I(className="bi bi-check-circle-fill me-2"), 
                     f"Portfolio constructed: {len(selected_tickers)} futures"],
                    color="success",
                    className="mb-0 py-2"
                )
            else:
                status = dbc.Alert("Click 'Construct Portfolio' to begin", color="info", className="mb-0 py-2")
            
            # Signals display
            signal_cards = []
            for ticker in selected_tickers:
                signals = self.get_current_signals(ticker)
                
                def signal_badge(signal_val, strategy_name):
                    if signal_val == 1:
                        return dbc.Badge("LONG ↑", color="success", className="me-2")
                    elif signal_val == -1:
                        return dbc.Badge("SHORT ↓", color="danger", className="me-2")
                    else:
                        return dbc.Badge("NEUTRAL →", color="secondary", className="me-2")
                
                card = dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H5(ticker, className="text-center mb-3", 
                                   style={'fontWeight': 'bold'}),
                            html.Div([
                                html.Span("Trend: ", style={'fontWeight': 'bold'}),
                                signal_badge(signals['trend'], 'Trend')
                            ], className="mb-2"),
                            html.Div([
                                html.Span("Mean Rev: ", style={'fontWeight': 'bold'}),
                                signal_badge(signals['mr'], 'MR')
                            ])
                        ])
                    ], style={'border': '2px solid #e0e0e0'})
                ], width=12, md=6, lg=4, xl=2, className="mb-3")
                
                signal_cards.append(card)
            
            signals_display = dbc.Row(signal_cards)
            
            return fig_alloc, allocation_table, correlation_table, signals_display, status, selected_tickers
        
        @self.app.callback(
            [Output('trend-position-chart', 'figure'),
             Output('trend-pnl-chart', 'figure'),
             Output('trend-metrics', 'children'),
             Output('mr-position-chart', 'figure'),
             Output('mr-pnl-chart', 'figure'),
             Output('mr-metrics', 'children'),
             Output('combined-position-chart', 'figure'),
             Output('combined-pnl-chart', 'figure'),
             Output('combined-metrics', 'children'),
             Output('backtest-status', 'children')],
            [Input('run-backtest-button', 'n_clicks')],
            [State('ticker-dropdown', 'value'),
             State('backtest-date-range', 'start_date'),
             State('backtest-date-range', 'end_date')]
        )
        def update_backtest(n_clicks, ticker, start_date, end_date):
            """Update backtest results."""
            
            # Return empty state if not clicked
            if n_clicks == 0:
                empty_fig = go.Figure()
                empty_fig.update_layout(
                    xaxis=dict(visible=False),
                    yaxis=dict(visible=False),
                    annotations=[dict(
                        text="Click 'Run Analysis' to view results",
                        xref="paper", yref="paper",
                        x=0.5, y=0.5, showarrow=False,
                        font=dict(size=14, color="gray")
                    )]
                )
                status = dbc.Badge("Ready", color="secondary", className="fs-6")
                empty_metrics = html.Div("Click 'Run Analysis'", className="text-center text-muted")
                return (empty_fig, empty_fig, empty_metrics,
                       empty_fig, empty_fig, empty_metrics,
                       empty_fig, empty_fig, empty_metrics,
                       status)
            
            # Convert date strings to datetime if needed
            if isinstance(start_date, str):
                start_date = pd.to_datetime(start_date).date()
            if isinstance(end_date, str):
                end_date = pd.to_datetime(end_date).date()
            
            results = self.backtest_ticker(ticker, start_date=start_date, end_date=end_date)
            
            if results is None:
                empty_fig = go.Figure()
                empty_fig.update_layout(
                    xaxis=dict(visible=False),
                    yaxis=dict(visible=False),
                    annotations=[dict(
                        text="Insufficient data",
                        xref="paper", yref="paper",
                        x=0.5, y=0.5, showarrow=False,
                        font=dict(size=14, color="red")
                    )]
                )
                error_status = dbc.Badge("Error", color="danger", className="fs-6")
                error_metrics = html.Div("No data", className="text-center text-muted")
                return (empty_fig, empty_fig, error_metrics,
                       empty_fig, empty_fig, error_metrics,
                       empty_fig, empty_fig, error_metrics,
                       error_status)
            
            dates = results['dates']
            
            # Trend Following Position Chart
            fig_trend_pos = go.Figure()
            fig_trend_pos.add_trace(go.Scatter(
                x=dates,
                y=results['trend_positions'],
                mode='lines',
                name='Position',
                line=dict(color='#3498db', width=2),
                fill='tozeroy',
                fillcolor='rgba(52, 152, 219, 0.2)'
            ))
            fig_trend_pos.update_layout(
                title="Position Series",
                xaxis_title="Date",
                yaxis_title="Position",
                height=250,
                autosize=False,
                margin=dict(l=50, r=20, t=40, b=40),
                hovermode='x unified'
            )
            
            # Trend Following PnL Chart
            fig_trend_pnl = go.Figure()
            fig_trend_pnl.add_trace(go.Scatter(
                x=dates,
                y=results['trend_cum_pnl'],
                mode='lines',
                name='Cumulative PnL',
                line=dict(color='#27ae60', width=2)
            ))
            fig_trend_pnl.update_layout(
                title="Cumulative PnL",
                xaxis_title="Date",
                yaxis_title="Value",
                height=250,
                autosize=False,
                margin=dict(l=50, r=20, t=40, b=40),
                hovermode='x unified'
            )
            
            # Trend Metrics
            tm = results['trend_metrics']
            trend_metrics = dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Small("Annual Return", className="text-muted"),
                        html.H6(f"{tm['annualized_return']:.2%}", 
                               style={'color': '#2ecc71' if tm['annualized_return'] > 0 else '#e74c3c'})
                    ])
                ], width=3),
                dbc.Col([
                    html.Div([
                        html.Small("Sharpe Ratio", className="text-muted"),
                        html.H6(f"{tm['sharpe_ratio']:.3f}")
                    ])
                ], width=3),
                dbc.Col([
                    html.Div([
                        html.Small("Max Drawdown", className="text-muted"),
                        html.H6(f"{tm['max_drawdown']:.2%}", style={'color': '#e74c3c'})
                    ])
                ], width=3),
                dbc.Col([
                    html.Div([
                        html.Small("Win Rate", className="text-muted"),
                        html.H6(f"{tm['win_rate']:.2%}")
                    ])
                ], width=3)
            ], className="text-center")
            
            # Mean Reversion Position Chart
            fig_mr_pos = go.Figure()
            fig_mr_pos.add_trace(go.Scatter(
                x=dates,
                y=results['mr_positions'],
                mode='lines',
                name='Position',
                line=dict(color='#9b59b6', width=2),
                fill='tozeroy',
                fillcolor='rgba(155, 89, 182, 0.2)'
            ))
            fig_mr_pos.update_layout(
                title="Position Series",
                xaxis_title="Date",
                yaxis_title="Position",
                height=250,
                autosize=False,
                margin=dict(l=50, r=20, t=40, b=40),
                hovermode='x unified'
            )
            
            # Mean Reversion PnL Chart
            fig_mr_pnl = go.Figure()
            fig_mr_pnl.add_trace(go.Scatter(
                x=dates,
                y=results['mr_cum_pnl'],
                mode='lines',
                name='Cumulative PnL',
                line=dict(color='#27ae60', width=2)
            ))
            fig_mr_pnl.update_layout(
                title="Cumulative PnL",
                xaxis_title="Date",
                yaxis_title="Value",
                height=250,
                autosize=False,
                margin=dict(l=50, r=20, t=40, b=40),
                hovermode='x unified'
            )
            
            # MR Metrics
            mm = results['mr_metrics']
            mr_metrics = dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Small("Annual Return", className="text-muted"),
                        html.H6(f"{mm['annualized_return']:.2%}", 
                               style={'color': '#2ecc71' if mm['annualized_return'] > 0 else '#e74c3c'})
                    ])
                ], width=3),
                dbc.Col([
                    html.Div([
                        html.Small("Sharpe Ratio", className="text-muted"),
                        html.H6(f"{mm['sharpe_ratio']:.3f}")
                    ])
                ], width=3),
                dbc.Col([
                    html.Div([
                        html.Small("Max Drawdown", className="text-muted"),
                        html.H6(f"{mm['max_drawdown']:.2%}", style={'color': '#e74c3c'})
                    ])
                ], width=3),
                dbc.Col([
                    html.Div([
                        html.Small("Win Rate", className="text-muted"),
                        html.H6(f"{mm['win_rate']:.2%}")
                    ])
                ], width=3)
            ], className="text-center")
            
            # Combined Position Chart
            fig_combined_pos = go.Figure()
            fig_combined_pos.add_trace(go.Scatter(
                x=dates,
                y=results['combined_positions'],
                mode='lines',
                name='Position',
                line=dict(color='#f39c12', width=2),
                fill='tozeroy',
                fillcolor='rgba(243, 156, 18, 0.2)'
            ))
            fig_combined_pos.update_layout(
                title="Combined Position Series (Optimal Weights)",
                xaxis_title="Date",
                yaxis_title="Position",
                height=300,
                autosize=False,
                margin=dict(l=50, r=20, t=40, b=40),
                hovermode='x unified'
            )
            
            # Combined PnL Chart
            fig_combined_pnl = go.Figure()
            fig_combined_pnl.add_trace(go.Scatter(
                x=dates,
                y=results['combined_cum_pnl'],
                mode='lines',
                name='Cumulative PnL',
                line=dict(color='#27ae60', width=3)
            ))
            fig_combined_pnl.update_layout(
                title="Cumulative PnL",
                xaxis_title="Date",
                yaxis_title="Value",
                height=250,
                autosize=False,
                margin=dict(l=50, r=20, t=40, b=40),
                hovermode='x unified'
            )
            
            # Get optimal weights and correlation
            opt_weights = results.get('optimal_weights', {'TrendFollowing': 0.5, 'MeanReversion': 0.5})
            correlation = results.get('correlation', 0.0)
            
            # Combined Metrics
            cm = results['combined_metrics']
            combined_metrics = dbc.Card([
                dbc.CardBody([
                    # Weights and correlation info
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                html.Small("TF Weight", className="text-muted"),
                                html.H6(f"{opt_weights.get('TrendFollowing', 0.5):.1%}", 
                                       style={'fontWeight': 'bold', 'color': '#3498db'})
                            ])
                        ], width=3),
                        dbc.Col([
                            html.Div([
                                html.Small("MR Weight", className="text-muted"),
                                html.H6(f"{opt_weights.get('MeanReversion', 0.5):.1%}", 
                                       style={'fontWeight': 'bold', 'color': '#9b59b6'})
                            ])
                        ], width=3),
                        dbc.Col([
                            html.Div([
                                html.Small("Correlation", className="text-muted"),
                                html.H6(f"{correlation:.3f}", 
                                       style={'fontWeight': 'bold', 
                                              'color': '#2ecc71' if abs(correlation) < 0.3 else '#f39c12'})
                            ])
                        ], width=3),
                        dbc.Col([
                            html.Div([
                                html.Small("Blending", className="text-muted"),
                                html.H6("Mean-Var Opt", 
                                       style={'fontWeight': 'bold', 'fontSize': '0.9rem'})
                            ])
                        ], width=3)
                    ], className="text-center mb-3"),
                    # Performance metrics
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                html.Small("Annual Return", className="text-muted"),
                                html.H5(f"{cm['annualized_return']:.2%}", 
                                       style={'color': '#2ecc71' if cm['annualized_return'] > 0 else '#e74c3c',
                                              'fontWeight': 'bold'})
                            ])
                        ], width=3),
                        dbc.Col([
                            html.Div([
                                html.Small("Sharpe Ratio", className="text-muted"),
                                html.H5(f"{cm['sharpe_ratio']:.3f}", style={'fontWeight': 'bold'})
                            ])
                        ], width=3),
                        dbc.Col([
                            html.Div([
                                html.Small("Max Drawdown", className="text-muted"),
                                html.H5(f"{cm['max_drawdown']:.2%}", 
                                       style={'color': '#e74c3c', 'fontWeight': 'bold'})
                            ])
                        ], width=3),
                        dbc.Col([
                            html.Div([
                                html.Small("Win Rate", className="text-muted"),
                                html.H5(f"{cm['win_rate']:.2%}", style={'fontWeight': 'bold'})
                            ])
                        ], width=3)
                    ], className="text-center")
                ])
            ], style={'backgroundColor': '#fff3cd'})
            
            # Success status
            success_status = dbc.Badge("✓ Complete", color="success", className="fs-6")
            
            return (fig_trend_pos, fig_trend_pnl, trend_metrics,
                   fig_mr_pos, fig_mr_pnl, mr_metrics,
                   fig_combined_pos, fig_combined_pnl, combined_metrics,
                   success_status)
    
    def run(self, host='127.0.0.1', port=8050, debug=True):
        """
        Run the dashboard server.
        
        Args:
            host: Host address
            port: Port number
            debug: Debug mode
        """
        print(f"\n{'='*80}")
        print(f"Starting Futures Portfolio Dashboard")
        print(f"{'='*80}")
        print(f"Dashboard URL: http://{host}:{port}")
        print(f"Reference Date: {self.reference_date.strftime('%Y-%m-%d')}")
        print(f"{'='*80}\n")
        
        self.app.run(host=host, port=port, debug=debug)

