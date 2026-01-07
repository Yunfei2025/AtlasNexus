"""
Price factors calculator.

This module contains the price-based factors calculator class.
"""

import pandas as pd
import numpy as np
from typing import Dict
from .base import BaseFactorCalculator


class PriceFactors(BaseFactorCalculator):
    """Calculator for price-based factors."""
    
    def calculate_price_position(self, period: int = 20) -> pd.Series:
        """Calculate price position within recent range."""
        high = self.data['High'].rolling(window=period).max()
        low = self.data['Low'].rolling(window=period).min()
        range_val = high - low
        return (self.data['Close'] - low) / (range_val + 1e-8)
    
    def calculate_close_open_diff(self) -> pd.Series:
        """Calculate close to open difference."""
        return self.data['Close'] - self.data['Open']
    
    def calculate_high_low_diff(self) -> pd.Series:
        """Calculate high to low difference."""
        return self.data['High'] - self.data['Low']
    
    def calculate_return_mean(self, period: int = 10) -> pd.Series:
        """Calculate rolling mean of returns."""
        return self.data['Close'].pct_change().rolling(window=period).mean()
    
    def calculate_price_momentum(self, period: int = 5) -> pd.Series:
        """Calculate price momentum."""
        return self.data['Close'] - self.data['Close'].shift(period)
    
    def calculate_price_acceleration(self, period: int = 5) -> pd.Series:
        """Calculate price acceleration (second derivative)."""
        momentum = self.calculate_price_momentum(period)
        return momentum - momentum.shift(period)
    
    def calculate_all(self) -> Dict[str, pd.Series]:
        """Calculate all price factors."""
        factors = {}
        factors['Price_Position'] = self.calculate_price_position(period=20)
        factors['Close_Open_Diff'] = self.calculate_close_open_diff()
        factors['High_Low_Diff'] = self.calculate_high_low_diff()
        factors['Return_Mean'] = self.calculate_return_mean(period=10)
        factors['Price_Momentum'] = self.calculate_price_momentum(period=5)
        factors['Price_Acceleration'] = self.calculate_price_acceleration(period=5)
        return factors