"""
Momentum factors calculator.

This module contains the momentum and trend-based factors calculator class.
"""

import pandas as pd
import numpy as np
from typing import Dict
from .base import BaseFactorCalculator


class MomentumFactors(BaseFactorCalculator):
    """Calculator for momentum and trend-based factors."""
    
    def calculate_momentum(self, period: int = 10) -> pd.Series:
        """Calculate momentum."""
        return self.data['Close'].pct_change(period)
    
    def calculate_trend_strength(self, period: int = 20) -> pd.Series:
        """Calculate trend strength."""
        sma = self.data['Close'].rolling(window=period).mean()
        return self.data['Close'] - sma
    
    def calculate_bias(self, period: int = 20) -> pd.Series:
        """Calculate bias from moving average."""
        ma = self.data['Close'].rolling(window=period).mean()
        return self.data['Close'] - ma
    
    def calculate_n_day_return(self, period: int = 5) -> pd.Series:
        """Calculate n-day return."""
        return self.data['Close'].pct_change(period)
    
    def calculate_close_change(self, period: int = 5) -> pd.Series:
        """Calculate close price change."""
        return self.data['Close'].pct_change(period)
    
    def calculate_all(self) -> Dict[str, pd.Series]:
        """Calculate all momentum factors."""
        factors = {}
        factors['Momentum'] = self.calculate_momentum(period=10)
        factors['Trend_Strength'] = self.calculate_trend_strength(period=20)
        factors['Bias'] = self.calculate_bias(period=20)
        factors['N_Day_Return'] = self.calculate_n_day_return(period=5)
        factors['Close_Change'] = self.calculate_close_change(period=5)
        return factors