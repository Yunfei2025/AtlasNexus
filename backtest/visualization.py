# -*- coding: utf-8 -*-
"""
Backtest Visualization Module

Interactive visualization using Plotly for backtest results.

@author: CMBC
"""
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, Optional, List


def plot_pnl_curve(pnl: pd.Series, title: str = "Accumulated PnL", 
                   capital: float = None) -> go.Figure:
    """
    Plot accumulated PnL curve with optional return percentage.
    
    Parameters:
    -----------
    pnl : pd.Series
        Daily PnL series
    title : str
        Chart title
    capital : float, optional
        Initial capital for return percentage calculation
        
    Returns:
    --------
    go.Figure : Plotly figure object
    """
    cumulative_pnl = pnl.cumsum()
    
    fig = go.Figure()
    
    # Main PnL curve
    fig.add_trace(go.Scatter(
        x=cumulative_pnl.index,
        y=cumulative_pnl.values,
        mode='lines',
        name='Accumulated PnL',
        line=dict(color='#1f77b4', width=2),
        hovertemplate='<b>Date</b>: %{x}<br><b>PnL</b>: %{y:.2f}<extra></extra>'
    ))
    
    # Add zero line
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)
    
    # Add return percentage on secondary y-axis if capital provided
    if capital is not None:
        returns_pct = (cumulative_pnl / capital * 100)
        fig.add_trace(go.Scatter(
            x=returns_pct.index,
            y=returns_pct.values,
            mode='lines',
            name='Return %',
            line=dict(color='#ff7f0e', width=2, dash='dot'),
            yaxis='y2',
            hovertemplate='<b>Date</b>: %{x}<br><b>Return</b>: %{y:.2f}%<extra></extra>'
        ))
    
    # Layout
    layout_config = dict(
        title=dict(text=title, x=0.5, xanchor='center'),
        xaxis=dict(title='Date', showgrid=True, gridcolor='lightgray'),
        yaxis=dict(title='PnL', showgrid=True, gridcolor='lightgray'),
        hovermode='x unified',
        template='plotly_white',
        height=500
    )
    
    if capital is not None:
        layout_config['yaxis2'] = dict(
            title='Return (%)',
            overlaying='y',
            side='right',
            showgrid=False
        )
    
    fig.update_layout(**layout_config)
    
    return fig


def plot_drawdown(pnl: pd.Series, capital: float, title: str = "Drawdown Analysis") -> go.Figure:
    """
    Plot drawdown curve showing peak-to-trough declines.
    
    Parameters:
    -----------
    pnl : pd.Series
        Daily PnL series
    capital : float
        Initial capital
    title : str
        Chart title
        
    Returns:
    --------
    go.Figure : Plotly figure object
    """
    returns = pnl.fillna(0) / capital
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative / running_max - 1) * 100
    
    fig = go.Figure()
    
    # Drawdown area
    fig.add_trace(go.Scatter(
        x=drawdown.index,
        y=drawdown.values,
        mode='lines',
        name='Drawdown',
        fill='tozeroy',
        fillcolor='rgba(255, 0, 0, 0.2)',
        line=dict(color='red', width=2),
        hovertemplate='<b>Date</b>: %{x}<br><b>Drawdown</b>: %{y:.2f}%<extra></extra>'
    ))
    
    # Mark maximum drawdown
    max_dd_idx = drawdown.idxmin()
    max_dd_val = drawdown.min()
    fig.add_trace(go.Scatter(
        x=[max_dd_idx],
        y=[max_dd_val],
        mode='markers',
        name='Max Drawdown',
        marker=dict(color='darkred', size=10, symbol='x'),
        hovertemplate=f'<b>Max Drawdown</b><br>Date: {max_dd_idx}<br>Value: {max_dd_val:.2f}%<extra></extra>'
    ))
    
    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor='center'),
        xaxis=dict(title='Date', showgrid=True, gridcolor='lightgray'),
        yaxis=dict(title='Drawdown (%)', showgrid=True, gridcolor='lightgray'),
        hovermode='x unified',
        template='plotly_white',
        height=400
    )
    
    return fig


