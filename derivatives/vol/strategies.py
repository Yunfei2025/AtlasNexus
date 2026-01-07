# -*- coding: utf-8 -*-
"""
Concrete volatility trading strategy implementations
Created on Oct 29, 2025

@author: CMBC
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from .vol import BaseStrategy, VolatilityData, StrategyConfig


class TermStructureStrategy(BaseStrategy):
    """
    Term Structure Arbitrage Strategy
    
    Trades based on abnormal term structure slopes (steep or inverted curves)
    """
    
    def __init__(self, params: Optional[Dict] = None):
        default_params = StrategyConfig.get_config('term_structure')
        if params:
            default_params.update(params)
        super().__init__("Term Structure Arbitrage", default_params)
        
    def compute_features(self, vol_data: VolatilityData) -> pd.DataFrame:
        """Compute term structure slopes and z-scores"""
        data = vol_data.get_data()
        features = pd.DataFrame(index=data.index)
        
        # Calculate term structure slopes
        features['Slope_1M2M'] = data['IV_2M'] - data['IV_1M']
        features['Slope_2M3M'] = data['IV_3M'] - data['IV_2M']
        features['Slope_1M3M'] = data['IV_3M'] - data['IV_1M']
        
        # Standardize slopes (Z-score)
        for col in ['Slope_1M2M', 'Slope_2M3M', 'Slope_1M3M']:
            mean = features[col].mean()
            std = features[col].std()
            features[f'{col}_Zscore'] = (features[col] - mean) / std
        
        return features
    
    def generate_signals(self, vol_data: VolatilityData) -> pd.Series:
        """Generate signals based on term structure z-scores"""
        data = vol_data.get_data()
        signals = pd.Series(0, index=data.index)
        
        z_threshold = self.params.get('z_threshold', 1.5)
        zscore_col = 'Slope_1M3M_Zscore'
        
        # Short steep curve: Z-score > threshold
        signals[data[zscore_col] > z_threshold] = -1
        
        # Long flat/inverted curve: Z-score < -threshold
        signals[data[zscore_col] < -z_threshold] = 1
        
        return signals


class MeanReversionStrategy(BaseStrategy):
    """
    Mean Reversion Strategy using Bollinger Bands
    
    Trades based on volatility deviation from its moving average
    """
    
    def __init__(self, params: Optional[Dict] = None):
        default_params = StrategyConfig.get_config('mean_reversion')
        if params:
            default_params.update(params)
        super().__init__("Volatility Mean Reversion", default_params)
        
    def compute_features(self, vol_data: VolatilityData) -> pd.DataFrame:
        """Compute Bollinger Bands"""
        data = vol_data.get_data()
        features = pd.DataFrame(index=data.index)
        
        lookback = self.params.get('lookback', 10)
        num_std = self.params.get('num_std', 2)
        
        # Calculate moving average and standard deviation
        features['IV_1M_MA'] = data['IV_1M'].rolling(window=lookback).mean()
        features['IV_1M_Std'] = data['IV_1M'].rolling(window=lookback).std()
        
        # Bollinger Bands
        features['IV_1M_Upper'] = features['IV_1M_MA'] + num_std * features['IV_1M_Std']
        features['IV_1M_Lower'] = features['IV_1M_MA'] - num_std * features['IV_1M_Std']
        
        return features
    
    def generate_signals(self, vol_data: VolatilityData) -> pd.Series:
        """Generate signals based on Bollinger Band breakouts"""
        data = vol_data.get_data()
        signals = pd.Series(0, index=data.index)
        
        # Short volatility: IV breaks above upper band
        signals[data['IV_1M'] > data['IV_1M_Upper']] = -1
        
        # Long volatility: IV breaks below lower band
        signals[data['IV_1M'] < data['IV_1M_Lower']] = 1
        
        return signals


class MomentumStrategy(BaseStrategy):
    """
    Volatility Momentum Strategy
    
    Follows trends in volatility changes
    """
    
    def __init__(self, params: Optional[Dict] = None):
        default_params = StrategyConfig.get_config('momentum')
        if params:
            default_params.update(params)
        super().__init__("Volatility Momentum", default_params)
        
    def compute_features(self, vol_data: VolatilityData) -> pd.DataFrame:
        """Compute volatility rate of change"""
        data = vol_data.get_data()
        features = pd.DataFrame(index=data.index)
        
        short_window = self.params.get('short_window', 1)
        long_window = self.params.get('long_window', 5)
        
        # Calculate volatility changes
        features['IV_1M_Chg_1D'] = data['IV_1M'].pct_change(short_window)
        features['IV_1M_Chg_5D'] = data['IV_1M'].pct_change(long_window)
        
        return features
    
    def generate_signals(self, vol_data: VolatilityData) -> pd.Series:
        """Generate signals based on momentum"""
        data = vol_data.get_data()
        signals = pd.Series(0, index=data.index)
        
        threshold = self.params.get('threshold', 0.05)
        
        # Long volatility: positive momentum exceeds threshold
        signals[data['IV_1M_Chg_5D'] > threshold] = 1
        
        # Short volatility: negative momentum exceeds threshold
        signals[data['IV_1M_Chg_5D'] < -threshold] = -1
        
        return signals


class CombinedStrategy(BaseStrategy):
    """
    Combined Strategy
    
    Weighted combination of multiple strategies
    """
    
    def __init__(self, strategies: List[BaseStrategy], params: Optional[Dict] = None):
        """
        Initialize combined strategy
        
        Parameters:
        -----------
        strategies : list
            List of strategy instances to combine
        params : dict, optional
            Parameters including 'weights' and 'signal_threshold'
        """
        default_params = StrategyConfig.get_config('combined')
        if params:
            default_params.update(params)
        super().__init__("Combined Strategy", default_params)
        
        self.strategies = strategies
        self.strategy_signals = {}
        
    def compute_features(self, vol_data: VolatilityData) -> pd.DataFrame:
        """
        Run all sub-strategies and collect their signals
        Note: Features are computed within each sub-strategy
        """
        features = pd.DataFrame(index=vol_data.get_data().index)
        
        # Run each strategy and store signals
        for strategy in self.strategies:
            signal = strategy.run(vol_data)
            signal_name = f"Signal_{strategy.name.replace(' ', '_')}"
            features[signal_name] = signal
            self.strategy_signals[strategy.name] = signal
        
        return features
    
    def generate_signals(self, vol_data: VolatilityData) -> pd.Series:
        """Generate combined signals using weighted average"""
        data = vol_data.get_data()
        
        # Get weights from params
        weights = self.params.get('weights', {})
        signal_threshold = self.params.get('signal_threshold', 0.5)
        
        # Default equal weights if not specified
        if not weights:
            weight_value = 1.0 / len(self.strategies)
            weights = {s.name: weight_value for s in self.strategies}
        
        # Compute weighted signal
        combined_signal = pd.Series(0.0, index=data.index)
        
        for strategy_name, signal in self.strategy_signals.items():
            weight = weights.get(strategy_name, 0)
            combined_signal += weight * signal
        
        # Store continuous signal for analysis
        continuous_signal = combined_signal.copy()
        
        # Discretize signal
        final_signal = pd.Series(0, index=data.index)
        final_signal[continuous_signal > signal_threshold] = 1
        final_signal[continuous_signal < -signal_threshold] = -1
        
        # Add combined score to features for analysis
        if self.features is not None:
            self.features['Signal_Combined_Score'] = continuous_signal
        
        return final_signal
    
    def print_stats(self):
        """Print statistics for combined strategy and sub-strategies"""
        super().print_stats()
        
        print(f"\nSub-Strategy Statistics:")
        for strategy in self.strategies:
            stats = strategy.get_signal_stats()
            if stats:
                print(f"\n  {strategy.name}:")
                print(f"    Signal Changes: {stats['total_changes']}")
                print(f"    Current Signal: {stats['latest_signal']:+d}")


class StrategyFactory:
    """Factory class for creating strategy instances"""
    
    @staticmethod
    def create_strategy(strategy_type: str, params: Optional[Dict] = None) -> BaseStrategy:
        """
        Create a strategy instance
        
        Parameters:
        -----------
        strategy_type : str
            Type of strategy ('term_structure', 'mean_reversion', 'momentum', 'combined')
        params : dict, optional
            Strategy parameters
            
        Returns:
        --------
        BaseStrategy
            Strategy instance
        """
        strategy_map = {
            'term_structure': TermStructureStrategy,
            'mean_reversion': MeanReversionStrategy,
            'momentum': MomentumStrategy,
        }
        
        strategy_class = strategy_map.get(strategy_type.lower())
        if strategy_class is None:
            raise ValueError(f"Unknown strategy type: {strategy_type}")
        
        return strategy_class(params)
    
    @staticmethod
    def create_all_strategies(custom_params: Optional[Dict] = None) -> List[BaseStrategy]:
        """
        Create all individual strategies (excluding combined)
        
        Parameters:
        -----------
        custom_params : dict, optional
            Dictionary mapping strategy types to their parameters
            
        Returns:
        --------
        list
            List of strategy instances
        """
        custom_params = custom_params or {}
        
        strategies = []
        for strategy_type in ['term_structure', 'mean_reversion', 'momentum']:
            params = custom_params.get(strategy_type)
            strategy = StrategyFactory.create_strategy(strategy_type, params)
            strategies.append(strategy)
        
        return strategies
    
    @staticmethod
    def create_combined_strategy(
        individual_strategies: Optional[List[BaseStrategy]] = None,
        params: Optional[Dict] = None
    ) -> CombinedStrategy:
        """
        Create combined strategy
        
        Parameters:
        -----------
        individual_strategies : list, optional
            List of strategies to combine. If None, creates default strategies
        params : dict, optional
            Combined strategy parameters
            
        Returns:
        --------
        CombinedStrategy
            Combined strategy instance
        """
        if individual_strategies is None:
            individual_strategies = StrategyFactory.create_all_strategies()
        
        return CombinedStrategy(individual_strategies, params)
