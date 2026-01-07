# -*- coding: utf-8 -*-
"""
Plot Generator Module for Pair Analysis

This module handles the core Plotly figure generation functionality.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from .stats import RegressionResults


class PlotGenerator:
    """Core class for generating Plotly figures"""
    
    def __init__(self):
        self.plot_cache = {}  # Cache for performance
        
    def create_base_figure(self, spread_df: pd.DataFrame, regression_result: RegressionResults,
                          leg1: str, leg2: str, pair_name: str) -> go.Figure:
        """Create the base Plotly figure for interactive plots"""
        # Normalize types to avoid serialization quirks
        dates = pd.to_datetime(spread_df["date"]).dt.strftime('%Y-%m-%d').tolist()
        spreads = pd.to_numeric(spread_df["spread"], errors='coerce').astype(float).tolist()
        # Ensure numpy arrays become plain float lists
        fitted = [float(v) for v in regression_result.fitted]
        
        # Create a perfectly straight trend line using regression parameters
        # This ensures the line is truly straight even with data gaps
        n_points = len(dates)
        x_values = np.arange(n_points)
        straight_trend = regression_result.intercept + regression_result.slope * x_values
        straight_trend = [float(v) for v in straight_trend]
        
        ub, lb = regression_result.get_confidence_bands()
        upper_band = [float(v) for v in ub]
        lower_band = [float(v) for v in lb]

        # Create Plotly figure
        fig = go.Figure()
        
        # Add confidence bands first (so they appear behind other traces)
        # Use lower band first, then upper band with fill to avoid order issues after JSON serialization
        fig.add_trace(go.Scatter(
            x=dates,
            y=lower_band,
            mode='lines',
            name='-1σ Band',
            line=dict(color='rgba(255,255,0,0.6)', width=2, dash='dash'),  # Yellow lines for better visibility on dark blue
            showlegend=False,
            hovertemplate='<b>Date:</b> %{x}<br><b>-1σ Band:</b> %{y:.2f} bp<extra></extra>'
        ))

        fig.add_trace(go.Scatter(
            x=dates,
            y=upper_band,
            mode='lines',
            name='±1σ Confidence',
            line=dict(color='rgba(255,255,0,0.6)', width=2, dash='dash'),  # Yellow lines for better visibility on dark blue
            fill='tonexty',  # Fill between upper and the previous lower band trace
            fillcolor='rgba(255,255,0,0.1)',  # Light yellow fill
            showlegend=True,
            hovertemplate='<b>Date:</b> %{x}<br><b>+1σ Band:</b> %{y:.2f} bp<extra></extra>'
        ))
        
        # Add scatter plot for actual spreads
        fig.add_trace(go.Scatter(
            x=dates, 
            y=spreads,
            mode='markers',
            name='Spread',
            marker=dict(
                size=8,
                opacity=0.8,
                color='#00cc96'  # Bright teal/cyan - good contrast on dark blue
            ),
            hovertemplate=f'<b>Date:</b> %{{x}}<br><b>Spread:</b> %{{y:.2f}} bp<br><b>Pair:</b> {pair_name}<extra></extra>'
        ))
        
        # Add line plot for regression trend - using straight line
        fig.add_trace(go.Scatter(
            x=dates, 
            y=straight_trend,  # Use straight trend instead of fitted
            mode='lines',
            name='Trend (OLS)',
            line=dict(
                color='#ff6692',  # Bright pink/salmon - good contrast on dark blue
                width=3
            ),
            hovertemplate='<b>Date:</b> %{x}<br><b>Trend:</b> %{y:.2f} bp<extra></extra>'
        ))
        
        return fig
    
    def apply_interactive_layout(self, fig: go.Figure, leg1: str, leg2: str, 
                               regression_result: RegressionResults) -> None:
        """Apply layout styling for interactive plots with dark blue theme"""
        # Dark blue theme layout for interactive plots
        fig.update_layout(
            # Remove title for cleaner subplot appearance
            xaxis=dict(
                title='Date',
                title_font=dict(color='white'),  # White axis title
                showgrid=True,
                gridwidth=1,
                gridcolor='white',  # White grid lines
                showline=True,
                linewidth=2,
                linecolor='white',  # White axis line
                tickfont=dict(color='white'),  # White tick labels
                # Remove navigation subplot/range slider as requested
                rangeslider=dict(visible=False)
            ),
            yaxis=dict(
                title='Spread (bp)',  # Updated to show basis points
                title_font=dict(color='white'),  # White axis title
                showgrid=True,
                gridwidth=1,
                gridcolor='white',  # White grid lines
                showline=True,
                linewidth=2,
                linecolor='white',  # White axis line
                tickfont=dict(color='white')  # White tick labels
            ),
            plot_bgcolor='#082255',  # Dark blue background (matching app theme)
            paper_bgcolor='#082255',  # Dark blue background (matching app theme)
            font=dict(color='white'),  # White font for all text
            autosize=True,  # Enable responsive sizing
            margin=dict(l=60, r=60, t=40, b=60),  # Reduced top margin since no title
            legend=dict(
                x=0.02,
                y=0.98,
                bgcolor='rgba(8,34,85,0.9)',  # Dark blue legend background
                bordercolor='white',  # White legend border
                borderwidth=2,
                font=dict(color='white')  # White legend text
            ),
            hovermode='x unified'
        )
        
        # Statistical Summary and annotations removed for cleaner subplot appearance