def plot_attribution(attribution: pd.DataFrame, title: str = "Attribution Analysis") -> go.Figure:
    """
    Plot stacked attribution components over time.
    
    Parameters:
    -----------
    attribution : pd.DataFrame
        Attribution dataframe with Carry, Roll-down, Rate Change, Residual columns
    title : str
        Chart title
        
    Returns:
    --------
    go.Figure : Plotly figure object
    """
    components = ['Carry', 'Roll-down', 'Rate Change', 'Residual']
    colors = ['#2ecc71', '#3498db', '#e74c3c', '#95a5a6']
    
    fig = go.Figure()
    
    for component, color in zip(components, colors):
        if component in attribution.columns:
            fig.add_trace(go.Bar(
                x=attribution.index,
                y=attribution[component],
                name=component,
                marker_color=color,
                hovertemplate='<b>%{fullData.name}</b><br>Date: %{x}<br>Value: %{y:.2f}<extra></extra>'
            ))
    
    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor='center'),
        xaxis=dict(title='Date', showgrid=True, gridcolor='lightgray'),
        yaxis=dict(title='Attribution', showgrid=True, gridcolor='lightgray'),
        barmode='relative',
        hovermode='x unified',
        template='plotly_white',
        height=500,
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1)
    )
    
    return fig


def plot_metrics_table(metrics: pd.Series, title: str = "Performance Metrics") -> go.Figure:
    """
    Display metrics as an interactive table.
    
    Parameters:
    -----------
    metrics : pd.Series
        Performance metrics
    title : str
        Table title
        
    Returns:
    --------
    go.Figure : Plotly figure object
    """
    # Format metrics
    formatted_values = []
    for idx, val in metrics.items():
        if idx in ['Total Return', 'Annualized Return', 'Annualized Volatility', 'Max Drawdown']:
            formatted_values.append(f"{val*100:.2f}%")
        elif idx == 'Sharpe Ratio':
            formatted_values.append(f"{val:.3f}")
        elif idx == 'Win Rate':
            formatted_values.append(f"{val*100:.1f}%")
        elif idx == 'Total Days':
            formatted_values.append(f"{int(val)}")
        else:
            formatted_values.append(f"{val:.4f}")
    
    fig = go.Figure(data=[go.Table(
        header=dict(
            values=['<b>Metric</b>', '<b>Value</b>'],
            fill_color='#3498db',
            font=dict(color='white', size=14),
            align='left',
            height=40
        ),
        cells=dict(
            values=[metrics.index.tolist(), formatted_values],
            fill_color=[['#ecf0f1', 'white'] * len(metrics)],
            align='left',
            font=dict(size=12),
            height=35
        )
    )])
    
    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor='center'),
        height=400,
        margin=dict(l=20, r=20, t=60, b=20)
    )
    
    return fig


