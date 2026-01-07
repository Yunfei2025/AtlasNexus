#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Plotting Functions Module

This module contains visualization functions for factor analysis and backtesting results.
Provides comprehensive plotting capabilities with Plotly interactive charts.
"""

import pandas as pd
import numpy as np
import os
from typing import Dict, Tuple, List, Any
from datetime import datetime


def _extract_factor_metrics(analysis_summary: Dict, backtest_result: Dict) -> List[List[str]]:
    """Extract factor metrics data for table display"""
    factor_metrics_data = [['Factor Name', 'IC Value', 'Weight', 'Return Contribution', 'Information Ratio']]
    
    # Extract from analysis summary
    if (analysis_summary and 'results' in analysis_summary):
        successful_results = [r for r in analysis_summary['results'] if r.get('result', {}).get('status') == 'success']
        
        if successful_results:
            result_data = successful_results[-1].get('result', {})
            selected_factors = result_data.get('selected_factors', [])
            selected_factor_metrics = result_data.get('selected_factor_metrics', {})
            factor_weights = _extract_factor_weights(result_data, backtest_result)
            
            for factor in selected_factors:
                factor_metrics = selected_factor_metrics.get(factor, {})
                ic_value = _extract_ic_value(factor_metrics)
                weight = factor_weights.get(factor, 'N/A')
                
                ic_str = f"{ic_value:.4f}" if isinstance(ic_value, (int, float)) else str(ic_value)
                weight_str = f"{weight:.4f}" if isinstance(weight, (int, float)) else str(weight)
                contribution = _calculate_contribution(weight, ic_value)
                info_ratio = _extract_info_ratio(factor_metrics)
                
                factor_metrics_data.append([factor, ic_str, weight_str, contribution, info_ratio])
    
    # Fallback to backtest result
    if len(factor_metrics_data) == 1:
        factor_metrics_data.extend(_extract_from_backtest_result(backtest_result))
    
    # Default placeholder if no data
    if len(factor_metrics_data) == 1:
        factor_metrics_data.append(['No Factor Data', 'N/A', 'N/A', 'N/A', 'N/A'])
    
    return factor_metrics_data


def _extract_factor_weights(result_data: Dict, backtest_result: Dict) -> Dict:
    """Extract factor weights from available sources"""
    # Try result_data first
    if 'factor_weights' in result_data:
        return result_data['factor_weights']
    
    # Try backtest result trained_model
    for source in [backtest_result, result_data]:
        trained_model = source.get('trained_model')
        if trained_model and isinstance(trained_model, dict):
            coefficients = trained_model.get('coefficients')
            if hasattr(coefficients, 'to_dict'):
                return coefficients.to_dict()
            elif isinstance(coefficients, dict):
                return coefficients
    
    return {}


def _extract_ic_value(factor_metrics: Any) -> Any:
    """Extract IC value from factor metrics"""
    if isinstance(factor_metrics, dict):
        return (factor_metrics.get('IC') or factor_metrics.get('ic') or 
                factor_metrics.get('IC_spearman') or factor_metrics.get('correlation') or 'N/A')
    return factor_metrics if isinstance(factor_metrics, (int, float)) else 'N/A'


def _extract_info_ratio(factor_metrics: Any) -> str:
    """Extract information ratio from factor metrics"""
    if isinstance(factor_metrics, dict):
        ir_val = (factor_metrics.get('IR') or factor_metrics.get('ir') or 
                 factor_metrics.get('information_ratio') or 'N/A')
        return f"{ir_val:.4f}" if isinstance(ir_val, (int, float)) else 'N/A'
    return 'N/A'


def _calculate_contribution(weight: Any, ic_value: Any) -> str:
    """Calculate return contribution from weight and IC"""
    if isinstance(weight, (int, float)) and isinstance(ic_value, (int, float)):
        return f"{weight * ic_value:.4f}"
    return 'N/A'


def _extract_from_backtest_result(backtest_result: Dict) -> List[List[str]]:
    """Extract factor data from backtest result as fallback"""
    selected_factors = backtest_result.get('selected_factors', [])
    selected_factor_metrics = backtest_result.get('selected_factor_metrics', {})
    
    # Extract weights from trained model
    factor_weights = {}
    trained_model = backtest_result.get('trained_model')
    if trained_model and isinstance(trained_model, dict):
        coefficients = trained_model.get('coefficients')
        if hasattr(coefficients, 'to_dict'):
            factor_weights = coefficients.to_dict()
        elif isinstance(coefficients, dict):
            factor_weights = coefficients
    
    factor_data = []
    for factor in selected_factors:
        factor_metrics = selected_factor_metrics.get(factor, {})
        ic_value = factor_metrics.get('IC', 'N/A')
        weight = factor_weights.get(factor, 'N/A')
        
        ic_str = f"{ic_value:.4f}" if isinstance(ic_value, (int, float)) else str(ic_value)
        weight_str = f"{weight:.4f}" if isinstance(weight, (int, float)) else str(weight)
        contribution = _calculate_contribution(weight, ic_value)
        
        info_ratio = 'N/A'
        if 'IR' in factor_metrics and isinstance(factor_metrics['IR'], (int, float)):
            info_ratio = f"{factor_metrics['IR']:.4f}"
        
        factor_data.append([factor, ic_str, weight_str, contribution, info_ratio])
    
    return factor_data


def _calculate_basic_metrics(strategy_returns: pd.Series, test_returns_aligned: pd.Series) -> Tuple[Dict, Dict]:
    """Calculate basic performance metrics for strategy and benchmark"""
    # Get annual trading days from config
    try:
        from ..config import config_manager
        annual_trading_days = config_manager.backtest_config.annual_trading_days
    except ImportError:
        annual_trading_days = 252  # Fallback to default if config not available
      # For percentage returns: NAV = cumulative product of (1 + returns)
    # strategy_returns are already percentage returns (e.g., 0.001 for 0.1%)
    strategy_nav = (1 + strategy_returns).cumprod()
    benchmark_nav = (1 + test_returns_aligned).cumprod()

    # Strategy metrics
    total_return = strategy_nav.iloc[-1] - 1
    annual_return = total_return * annual_trading_days / len(strategy_returns) if len(strategy_returns) > 0 else 0
    volatility = strategy_returns.std() * np.sqrt(annual_trading_days) if len(strategy_returns) > 0 else 0
    sharpe_ratio = annual_return / volatility if volatility > 0 else 0
    max_drawdown = ((strategy_nav / strategy_nav.cummax()) - 1).min()
    
    # Benchmark metrics  
    benchmark_total_return = benchmark_nav.iloc[-1] - 1 if len(benchmark_nav) > 0 else 0
    benchmark_annual_return = benchmark_total_return * annual_trading_days / len(test_returns_aligned) if len(test_returns_aligned) > 0 else 0
    benchmark_volatility = test_returns_aligned.std() * np.sqrt(annual_trading_days) if len(test_returns_aligned) > 0 else 0
    benchmark_sharpe = benchmark_annual_return / benchmark_volatility if benchmark_volatility > 0 else 0
    benchmark_max_drawdown = ((benchmark_nav / benchmark_nav.cummax()) - 1).min() if len(benchmark_nav) > 0 else 0
    
    return {
        'nav': strategy_nav, 'total_return': total_return, 'annual_return': annual_return,
        'sharpe_ratio': sharpe_ratio, 'max_drawdown': max_drawdown
    }, {
        'nav': benchmark_nav, 'total_return': benchmark_total_return, 'annual_return': benchmark_annual_return,
        'sharpe_ratio': benchmark_sharpe, 'max_drawdown': benchmark_max_drawdown
    }

def _get_model_params(model_config):
    return [
        # Row 1: Basic Settings
        ['Ticker', 'IC Threshold', 'IR Threshold', 'Top N Factors', 'Filtering Method'],
        [getattr(model_config, 'ticker', 'N/A'), f"{getattr(model_config, 'ic_threshold', 0)}",
         f"{getattr(model_config, 'ir_threshold', 0)}", f"{getattr(model_config, 'top_n', 0)}",
         getattr(model_config, 'filtering_method', 'N/A')],
        
        # Row 2: Factor Selection
        ['Correlation Thresh', 'VIF Threshold', 'VIF Fallback', 'Min Observations', 'Factor Returns'],
        [f"{getattr(model_config, 'correlation_threshold', 0)}", f"{getattr(model_config, 'vif_threshold', 0)}",
         f"{getattr(model_config, 'vif_fallback_threshold', 0)}", f"{getattr(model_config, 'min_observations', 0)}",
         getattr(model_config, 'factor_return_method', 'N/A')],
        
        # Row 3: Model Training & Weighting
        ['Weighting Method', 'Scale IC Pred', 'Portfolio Method', 'Max Position', 'Threshold'],
        [getattr(model_config, 'weighting_method', 'N/A'), f"{getattr(model_config, 'scale_ic_predictions', False)}",
         getattr(model_config, 'portfolio_method', 'N/A'), f"{getattr(model_config, 'max_position', 0)}",
         f"{getattr(model_config, 'threshold', 0)}"],
        
        # Row 4: Signal Processing
        ['Position Method', 'Lookback Window', 'Tanh Scale', 'Max Daily Change', 'Friction Cost'],
        [getattr(model_config, 'position_method', 'N/A'), f"{getattr(model_config, 'lookback_window', 0)}",
         f"{getattr(model_config, 'tanh_scale', 0)}", f"{getattr(model_config, 'max_daily_change', 0)}",
         f"{getattr(model_config, 'friction_cost', 0)}"],
        
        # Row 5: Signal Smoothing
        ['Signal Smoothing', 'Smoothing Method', 'Smoothing Window', 'Min Signal Strength', 'Persistence Thresh'],
        [f"{getattr(model_config, 'signal_smoothing', False)}", getattr(model_config, 'signal_smoothing_method', 'N/A'),
         f"{getattr(model_config, 'signal_smoothing_window', 0)}", f"{getattr(model_config, 'min_signal_strength', 0)}",
         f"{getattr(model_config, 'signal_persistence_threshold', 0)}"],
        
        # Row 6: Quadratic Tracking & Advanced
        ['Turnover Penalty', 'Tracking Weight', 'Adaptive Thresh', 'Win Rate Opt', 'Normalization'],
        [f"{getattr(model_config, 'turnover_penalty_lambda', 0)}", f"{getattr(model_config, 'tracking_weight', 0)}",
         f"{getattr(model_config, 'adaptive_threshold', False)}", f"{getattr(model_config, 'win_rate_optimization', False)}",
         getattr(model_config, 'normalization_method', 'N/A')]
    ]
    
    
    
def plot_results(backtest_result: Dict, analysis_summary: Dict = None) -> None:
    """Generate plots for backtest results."""
    # print("\n📈 Generating backtest visualization plots...")
    print("\nGenerating backtest visualization plots...")
    try:
        relative_returns = backtest_result.get('strategy_returns')
        actual_close_prices = backtest_result.get('actual_close_prices')
        test_returns = actual_close_prices.pct_change().shift(-1).dropna()
        positions = backtest_result.get('positions', None)
        if positions is not None:
            if isinstance(positions, pd.Series):
                positions = pd.DataFrame({'Asset_1': positions})
            elif hasattr(positions, 'to_frame'):
                positions = positions.to_frame('Asset_1')
        if relative_returns is not None and not relative_returns.empty:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
            import plotly.offline as pyo
            import webbrowser
            test_returns_aligned = test_returns.reindex(relative_returns.index).fillna(0.0)
            strategy_metrics, benchmark_metrics = _calculate_basic_metrics(relative_returns, test_returns_aligned)
            try:
                from ..config import config_manager
                model_config = config_manager.model_config
            except ImportError:
                model_config = None
                
            fig = make_subplots(
                rows=6, cols=2,
                subplot_titles=[
                    'Model Parameter Configuration', 'Win Rate Analysis',
                    'Selected Factor Metrics',
                    'Strategy Returns Distribution', 'Drawdown Curve',
                    'Net Value Curve', 'Key Metrics Comparison',
                    'Position Distribution', 'Rolling Sharpe Ratio',
                    'Final Period Factor Time Series', 'Actual vs Predicted Prices'
                ],
                specs=[
                    [{"type": "table"}, {"type": "pie"}],
                    [{"type": "table", "colspan": 2}, None],
                    [{"secondary_y": False}, {"secondary_y": False}],
                    [{"secondary_y": False}, {"secondary_y": False}],
                    [{"secondary_y": False}, {"secondary_y": False}],
                    [{"secondary_y": False}, {"secondary_y": False}]
                ]
            )
            
             # Note: Row 1 has table and pie chart which need different domain settings
            # We need to manually adjust the domains after adding the traces
            config_data = _get_model_params(model_config)
            
            # Row 1
            N_col = len(config_data)//2
            header = ['Item','Value']*N_col
            fill_color = [['lightblue']*5, ['white']*5]*N_col
            fig.add_trace(go.Table(#header=dict(values=header),
                                   cells=dict(values=config_data,
                                   fill_color=fill_color,
                                   align='center', font=dict(size=10), height=30)), row=1, col=1)
            win_counts = [(relative_returns > 0).sum(), (relative_returns <= 0).sum()]
            fig.add_trace(go.Pie(labels=['Profitable Days', 'Loss Days'], values=win_counts,
                                 name='Win Rate Analysis', marker_colors=['green', 'red']), row=1, col=2)
            
            # Adjust domains for 4:1 ratio in first row only
            # Table (row 1, col 1) - adjust its domain
            fig.data[0].domain = {'x': [0.0, 0.7], 'y': [0.9, 1.0]}
            # Pie chart (row 1, col 2) - adjust its domain  
            fig.data[1].domain = {'x': [0.8, 1.0], 'y': [0.9, 1.0]}
            
            # Adjust subplot titles for row 1 to match the repositioned subplots
            fig.layout.annotations[0].update(x=0.35)  # Center title over table (x=0.35 is center of 0.0-0.7)
            fig.layout.annotations[1].update(x=0.9)   # Center title over pie chart (x=0.9 is center of 0.8-1.0)
            axis_idx = 1
            for row in range(3, 7):            # rows 3,4,5,6
                xa_name = 'xaxis' if axis_idx == 1 else f'xaxis{axis_idx}'
                xb_name = f'xaxis{axis_idx + 1}'
                # make sure axis entries exist before assigning
                if xa_name in fig.layout and fig.layout[xa_name] is not None:
                    fig.layout[xa_name].domain = [0.0, 0.5]
                if xb_name in fig.layout and fig.layout[xb_name] is not None:
                    fig.layout[xb_name].domain = [0.6, 1.0]
                axis_idx += 2

            # Row 2
            factor_metrics_data = _extract_factor_metrics(analysis_summary, backtest_result)
            fig.add_trace(go.Table(header=dict(values=factor_metrics_data[0], fill_color='lightblue', align='center', font=dict(size=12)),
                                   cells=dict(values=list(zip(*factor_metrics_data[1:])), fill_color='white', align='center', font=dict(size=10))), row=2, col=1)
            
            # Row 3
            fig.add_trace(go.Histogram(x=relative_returns.values, nbinsx=50, name='Strategy Returns Distribution',
                                       marker_color='lightblue', opacity=0.7), row=3, col=1)
            drawdown = (strategy_metrics['nav'] / strategy_metrics['nav'].cummax()) - 1
            fig.add_trace(go.Scatter(x=drawdown.index, y=drawdown.values, fill='tonexty',
                                     mode='lines', name='Strategy Drawdown', line=dict(color='red')), row=3, col=2)
            
            # Row 4
            fig.add_trace(go.Scatter(x=strategy_metrics['nav'].index, y=strategy_metrics['nav'].values,
                                     name=f'Strategy NAV (Final: {strategy_metrics["nav"].iloc[-1]:.4f})',
                                     line=dict(color='blue', width=2)), row=4, col=1)
            fig.add_trace(go.Scatter(x=benchmark_metrics['nav'].index, y=benchmark_metrics['nav'].values,
                                     name=f'Benchmark NAV (Final: {benchmark_metrics["nav"].iloc[-1]:.4f})',
                                     line=dict(color='red', width=2, dash='dash')), row=4, col=1)
            metrics_names = ['Total Return (%)', 'Annual Return (%)', 'Sharpe Ratio', 'Max Drawdown (%)']
            strategy_values = [strategy_metrics['total_return'] * 100, strategy_metrics['annual_return'] * 100,
                              strategy_metrics['sharpe_ratio'], strategy_metrics['max_drawdown'] * 100]
            benchmark_values = [benchmark_metrics['total_return'] * 100, benchmark_metrics['annual_return'] * 100,
                               benchmark_metrics['sharpe_ratio'], benchmark_metrics['max_drawdown'] * 100]
            fig.add_trace(go.Bar(x=metrics_names, y=strategy_values, name='Strategy Metrics', marker_color='blue', opacity=0.7), row=4, col=2)
            fig.add_trace(go.Bar(x=metrics_names, y=benchmark_values, name='Benchmark Metrics', marker_color='red', opacity=0.7), row=4, col=2)
            
            # Row 5
            if positions is not None and not positions.empty:
                if hasattr(positions.index, 'tz') and positions.index.tz is not None:
                    positions = positions.tz_localize(None)
                for column in positions.columns:
                    fig.add_trace(go.Scatter(x=positions.index, y=positions[column], mode='lines', name=f'Position {column}', line=dict(shape='hv', width=2), opacity=0.8), row=5, col=1)
            try:
                from ..config import config_manager
                annual_trading_days = config_manager.backtest_config.annual_trading_days
            except ImportError:
                annual_trading_days = 252
            rolling_window = min(annual_trading_days, len(relative_returns) // 4)
            if rolling_window >= 20:
                rolling_sharpe = relative_returns.rolling(window=rolling_window).apply(
                    lambda x: (x.mean() * annual_trading_days) / (x.std() * np.sqrt(annual_trading_days)) if x.std() > 0 else 0
                )
                fig.add_trace(go.Scatter(x=rolling_sharpe.index, y=rolling_sharpe.values,
                                         mode='lines', name=f'Rolling Sharpe Ratio ({rolling_window}d)',
                                         line=dict(color='green', width=2)), row=5, col=2)
            # Row 6
            # Final period factor time series analysis (Row 6)
            try:
                selected_factors = []
                factor_timeseries = {}
                if analysis_summary and 'results' in analysis_summary:
                    successful_results = [r for r in analysis_summary['results'] if r.get('result', {}).get('status') == 'success']
                    if successful_results:
                        result_data = successful_results[-1].get('result', {})
                        selected_factors = result_data.get('selected_factors', [])
                        factor_timeseries = result_data.get('factor_timeseries', {})
                colors = ['purple', 'orange', 'green', 'red', 'blue', 'brown', 'pink', 'gray', 'olive', 'cyan']
                line_styles = ['solid', 'dash', 'dot', 'dashdot']
                for i, factor in enumerate(selected_factors):
                    if factor in factor_timeseries:
                        factor_data = factor_timeseries[factor]
                        has_data = (hasattr(factor_data, 'empty') and not factor_data.empty) or (hasattr(factor_data, '__len__') and len(factor_data) > 0) or (factor_data is not None)
                        if has_data:
                            fig.add_trace(go.Scatter(x=factor_data.index, y=factor_data.values, mode='lines+markers',
                                                     name=f'Factor{i+1}: {factor}',
                                                     line=dict(color=colors[i % len(colors)], width=2, dash=line_styles[i % len(line_styles)]),
                                                     marker=dict(size=3, color=colors[i % len(colors)]), opacity=0.8), row=6, col=1)
                actual_close_prices = backtest_result.get('actual_close_prices')
                predicted_close_prices = backtest_result.get('predicted_close_prices')
                fig.add_trace(go.Scatter(x=actual_close_prices.index, y=actual_close_prices.values, mode='lines+markers',
                                         name='Actual Close Price', line=dict(color='blue', width=2),
                                         marker=dict(size=4, color='blue'), connectgaps=False), row=6, col=2)
                fig.add_trace(go.Scatter(x=predicted_close_prices.index, y=predicted_close_prices.values, mode='markers',
                                         name='Predicted Close Price', marker=dict(size=4, color='red', symbol='diamond'), connectgaps=False), row=6, col=2)
            except Exception as e:
                print(f"⚠️ Failed to add final period analysis: {e}")
            fig.update_layout(title=dict(text="Factor Strategy Backtest Results Comprehensive Report", x=0.5, font=dict(size=16)),
                              height=1200, showlegend=True, template="plotly_white", font=dict(family="Arial, sans-serif"))
            filename = 'backtest_results.html'
            pyo.plot(fig, filename=filename, auto_open=False)
            file_path = os.path.abspath(filename)
            # print(f"📁 Plot saved to: {file_path}")
            print(f"Plot saved to: {file_path}")
            try:
                webbrowser.open(f'file://{file_path}')
                # print("🌐 Opening in default browser...")
                print("Opening in default browser...")
            except Exception as e1:
                try:
                    os.startfile(file_path)
                    # print("🚀 Opening with Windows default application...")
                    print("Opening with Windows default application...")
                except Exception as e2:
                    print(f"⚠️ Could not auto-open browser. Please manually open: {file_path}")
            # print("✅ Comprehensive interactive plot generated successfully")
            print("Comprehensive interactive plot generated successfully")
        else:
            print("⚠️ No strategy returns found for plotting")
    except Exception as e:
        print(f"❌ Plot generation failed: {e}")


def _create_text_summary(backtest_result: Dict) -> None:
    """Create a text summary when plotting fails"""
    try:
        summary_file = "backtest_summary.txt"
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write("FactorEngine Backtest Results Summary\n")
            f.write("=" * 50 + "\n\n")
            
            for key, value in backtest_result.items():
                if key != 'strategy_returns':  # Skip the series data
                    f.write(f"{key}: {value}\n")
            
            f.write(f"\nGenerated: {datetime.now()}\n")
        
        print(f"📄 Text summary saved: {summary_file}")
    except Exception as e:
        print(f"❌ Text summary creation failed: {e}")
