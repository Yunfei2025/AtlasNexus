#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Portfolio Management for Factor-Based Strategies

Simplified and optimized portfolio creation functions.
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


def calculate_signal_intensity(portfolio: pd.Series, lookback_window: int = 252) -> pd.Series:
    """Calculate z-score signal intensity with adaptive parameters."""
    if portfolio.empty:
        return pd.Series()
    
    try:
        min_periods = max(3, min(lookback_window // 3, len(portfolio) // 2))
        window = min(lookback_window, len(portfolio))
        
        rolling_mean = portfolio.rolling(window=window, min_periods=min_periods).mean()
        rolling_std = portfolio.rolling(window=window, min_periods=min_periods).std()
        z_scores = (portfolio - rolling_mean) / rolling_std
        
        return z_scores.replace([np.inf, -np.inf], np.nan).fillna(0)
        
    except Exception as e:
        print(f"Signal intensity calculation failed: {e}")
        return pd.Series(index=portfolio.index, data=0)


def create_simple_portfolio(predictions: pd.Series, config, data: pd.DataFrame = None) -> Dict:
    """Create simple long/short positions based on prediction sign with risk management."""
    positions = pd.Series(0, index=predictions.index, dtype=float)
    threshold = 0.0 * predictions.std() if len(predictions) > 5 else 0.0
    positions[predictions > threshold] = 1.0
    positions[predictions < -threshold] = -1.0
    
    # Apply risk management if enabled
    if getattr(config, 'use_risk_management', False) and data is not None:
        try:
            from ..engine.risk_management import RiskManager, calculate_prediction_confidence
            
            risk_manager = RiskManager(config)
            returns = data['Returns'] if 'Returns' in data.columns else pd.Series()
            
            if not returns.empty and len(returns) > 20:
                # Calculate prediction confidence
                confidence = calculate_prediction_confidence(predictions)
                
                # Apply risk controls
                result = risk_manager.apply_all_controls(positions, returns, confidence)
                positions = result['positions']
                
                print(f"🛡️ Risk management: {result['n_original_signals']} → {result['n_filtered_signals']} signals "
                      f"(filter rate: {result['filter_rate']:.1%})")
        except Exception as e:
            print(f"⚠️ Risk management failed: {e}, using unfiltered positions")
    
    long_count = (positions > 0).sum()
    short_count = (positions < 0).sum()
    
    # print(f"📊 Simple portfolio: {long_count} long, {short_count} short")
    
    return {
        'portfolio': positions,
        'predictions': predictions,
        'method_info': {
            'type': 'simple',
            'long_count': long_count,
            'short_count': short_count,
            'zero_count': 0
        }
    }


def create_smooth_portfolio(predictions: pd.Series, config, 
                          returns_train: pd.Series = None, **kwargs) -> Dict:
    """
    Create smooth positions with tanh mapping and gradual position changes.
    
    Args:
        predictions: Predicted returns series
        config: Configuration object
        returns_train: Training returns for optimization (optional)
        
    Returns:
        Dictionary with portfolio positions
    """
    # Parameters with defaults
    tanh_scale = getattr(config, 'tanh_scale', 2.0)
    max_daily_change = getattr(config, 'max_daily_change', 0.25)
    min_tick = getattr(config, 'min_tick', 0.01)
    friction_cost = getattr(config, 'friction_cost', 0.0001)
    
    def create_smooth_positions(pred_series, scale, max_change, min_tick_size):
        """Create smooth positions with tanh mapping."""
        # Map predictions to target positions
        target_positions = np.tanh(pred_series * scale)
        actual_positions = pd.Series(0.0, index=pred_series.index)
        
        for i, date in enumerate(pred_series.index):
            current_target = target_positions.iloc[i]
            
            if i == 0:
                change = np.clip(current_target, -max_change, max_change)
                if abs(change) >= min_tick_size:
                    change = np.round(change / min_tick_size) * min_tick_size
                else:
                    change = 0.0
                actual_positions.iloc[i] = change
            else:
                current_position = actual_positions.iloc[i-1]
                desired_change = current_target - current_position
                capped_change = np.clip(desired_change, -max_change, max_change)
                
                if abs(capped_change) >= min_tick_size:
                    capped_change = np.round(capped_change / min_tick_size) * min_tick_size
                else:
                    capped_change = 0.0
                
                actual_positions.iloc[i] = current_position + capped_change
        
        return target_positions, actual_positions.clip(-1.0, 1.0)
    
    # Simple parameter optimization if training data available
    best_params = {'scale': tanh_scale, 'max_change': max_daily_change, 'min_tick': min_tick}
    
    if returns_train is not None and len(returns_train) > 50:
        # print("🔍 Optimizing smooth portfolio parameters...")
        
        train_predictions = predictions.loc[predictions.index.intersection(returns_train.index)]
        train_returns = returns_train.loc[train_predictions.index]
        
        if len(train_predictions) >= 50:
            best_sharpe = -np.inf
            
            # Simple grid search
            for scale in [1.0, 1.5, 2.0, 2.5, 3.0]:
                for max_change in [0.15, 0.2, 0.25, 0.3]:
                    for min_tick_val in [0.01, 0.02]:
                        try:
                            _, actual_pos = create_smooth_positions(
                                train_predictions, scale, max_change, min_tick_val
                            )
                            
                            # Calculate strategy returns
                            pos_aligned = actual_pos[:-1]
                            ret_aligned = train_returns[1:]
                            common_idx = pos_aligned.index.intersection(ret_aligned.index)
                            
                            if len(common_idx) > 20:
                                strategy_returns = pos_aligned.loc[common_idx] * ret_aligned.loc[common_idx]
                                
                                if strategy_returns.std() > 0:
                                    sharpe = strategy_returns.mean() / strategy_returns.std() * np.sqrt(252)
                                    if sharpe > best_sharpe:
                                        best_sharpe = sharpe
                                        best_params = {
                                            'scale': scale, 
                                            'max_change': max_change, 
                                            'min_tick': min_tick_val
                                        }
                        except:
                            continue
            
            # print(f"✅ Best parameters: scale={best_params['scale']:.2f}, "
            #       f"max_change={best_params['max_change']:.2f}")
    
    # Create final positions
    target_positions, actual_positions = create_smooth_positions(
        predictions, best_params['scale'], best_params['max_change'], best_params['min_tick']
    )
    
    # Statistics
    long_count = (actual_positions > 0).sum()
    short_count = (actual_positions < 0).sum()
    neutral_count = (actual_positions == 0).sum()
    
    # print(f"📊 Smooth portfolio: {long_count} long, {short_count} short, {neutral_count} neutral")
    # print(f"📊 Position range: [{actual_positions.min():.3f}, {actual_positions.max():.3f}]")
    
    return {
        'portfolio': actual_positions,
        'target_positions': target_positions,
        'predictions': predictions,
        'best_parameters': best_params,
        'method_info': {
            'type': 'smooth',
            'long_count': long_count,
            'short_count': short_count,
            'neutral_count': neutral_count,
            'avg_position': actual_positions.abs().mean()
        }
    }


def create_intensity_portfolio(predictions: pd.Series, config) -> Dict:
    """
    Create intensity-based bucketed portfolio with discrete position levels.
    
    Args:
        predictions: Predicted returns series
        config: Configuration object containing position_buckets and other parameters
        
    Returns:
        Dictionary with portfolio positions and statistics
    """
    # Get configuration parameters
    position_buckets = getattr(config, 'position_buckets', 
                              [-1.0, -0.8, -0.6, -0.4, -0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 1.0])
    
    # Calculate signal intensity (z-scores)
    z_scores = calculate_signal_intensity(predictions)
    
    # Map z-scores to position buckets
    positions = pd.Series(0.0, index=predictions.index)
    
    # Simple percentile-based bucket assignment
    if len(predictions) > 10:
        positive_buckets = [b for b in position_buckets if b > 0]
        negative_buckets = [b for b in position_buckets if b < 0]
        
        # Map positive predictions
        positive_mask = predictions > 0
        if positive_mask.any():
            pos_preds = predictions[positive_mask]
            pos_quantiles = np.linspace(0, 1, len(positive_buckets) + 1)[1:]
            pos_thresholds = pos_preds.quantile(pos_quantiles)
            
            for i, bucket in enumerate(positive_buckets):
                if i == 0:
                    mask = positive_mask & (predictions <= pos_thresholds.iloc[i])
                else:
                    mask = positive_mask & (predictions > pos_thresholds.iloc[i-1]) & (predictions <= pos_thresholds.iloc[i])
                positions[mask] = bucket
        
        # Map negative predictions
        negative_mask = predictions < 0
        if negative_mask.any():
            neg_preds = predictions[negative_mask]
            neg_quantiles = np.linspace(0, 1, len(negative_buckets) + 1)[1:]
            neg_thresholds = neg_preds.quantile(neg_quantiles)
            
            for i, bucket in enumerate(negative_buckets[::-1]):
                if i == 0:
                    mask = negative_mask & (predictions >= neg_thresholds.iloc[-(i+1)])
                else:
                    mask = negative_mask & (predictions < neg_thresholds.iloc[-(i)]) & (predictions >= neg_thresholds.iloc[-(i+1)])
                positions[mask] = bucket
    
    # Statistics
    long_count = (positions > 0).sum()
    short_count = (positions < 0).sum()
    neutral_count = (positions == 0).sum()
    
    # print(f"📊 Intensity portfolio: {long_count} long, {short_count} short, {neutral_count} neutral")
    # print(f"📊 Average intensity: {positions.abs().mean():.3f}")
    
    return {
        'portfolio': positions,
        'predictions': predictions,
        'method_info': {
            'type': 'intensity',
            'long_count': long_count,
            'short_count': short_count,
            'neutral_count': neutral_count,
            'position_buckets': position_buckets
        }
    }


def create_smooth_portfolio_qp(predictions: pd.Series, config, 
                              returns_train: pd.Series = None, 
                              previous_positions: pd.Series = None) -> Dict:
    """
    Create portfolio using Quadratic Programming with total return optimization.
    
    Objective: Maximize total return - lambda * turnover penalty (changed from Sharpe ratio)
    
    Args:
        predictions: Predicted returns series
        config: Configuration object
        returns_train: Training returns for optimization
        previous_positions: Previous positions for smooth transitions
        
    Returns:
        Dictionary with optimized portfolio positions
    """
    try:
        from scipy.optimize import minimize
    except ImportError:
        print("⚠️ scipy not available, falling back to simple portfolio")
        return create_simple_portfolio(predictions, config)
    
    if predictions.empty:
        return {
            'portfolio': pd.Series(dtype=float),
            'method_info': {'type': 'smooth_qp', 'error': 'Empty predictions'}
        }
    
    # Configuration
    turnover_lambda = getattr(config, 'turnover_lambda', 0.05)
    tick_size = getattr(config, 'tick_size', 0.2)
    ema_alpha = getattr(config, 'ema_alpha', 0.3)
    
    def create_qp_positions(pred_values, ret_values=None, prev_pos=None):
        """Create positions using QP optimization with total return objective."""
        n = len(pred_values)
        positions = np.zeros(n)
        
        start_pos = 0.0
        if prev_pos is not None and len(prev_pos) > 0:
            start_pos = prev_pos[-1]
        
        # print(f"📊 QP optimization with total return objective")
        
        # QP optimization for first position
        if ret_values is not None and len(ret_values) > 5:
            try:
                def qp_objective(pos):
                    """Total return objective (changed from Sharpe ratio)."""
                    # Expected return from position and prediction
                    scaled_prediction = pred_values[0] * 500  # Aggressive scaling
                    expected_return = pos * scaled_prediction
                    
                    # Add momentum factor
                    momentum_boost = 0.0
                    if len(ret_values) > 3:
                        recent_momentum = np.mean(ret_values[-3:])
                        momentum_boost = pos * recent_momentum * 100
                    
                    # Turnover penalty
                    turnover_penalty = turnover_lambda * (pos - start_pos) ** 2
                    
                    # Maximize total return: expected return + momentum - turnover
                    total_return_objective = expected_return + momentum_boost - turnover_penalty
                    return -total_return_objective  # Minimize negative for maximize
                
                result = minimize(
                    qp_objective,
                    x0=[start_pos],
                    method='L-BFGS-B',
                    bounds=[(-1.0, 1.0)]
                )
                
                if result.success:
                    optimal_start_pos = result.x[0]
                    print(f"✅ QP total return optimization: {start_pos:.3f} → {optimal_start_pos:.3f}")
                else:
                    optimal_start_pos = np.clip(pred_values[0] * 500, -1.0, 1.0)
                    print(f"⚠️ QP failed, using scaled prediction: {optimal_start_pos:.3f}")
            except Exception as e:
                print(f"⚠️ QP optimization failed: {e}")
                optimal_start_pos = np.clip(pred_values[0] * 500, -1.0, 1.0)
        else:
            optimal_start_pos = np.clip(pred_values[0] * 500, -1.0, 1.0)
            # print(f"📊 No training data, using scaled prediction: {optimal_start_pos:.3f}")
        
        # Apply tick size
        optimal_start_pos = np.round(optimal_start_pos / tick_size) * tick_size
        positions[0] = np.clip(optimal_start_pos, -1.0, 1.0)
        
        # EMA drift for subsequent positions  
        for i in range(1, n):
            target_pos = np.clip(pred_values[i] * 500, -1.0, 1.0)
            
            # Enhanced EMA with momentum
            current_pos = positions[i-1]
            enhanced_alpha = min(ema_alpha * 1.5, 0.8)
            ema_position = (1 - enhanced_alpha) * current_pos + enhanced_alpha * target_pos
            
            # Apply tick-based adjustment
            desired_change = ema_position - current_pos
            if abs(desired_change) >= tick_size / 3:
                step_direction = np.sign(desired_change)
                step_size = min(abs(desired_change), tick_size * 6)
                change = step_direction * step_size
            else:
                change = desired_change * 0.7
            
            positions[i] = np.clip(current_pos + change, -1.0, 1.0)
        
        return positions
    
    # Create positions
    if returns_train is not None and len(returns_train) > 20:
        train_ret = returns_train.loc[returns_train.index.intersection(predictions.index)]
        ret_values = train_ret.values if len(train_ret) > 0 else None
    else:
        ret_values = None
    
    prev_pos_values = previous_positions.values if previous_positions is not None else None
    positions = create_qp_positions(predictions.values, ret_values, prev_pos_values)
    
    # Create portfolio series
    portfolio = pd.Series(positions, index=predictions.index)
    
    # Statistics
    long_count = (portfolio > 0.01).sum()
    short_count = (portfolio < -0.01).sum()
    neutral_count = len(portfolio) - long_count - short_count
    
    # print(f"📊 QP portfolio: {long_count} long, {short_count} short, {neutral_count} neutral")
    # print(f"📊 Portfolio stats: min={portfolio.min():.3f}, max={portfolio.max():.3f}")
    
    return {
        'portfolio': portfolio,
        'method_info': {
            'type': 'smooth_qp',
            'objective': 'total_return',  # Changed from 'sharpe_ratio'
            'tick_size': tick_size,
            'long_count': long_count,
            'short_count': short_count,
            'neutral_count': neutral_count
        }
    }


def create_portfolio_by_method(portfolio_method: str, predictions: pd.Series, config, data: pd.DataFrame) -> pd.Series:
    """Create portfolio using specified method."""
    try:
        if portfolio_method == 'simple':
            portfolio_result = create_simple_portfolio(predictions, config)
            return portfolio_result['portfolio']
            
        elif portfolio_method == 'smooth':
            # Get training returns for optimization
            pred_start = predictions.index[0]
            train_end = pred_start - pd.Timedelta(days=1)
            lookback_months = getattr(config, 'lookback_window', 6)
            train_start = train_end - pd.Timedelta(days=lookback_months * 30)
            
            available_train_data = data['Returns'].loc[train_start:train_end]
            # print(f"📊 Training data for smooth: {len(available_train_data)} points")
            
            portfolio_result = create_smooth_portfolio(predictions, config, available_train_data)
            return portfolio_result['portfolio']
            
        elif portfolio_method == 'intensity':
            portfolio_result = create_intensity_portfolio(predictions, config)
            # print(f"📊 Portfolio stats: min={portfolio_result['portfolio'].min():.6f}, "
            #       f"max={portfolio_result['portfolio'].max():.6f}, "
            #       f"mean abs={portfolio_result['portfolio'].abs().mean():.6f}")
            return portfolio_result['portfolio']
            
        elif portfolio_method == 'smooth_qp':
            # Get training returns for QP optimization
            pred_start = predictions.index[0]
            train_end = pred_start - pd.Timedelta(days=1)
            lookback_months = getattr(config, 'lookback_window', 6)
            train_start = train_end - pd.Timedelta(days=lookback_months * 30)
            
            available_train_data = data['Returns'].loc[train_start:train_end]
            # print(f"📊 Training data for QP: {len(available_train_data)} points")
            
            portfolio_result = create_smooth_portfolio_qp(
                predictions, config, available_train_data, previous_positions=None
            )
            return portfolio_result['portfolio']
            
        else:
            print(f"⚠️ Unknown portfolio method '{portfolio_method}', using simple")
            portfolio_result = create_simple_portfolio(predictions, config)
            return portfolio_result['portfolio']
            
    except Exception as e:
        print(f"⚠️ Portfolio creation failed: {e}. Using simple positions...")
        return pd.Series(np.sign(predictions), index=predictions.index)