def plot_backtest_dashboard(pnl: pd.Series, attribution: Optional[pd.DataFrame], 
                            metrics: pd.Series, capital: float,
                            title: str = "Backtest Dashboard",
                            comparison_data: Optional[Dict] = None,
                            rate_data: Optional[Dict] = None) -> go.Figure:
    """
    Create comprehensive dashboard with all backtest visualizations.
    
    Parameters:
    -----------
    pnl : pd.Series
        Daily PnL series
    attribution : pd.DataFrame, optional
        Attribution analysis
    metrics : pd.Series
        Performance metrics
    capital : float
        Initial capital
    title : str
        Dashboard title
    comparison_data : dict, optional
        Dict with 'portfolio', 'bond', 'irs' results for comparison
    rate_data : dict, optional
        Dict with 'bond_yields' and 'irs_quotes' for rate time series
        
    Returns:
    --------
    go.Figure : Plotly figure object with subplots
    """
    # Calculate number of rows needed
    #　Full dashboard: Rates, PnL, DD, Attribution, Comparison, Stats
    fig = make_subplots(
        rows=6, cols=2,
        row_heights=[0.13, 0.15, 0.12, 0.17, 0.18, 0.13],
        column_widths=[0.7, 0.3],
        subplot_titles=('Rate/YTM Time Series',
                      'Accumulated PnL', 'Performance Metrics',
                      'Drawdown Analysis', '',
                      'Attribution Analysis', 'Attribution Summary',
                      'Portfolio vs Components', 'Metrics Comparison',
                      'Daily Statistics', ''),
        specs=[
            [{"type": "scatter", "colspan": 2}, None],  # Rates at top
            [{"type": "scatter"}, {"type": "table", "rowspan": 2}],  # PnL + Metrics
            [{"type": "scatter"}, None],  # DD
            [{"type": "bar"}, {"type": "table"}],  # Attribution
            [{"type": "scatter"}, {"type": "bar"}],  # Comparison
            [{"type": "table", "colspan": 2}, None]  # Stats
        ],
        vertical_spacing=0.06,
        horizontal_spacing=0.1
    )
    
    # Determine row positions based on whether rates are shown
    pnl_row = 2
    dd_row = 3
    attr_row = 4
    comp_row = 5
    stats_row = 6
    
    # 0. Rate Time Series (if available) - at top
    # if has_rates:
    colors_rate = ['#2ecc71', '#e74c3c', '#9b59b6', '#f39c12']
    color_idx = 0

    for key, rate_info in rate_data.items():
        rate_series = rate_info.get('data')
        rate_name = rate_info.get('name', key)

        if rate_series is not None:
            fig.add_trace(go.Scatter(
                x=rate_series.index,
                y=rate_series.values,
                mode='lines',
                name=rate_name,
                line=dict(color=colors_rate[color_idx % len(colors_rate)], width=2),
                hovertemplate=f'<b>{rate_name}</b><br>' + '%{y:.3f}%<extra></extra>'
            ), row=1, col=1)
            color_idx += 1

    # 1. Accumulated PnL
    cumulative_pnl = pnl.cumsum()
    returns_pct = (cumulative_pnl / capital * 100)
    
    fig.add_trace(go.Scatter(
        x=cumulative_pnl.index,
        y=cumulative_pnl.values,
        mode='lines',
        name='%',
        line=dict(color='#1f77b4', width=2),
        hovertemplate='%: %{y:.2f}<extra></extra>'
    ), row=pnl_row, col=1)
    
    fig.add_trace(go.Scatter(
        x=returns_pct.index,
        y=returns_pct.values,
        mode='lines',
        name='Return %',
        line=dict(color='#ff7f0e', width=2, dash='dot'),
        yaxis='y2',
        hovertemplate='Return: %{y:.2f}%<extra></extra>'
    ), row=pnl_row, col=1)
    
    # 2. Drawdown
    returns = pnl.fillna(0) / capital
    cumulative = (1 + returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative / running_max - 1) * 100
    
    fig.add_trace(go.Scatter(
        x=drawdown.index,
        y=drawdown.values,
        mode='lines',
        name='Drawdown',
        fill='tozeroy',
        fillcolor='rgba(255, 0, 0, 0.2)',
        line=dict(color='red', width=2),
        showlegend=False,
        hovertemplate='DD: %{y:.2f}%<extra></extra>'
    ), row=dd_row, col=1)
    
    # 3. Performance Metrics Table
    formatted_values = []
    for idx, val in metrics.items():
        if idx in ['Total Return', 'Annualized Return', 'Annualized Volatility', 'Max Drawdown']:
            formatted_values.append(f"{val*100:.2f}%")
        elif idx == 'Sharpe Ratio':
            formatted_values.append(f"{val:.3f}")
        elif idx == 'Win Rate':
            formatted_values.append(f"{val*100:.1f}%")
        elif idx == 'Total Days':
            formatted_values.append(f"{int(val)}")
        else:
            formatted_values.append(f"{val:.4f}")
    
    fig.add_trace(go.Table(
        header=dict(
            values=['<b>Metric</b>', '<b>Value</b>'],
            fill_color='#3498db',
            font=dict(color='white', size=12),
            align='left'
        ),
        cells=dict(
            values=[metrics.index.tolist(), formatted_values],
            fill_color=[['#ecf0f1', 'white'] * len(metrics)],
            align='left',
            font=dict(size=11)
        )
    ), row=pnl_row, col=2)
    
    # 4. Attribution (if available)
    # if has_attribution:
    components = ['Carry', 'Roll-down', 'Rate Change', 'Residual']
    colors = ['#2ecc71', '#3498db', '#e74c3c', '#95a5a6']

    for component, color in zip(components, colors):
        if component in attribution.columns:
            fig.add_trace(go.Bar(
                x=attribution.index,
                y=attribution[component],
                name=component,
                marker_color=color,
                hovertemplate=f'{component}: ' + '%{y:.2f}<extra></extra>'
            ), row=attr_row, col=1)
        
    # Attribution Summary Table
    attr_sum = attribution[components].sum()
    attr_pct = (attr_sum / attr_sum.sum() * 100)

    fig.add_trace(go.Table(
        header=dict(
            values=['<b>Component</b>', '<b>Total</b>', '<b>%</b>'],
            fill_color='#e74c3c',
            font=dict(color='white', size=11),
            align='left'
        ),
        cells=dict(
            values=[
                components,
                [f"{v:.2f}" for v in attr_sum.values],
                [f"{v:.1f}%" for v in attr_pct.values]
            ],
            fill_color=[['#ecf0f1', 'white'] * len(components)],
            align='left',
            font=dict(size=10)
        )
    ), row=attr_row, col=2)

    # if has_comparison:
    colors_comp = ['#1f77b4', '#2ecc71', '#e74c3c']
    color_idx = 0

    # Plot accumulated PnL comparison
    for name, results in comparison_data.items():
        comp_pnl = results.get('pnl')
        if comp_pnl is not None:
            cumulative = comp_pnl.cumsum()
            fig.add_trace(go.Scatter(
                x=cumulative.index,
                y=cumulative.values,
                mode='lines',
                name=name.capitalize(),
                line=dict(color=colors_comp[color_idx % len(colors_comp)], width=2),
                hovertemplate=f'<b>{name.capitalize()}</b><br>PnL: ' + '%{y:.2f}<extra></extra>'
            ), row=comp_row, col=1)
            color_idx += 1

    # Metrics comparison bar chart
    metrics_to_compare = ['Total Return', 'Annualized Return', 'Sharpe Ratio', 'Max Drawdown']
    for metric in metrics_to_compare:
        values = []
        names = []
        for name, results in comparison_data.items():
            if 'metrics' in results and metric in results['metrics']:
                val = results['metrics'][metric]
                if metric in ['Total Return', 'Annualized Return', 'Max Drawdown']:
                    val *= 100
                values.append(val)
                names.append(name.capitalize())

        if values:
            fig.add_trace(go.Bar(
                x=names,
                y=values,
                name=metric,
                hovertemplate=f'<b>{metric}</b><br>' + '%{y:.2f}<extra></extra>'
            ), row=comp_row, col=2)
        
            # Daily statistics at bottom
            daily_stats = pd.DataFrame({
                'Mean': pnl.mean(),
                'Std': pnl.std(),
                'Min': pnl.min(),
                'Max': pnl.max(),
                'Positive Days': (pnl > 0).sum(),
                'Negative Days': (pnl < 0).sum()
            }, index=[0])

            fig.add_trace(go.Table(
                header=dict(
                    values=['<b>Statistic</b>', '<b>Value</b>'],
                    fill_color='#95a5a6',
                    font=dict(color='white', size=12),
                    align='left'
                ),
                cells=dict(
                    values=[
                        ['Mean Daily PnL', 'Std Dev', 'Min Daily', 'Max Daily', 'Positive Days', 'Negative Days'],
                        [f"{daily_stats['Mean'][0]:.2f}",
                         f"{daily_stats['Std'][0]:.2f}",
                         f"{daily_stats['Min'][0]:.2f}",
                         f"{daily_stats['Max'][0]:.2f}",
                         f"{int(daily_stats['Positive Days'][0])}",
                         f"{int(daily_stats['Negative Days'][0])}"]
                    ],
                    fill_color=[['#ecf0f1', 'white'] * 6],
                    align='left',
                    font=dict(size=11)
                )
            ), row=stats_row, col=1)
        else:
            # Simple dashboard without attribution - just daily statistics at bottom
            daily_stats = pd.DataFrame({
                'Mean': pnl.mean(),
                'Std': pnl.std(),
                'Min': pnl.min(),
                'Max': pnl.max(),
                'Positive Days': (pnl > 0).sum(),
                'Negative Days': (pnl < 0).sum()
            }, index=[0])

            fig.add_trace(go.Table(
                header=dict(
                    values=['<b>Statistic</b>', '<b>Value</b>'],
                    fill_color='#95a5a6',
                    font=dict(color='white', size=12),
                    align='left'
                ),
                cells=dict(
                    values=[
                        ['Mean Daily PnL', 'Std Dev', 'Min Daily', 'Max Daily', 'Positive Days', 'Negative Days'],
                        [f"{daily_stats['Mean'][0]:.2f}",
                         f"{daily_stats['Std'][0]:.2f}",
                         f"{daily_stats['Min'][0]:.2f}",
                         f"{daily_stats['Max'][0]:.2f}",
                         f"{int(daily_stats['Positive Days'][0])}",
                         f"{int(daily_stats['Negative Days'][0])}"]
                    ],
                    fill_color=[['#ecf0f1', 'white'] * 6],
                    align='left',
                    font=dict(size=11)
                )
            ), row=3, col=1)
    
    # Update layout
    fig.update_xaxes(showgrid=True, gridcolor='lightgray')
    fig.update_yaxes(showgrid=True, gridcolor='lightgray')
    
    # Determine height based on panels
    # if has_attribution and has_comparison and has_rates:
    height = 1800
    # elif has_attribution and has_comparison:
    #     height = 1600
    # elif has_attribution:
    #     height = 1400
    # else:
    #     height = 1000
    
    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor='center', font=dict(size=20)),
        height=height,
        showlegend=True,
        hovermode='x unified',
        template='plotly_white',
        barmode='relative'
    )
    
    # Update specific axes labels
    fig.update_yaxes(title_text="%", row=1, col=1)
    # fig.update_yaxes(title_text="Return (%)", secondary_y=True, row=1, col=1)
    fig.update_yaxes(title_text="Drawdown (%)", row=3, col=1)
    
    # if has_attribution:
    fig.update_yaxes(title_text="Attribution", row=4, col=1)
        
    # if has_comparison:
    comparison_row = 5
    fig.update_yaxes(title_text="Accumulated PnL", row=comparison_row, col=1)
    fig.update_xaxes(title_text="Date", row=comparison_row, col=1)
    fig.update_yaxes(title_text="Value", row=comparison_row, col=2)
        
    # # if has_rates:
    # rates_row = 5
    # fig.update_yaxes(title_text="Rate (%)", row=rates_row, col=1)
    # fig.update_xaxes(title_text="Date", row=rates_row, col=1)

    return fig


