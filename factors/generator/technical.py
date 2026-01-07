"""
Technical indicators factor calculator.

This module contains the technical indicators factor calculator class.
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple
from .base import BaseFactorCalculator


class TechnicalIndicators(BaseFactorCalculator):
    """Calculator for technical indicators (ATR, RSI, MACD, Bollinger Bands, KDJ)."""
    
    def calculate_atr(self, period: int = 12) -> pd.Series:
        """Calculate Average True Range (ATR)."""
        high_low = self.data['High'] - self.data['Low']
        high_close = (self.data['High'] - self.data['Close'].shift()).abs()
        low_close = (self.data['Low'] - self.data['Close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.ewm(span=period, adjust=False).mean()
    
    def calculate_rsi(self, period: int = 14) -> pd.Series:
        """Calculate Relative Strength Index (RSI)."""
        delta = self.data['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    
    def calculate_macd(self, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate MACD (Moving Average Convergence Divergence)."""
        ema_fast = self.data['Close'].ewm(span=fast).mean()
        ema_slow = self.data['Close'].ewm(span=slow).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal).mean()
        histogram = macd_line - signal_line
        return macd_line, signal_line, histogram
    
    def calculate_bollinger_bands(self, period: int = 20, std_dev: float = 2) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate Bollinger Bands."""
        sma = self.data['Close'].rolling(window=period).mean()
        std = self.data['Close'].rolling(window=period).std()
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        return upper_band, sma, lower_band
    
    def calculate_kdj(self, k_period: int = 9, d_period: int = 3) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Calculate KDJ indicator."""
        low_min = self.data['Low'].rolling(window=k_period).min()
        high_max = self.data['High'].rolling(window=k_period).max()
        rsv = (self.data['Close'] - low_min) / (high_max - low_min) * 100
        k = rsv.ewm(com=d_period-1).mean()
        d = k.ewm(com=d_period-1).mean()
        j = 3 * k - 2 * d
        return k, d, j
    
    def calculate_all(self) -> Dict[str, pd.Series]:
        """Calculate all technical indicators."""
        factors = {}
        
        # ATR
        factors['ATR'] = self.calculate_atr(period=12)
        
        # RSI
        factors['RSI'] = self.calculate_rsi(period=14)
        
        # MACD
        macd_line, signal_line, histogram = self.calculate_macd()
        factors['MACD'] = macd_line
        factors['MACD_Signal'] = signal_line
        factors['MACD_Histogram'] = histogram
        
        # Bollinger Bands
        upper, middle, lower = self.calculate_bollinger_bands()
        factors['BB_Upper'] = upper
        factors['BB_Middle'] = middle
        factors['BB_Lower'] = lower
        
        # KDJ
        k, d, j = self.calculate_kdj()
        factors['K'] = k
        factors['D'] = d
        factors['J'] = j
        
        return factors