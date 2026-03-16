"""
Factor calculator factory and utilities.

This module contains the factory class for creating and managing all factor calculators,
as well as utility functions for factor cleaning and scaling.
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple
from .base import BaseFactorCalculator
from .technical import TechnicalIndicators
from .momentum import MomentumFactors
from .volatility import VolatilityFactors
from .volume import VolumeFactors
from .price import PriceFactors
from .yield_curve import YieldCurveFactors
from .carry import CarryFactors
from .value import ValueFactors
from .macro import MacroFactors
from .high_order import HighOrderFactorGenerator


class FactorCalculatorFactory:
    """Factory class for creating and managing all factor calculators."""
    
    def __init__(self, data: pd.DataFrame):
        """
        Initialize factory with market data.
        
        Parameters:
        -----------
        data : pd.DataFrame
            Market data with OHLCV columns
        """
        self.data = data
        self.calculators = {}
        self._initialize_calculators()
    
    def _initialize_calculators(self):
        """Initialize all factor calculators."""
        self.calculators = {
            'technical': TechnicalIndicators(self.data),
            'momentum': MomentumFactors(self.data),
            'volatility': VolatilityFactors(self.data),
            'volume': VolumeFactors(self.data),
            'price': PriceFactors(self.data),
            'yield_curve': YieldCurveFactors(self.data),
            'carry': CarryFactors(self.data),
            'value': ValueFactors(self.data)
        }

    def generate_factors(self, max_high_order_factors: int = 100) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Generate all base and high-order factors, optionally including macro factors.
        """
        all_factors = {}

        # Calculate base factors
        for category, calculator in self.calculators.items():
            try:
                category_factors = calculator.calculate_all()
                all_factors.update(category_factors)
            except Exception as e:
                print(f"Warning: Error calculating {category} factors: {e}")
                continue

        base_factors = pd.DataFrame(all_factors, index=self.data.index)

        # Generate high-order factors
        high_order_generator = HighOrderFactorGenerator(base_factors, self.data)
        high_order_factors = high_order_generator.generate_all_high_order_factors(max_high_order_factors)

        macro_calc = MacroFactors()
        macro_factors = macro_calc.calculate_all()
        all_factors = pd.concat([base_factors, macro_factors, high_order_factors], axis=1, copy=False)
        all_factors = clean_factors(all_factors)
        return all_factors

    
    def get_calculator(self, category: str) -> BaseFactorCalculator:
        """Get a specific factor calculator by category."""
        if category not in self.calculators:
            raise ValueError(f"Unknown category: {category}. Available: {list(self.calculators.keys())}")
        return self.calculators[category]


def clean_factors(factors: pd.DataFrame, nan_threshold: float = 0.5) -> pd.DataFrame:
    """
    Clean factors by removing columns with excessive NaN values.
    
    Args:
        factors: Factor DataFrame
        nan_threshold: Maximum allowed NaN percentage (0.5 = 50%)
        
    Returns:
        Cleaned factor DataFrame
    """
    if factors.empty:
        return factors
    
    # Remove columns with >threshold NaN values
    nan_pct = factors.isnull().sum() / len(factors)
    valid_cols = nan_pct[nan_pct < nan_threshold].index
    
    return factors[valid_cols]#.dropna()


def scale_factors_rolling(factors: pd.DataFrame, train_end_date) -> pd.DataFrame:
    """
    Scale factors using rolling window to avoid look-ahead bias.
    
    Args:
        factors: Raw factor DataFrame with DatetimeIndex
        train_end_date: End of training period (last date to use for statistics)
        lookback_months: Months to look back for scaling statistics (default from config)
        
    Returns:
        Scaled factor DataFrame
    """
    if factors.empty:
        return factors

    try:
        from ..config import ModelConfig
        config = ModelConfig()
        lookback_months = config.lookback_window
    except ImportError:
        lookback_months = 12  # Default fallback
    
    import datetime
    from dateutil.relativedelta import relativedelta
    
    # Ensure consistent datetime handling - convert to date only if it's datetime
    if isinstance(train_end_date, datetime.datetime):
        train_end_date = train_end_date.date()
    elif isinstance(train_end_date, datetime.date):
        # Already a date object, no conversion needed
        pass
    else:
        # Handle other types (strings, etc.)
        train_end_date = pd.to_datetime(train_end_date).date()
    
    # Calculate rolling window using date arithmetic
    lookback_start_date = train_end_date - relativedelta(months=lookback_months)
    
    # Filter to rolling window - compare dates with dates
    rolling_mask = (factors.index >= lookback_start_date) & (factors.index <= train_end_date)
    rolling_data = factors.loc[rolling_mask]
    
    if rolling_data.empty:
        # Fallback to all historical data
        rolling_data = factors.loc[factors.index <= train_end_date]
        if rolling_data.empty:
            return factors
    
    # Calculate scaling statistics
    scaled_factors = factors.copy()
    min_points = max(30, len(rolling_data) // 20)
    
    for col in factors.columns:
        series = rolling_data[col].dropna()
        if len(series) < min_points:
            continue
            
        # Robust scaling parameters
        q01, q99 = series.quantile([0.005, 0.995])
        median = series.median()
        iqr = series.quantile(0.75) - series.quantile(0.25)
        
        # Apply scaling
        col_data = scaled_factors[col].clip(lower=q01, upper=q99)
        if iqr > 1e-10:
            scaled_factors[col] = (col_data - median) / iqr
        else:
            scaled_factors[col] = col_data - median
    
    # Clean up inf/nan values
    scaled_factors = scaled_factors.replace([np.inf, -np.inf], np.nan).fillna(0)
    return scaled_factors