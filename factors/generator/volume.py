"""
Volume factors calculator.

This module contains the volume-based factors calculator class.
"""

import pandas as pd
import numpy as np
from typing import Dict
from .base import BaseFactorCalculator


class VolumeFactors(BaseFactorCalculator):
    """Calculator for volume-based factors."""
    
    def calculate_volume_ma_ratio(self, period: int = 20) -> pd.Series:
        """Calculate volume to moving average ratio."""
        volume_ma = self.data['Volume'].rolling(window=period).mean()
        return self.data['Volume'] / (volume_ma + 1e-8)
    
    def calculate_volume_change(self, period: int = 5) -> pd.Series:
        """Calculate volume change."""
        return self.data['Volume'].pct_change(period)
    
    def calculate_volume_volatility(self, period: int = 10) -> pd.Series:
        """Calculate volume volatility."""
        return self.data['Volume'].rolling(window=period).std()
    
    def calculate_volume_trend(self, period: int = 5) -> pd.Series:
        """Calculate volume trend using linear regression slope."""
        def slope(x):
            if len(x) < 2:
                return 0
            return np.polyfit(range(len(x)), x, 1)[0]
        
        return self.data['Volume'].rolling(window=period).apply(slope, raw=True)
    
    def calculate_all(self) -> Dict[str, pd.Series]:
        """Calculate all volume factors."""
        factors = {}
        factors['Volume_MA_Ratio'] = self.calculate_volume_ma_ratio(period=20)
        factors['Volume_Change'] = self.calculate_volume_change(period=5)
        factors['Volume_Volatility'] = self.calculate_volume_volatility(period=10)
        factors['Volume_Trend'] = self.calculate_volume_trend(period=5)
        return factors