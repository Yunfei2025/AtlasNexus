# -*- coding: utf-8 -*-
"""
Dashboard Utility Functions
Contains utility functions for data formatting and chart creation

@author: CMBC
Created: Oct 29, 2025
"""
from typing import Dict, Any, Union
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

def parse_date(date_str):
    """Parse date string in YYYYMMDD format to datetime.date"""
    return datetime.strptime(date_str, "%Y%m%d").date()


class TimeStringConverter:
    """Utility class for converting time strings to float values"""

    @staticmethod
    def parse_time_string(time_str: Union[str, float, int]) -> float:
        """
        Convert time string to float in years.

        Examples:
        '1M' -> 1/12 (1 month)
        '3M' -> 3/12 (3 months)
        '6M' -> 6/12 (6 months)
        '1Y' -> 1.0 (1 year)
        '2Y' -> 2.0 (2 years)
        '1.5Y' -> 1.5 (1.5 years)
        """
        if isinstance(time_str, (int, float)):
            return float(time_str)

        time_str = str(time_str).strip().upper()

        # Handle year format (Y)
        if time_str.endswith('Y'):
            year_part = time_str[:-1]
            try:
                return float(year_part)
            except ValueError:
                raise ValueError(f"Invalid year format: {time_str}")

        # Handle month format (M)
        elif time_str.endswith('M'):
            month_part = time_str[:-1]
            try:
                months = float(month_part)
                return months / 12.0  # Convert months to years
            except ValueError:
                raise ValueError(f"Invalid month format: {time_str}")

        # Handle day format (D)
        elif time_str.endswith('D'):
            day_part = time_str[:-1]
            try:
                days = float(day_part)
                return days / 365.0  # Convert days to years
            except ValueError:
                raise ValueError(f"Invalid day format: {time_str}")

        # Try to parse as pure number
        else:
            try:
                return float(time_str)
            except ValueError:
                raise ValueError(f"Cannot parse time string: {time_str}")


def format_results_to_dataframe(results: Dict[str, Any], option_type: str) -> pd.DataFrame:
    """
    Format results dictionary to pandas DataFrame for display
    
    Parameters:
    -----------
    results : dict
        Results from option pricing
    option_type : str
        'bond' or 'interest_rate'
    
    Returns:
    --------
    pd.DataFrame
        Formatted results
    """
    data = []
    
    # Basic Information
    data.append({'Parameter': 'Option Type', 
                'Value': results.get('option_type', 'N/A').upper()})
    data.append({'Parameter': 'Notional', 
                'Value': f"{results.get('notional', 0):,.0f}"})
    
    # Pricing
    data.append({'Parameter': 'Market Value', 
                'Value': f"{results.get('price', 0):,.2f}"})
    data.append({'Parameter': 'Price per 100', 
                'Value': f"{100*results.get('price', 0)/results.get('notional', 1):.4f}"})
    
    # Strike and Underlying
    strike = results.get('strike')
    if strike is not None and not np.isnan(strike):
        data.append({'Parameter': 'Strike Price', 
                    'Value': f"{strike:.4f}"})
    
    strike_yield = results.get('strike_yield')
    if strike_yield is not None:
        data.append({'Parameter': 'Strike Yield', 
                    'Value': f"{strike_yield*100:.4f}%"})
    
    underlying_price = results.get('underlying_price')
    if underlying_price is not None and not np.isnan(underlying_price):
        data.append({'Parameter': 'Current Price', 
                    'Value': f"{underlying_price:.4f}"})
    
    underlying_ytm = results.get('underlying_ytm')
    if underlying_ytm is not None:
        data.append({'Parameter': 'Current Yield', 
                    'Value': f"{underlying_ytm*100:.4f}%"})
    
    duration = results.get('duration')
    if duration is not None and not np.isnan(duration):
        data.append({'Parameter': 'Duration', 
                    'Value': f"{duration:.4f}"})
    
    # Greeks
    delta = results.get('delta')
    if delta is not None and not np.isnan(delta):
        data.append({'Parameter': 'Delta (Price)', 
                    'Value': f"{delta:,.4f}"})
    
    delta_yield = results.get('delta_yield')
    if delta_yield is not None and not np.isnan(delta_yield):
        data.append({'Parameter': 'Delta (Yield)', 
                    'Value': f"{delta_yield:,.4f}"})
    
    gamma = results.get('gamma')
    if gamma is not None and not np.isnan(gamma):
        data.append({'Parameter': 'Gamma', 
                    'Value': f"{gamma:,.2f}"})
    
    vega = results.get('vega')
    if vega is not None and not np.isnan(vega):
        data.append({'Parameter': 'Vega', 
                    'Value': f"{vega:,.2f}"})
    
    theta = results.get('theta')
    if theta is not None and not np.isnan(theta):
        data.append({'Parameter': 'Theta', 
                    'Value': f"{theta:,.2f}"})
    
    rho = results.get('rho')
    if rho is not None and not np.isnan(rho):
        data.append({'Parameter': 'Rho', 
                    'Value': f"{rho:,.2f}"})
    
    # Market Data
    time_to_expiry = results.get('time_to_expiry')
    if time_to_expiry is not None and not np.isnan(time_to_expiry):
        data.append({'Parameter': 'Time to Expiry', 
                    'Value': f"{time_to_expiry:.2f} months"})
    
    volatility = results.get('volatility')
    if volatility is not None and not np.isnan(volatility):
        data.append({'Parameter': 'Volatility', 
                    'Value': f"{volatility*100:.4f}%"})
    
    risk_free_rate = results.get('risk_free_rate')
    if risk_free_rate is not None and not np.isnan(risk_free_rate):
        data.append({'Parameter': 'Risk Free Rate', 
                    'Value': f"{risk_free_rate*100:.4f}%"})
    
    return pd.DataFrame(data)


