#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Data Processing Utilities for Factor Analysis

Handles data preprocessing, splitting, and cleaning operations.
"""

import pandas as pd
import numpy as np
import os
import pickle as _pickle
from datetime import datetime
from dateutil.relativedelta import relativedelta
from typing import Tuple, Dict
from settings.paths import DIR_DATA

from ..config import config_manager

def ensure_returns_column(data: pd.DataFrame, return_method: str = 'pct_change') -> pd.DataFrame:
    """
    Ensure the data has a Returns column using specified method.
    
    Args:
        data: Input DataFrame with price data
        return_method: Method for return calculation ('pct_change', 'diff', 'log_returns')
        
    Returns:
        DataFrame with Returns column
    """
    if 'Returns' not in data.columns:
        if 'Close' in data.columns:
            if return_method == 'pct_change':
                data['Returns'] = data['Close'].pct_change()
            elif return_method == 'diff':
                data['Returns'] = data['Close'].diff()
            elif return_method == 'log_returns':
                data['Returns'] = np.log(data['Close'] / data['Close'].shift(1))
            else:
                # Default fallback
                data['Returns'] = data['Close'].pct_change()
        else:
            raise ValueError("No returns or close price data found")
    
    return data.dropna(subset=['Returns'])


def split_data_by_periods(data: pd.DataFrame, train_end: datetime, 
                         test_start: datetime, test_end: datetime,
                         lookback_months: int = 12) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split data into training and testing periods.
    
    Args:
        data: Input DataFrame
        train_end: End date for training period
        test_start: Start date for testing period  
        test_end: End date for testing period
        lookback_months: Training period length in months
        
    Returns:
        Tuple of (train_data, test_data)
    """
    import datetime as dt
    
    # Convert datetime objects to date for comparison with index
    train_end_date = train_end.date() if isinstance(train_end, dt.datetime) else train_end
    test_start_date = test_start.date() if isinstance(test_start, dt.datetime) else test_start
    test_end_date = test_end.date() if isinstance(test_end, dt.datetime) else test_end
    
    train_start_date = train_end_date - relativedelta(months=lookback_months)
    
    train_mask = (data.index >= train_start_date) & (data.index <= train_end_date)
    test_mask = (data.index >= test_start_date) & (data.index <= test_end_date)
    
    return data.loc[train_mask], data.loc[test_mask]



