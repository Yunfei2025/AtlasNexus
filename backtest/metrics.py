# -*- coding: utf-8 -*-
"""
Performance Metrics Module

Calculates comprehensive performance metrics from PnL series.

@author: CMBC
"""
import pandas as pd
import numpy as np


class PerformanceMetrics:
    """Calculate and store performance metrics from PnL series."""
    
    def __init__(self, pnl: pd.Series, capital: float, trading_days: int = 252):
        """
        Initialize with PnL series.
        
        Parameters:
        -----------
        pnl : pd.Series
            Daily PnL series
        capital : float
            Initial capital/notional
        trading_days : int
            Trading days per year for annualization
        """
        self.pnl = pnl
        self.capital = capital
        self.trading_days = trading_days
        self.daily_ret = pd.to_numeric(pnl.fillna(0), errors='coerce').fillna(0) / capital
        self._metrics = None
    
    def calculate(self) -> pd.Series:
        """Calculate comprehensive performance metrics."""
        if self._metrics is not None:
            return self._metrics
        
        # Total return (compounded)
        prod_value = self.daily_ret.add(1).prod()
        total_return = float(prod_value) - 1.0
        
        # Annualized metrics
        ann_return = self.daily_ret.mean() * self.trading_days
        ann_vol = self.daily_ret.std(ddof=1) * np.sqrt(self.trading_days)
        
        # Sharpe ratio
        sharpe = ann_return / ann_vol if ann_vol != 0 else np.nan
        
        # Maximum drawdown
        cumret = self.daily_ret.add(1).cumprod()
        running_max = cumret.cummax()
        drawdown = cumret.div(running_max).sub(1)
        max_drawdown = float(drawdown.min())
        
        # Win rate
        win_rate = (self.daily_ret > 0).sum() / len(self.daily_ret) if len(self.daily_ret) > 0 else 0
        
        self._metrics = pd.Series({
            'Total Return': total_return,
            'Annualized Return': ann_return,
            'Annualized Volatility': ann_vol,
            'Sharpe Ratio': sharpe,
            'Max Drawdown': max_drawdown,
            'Win Rate': win_rate,
            'Total Days': len(self.daily_ret)
        })
        
        return self._metrics