def create_payoff_chart(strike: float, option_type: str, pricing_type: str, 
                       current_price: float, option_price: float, notional: float) -> go.Figure:
    """
    Create payoff diagram for the option
    
    Parameters:
    -----------
    strike : float
        Strike price or yield
    option_type : str
        'call' or 'put'
    pricing_type : str
        'bond' or 'interest_rate'
    current_price : float
        Current underlying price/yield
    option_price : float
        Option premium
    notional : float
        Notional amount
    
    Returns:
    --------
    go.Figure
        Plotly figure with payoff diagram
    """
    # Generate range of underlying prices around strike
    price_range = np.linspace(strike * 0.8, strike * 1.2, 100)
    
    # Calculate intrinsic values
    if option_type == 'call':
        intrinsic_values = np.maximum(price_range - strike, 0)
        payoff_values = intrinsic_values - option_price / notional
    else:  # put
        intrinsic_values = np.maximum(strike - price_range, 0)
        payoff_values = intrinsic_values - option_price / notional
    
    # Scale to notional
    intrinsic_scaled = intrinsic_values * notional
    payoff_scaled = payoff_values * notional
    
    # Create figure
    fig = go.Figure()
    
    # Add intrinsic value line
    fig.add_trace(go.Scatter(
        x=price_range,
        y=intrinsic_scaled,
        mode='lines',
        name='Intrinsic Value',
        line=dict(color='#3498db', width=2, dash='dash')
    ))
    
    # Add payoff line (intrinsic - premium)
    fig.add_trace(go.Scatter(
        x=price_range,
        y=payoff_scaled,
        mode='lines',
        name='Payoff (at Expiry)',
        line=dict(color='#e74c3c', width=3)
    ))
    
    # Add zero line
    fig.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.5)
    
    # Add strike line
    fig.add_vline(x=strike, line_dash="dot", line_color="green", opacity=0.5,
                 annotation_text=f"Strike: {strike:.4f}")
    
    # Add current price marker
    if current_price and not np.isnan(current_price):
        fig.add_vline(x=current_price, line_dash="dot", line_color="orange", opacity=0.5,
                     annotation_text=f"Current: {current_price:.4f}")
    
    # Update layout
    x_label = "Underlying Price" if pricing_type == 'bond' else "Underlying Yield"
    title = f"{option_type.upper()} Option Payoff Diagram"
    
    fig.update_layout(
        title=title,
        xaxis_title=x_label,
        yaxis_title="Payoff (CNY)",
        template="plotly_white",
        hovermode='x unified',
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01
        ),
        height=400
    )
    
    return fig


def create_empty_chart(message: str = "Click Calculate to generate payoff diagram") -> go.Figure:
    """
    Create an empty placeholder chart
    
    Parameters:
    -----------
    message : str
        Message to display on empty chart
    
    Returns:
    --------
    go.Figure
        Empty plotly figure
    """
    fig = go.Figure()
    fig.update_layout(
        title=message,
        xaxis_title="Underlying Price",
        yaxis_title="Payoff",
        template="plotly_white"
    )
    return fig
