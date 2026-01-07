#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Factor Metrics - Performance metrics and analysis functions

This module contains functions for calculating factor performance metrics including
IC, IR, and statistical significance tests.
"""

import pandas as pd
import numpy as np
from typing import Dict, List
import warnings
warnings.filterwarnings('ignore')

# Import statistical modules for robust correlation analysis
from scipy.stats import spearmanr, pearsonr, kendalltau


def calculate_ir(factor: pd.Series, returns: pd.Series, window: int = 20) -> float:
    """
    Calculate Information Ratio correctly: IR = IC / std(IC over time)
    
    Args:
        factor: Factor values
        returns: Return values  
        window: Rolling window size for IC calculation
        
    Returns:
        Information Ratio
    """
    if len(factor) < window + 5:
        return np.nan
    
    # Calculate rolling IC values
    ic_series = []
    for i in range(len(factor) - window + 1):
        window_factor = factor.iloc[i:i+window]
        window_returns = returns.iloc[i:i+window]
        
        if len(window_factor) >= 10 and window_factor.std() > 0:
            ic = window_factor.corr(window_returns)
            if not np.isnan(ic):
                ic_series.append(ic)
    
    if len(ic_series) < 5:
        return np.nan
    
    ic_mean = np.mean(ic_series)
    ic_std = np.std(ic_series)
    
    if ic_std == 0:
        return np.nan
    
    return ic_mean / ic_std


def calculate_metrics(factors: pd.DataFrame, returns: pd.Series) -> pd.DataFrame:
    """
    Calculate factor metrics including IC, IC_abs, and IR
    
    Args:
        factors: Factor data DataFrame (at time t)
        returns: Return series (from t to t+1)
        
    Returns:
        DataFrame with metrics for each factor
          Note: IC is calculated using factor at time t vs future returns (t+1 to t+2)
    to avoid look-ahead bias
    """
    if factors.empty or returns.empty:
        return pd.DataFrame()
    
    # Calculate future returns for proper IC calculation (avoid look-ahead bias)
    future_returns = returns.shift(-1)  # Returns from t+1 to t+2
    
    # Remove the last NaN created by shift(-1)
    future_returns = future_returns.dropna()
    
    # Align data - use intersection of indices after removing NaN
    common_idx = factors.index.intersection(future_returns.index)
    if len(common_idx) < 10:
        return pd.DataFrame()
    
    factors_aligned = factors.loc[common_idx]
    future_returns_aligned = future_returns.loc[common_idx]
    
    metrics = []
    
    for factor_name in factors_aligned.columns:
        factor_data = factors_aligned[factor_name].dropna()
        
        if len(factor_data) < 10:
            continue
        
        # Align factor and future returns
        common_dates = factor_data.index.intersection(future_returns_aligned.index)
        if len(common_dates) < 10:
            continue
        
        factor_aligned = factor_data.loc[common_dates]
        future_returns_common = future_returns_aligned.loc[common_dates]
        
        # Enhanced IC calculation with statistical tests
        # Both spearmanr and pearsonr expect:
        # - factor_aligned: factor LEVEL data at time t  
        # - future_returns_common: RETURN data from t to t+1
        # This measures how current factor levels predict future returns
        
        ic_spear, p_spear = spearmanr(factor_aligned, future_returns_common)
        ic_pear, p_pear = pearsonr(factor_aligned, future_returns_common)
        
        # Use Spearman as primary (more robust to outliers and monotonic relationships)
        ic = ic_spear if not np.isnan(ic_spear) else 0
        p_value = p_spear if not np.isnan(p_spear) else 1
        ic_abs = abs(ic)
        
        # Nonlinearity indicator: large difference suggests nonlinear relationship
        rank_vs_linear_diff = abs(ic_spear - ic_pear) if not (np.isnan(ic_spear) or np.isnan(ic_pear)) else 0
        is_significant = p_value < 0.05
        
        # Calculate IR (Information Ratio) - correct method: IC / std(IC over time)
        ir = calculate_ir(factor_aligned, future_returns_common)
        if np.isnan(ir):
            ir = 0
        
        # Build metrics dictionary with enhanced IC information
        metric_dict = {
            'factor': factor_name,
            'IC': ic,  # Primary IC (Spearman rank correlation)
            'IC_abs': ic_abs,
            'IR': ir,
            'count': len(common_dates),
            'p_value': p_value,  # Statistical significance
            'is_significant': is_significant,  # p < 0.05
            'rank_vs_linear_diff': rank_vs_linear_diff,  # Nonlinearity indicator
            'IC_spearman': ic_spear if not np.isnan(ic_spear) else 0,
            'IC_pearson': ic_pear if not np.isnan(ic_pear) else 0,
            'p_spearman': p_spear if not np.isnan(p_spear) else 1,
            'p_pearson': p_pear if not np.isnan(p_pear) else 1,
        }
        
        metrics.append(metric_dict)
    
    if not metrics:
        return pd.DataFrame()
    
    return pd.DataFrame(metrics).set_index('factor')


def calculate_all_factor_metrics(base_factors: pd.DataFrame, high_order_factors: pd.DataFrame, 
                                returns: pd.Series) -> pd.DataFrame:
    """
    Calculate all factor metrics by combining base and high-order factors
    
    Args:
        base_factors: Base factor data
        high_order_factors: High-order factor data
        returns: Return series
    
    Returns:
        DataFrame with metrics for all factors
    """
    all_factors = pd.concat([base_factors, high_order_factors], axis=1)
    return calculate_metrics(all_factors, returns)


def quick_factor_summary(factors: pd.DataFrame, returns: pd.Series, 
                        top_n: int = 10) -> pd.DataFrame:
    """
    Get a quick summary of top factors by IC
    
    Args:
        factors: Factor data
        returns: Return series
        top_n: Number of top factors to show
    
    Returns:
        DataFrame with top factors and their metrics
    """
    try:
        metrics = calculate_metrics(factors, returns)
        if metrics.empty:
            return pd.DataFrame()
        
        # Sort by absolute IC and take top N
        top_factors = metrics.sort_values('IC_abs', ascending=False).head(top_n)
        
        # Create summary with essential info
        summary = top_factors[['IC', 'IC_abs', 'IR', 'is_significant', 'count']].copy()
        summary = summary.round(4)
        
        return summary
        
    except Exception as e:
        print(f"Failed to create factor summary: {e}")
        return pd.DataFrame()


def calculate_max_drawdown(cumulative_returns: pd.Series) -> float:
    """
    Calculate maximum drawdown of a cumulative return series
    
    Args:
        cumulative_returns: Series of cumulative returns
        
    Returns:
        Maximum drawdown value
    """
    if cumulative_returns.empty:
        return np.nan
    
    # Calculate running maximum
    peak = cumulative_returns.expanding().max()
    
    # Calculate drawdown
    drawdown = (cumulative_returns - peak) / peak
    
    # Return maximum drawdown (most negative value)
    return drawdown.min()
