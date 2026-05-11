# -*- coding: utf-8 -*-
"""
Visualization tools for volatility trading strategies
Created on Oct 29, 2025

@author: CMBC
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .vol import VolatilityData, BaseStrategy
from settings.futures import FuturesConfig
from .backtest import StrategyBacktester


class VolatilityVisualizer:
    """
    Visualization engine for volatility strategies using Plotly
    """
    
    def __init__(self, vol_data: VolatilityData, backtester: Optional[StrategyBacktester] = None):
        """
        Initialize visualizer
        
        Parameters:
        -----------
        vol_data : VolatilityData
            Volatility data container
        backtester : StrategyBacktester, optional
            Backtester instance with results
        """
        self.vol_data = vol_data
        self.backtester = backtester
        self.data = vol_data.get_data()
        
    def plot_volatility_surface(self, title: str = "Implied Volatility Term Structure") -> go.Figure:
        """Plot IV term structure time series"""
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=self.data.index, y=self.data['IV_1M'],
            name='1M IV', mode='lines', line=dict(width=2)
        ))
        fig.add_trace(go.Scatter(
            x=self.data.index, y=self.data['IV_2M'],
            name='2M IV', mode='lines', line=dict(width=2)
        ))
        fig.add_trace(go.Scatter(
            x=self.data.index, y=self.data['IV_3M'],
            name='3M IV', mode='lines', line=dict(width=2)
        ))
        
        fig.update_layout(
            title=title,
            xaxis_title='Date',
            yaxis_title='Implied Volatility',
            height=500,
            hovermode='x unified'
        )
        
        return fig
    
    def plot_term_structure_analysis(self) -> go.Figure:
        """Plot term structure slope analysis"""
        fig = make_subplots(
            rows=2, cols=1,
            subplot_titles=('Term Structure Slope (1M-3M)', 'Slope Z-Score'),
            vertical_spacing=0.12
        )
        
        if 'Slope_1M3M' in self.data.columns:
            mean_slope = self.data['Slope_1M3M'].mean()
            std_slope = self.data['Slope_1M3M'].std()
            
            # Slope
            fig.add_trace(
                go.Scatter(x=self.data.index, y=self.data['Slope_1M3M'],
                          name='1M-3M Slope', line=dict(color='purple', width=2)),
                row=1, col=1
            )
            
            fig.add_hline(y=mean_slope, line_dash="dash", line_color="red",
                         annotation_text="Mean", row=1, col=1)
            
            # Z-Score
            if 'Slope_1M3M_Zscore' in self.data.columns:
                fig.add_trace(
                    go.Scatter(x=self.data.index, y=self.data['Slope_1M3M_Zscore'],
                              name='Z-Score', line=dict(color='blue', width=2)),
                    row=2, col=1
                )
                
                fig.add_hline(y=1.5, line_dash="dash", line_color="orange",
                             annotation_text="+1.5σ", row=2, col=1)
                fig.add_hline(y=-1.5, line_dash="dash", line_color="orange",
                             annotation_text="-1.5σ", row=2, col=1)
                fig.add_hline(y=0, line_dash="solid", line_color="gray", row=2, col=1)
        
        fig.update_layout(height=700, showlegend=True, hovermode='x unified')
        fig.update_xaxes(title_text="Date", row=2, col=1)
        fig.update_yaxes(title_text="Slope", row=1, col=1)
        fig.update_yaxes(title_text="Z-Score", row=2, col=1)
        
        return fig
    
    def plot_mean_reversion_bands(self) -> go.Figure:
        """Plot Bollinger Bands for mean reversion strategy"""
        fig = go.Figure()
        
        # 1M IV
        fig.add_trace(go.Scatter(
            x=self.data.index, y=self.data['IV_1M'],
            name='1M IV', line=dict(color='blue', width=2)
        ))
        
        # Moving average
        if 'IV_1M_MA' in self.data.columns:
            fig.add_trace(go.Scatter(
                x=self.data.index, y=self.data['IV_1M_MA'],
                name='Moving Average', line=dict(color='red', width=1.5, dash='dash')
            ))
        
        # Bollinger Bands
        if 'IV_1M_Upper' in self.data.columns and 'IV_1M_Lower' in self.data.columns:
            fig.add_trace(go.Scatter(
                x=self.data.index, y=self.data['IV_1M_Upper'],
                name='Upper Band', line=dict(color='gray', width=1),
                showlegend=False
            ))
            fig.add_trace(go.Scatter(
                x=self.data.index, y=self.data['IV_1M_Lower'],
                name='Bollinger Bands', line=dict(color='gray', width=1),
                fill='tonexty', fillcolor='rgba(128,128,128,0.2)'
            ))
        
        fig.update_layout(
            title='Mean Reversion Strategy - Bollinger Bands',
            xaxis_title='Date',
            yaxis_title='Implied Volatility (1M)',
            height=500,
            hovermode='x unified'
        )
        
        return fig
    
    def plot_momentum_indicator(self) -> go.Figure:
        """Plot momentum indicator"""
        fig = go.Figure()
        
        if 'IV_1M_Chg_5D' in self.data.columns:
            colors = ['red' if x < 0 else 'green' for x in self.data['IV_1M_Chg_5D']]
            
            fig.add_trace(go.Bar(
                x=self.data.index, y=self.data['IV_1M_Chg_5D'] * 100,
                name='5-Day Change', marker_color=colors, opacity=0.6
            ))
            
            fig.add_hline(y=5, line_dash="dash", line_color="orange",
                         annotation_text="Threshold +5%")
            fig.add_hline(y=-5, line_dash="dash", line_color="orange",
                         annotation_text="Threshold -5%")
            fig.add_hline(y=0, line_dash="solid", line_color="gray")
        
        fig.update_layout(
            title='Volatility Momentum (5-Day % Change)',
            xaxis_title='Date',
            yaxis_title='Change Rate (%)',
            height=500,
            hovermode='x unified'
        )
        
        return fig
    
    def plot_strategy_signals(self, strategy: BaseStrategy) -> go.Figure:
        """
        Plot strategy signals overlaid on volatility
        
        Parameters:
        -----------
        strategy : BaseStrategy
            Strategy with generated signals
        """
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        # Plot 1M IV
        fig.add_trace(
            go.Scatter(x=self.data.index, y=self.data['IV_1M'],
                      name='1M IV', line=dict(color='blue', width=2), opacity=0.6),
            secondary_y=False
        )
        
        # Plot signals
        if strategy.signals is not None:
            signal_colors = {1: 'green', -1: 'red', 0: 'gray'}
            
            for sig in [-1, 0, 1]:
                mask = strategy.signals == sig
                if mask.any():
                    fig.add_trace(
                        go.Scatter(
                            x=self.data.index[mask],
                            y=strategy.signals[mask],
                            name=f'Signal={sig:+d}',
                            mode='markers',
                            marker=dict(color=signal_colors[sig], size=8),
                            opacity=0.7
                        ),
                        secondary_y=True
                    )
        
        fig.update_layout(
            title=f'{strategy.name} - Trading Signals',
            height=500,
            hovermode='x unified'
        )
        
        fig.update_xaxes(title_text="Date")
        fig.update_yaxes(title_text="Implied Volatility", secondary_y=False)
        fig.update_yaxes(title_text="Trading Signal", secondary_y=True)
        
        return fig
    
    def plot_comprehensive_analysis(self, strategies: List[BaseStrategy]) -> go.Figure:
        """
        Create comprehensive multi-panel analysis
        
        Parameters:
        -----------
        strategies : list
            List of strategies to visualize
        """
        n_strategies = len(strategies)
        fig = make_subplots(
            rows=2 + n_strategies, cols=2,
            subplot_titles=(
                'Implied Volatility Term Structure',
                'Term Structure Slope (1M-3M)',
                'Mean Reversion - Bollinger Bands',
                'Volatility Momentum (5-Day % Change)',
                *[f'{s.name} Signals' for s in strategies],
            ),
            specs=[
                [{"secondary_y": False}, {"secondary_y": False}],
                [{"secondary_y": False}, {"secondary_y": False}],
                *[[{"secondary_y": True}, {"secondary_y": True}] for _ in range(n_strategies)]
            ],
            vertical_spacing=0.06,
            horizontal_spacing=0.1
        )
        
        # Chart 1: IV Time Series
        for col, name in zip(['IV_1M', 'IV_2M', 'IV_3M'], ['1M', '2M', '3M']):
            fig.add_trace(
                go.Scatter(x=self.data.index, y=self.data[col],
                          name=f'{name} IV', line=dict(width=2)),
                row=1, col=1
            )
        
        # Chart 2: Term Structure Slope
        if 'Slope_1M3M' in self.data.columns:
            mean_slope = self.data['Slope_1M3M'].mean()
            fig.add_trace(
                go.Scatter(x=self.data.index, y=self.data['Slope_1M3M'],
                          name='Slope', line=dict(color='purple', width=2)),
                row=1, col=2
            )
            fig.add_hline(y=mean_slope, line_dash="dash", line_color="red", row=1, col=2)
        
        # Chart 3: Bollinger Bands
        fig.add_trace(
            go.Scatter(x=self.data.index, y=self.data['IV_1M'],
                      name='1M IV', line=dict(color='blue', width=2), showlegend=False),
            row=2, col=1
        )
        if 'IV_1M_MA' in self.data.columns:
            fig.add_trace(
                go.Scatter(x=self.data.index, y=self.data['IV_1M_MA'],
                          name='MA', line=dict(color='red', width=1.5, dash='dash')),
                row=2, col=1
            )
        if 'IV_1M_Upper' in self.data.columns and 'IV_1M_Lower' in self.data.columns:
            fig.add_trace(
                go.Scatter(x=self.data.index, y=self.data['IV_1M_Upper'],
                          line=dict(color='gray', width=1), showlegend=False),
                row=2, col=1
            )
            fig.add_trace(
                go.Scatter(x=self.data.index, y=self.data['IV_1M_Lower'],
                          name='BB', line=dict(color='gray', width=1),
                          fill='tonexty', fillcolor='rgba(128,128,128,0.2)'),
                row=2, col=1
            )
        
        # Chart 4: Momentum
        if 'IV_1M_Chg_5D' in self.data.columns:
            colors = ['red' if x < 0 else 'green' for x in self.data['IV_1M_Chg_5D']]
            fig.add_trace(
                go.Bar(x=self.data.index, y=self.data['IV_1M_Chg_5D'] * 100,
                      name='5D Chg', marker_color=colors, opacity=0.6),
                row=2, col=2
            )
        
        # Strategy signal charts
        signal_colors = {1: 'green', -1: 'red', 0: 'gray'}
        for idx, strategy in enumerate(strategies):
            row = 3 + idx
            col = 1 if idx < n_strategies else 2
            if idx >= n_strategies:
                row = 3 + (idx - n_strategies)
                col = 2
            
            # Plot IV
            fig.add_trace(
                go.Scatter(x=self.data.index, y=self.data['IV_1M'],
                          name='1M IV', line=dict(color='blue', width=1.5),
                          opacity=0.5, showlegend=False),
                row=row, col=col, secondary_y=False
            )
            
            # Plot signals
            if strategy.signals is not None:
                for sig in [-1, 0, 1]:
                    mask = strategy.signals == sig
                    if mask.any():
                        fig.add_trace(
                            go.Scatter(
                                x=self.data.index[mask],
                                y=strategy.signals[mask],
                                name=f'{strategy.name[:10]}={sig:+d}',
                                mode='markers',
                                marker=dict(color=signal_colors[sig], size=6),
                                opacity=0.6
                            ),
                            row=row, col=col, secondary_y=True
                        )
        
        fig.update_layout(
            height=400 + 250 * n_strategies,
            width=1600,
            title_text="Volatility Trading Strategy - Comprehensive Analysis",
            showlegend=True,
            hovermode='x unified'
        )
        
        return fig
    
    def plot_performance_comparison(self) -> go.Figure:
        """Plot cumulative returns comparison"""
        if self.backtester is None or not self.backtester.results:
            print("No backtest results available")
            return go.Figure()
        
        fig = go.Figure()
        
        for strategy_name, results in self.backtester.results.items():
            cumulative_pct = (results['Cumulative_Return'] - 1) * 100
            
            fig.add_trace(go.Scatter(
                x=results.index,
                y=cumulative_pct,
                name=strategy_name,
                mode='lines',
                line=dict(width=2),
                opacity=0.8
            ))
        
        fig.update_layout(
            title='Strategy Cumulative Returns Comparison (%)',
            xaxis_title='Date',
            yaxis_title='Cumulative Return (%)',
            height=600,
            width=1200,
            hovermode='x unified',
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01)
        )
        
        fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='lightgray')
        fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='lightgray')
        
        return fig
    
    def save_figure(self, fig: go.Figure, filepath: str):
        """
        Save figure to HTML file with embedded dashboard controls
        
        Parameters:
        -----------
        fig : go.Figure
            Plotly figure
        filepath : str
            Output file path
        """
        # Get the HTML from plotly
        html_string = fig.to_html(include_plotlyjs='cdn')
        
        # Build dynamic ticker options from FuturesConfig.VOL_SYMBOLS with current selection
        current_code = getattr(self.vol_data, 'code', None)
        options_html = ''.join([
            f'<option value="{sym}"' + (" selected" if sym == current_code else "") + f'>{sym}</option>'
            for sym in FuturesConfig.VOL_SYMBOLS
        ])

        # Create enhanced dashboard HTML with controls (dynamic ticker list)
        import time
        cache_buster = int(time.time())
        dashboard_html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>Volatility Trading Strategy Dashboard - v{cache_buster}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f5f5f5;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px 40px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .header h1 {{
            margin: 0;
            font-size: 28px;
            font-weight: 600;
        }}
        .header p {{
            margin: 5px 0 0 0;
            opacity: 0.9;
            font-size: 14px;
        }}
        .control-panel {{
            background: white;
            padding: 20px 40px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            display: flex;
            align-items: center;
            gap: 20px;
            flex-wrap: wrap;
        }}
        .control-group {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .control-group label {{
            font-weight: 500;
            color: #555;
            font-size: 14px;
        }}
        .control-group select {{
            padding: 8px 15px;
            border: 2px solid #ddd;
            border-radius: 5px;
            font-size: 14px;
            cursor: pointer;
            background: white;
            transition: border-color 0.3s;
        }}
        .control-group select:hover {{
            border-color: #667eea;
        }}
        .control-group select:focus {{
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102,126,234,0.1);
        }}
        .btn {{
            padding: 10px 25px;
            border: none;
            border-radius: 5px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }}
        .btn-primary {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}
        .btn-primary:hover {{
            transform: translateY(-2px);
            box-shadow: 0 4px 10px rgba(102,126,234,0.3);
        }}
        .btn-primary:active {{
            transform: translateY(0);
        }}
        .btn-secondary {{
            background: white;
            color: #667eea;
            border: 2px solid #667eea;
        }}
        .btn-secondary:hover {{
            background: #667eea;
            color: white;
        }}
        .status-indicator {{
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 15px;
            background: #f0f0f0;
            border-radius: 5px;
            font-size: 13px;
            color: #555;
        }}
        .status-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #4CAF50;
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
        }}
        .chart-container {{
            padding: 20px;
            background: white;
            margin: 20px 40px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        .chart-container .plotly-graph-div {{
            width: 100% !important;
            height: auto !important;
        }}
        .loader {{
            display: none;
            border: 4px solid #f3f3f3;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            width: 30px;
            height: 30px;
            animation: spin 1s linear infinite;
        }}
        @keyframes spin {{
            0% {{ transform: rotate(0deg); }}
            100% {{ transform: rotate(360deg); }}
        }}
        .info-panel {{
            background: white;
            padding: 15px 40px;
            margin: 0 40px 20px 40px;
            border-radius: 10px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
        }}
        .info-item {{
            padding: 10px;
        }}
        .info-item h3 {{
            margin: 0 0 5px 0;
            font-size: 12px;
            color: #888;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .info-item p {{
            margin: 0;
            font-size: 18px;
            font-weight: 600;
            color: #333;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 Volatility Trading Strategy Dashboard</h1>
        <p>Real-time analysis and mean reversion strategy monitoring</p>
    </div>
    
    <div class="control-panel">
        <div class="control-group">
            <label for="ticker-select">Select Ticker:</label>
            <select id="ticker-select" onchange="updateInfo()">
                {options_html}
            </select>
        </div>
        
        <button class="btn btn-primary" onclick="runAnalysis()">
            ▶ Run Analysis
        </button>
        
        <button class="btn btn-secondary" onclick="refreshPage()">
            🔄 Refresh
        </button>
        
        <div class="loader" id="loader"></div>
        
        <div class="status-indicator" id="status">
            <div class="status-dot"></div>
            <span>Ready</span>
        </div>
    </div>
    
    <div class="info-panel" id="info-panel">
        <div class="info-item">
            <h3>Current Ticker</h3>
            <p id="current-ticker">-</p>
        </div>
        <div class="info-item">
            <h3>Last Updated</h3>
            <p id="last-updated">-</p>
        </div>
        <div class="info-item">
            <h3>Strategy</h3>
            <p>Mean Reversion</p>
        </div>
    </div>
    
    <div class="chart-container">
        {html_string.split('<body>')[1].split('</body>')[0] if '<body>' in html_string else html_string}
    </div>
    
    <script>
        // Set current ticker on load
        document.addEventListener('DOMContentLoaded', function() {{
            updateInfo();
        }});
        
        function updateInfo() {{
            const select = document.getElementById('ticker-select');
            const ticker = select ? select.value : 'Unknown';
            const currentTickerEl = document.getElementById('current-ticker');
            const lastUpdatedEl = document.getElementById('last-updated');
            
            if (currentTickerEl) {{
                currentTickerEl.textContent = ticker;
            }}
            if (lastUpdatedEl) {{
                lastUpdatedEl.textContent = new Date().toLocaleString();
            }}
        }}
        
        function runAnalysis() {{
            const ticker = document.getElementById('ticker-select').value;
            const loader = document.getElementById('loader');
            const status = document.getElementById('status');
            const startedAt = new Date();
            // Detect if opened as local file (file://) and adjust endpoint
            const isFileOrigin = window.location.protocol === 'file:';
            const endpoint = isFileOrigin ? 'http://localhost:5000/run_analysis' : '/run_analysis';
            
            // Visual feedback
            loader.style.display = 'block';
            status.innerHTML = '<div class="status-dot" style="background: #ff9800;"></div><span>Running Analysis for ' + ticker + '...</span>';
            console.log('[VolDash] Starting analysis request', {{ ticker, endpoint, time: startedAt.toISOString(), fileOrigin: isFileOrigin }});
            
            // Timeout guard (e.g. server not running)
            const timeoutMs = 15000;
            let timeoutHandle = setTimeout(() => {{
                if (loader.style.display === 'block') {{
                    loader.style.display = 'none';
                    status.innerHTML = '<div class="status-dot" style="background: #f44336;"></div><span>Timeout waiting for server</span>';
                    alert('No response from server after ' + (timeoutMs/1000) + 's. Make sure Flask server is running on port 5000.');
                }}
            }}, timeoutMs);
            
            fetch(endpoint, {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ ticker }})
            }})
            .then(resp => {{
                if (!resp.ok) {{
                    throw new Error('HTTP ' + resp.status);
                }}
                return resp.json();
            }})
            .then(data => {{
                clearTimeout(timeoutHandle);
                loader.style.display = 'none';
                if (data.success) {{
                    status.innerHTML = '<div class="status-dot" style="background: #4CAF50;"></div><span>Complete (' + ticker + ')</span>';
                    updateInfo();
                    console.log('[VolDash] Analysis succeeded', data);
                    // Reload page to show new results
                    setTimeout(() => {{ window.location.reload(); }}, 1000);
                }} else {{
                    status.innerHTML = '<div class="status-dot" style="background: #f44336;"></div><span>Error</span>';
                    console.error('[VolDash] Analysis error', data.error);
                    alert('Error: ' + (data.error || 'Unknown'));
                }}
            }})
            .catch(err => {{
                clearTimeout(timeoutHandle);
                loader.style.display = 'none';
                status.innerHTML = '<div class="status-dot" style="background: #f44336;"></div><span>Connection Error</span>';
                console.error('[VolDash] Fetch failed', err);
                alert('Connection error: ' + err.message + '. Make sure Flask server is running on port 5000.');
            }});
        }}
        
        function refreshPage() {{
            window.location.reload();
        }}
    </script>
</body>
</html>
"""
        
        # Write the enhanced HTML
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(dashboard_html)
        
        print(f"✅ Dashboard saved to: {filepath}")
    
    def plot_combined_analysis(self, mean_reversion_strategy: BaseStrategy) -> go.Figure:
        """
        Create combined analysis with only 5 specific figures:
        1. Implied volatility term structure
        2. Mean reversion - Bollinger bands
        3. Volatility momentum
        4. Volatility mean reversion signals
        5. Strategy accumulative returns
        
        Parameters:
        -----------
        mean_reversion_strategy : BaseStrategy
            The mean reversion strategy with signals
        """
        fig = make_subplots(
            rows=3, cols=2,
            subplot_titles=(
                'Implied Volatility Term Structure',
                'Mean Reversion - Bollinger Bands',
                'Volatility Momentum',
                'Volatility Mean Reversion Signals',
                'Strategy Accumulative Returns',
                ''  # Empty for layout
            ),
            specs=[
                [{"secondary_y": False}, {"secondary_y": False}],
                [{"secondary_y": False}, {"secondary_y": True}],
                [{"colspan": 2}, None]
            ],
            vertical_spacing=0.10,
            horizontal_spacing=0.12,
            row_heights=[0.3, 0.3, 0.4]
        )
        
        # Chart 1: Implied Volatility Term Structure
        for col, name in zip(['IV_1M', 'IV_2M', 'IV_3M'], ['1M', '2M', '3M']):
            fig.add_trace(
                go.Scatter(x=self.data.index, y=self.data[col],
                          name=f'{name} IV', line=dict(width=2)),
                row=1, col=1
            )
        
        # Chart 2: Mean Reversion - Bollinger Bands
        fig.add_trace(
            go.Scatter(x=self.data.index, y=self.data['IV_1M'],
                      name='1M IV', line=dict(color='blue', width=2)),
            row=1, col=2
        )
        if 'IV_1M_MA' in self.data.columns:
            fig.add_trace(
                go.Scatter(x=self.data.index, y=self.data['IV_1M_MA'],
                          name='MA', line=dict(color='red', width=1.5, dash='dash')),
                row=1, col=2
            )
        if 'IV_1M_Upper' in self.data.columns and 'IV_1M_Lower' in self.data.columns:
            fig.add_trace(
                go.Scatter(x=self.data.index, y=self.data['IV_1M_Upper'],
                          line=dict(color='gray', width=1), showlegend=False),
                row=1, col=2
            )
            fig.add_trace(
                go.Scatter(x=self.data.index, y=self.data['IV_1M_Lower'],
                          name='Bollinger Bands', line=dict(color='gray', width=1),
                          fill='tonexty', fillcolor='rgba(128,128,128,0.2)'),
                row=1, col=2
            )

        # Add Historical Volatility (EWMA)
        try:
            import os
            from settings.paths import DIR_INPUT
            
            pkl_path = os.path.join(DIR_INPUT, "futures-dailyK_con.pkl")
            if os.path.exists(pkl_path):
                daily_data = pd.read_pickle(pkl_path)
                ticker = self.vol_data.code
                
                if ticker in daily_data:
                    df_price = daily_data[ticker]

                    # Calculate returns and EWMA Volatility (Span=20, Annualized)
                    returns = df_price["Close"].pct_change()
                    ewma_vol = returns.ewm(span=20).std() * np.sqrt(252)
                    
                    # Align with IV data index
                    ewma_vol_aligned = ewma_vol.reindex(self.data.index)
                    
                    fig.add_trace(
                        go.Scatter(x=ewma_vol_aligned.index, y=100*ewma_vol_aligned,
                                    name='Hist Vol (EWMA)', 
                                    line=dict(color='orange', width=1.5, dash='dot')),
                        row=1, col=2
                    )
        except Exception as e:
            print(f"Warning: Could not add historical volatility: {e}")
        
        # Chart 3: Volatility Momentum
        # Calculate 5-day momentum if not already present
        if 'IV_1M_Chg_5D' not in self.data.columns:
            self.data['IV_1M_Chg_5D'] = self.data['IV_1M'].pct_change(5)
        
        if 'IV_1M_Chg_5D' in self.data.columns:
            colors = ['red' if x < 0 else 'green' for x in self.data['IV_1M_Chg_5D']]
            fig.add_trace(
                go.Bar(x=self.data.index, y=self.data['IV_1M_Chg_5D'] * 100,
                      name='5-Day Change (%)', marker_color=colors, opacity=0.6),
                row=2, col=1
            )
            fig.add_hline(y=5, line_dash="dash", line_color="orange", row=2, col=1)
            fig.add_hline(y=-5, line_dash="dash", line_color="orange", row=2, col=1)
            fig.add_hline(y=0, line_dash="solid", line_color="gray", row=2, col=1)
        
        # Chart 4: Volatility Mean Reversion Signals
        signal_colors = {1: 'green', -1: 'red', 0: 'gray'}
        
        # Plot IV on primary axis
        fig.add_trace(
            go.Scatter(x=self.data.index, y=self.data['IV_1M'],
                      name='1M IV', line=dict(color='blue', width=2),
                      opacity=0.6),
            row=2, col=2, secondary_y=False
        )
        
        # Plot signals on secondary axis
        if mean_reversion_strategy.signals is not None:
            for sig in [-1, 0, 1]:
                mask = mean_reversion_strategy.signals == sig
                if mask.any():
                    signal_label = {1: 'Long', -1: 'Short', 0: 'Neutral'}
                    fig.add_trace(
                        go.Scatter(
                            x=self.data.index[mask],
                            y=mean_reversion_strategy.signals[mask],
                            name=signal_label[sig],
                            mode='markers',
                            marker=dict(color=signal_colors[sig], size=8),
                            opacity=0.7
                        ),
                        row=2, col=2, secondary_y=True
                    )
        
        # Chart 5: Strategy Accumulative Returns
        if self.backtester and self.backtester.results:
            strategy_name = mean_reversion_strategy.name
            if strategy_name in self.backtester.results:
                results = self.backtester.results[strategy_name]
                cumulative_pct = (results['Cumulative_Return'] - 1) * 100
                
                fig.add_trace(go.Scatter(
                    x=results.index,
                    y=cumulative_pct,
                    name='Cumulative Return (%)',
                    mode='lines',
                    line=dict(width=2.5, color='darkgreen'),
                    opacity=0.8,
                    fill='tozeroy',
                    fillcolor='rgba(0,128,0,0.1)'
                ), row=3, col=1)
        
        # Update layout
        fig.update_layout(
            height=900,
            title_text="Volatility Trading Strategy - Comprehensive Analysis",
            showlegend=True,
            hovermode='x unified',
            margin=dict(l=50, r=50, t=80, b=50)
        )
        
        # Update axes labels
        fig.update_xaxes(title_text="Date", row=3, col=1)
        fig.update_yaxes(title_text="IV", row=1, col=1)
        fig.update_yaxes(title_text="IV", row=1, col=2)
        fig.update_yaxes(title_text="Change (%)", row=2, col=1)
        fig.update_yaxes(title_text="IV", row=2, col=2, secondary_y=False)
        fig.update_yaxes(title_text="Signal", row=2, col=2, secondary_y=True)
        fig.update_yaxes(title_text="Cumulative Return (%)", row=3, col=1)
        
        return fig
    
    def generate_all_charts(self, strategies: List[BaseStrategy], output_dir: str = "."):
        """
        Generate and save combined analysis chart with 5 specific figures
        
        Parameters:
        -----------
        strategies : list
            List of strategies to visualize (only mean reversion will be used)
        output_dir : str
            Output directory for saving charts
        """
        import os
        
        # Find mean reversion strategy
        mean_reversion_strategy = None
        for strategy in strategies:
            if 'Mean Reversion' in strategy.name:
                mean_reversion_strategy = strategy
                break
        
        if mean_reversion_strategy is None:
            print("⚠️ Mean Reversion strategy not found in strategies list")
            return
        
        # Generate combined analysis
        fig_combined = self.plot_combined_analysis(mean_reversion_strategy)
        self.save_figure(fig_combined, os.path.join(output_dir, "vol_strategy_analysis.html"))
        
        print(f"\n✅ Combined analysis chart generated in: {output_dir}")
