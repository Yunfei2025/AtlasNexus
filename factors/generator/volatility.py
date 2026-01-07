"""
Volatility factors calculator.

This module contains the volatility-based factors calculator class.
"""

import pandas as pd
import numpy as np
from typing import Dict
from .base import BaseFactorCalculator


class VolatilityFactors(BaseFactorCalculator):
    """Calculator for volatility-based factors."""
    
    def calculate_volatility(self, period: int = 20) -> pd.Series:
        """Calculate rolling volatility."""
        return self.data['Close'].rolling(window=period).std()
    
    def calculate_return_volatility(self, period: int = 10) -> pd.Series:
        """Calculate return volatility."""
        return self.data['Close'].pct_change().rolling(window=period).std()
    
    def calculate_max_drawdown(self, period: int = 20) -> pd.Series:
        """Calculate rolling maximum drawdown."""
        roll_max = self.data['Close'].rolling(window=period, min_periods=1).max()
        daily_drawdown = self.data['Close'] - roll_max
        return daily_drawdown.rolling(window=period, min_periods=1).min()
    
    def calculate_amplitude(self, period: int = 5) -> pd.Series:
        """Calculate price amplitude."""
        return (self.data['High'] - self.data['Low']).rolling(window=period).mean()
    
    def calculate_all(self) -> Dict[str, pd.Series]:
        """Calculate all volatility factors."""
        factors = {}
        factors['Volatility'] = self.calculate_volatility(period=20)
        factors['Return_Volatility'] = self.calculate_return_volatility(period=10)
        factors['Max_Drawdown'] = self.calculate_max_drawdown(period=20)
        factors['Amplitude'] = self.calculate_amplitude(period=5)
        return factors