# -*- coding: utf-8 -*-
"""
Base classes for volatility trading strategies
Created on Oct 29, 2025

@author: CMBC
"""
from abc import ABC, abstractmethod
from typing import Dict, Optional
import pandas as pd
import numpy as np


class VolatilityData:
    """
    Container class for volatility time series data
    """
    
    def __init__(self, data: pd.DataFrame, code: str = "AU.SHF"):
        """
        Initialize volatility data container
        
        Parameters:
        -----------
        data : pd.DataFrame
            Time series data with columns for different maturities
        code : str
            Futures contract code
        """
        self.code = code
        self.raw_data = data.copy()
        self._prepare_data()
        
    def _prepare_data(self):
        """Prepare and standardize data"""
        self.data = self.raw_data.copy()
        
        # Standardize column names if needed
        if len(self.data.columns) == 3 and not all(col in self.data.columns for col in ['IV_1M', 'IV_2M', 'IV_3M']):
            self.data.columns = ['IV_1M', 'IV_2M', 'IV_3M']
    
    def get_data(self) -> pd.DataFrame:
        """Get the processed data"""
        return self.data.copy()
    
    def get_latest(self) -> pd.Series:
        """Get the latest data point"""
        return self.data.iloc[-1]
    
    def add_features(self, features: pd.DataFrame):
        """Add computed features to the dataset"""
        for col in features.columns:
            if col not in self.data.columns:
                self.data[col] = features[col]
    
    def __len__(self) -> int:
        return len(self.data)
    
    def __repr__(self) -> str:
        return f"VolatilityData(code={self.code}, periods={len(self)}, start={self.data.index[0]}, end={self.data.index[-1]})"


class BaseStrategy(ABC):
    """
    Abstract base class for volatility trading strategies
    """
    
    def __init__(self, name: str, params: Optional[Dict] = None):
        """
        Initialize strategy
        
        Parameters:
        -----------
        name : str
            Strategy name
        params : dict, optional
            Strategy parameters
        """
        self.name = name
        self.params = params or {}
        self.signals = None
        self.features = None
        
    @abstractmethod
    def compute_features(self, vol_data: VolatilityData) -> pd.DataFrame:
        """
        Compute strategy-specific features
        
        Parameters:
        -----------
        vol_data : VolatilityData
            Volatility data container
            
        Returns:
        --------
        pd.DataFrame
            DataFrame with computed features
        """
        pass
    
    @abstractmethod
    def generate_signals(self, vol_data: VolatilityData) -> pd.Series:
        """
        Generate trading signals based on strategy logic
        
        Parameters:
        -----------
        vol_data : VolatilityData
            Volatility data container
            
        Returns:
        --------
        pd.Series
            Series with trading signals (1: Long, -1: Short, 0: Neutral)
        """
        pass
    
    def run(self, vol_data: VolatilityData) -> pd.Series:
        """
        Execute the strategy: compute features and generate signals
        
        Parameters:
        -----------
        vol_data : VolatilityData
            Volatility data container
            
        Returns:
        --------
        pd.Series
            Trading signals
        """
        self.features = self.compute_features(vol_data)
        vol_data.add_features(self.features)
        self.signals = self.generate_signals(vol_data)
        return self.signals
    
    def get_signal_stats(self) -> Dict:
        """Get statistics about generated signals"""
        if self.signals is None:
            return {}
        
        signal_counts = self.signals.value_counts().to_dict()
        signal_changes = (self.signals.diff() != 0).sum()
        
        return {
            'signal_counts': signal_counts,
            'total_changes': signal_changes,
            'avg_holding_period': len(self.signals) / max(signal_changes, 1),
            'latest_signal': self.signals.iloc[-1] if len(self.signals) > 0 else 0
        }
    
    def get_latest_signal(self) -> int:
        """Get the most recent trading signal"""
        if self.signals is None or len(self.signals) == 0:
            return 0
        return int(self.signals.iloc[-1])
    
    def print_stats(self):
        """Print strategy statistics"""
        stats = self.get_signal_stats()
        
        print(f"\n{'='*60}")
        print(f"{self.name}")
        print(f"{'='*60}")
        
        if stats:
            print(f"\nSignal Distribution:")
            for signal, count in sorted(stats['signal_counts'].items()):
                print(f"  Signal {signal:+2d}: {count:4d} times")
            
            print(f"\nTrading Statistics:")
            print(f"  Signal Changes: {stats['total_changes']}")
            print(f"  Avg Holding Period: {stats['avg_holding_period']:.1f} days")
            print(f"  Current Signal: {stats['latest_signal']:+d}")
        else:
            print("No signals generated yet")
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}', params={self.params})"


class StrategyConfig:
    """Configuration container for strategy parameters"""
    
    # Default parameters for various strategies
    TERM_STRUCTURE = {
        'z_threshold': 1.5,
        'lookback_window': None  # Use all available data
    }
    
    MEAN_REVERSION = {
        'lookback': 10,
        'num_std': 2
    }
    
    MOMENTUM = {
        'short_window': 1,
        'long_window': 5,
        'threshold': 0.05
    }
    
    COMBINED = {
        'weights': {
            'term_structure': 0.4,
            'mean_reversion': 0.3,
            'momentum': 0.3
        },
        'signal_threshold': 0.5
    }
    
    @classmethod
    def get_config(cls, strategy_type: str) -> Dict:
        """Get default configuration for a strategy type"""
        configs = {
            'term_structure': cls.TERM_STRUCTURE,
            'mean_reversion': cls.MEAN_REVERSION,
            'momentum': cls.MOMENTUM,
            'combined': cls.COMBINED
        }
        return configs.get(strategy_type.lower(), {})
