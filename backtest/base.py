# -*- coding: utf-8 -*-
"""
Base Backtester Class

Abstract base class for all backtest implementations.

@author: CMBC
"""
from typing import Dict, Union
from datetime import date
from abc import ABC, abstractmethod
import pandas as pd


class Backtester(ABC):
    """Abstract base class for backtesters."""
    
    def __init__(self, start: Union[pd.Timestamp, date], end: Union[pd.Timestamp, date]):
        """
        Initialize backtester with date range.
        
        Parameters:
        -----------
        start : pd.Timestamp or date
            Start date for backtest
        end : pd.Timestamp or date
            End date for backtest
        """
        self.start = start
        self.end = end
        self.pnl = None
        self.attribution = None
        self.metrics = None
    
    @abstractmethod
    def run(self) -> None:
        """Execute backtest. Must be implemented by subclasses."""
        pass
    
    def get_results(self) -> Dict:
        """Get backtest results as dictionary."""
        return {
            'pnl': self.pnl,
            'attribution': self.attribution,
            'metrics': self.metrics
        }
