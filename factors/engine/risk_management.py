#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Risk Management Module

Provides risk controls including stop-loss, position limits, volatility adjustment,
and drawdown protection to improve win rate and reduce maximum drawdown.
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple


class RiskManager:
    """Comprehensive risk management for trading positions."""
    
    def __init__(self, config):
        """
        Initialize risk manager with configuration.
        
        Args:
            config: ModelConfig object with risk parameters
        """
        self.config = config
        self.max_position = getattr(config, 'max_position', 1.0)
        self.stop_loss_pct = getattr(config, 'stop_loss_pct', 0.05)
        self.trailing_stop_pct = getattr(config, 'trailing_stop_pct', 0.03)
        self.max_drawdown_limit = getattr(config, 'max_drawdown_limit', 0.15)
        self.volatility_target = getattr(config, 'volatility_target', 0.15)
        self.min_position_threshold = getattr(config, 'min_position_threshold', 0.05)
        
    def apply_position_limits(self, positions: pd.Series) -> pd.Series:
        """
        Apply hard position limits to prevent over-leverage.
        
        Args:
            positions: Raw position series
            
        Returns:
            Clipped positions within limits
        """
        return positions.clip(-self.max_position, self.max_position)
    
    def apply_volatility_scaling(self, positions: pd.Series, returns: pd.Series, 
                                 lookback_window: int = 20) -> pd.Series:
        """
        Scale positions based on recent volatility to maintain consistent risk.
        
        Args:
            positions: Original positions
            returns: Historical returns for volatility calculation
            lookback_window: Window for volatility calculation
            
        Returns:
            Volatility-adjusted positions
        """
        if len(returns) < lookback_window:
            return positions
        
        # Calculate rolling volatility
        rolling_vol = returns.rolling(window=lookback_window, min_periods=max(5, lookback_window//2)).std()
        rolling_vol = rolling_vol.reindex(positions.index, method='ffill')
        
        # Calculate scaling factor
        vol_scalar = self.volatility_target / (rolling_vol * np.sqrt(252))
        vol_scalar = vol_scalar.clip(0.2, 2.0)  # Limit extreme adjustments
        
        # Apply scaling
        adjusted_positions = positions * vol_scalar
        
        return adjusted_positions.clip(-self.max_position, self.max_position)
    
    def apply_stop_loss(self, positions: pd.Series, returns: pd.Series, 
                       cumulative_pnl: pd.Series = None) -> pd.Series:
        """
        Apply stop-loss and trailing stop logic.
        
        Args:
            positions: Current positions
            returns: Realized returns
            cumulative_pnl: Cumulative P&L series
            
        Returns:
            Positions with stop-loss applied
        """
        if cumulative_pnl is None:
            # Calculate cumulative PnL
            strategy_returns = positions.shift(1) * returns
            cumulative_pnl = strategy_returns.cumsum()
        
        adjusted_positions = positions.copy()
        peak_pnl = cumulative_pnl.expanding().max()
        drawdown = (cumulative_pnl - peak_pnl) / (peak_pnl.abs() + 1e-8)
        
        # Stop trading when hit stop loss
        stop_mask = drawdown < -self.stop_loss_pct
        adjusted_positions[stop_mask] = 0
        
        return adjusted_positions
    
    def apply_drawdown_protection(self, positions: pd.Series, returns: pd.Series) -> pd.Series:
        """
        Reduce or halt positions during significant drawdowns.
        
        Args:
            positions: Current positions
            returns: Historical returns
            
        Returns:
            Drawdown-protected positions
        """
        # Calculate strategy returns and cumulative wealth
        strategy_returns = positions.shift(1) * returns
        cumulative_returns = (1 + strategy_returns).cumprod()
        
        # Calculate running maximum and drawdown
        running_max = cumulative_returns.expanding().max()
        drawdown = (cumulative_returns - running_max) / running_max
        
        adjusted_positions = positions.copy()
        
        # Apply progressive position reduction based on drawdown severity
        for i in range(len(adjusted_positions)):
            dd = drawdown.iloc[i]
            
            if dd < -self.max_drawdown_limit:
                # Halt all trading
                adjusted_positions.iloc[i] = 0
            elif dd < -self.max_drawdown_limit * 0.7:
                # Reduce to 25% position
                adjusted_positions.iloc[i] *= 0.25
            elif dd < -self.max_drawdown_limit * 0.5:
                # Reduce to 50% position
                adjusted_positions.iloc[i] *= 0.5
        
        return adjusted_positions
    
    def filter_weak_signals(self, positions: pd.Series, 
                           prediction_confidence: pd.Series = None) -> pd.Series:
        """
        Filter out weak signals that are likely to lose money.
        
        Args:
            positions: Original positions
            prediction_confidence: Confidence score for each prediction (optional)
            
        Returns:
            Filtered positions with weak signals removed
        """
        adjusted_positions = positions.copy()
        
        # Remove very small positions
        small_position_mask = adjusted_positions.abs() < self.min_position_threshold
        adjusted_positions[small_position_mask] = 0
        
        # If confidence scores available, filter by confidence
        if prediction_confidence is not None:
            low_confidence_mask = prediction_confidence < 0.3
            adjusted_positions[low_confidence_mask] = 0
        
        return adjusted_positions
    
    def apply_all_controls(self, positions: pd.Series, returns: pd.Series,
                          prediction_confidence: pd.Series = None) -> Dict:
        """
        Apply all risk controls in sequence.
        
        Args:
            positions: Original positions
            returns: Historical returns
            prediction_confidence: Prediction confidence scores
            
        Returns:
            Dictionary with controlled positions and diagnostics
        """
        original_positions = positions.copy()
        
        # 1. Filter weak signals
        positions = self.filter_weak_signals(positions, prediction_confidence)
        
        # 2. Apply position limits
        positions = self.apply_position_limits(positions)
        
        # 3. Volatility scaling
        positions = self.apply_volatility_scaling(positions, returns)
        
        # 4. Drawdown protection
        positions = self.apply_drawdown_protection(positions, returns)
        
        # Calculate diagnostics
        n_original = (original_positions != 0).sum()
        n_filtered = (positions != 0).sum()
        avg_position_size = positions.abs().mean()
        
        return {
            'positions': positions,
            'n_original_signals': n_original,
            'n_filtered_signals': n_filtered,
            'filter_rate': (n_original - n_filtered) / max(n_original, 1),
            'avg_position_size': avg_position_size
        }


def calculate_prediction_confidence(predictions: pd.Series, 
                                   train_predictions: pd.Series = None,
                                   train_returns: pd.Series = None) -> pd.Series:
    """
    Calculate confidence score for each prediction based on historical accuracy.
    
    Args:
        predictions: Prediction series
        train_predictions: Training set predictions (for calibration)
        train_returns: Training set actual returns (for calibration)
        
    Returns:
        Confidence score series (0-1)
    """
    # Simple confidence based on prediction magnitude
    pred_std = predictions.std()
    
    if pred_std > 0:
        # Z-score based confidence: higher absolute predictions = higher confidence
        z_scores = (predictions.abs() - predictions.abs().mean()) / pred_std
        confidence = 1 / (1 + np.exp(-z_scores))  # Sigmoid transform to [0, 1]
    else:
        confidence = pd.Series(0.5, index=predictions.index)
    
    # If training data available, adjust by historical accuracy
    if train_predictions is not None and train_returns is not None:
        common_idx = train_predictions.index.intersection(train_returns.index)
        if len(common_idx) > 10:
            # Calculate directional accuracy
            train_pred = train_predictions.loc[common_idx]
            train_ret = train_returns.loc[common_idx]
            
            directional_accuracy = ((train_pred > 0) == (train_ret > 0)).mean()
            
            # Adjust confidence by historical accuracy
            confidence = confidence * (0.5 + directional_accuracy)
    
    return confidence.clip(0, 1)


class PositionSizer:
    """Dynamic position sizing based on multiple factors."""
    
    def __init__(self, config):
        self.config = config
        self.base_position = getattr(config, 'max_position', 1.0)
        self.kelly_fraction = getattr(config, 'kelly_fraction', 0.25)
        
    def kelly_criterion_sizing(self, predictions: pd.Series, 
                              train_predictions: pd.Series,
                              train_returns: pd.Series) -> pd.Series:
        """
        Apply Kelly Criterion for optimal position sizing.
        
        Args:
            predictions: Test predictions
            train_predictions: Training predictions
            train_returns: Training actual returns
            
        Returns:
            Kelly-adjusted positions
        """
        common_idx = train_predictions.index.intersection(train_returns.index)
        
        if len(common_idx) < 20:
            return predictions.apply(lambda x: np.sign(x) * self.base_position)
        
        train_pred = train_predictions.loc[common_idx]
        train_ret = train_returns.loc[common_idx]
        
        # Calculate win rate and average win/loss
        winning_trades = train_ret[train_pred * train_ret > 0]
        losing_trades = train_ret[train_pred * train_ret < 0]
        
        if len(winning_trades) == 0 or len(losing_trades) == 0:
            return predictions.apply(lambda x: np.sign(x) * self.base_position)
        
        win_rate = len(winning_trades) / len(common_idx)
        avg_win = winning_trades.mean()
        avg_loss = abs(losing_trades.mean())
        
        # Kelly formula: f = (p * b - q) / b
        # where p = win_rate, q = 1-p, b = avg_win/avg_loss
        if avg_loss > 0:
            b = avg_win / avg_loss
            kelly_f = (win_rate * b - (1 - win_rate)) / b
            kelly_f = np.clip(kelly_f, 0, 1) * self.kelly_fraction
        else:
            kelly_f = self.kelly_fraction
        
        # Apply Kelly fraction to position sizes
        positions = predictions.apply(lambda x: np.sign(x) * kelly_f * self.base_position)
        
        return positions
