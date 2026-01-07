# -*- coding: utf-8 -*-
"""
Trading Strategies Module

Trend-following and mean-reversion strategies with volatility targeting,
hysteresis, and risk controls.

@author: CMBC
"""
import pandas as pd
import numpy as np


class TrendFollowingStrategy:
    """
    Trend-following strategy using dual moving average crossover with hysteresis.
    
    Signal:
    - Long: Fast MA > Slow MA + threshold
    - Short: Fast MA < Slow MA - threshold
    - Threshold based on volatility to reduce whipsaws
    """
    
    def __init__(self, fast_period: int = 20, slow_period: int = 60, 
                 hysteresis_factor: float = 0.25, vol_target: float = 0.005):
        """
        Initialize trend-following strategy.
        
        Args:
            fast_period: Fast MA period (days)
            slow_period: Slow MA period (days)
            hysteresis_factor: Multiplier for volatility-based threshold
            vol_target: Target daily volatility for position sizing (e.g., 0.01 = 1%)
        """
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.hysteresis_factor = hysteresis_factor
        self.vol_target = vol_target
    
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        Generate trading signals with hysteresis.
        
        Args:
            df: OHLC DataFrame with 'Close' column
            
        Returns:
            Series of signals: 1 (long), -1 (short), 0 (neutral)
        """
        close = df['Close'].copy()
        
        # Calculate moving averages
        fast_ma = close.rolling(window=self.fast_period, min_periods=self.fast_period).mean()
        slow_ma = close.rolling(window=self.slow_period, min_periods=self.slow_period).mean()
        
        # Calculate hysteresis threshold based on volatility
        returns_vol = close.pct_change().rolling(window=20, min_periods=20).std()
        threshold = self.hysteresis_factor * returns_vol * close
        
        # Generate signals with hysteresis
        spread = fast_ma - slow_ma
        signals = pd.Series(0, index=df.index)
        
        # Use previous position to maintain until threshold breach
        position = 0
        final_signals = []
        for i in range(len(df)):
            if pd.notna(spread.iloc[i]) and pd.notna(threshold.iloc[i]):
                if spread.iloc[i] > threshold.iloc[i]:
                    position = 1
                elif spread.iloc[i] < -threshold.iloc[i]:
                    position = -1
                # else: hold current position
            final_signals.append(position)
        
        return pd.Series(final_signals, index=df.index)
    
    def calculate_returns(self, df: pd.DataFrame, transaction_cost: float = 0.0002) -> pd.Series:
        """
        Calculate strategy returns with volatility targeting and transaction costs.
        
        Args:
            df: OHLC DataFrame
            transaction_cost: Cost per trade as fraction (e.g., 0.0002 = 2 bps)
        """
        signals = self.generate_signals(df)
        
        # Shift signals to avoid look-ahead bias
        positions = signals.shift(1).fillna(0)
        
        # Calculate returns and realized volatility
        price_returns = df['Close'].pct_change()
        realized_vol = price_returns.ewm(span=20, min_periods=20).std()
        
        # Volatility targeting: scale positions
        vol_scalar = (self.vol_target / (realized_vol + 1e-8)).clip(upper=5.0)
        sized_positions = positions * vol_scalar
        
        # Calculate gross returns
        gross_returns = sized_positions * price_returns
        
        # Subtract transaction costs on position changes
        turnover = sized_positions.diff().abs().fillna(0)
        costs = turnover * transaction_cost
        
        net_returns = gross_returns - costs
        
        return net_returns.fillna(0)


class MeanReversionStrategy:
    """
    Mean-reversion strategy using Bollinger Bands with max hold and trend filter.
    
    Signal:
    - Long: Price < Lower Band (oversold)
    - Short: Price > Upper Band (overbought)
    - Exit: Price crosses middle band or max hold period reached
    - Filter: Avoid trades in strong trends
    """
    
    def __init__(self, period: int = 20, num_std: float = 1.0, 
                 max_hold: int = 10, vol_target: float = 0.005):
        """
        Initialize mean-reversion strategy.
        
        Args:
            period: Bollinger Band period (days)
            num_std: Number of standard deviations
            max_hold: Maximum holding period (days)
            vol_target: Target daily volatility for position sizing
        """
        self.period = period
        self.num_std = num_std
        self.max_hold = max_hold
        self.vol_target = vol_target
    
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        Generate trading signals with max hold and trend filter.
        
        Args:
            df: OHLC DataFrame with 'Close' column
            
        Returns:
            Series of signals: 1 (long), -1 (short), 0 (neutral)
        """
        close = df['Close'].copy()
        
        # Calculate Bollinger Bands
        middle = close.rolling(window=self.period, min_periods=self.period).mean()
        std = close.rolling(window=self.period, min_periods=self.period).std()
        upper = middle + self.num_std * std
        lower = middle - self.num_std * std
        
        # Trend filter: calculate 20-day slope
        close_20d_ago = close.shift(20)
        trend_slope = (close - close_20d_ago) / (close_20d_ago + 1e-8)
        strong_trend_threshold = 0.05  # 5% move over 20 days
        
        # Generate raw signals
        raw_signals = pd.Series(0, index=df.index)
        raw_signals[close < lower] = 1   # Oversold -> Long
        raw_signals[close > upper] = -1  # Overbought -> Short
        
        # Hold position with max hold and trend filter
        position = 0
        hold_days = 0
        final_signals = []
        
        for i in range(len(df)):
            # Check trend filter
            in_strong_trend = False
            if pd.notna(trend_slope.iloc[i]):
                in_strong_trend = abs(trend_slope.iloc[i]) > strong_trend_threshold
            
            # New entry signal (only if not in strong trend)
            if raw_signals.iloc[i] != 0 and not in_strong_trend:
                position = raw_signals.iloc[i]
                hold_days = 0
            elif position != 0:
                hold_days += 1
                
                # Exit conditions
                if pd.notna(middle.iloc[i]):
                    # Exit if price crosses middle band
                    if (position == 1 and close.iloc[i] > middle.iloc[i]) or \
                       (position == -1 and close.iloc[i] < middle.iloc[i]):
                        position = 0
                        hold_days = 0
                    # Exit if max hold reached
                    elif hold_days >= self.max_hold:
                        position = 0
                        hold_days = 0
            
            final_signals.append(position)
        
        return pd.Series(final_signals, index=df.index)
    
    def calculate_returns(self, df: pd.DataFrame, transaction_cost: float = 0.0002) -> pd.Series:
        """
        Calculate strategy returns with volatility targeting and transaction costs.
        
        Args:
            df: OHLC DataFrame
            transaction_cost: Cost per trade as fraction (e.g., 0.0002 = 2 bps)
        """
        signals = self.generate_signals(df)
        
        # Shift signals to avoid look-ahead bias
        positions = signals.shift(1).fillna(0)
        
        # Calculate returns and realized volatility
        price_returns = df['Close'].pct_change()
        realized_vol = price_returns.ewm(span=20, min_periods=20).std()
        
        # Volatility targeting: scale positions
        vol_scalar = (self.vol_target / (realized_vol + 1e-8)).clip(upper=5.0)
        sized_positions = positions * vol_scalar
        
        # Calculate gross returns
        gross_returns = sized_positions * price_returns
        
        # Subtract transaction costs on position changes
        turnover = sized_positions.diff().abs().fillna(0)
        costs = turnover * transaction_cost
        
        net_returns = gross_returns - costs
        
        return net_returns.fillna(0)