def plot_rate_timeseries(bond_yields: Optional[pd.Series] = None, 
                         irs_quotes: Optional[pd.Series] = None,
                         bond_name: str = "Bond", 
                         irs_name: str = "IRS",
                         title: str = "Rate Time Series") -> go.Figure:
    """
    Plot time series of bond YTM and IRS rates.
    
    Parameters:
    -----------
    bond_yields : pd.Series, optional
        Bond YTM time series
    irs_quotes : pd.Series, optional
        IRS quote time series
    bond_name : str
        Label for bond
    irs_name : str
        Label for IRS
    title : str
        Chart title
        
    Returns:
    --------
    go.Figure : Plotly figure object
    """
    fig = go.Figure()
    
    if bond_yields is not None:
        fig.add_trace(go.Scatter(
            x=bond_yields.index,
            y=bond_yields.values * 100,  # Convert to percentage
            mode='lines',
            name=f'{bond_name} YTM',
            line=dict(color='#2ecc71', width=2),
            hovertemplate=f'<b>{bond_name} YTM</b><br>Date: ' + '%{x}<br>YTM: %{y:.3f}%<extra></extra>'
        ))
    
    if irs_quotes is not None:
        fig.add_trace(go.Scatter(
            x=irs_quotes.index,
            y=irs_quotes.values * 100,  # Convert to percentage
            mode='lines',
            name=f'{irs_name} Rate',
            line=dict(color='#e74c3c', width=2),
            hovertemplate=f'<b>{irs_name} Rate</b><br>Date: ' + '%{x}<br>Rate: %{y:.3f}%<extra></extra>'
        ))
    
    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor='center'),
        xaxis=dict(title='Date', showgrid=True, gridcolor='lightgray'),
        yaxis=dict(title='Rate (%)', showgrid=True, gridcolor='lightgray'),
        hovermode='x unified',
        template='plotly_white',
        height=400,
        showlegend=True
    )
    
    return fig