def align_factors_with_returns(factors: pd.DataFrame, returns: pd.Series) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Align factor data with return data on common dates.
    
    Args:
        factors: Factor DataFrame
        returns: Returns Series
        
    Returns:
        Tuple of (aligned_factors, aligned_returns)
    """
    common_dates = factors.index.intersection(returns.index)
    if len(common_dates) == 0:
        print("⚠️ No common dates between factors and returns")
        return pd.DataFrame(), pd.Series()
    
    return factors.loc[common_dates], returns.loc[common_dates]


def get_train_returns(train_data: pd.DataFrame, train_factors: pd.DataFrame) -> pd.Series:
    """
    Get training returns that align with training factors.
    
    Args:
        train_data: Training data with Returns column
        train_factors: Training factor data
        
    Returns:
        Aligned training returns
    """
    if train_data is None or train_data.empty:
        print("⚠️ No training data available")
        return pd.Series()
    
    if 'Returns' not in train_data.columns:
        print("⚠️ No Returns column in training data")
        return pd.Series()
    
    train_returns = train_data['Returns']
    
    # Align with factor dates
    common_dates = train_factors.index.intersection(train_returns.index)
    if len(common_dates) > 0:
        return train_returns.loc[common_dates]
    else:
        print("⚠️ No common dates between training factors and returns")
        return pd.Series()


def validate_data_quality(data: pd.DataFrame, min_periods: int = 100) -> bool:
    """
    Validate data quality for analysis.
    
    Args:
        data: Input DataFrame
        min_periods: Minimum required periods
        
    Returns:
        True if data quality is acceptable
    """
    if data.empty:
        print("❌ Data is empty")
        return False
    
    if len(data) < min_periods:
        print(f"❌ Insufficient data: {len(data)} < {min_periods} periods")
        return False
    
    if data.isnull().all().any():
        print("❌ Contains columns with all NaN values")
        return False
    
    return True


def prepare_factor_data(data: pd.DataFrame, return_method: str = 'pct_change',
                       nan_threshold: float = 0.5) -> pd.DataFrame:
    """
    Complete data preparation pipeline for factor analysis.
    
    Args:
        data: Raw price data
        return_method: Return calculation method
        nan_threshold: NaN threshold for factor cleaning
        
    Returns:
        Prepared data with returns and cleaned structure
    """
    try:
        # Ensure returns column
        data = ensure_returns_column(data, return_method)
        
        # Validate data quality
        if not validate_data_quality(data):
            return pd.DataFrame()
        
        print(f"✅ Prepared {len(data)} data points with {len(data.columns)} columns")
        return data
        
    except Exception as e:
        print(f"❌ Data preparation failed: {e}")
        return pd.DataFrame()


def validate_factor_data(factors: pd.DataFrame, returns: pd.Series = None) -> Dict:
    """
    Validate factor data quality and return diagnostic information
    
    Args:
        factors: Factor data to validate
        returns: Optional return series for IC calculation
    
    Returns:
        Dictionary with validation results
    """
    if factors.empty:
        return {'status': 'error', 'message': 'Empty factor data'}
    
    validation = {
        'status': 'success',
        'n_factors': len(factors.columns),
        'n_observations': len(factors),
        'date_range': f"{factors.index.min()} to {factors.index.max()}",
        'missing_data': factors.isnull().sum().sum(),
        'infinite_values': np.isinf(factors.select_dtypes(include=[np.number])).sum().sum(),
        'zero_variance_factors': (factors.var() == 0).sum()
    }
    
    # Add IC information if returns are provided
    if returns is not None and not returns.empty:
        try:
            from ..analysis.metrics import calculate_metrics
            metrics = calculate_metrics(factors, returns)
            if not metrics.empty:
                validation.update({
                    'avg_ic': metrics['IC'].abs().mean(),
                    'max_ic': metrics['IC'].abs().max(),
                    'significant_factors': (metrics['is_significant']).sum()
                })
        except Exception as e:
            validation['ic_error'] = str(e)
    
    return validation


def split_train_test_data(data: pd.DataFrame, train_ratio: float = 0.7, random_state: int = None) -> tuple:
    """
    Split data into train and test sets
    
    Args:
        data: Input DataFrame
        train_ratio: Fraction of data for training
        random_state: Random seed for reproducibility
        
    Returns:
        Tuple of (train_data, test_data)
    """
    if random_state is not None:
        np.random.seed(random_state)
    
    n_train = int(len(data) * train_ratio)
    
    if random_state is None:
        # Time-series split (preserve order)
        train_data = data.iloc[:n_train]
        test_data = data.iloc[n_train:]
    else:
        # Random split
        shuffled_indices = np.random.permutation(len(data))
        train_indices = shuffled_indices[:n_train]
        test_indices = shuffled_indices[n_train:]
        
        train_data = data.iloc[train_indices]
        test_data = data.iloc[test_indices]
    
    return train_data, test_data

def getDailyTS(ticker):
    """
    Get daily time series data from local pickle file.
    Enhanced with Protocol 5 compatibility for pandas 1.5.3
    
    Parameters:
    -----------
    ticker : str
        Ticker symbol
        
    Returns:
    --------
    pd.DataFrame: OHLCV data
    """
    # Get the directory where this script is located
    # script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(DIR_DATA, 'futures-dailyK_con.pkl')
    
    # If not found in script directory, try the current working directory
    data_dict = pd.read_pickle(file_path)
    if ':' in ticker:
        label, legs_str = ticker.split(':', 1)
        legs = legs_str.split('-')
        
        if label == 'Pair':
            # Single pass: find common index and align data
            leg_data = [data_dict[leg] for leg in legs]
            common_idx = leg_data[0].index
            for df in leg_data[1:]:
                common_idx = common_idx.intersection(df.index)
            
            # Align all data to common index
            aligned = [df.loc[common_idx] for df in leg_data]
            
            # Calculate pair spread and minimum volume
            data = aligned[0] - aligned[1]
            data['Volume'] = np.minimum(aligned[0]['Volume'].values, aligned[1]['Volume'].values)
            
        elif label == 'Fly':
            # Single pass: find common index and align data
            leg_data = [data_dict[leg] for leg in legs]
            common_idx = leg_data[0].index
            for df in leg_data[1:]:
                common_idx = common_idx.intersection(df.index)
            
            # Align all data to common index
            aligned = [df.loc[common_idx] for df in leg_data]
            
            # Calculate butterfly spread and minimum volume across all legs
            data = aligned[1] - (aligned[0] + aligned[2]) * 0.5
            data['Volume'] = np.minimum.reduce([df['Volume'].values for df in aligned])
    else:
        data = data_dict[ticker]
    return data