def plot_portfolio_comparison(results_dict: Dict[str, Dict], 
                              title: str = "Portfolio vs Components") -> go.Figure:
    """
    Compare portfolio performance against individual components.
    
    Parameters:
    -----------
    results_dict : dict
        Dictionary with keys like 'portfolio', 'bond', 'irs' containing results
    title : str
        Chart title
        
    Returns:
    --------
    go.Figure : Plotly figure object
    """
    fig = make_subplots(
        rows=2, cols=1,
        row_heights=[0.6, 0.4],
        subplot_titles=('Accumulated PnL Comparison', 'Metrics Comparison'),
        specs=[[{"type": "scatter"}], [{"type": "bar"}]],
        vertical_spacing=0.15
    )
    
    colors = ['#1f77b4', '#2ecc71', '#e74c3c', '#f39c12', '#9b59b6']
    color_idx = 0
    
    # Plot accumulated PnL for each component
    for name, results in results_dict.items():
        pnl = results.get('pnl')
        if pnl is not None:
            cumulative = pnl.cumsum()
            fig.add_trace(go.Scatter(
                x=cumulative.index,
                y=cumulative.values,
                mode='lines',
                name=name.capitalize(),
                line=dict(color=colors[color_idx % len(colors)], width=2),
                hovertemplate=f'<b>{name.capitalize()}</b><br>PnL: ' + '%{y:.2f}<extra></extra>'
            ), row=1, col=1)
            color_idx += 1
    
    # Compare key metrics
    metrics_to_compare = ['Total Return', 'Annualized Return', 'Sharpe Ratio', 'Max Drawdown']
    
    for metric in metrics_to_compare:
        values = []
        names = []
        for name, results in results_dict.items():
            if 'metrics' in results and metric in results['metrics']:
                val = results['metrics'][metric]
                if metric in ['Total Return', 'Annualized Return', 'Max Drawdown']:
                    val *= 100  # Convert to percentage
                values.append(val)
                names.append(name.capitalize())
        
        if values:
            fig.add_trace(go.Bar(
                x=names,
                y=values,
                name=metric,
                hovertemplate=f'<b>{metric}</b><br>' + '%{y:.2f}<extra></extra>'
            ), row=2, col=1)
    
    fig.update_layout(
        title=dict(text=title, x=0.5, xanchor='center', font=dict(size=18)),
        height=900,
        showlegend=True,
        hovermode='closest',
        template='plotly_white',
        barmode='group'
    )
    
    fig.update_xaxes(title_text="Date", row=1, col=1, showgrid=True, gridcolor='lightgray')
    fig.update_yaxes(title_text="Accumulated PnL", row=1, col=1, showgrid=True, gridcolor='lightgray')
    fig.update_xaxes(title_text="Component", row=2, col=1)
    fig.update_yaxes(title_text="Value", row=2, col=1, showgrid=True, gridcolor='lightgray')
    
    return fig
