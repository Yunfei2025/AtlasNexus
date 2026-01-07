#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Signal Smoothing Module for Factor-Based Strategies
Implements quadratic tracking with turnover penalty to reduce signal flipping.
"""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional
from scipy.optimize import minimize


def apply_signal_smoothing(predictions: pd.Series, config, 
                         optimize_parameters: bool = False,
                         training_data: Optional[Dict] = None) -> pd.Series:
    """Apply signal smoothing to reduce frequent signal flips"""
    if not getattr(config, 'signal_smoothing', False) or len(predictions) < 3:
        return predictions
        
    try:
        smoothing_method = getattr(config, 'signal_smoothing_method', 'hysteresis')
        
        # Optimize parameters if requested
        if optimize_parameters and training_data:
            config = _optimize_parameters(training_data, config, smoothing_method)
            # print(f"🔧 Using optimized parameters for {smoothing_method}")
        
        # Apply smoothing method
        smoothing_methods = {
            'quadratic_tracking': apply_quadratic_tracking,
            'adaptive_quadratic': apply_adaptive_quadratic,
            'regime_aware_tracking': apply_regime_aware_tracking
        }
        
        method_func = smoothing_methods.get(smoothing_method, apply_hysteresis_smoothing)
        return method_func(predictions, config)
        
    except Exception as e:
        print(f"⚠️ Signal smoothing failed: {e}")
        return predictions


def apply_hysteresis_smoothing(predictions: pd.Series, config) -> pd.Series:
    """Simple hysteresis smoothing method"""
    smoothing_window = getattr(config, 'signal_smoothing_window', 3)
    hysteresis_upper = getattr(config, 'hysteresis_upper', 0.15)
    hysteresis_lower = getattr(config, 'hysteresis_lower', 0.08)
    persistence_threshold = getattr(config, 'signal_persistence_threshold', 2)
    tanh_scale = getattr(config, 'tanh_scale', 4.0)
    
    # Exponential weighted moving average
    ewm_smoothed = predictions.ewm(span=smoothing_window, min_periods=1).mean()
    
    # Apply hysteresis with state persistence
    result = predictions.copy()
    current_state = 0
    persistence_count = 0
    
    for i, signal in enumerate(ewm_smoothed):
        # Determine target state
        if signal > hysteresis_upper:
            target_state = 1
        elif signal < -hysteresis_upper:
            target_state = -1
        elif abs(signal) < hysteresis_lower:
            target_state = 0
        else:
            target_state = current_state
        
        # State persistence
        if target_state == current_state:
            persistence_count += 1
        else:
            persistence_count = 1
            
        if persistence_count >= persistence_threshold:
            current_state = target_state
        
        # Apply tanh mapping
        if current_state != 0:
            state_confidence = min(persistence_count / persistence_threshold, 2.0)
            effective_scale = tanh_scale * state_confidence
            result.iloc[i] = current_state * np.tanh(abs(signal) * effective_scale)
        else:
            result.iloc[i] = np.tanh(signal * tanh_scale * 0.5)
    
    _report_stats(predictions, result, "Hysteresis")
    return result


def apply_quadratic_tracking(predictions: pd.Series, config) -> pd.Series:
    """Quadratic tracking with turnover penalty - NO LOOK-AHEAD BIAS"""
    try:
        turnover_penalty = getattr(config, 'turnover_penalty_lambda', 0.5)
        tracking_weight = getattr(config, 'tracking_weight', 1.0)
        
        n = len(predictions)
        smoothed_values = np.zeros(n)
        raw_signals = predictions.values
        
        # Process sequentially to avoid look-ahead bias
        for i in range(n):
            if i == 0:
                smoothed_values[i] = raw_signals[i]
                continue
            
            # Only use data up to current time point i
            window_size = min(i + 1, 50)  # Limit window size for efficiency
            start_idx = max(0, i - window_size + 1)
            
            # Local data up to current time
            local_raw = raw_signals[start_idx:i+1]
            local_n = len(local_raw)
            
            if local_n <= 2:
                # Simple exponential smoothing for short series
                alpha = 1.0 / (1.0 + turnover_penalty)
                smoothed_values[i] = alpha * raw_signals[i] + (1 - alpha) * smoothed_values[i-1]
                continue
            
            # Build optimization matrices for local window only
            P_track = tracking_weight * np.eye(local_n)
            q_track = -2 * tracking_weight * local_raw
            
            # Turnover penalty matrix (only for local window)
            D = np.eye(local_n) - np.eye(local_n, k=-1)
            P_turnover = turnover_penalty * D.T @ D
            
            # Combined objective
            P = P_track + P_turnover
            q = q_track
            
            # Solve local optimization
            def objective(x):
                return 0.5 * x.T @ P @ x + q.T @ x
            
            # Initial guess: exponentially weighted values up to current time
            x0 = np.array([smoothed_values[j] for j in range(start_idx, i+1)])
            x0[-1] = raw_signals[i]  # Current raw signal as starting point
            
            try:
                result = minimize(objective, x0, method='BFGS')
                if result.success:
                    smoothed_values[i] = result.x[-1]  # Take only the current time value
                else:
                    # Fallback to exponential smoothing
                    alpha = 1.0 / (1.0 + turnover_penalty)
                    smoothed_values[i] = alpha * raw_signals[i] + (1 - alpha) * smoothed_values[i-1]
            except:
                # Fallback to exponential smoothing
                alpha = 1.0 / (1.0 + turnover_penalty)
                smoothed_values[i] = alpha * raw_signals[i] + (1 - alpha) * smoothed_values[i-1]
        
        smoothed_signals = pd.Series(smoothed_values, index=predictions.index)
        _report_stats(predictions, smoothed_signals, "Quadratic Tracking (No Look-Ahead)")
        
        return smoothed_signals
        
    except Exception as e:
        print(f"⚠️ Quadratic tracking failed: {e}")
        return predictions


def apply_adaptive_quadratic(predictions: pd.Series, config) -> pd.Series:
    """Adaptive quadratic tracking with time-varying penalty"""
    try:
        base_penalty = getattr(config, 'base_turnover_penalty', 0.3)
        window = getattr(config, 'adaptive_window', 10)
        
        n = len(predictions)
        smoothed_values = np.zeros(n)
        
        for i in range(n):
            if i == 0:
                smoothed_values[i] = predictions.iloc[i]
                continue
                
            # Calculate adaptive penalty based on local volatility
            start_idx = max(0, i - window + 1)
            local_data = predictions.iloc[start_idx:i+1]
            local_vol = local_data.std()
            
            # Adaptive penalty
            penalty = base_penalty + 2.0 * local_vol
            
            # Simple exponential smoothing with adaptive penalty
            alpha = 1.0 / (1.0 + penalty)
            smoothed_values[i] = alpha * predictions.iloc[i] + (1 - alpha) * smoothed_values[i-1]
        
        smoothed_signals = pd.Series(smoothed_values, index=predictions.index)
        _report_stats(predictions, smoothed_signals, "Adaptive Quadratic")
        
        return smoothed_signals
        
    except Exception as e:
        print(f"⚠️ Adaptive quadratic failed: {e}")
        return predictions


def apply_regime_aware_tracking(predictions: pd.Series, config) -> pd.Series:
    """Regime-aware quadratic tracking - NO LOOK-AHEAD BIAS"""
    try:
        regime_window = getattr(config, 'regime_detection_window', 20)
        low_vol_penalty = getattr(config, 'low_vol_penalty', 0.2)
        high_vol_penalty = getattr(config, 'high_vol_penalty', 0.8)
        
        n = len(predictions)
        smoothed_values = np.zeros(n)
        
        # Calculate rolling global volatility to avoid look-ahead bias
        rolling_global_vol = predictions.expanding().std()
        
        for i in range(n):
            if i == 0:
                smoothed_values[i] = predictions.iloc[i]
                continue
                
            # Detect regime based on local volatility using only past data
            start_idx = max(0, i - regime_window + 1)
            local_data = predictions.iloc[start_idx:i+1]  # Only up to current time
            local_vol = local_data.std()
            
            # Use rolling global volatility up to current time (no look-ahead)
            current_global_vol = rolling_global_vol.iloc[i]
            
            # Select penalty based on regime
            if local_vol < current_global_vol * 0.5:
                penalty = low_vol_penalty  # Low volatility regime
            else:
                penalty = high_vol_penalty  # High volatility regime
            
            # Apply smoothing
            alpha = 1.0 / (1.0 + penalty)
            smoothed_values[i] = alpha * predictions.iloc[i] + (1 - alpha) * smoothed_values[i-1]
        
        smoothed_signals = pd.Series(smoothed_values, index=predictions.index)
        _report_stats(predictions, smoothed_signals, "Regime-Aware (No Look-Ahead)")
        
        return smoothed_signals
        
    except Exception as e:
        print(f"⚠️ Regime-aware tracking failed: {e}")
        return predictions
        
        smoothed_signals = pd.Series(smoothed_values, index=predictions.index)
        _report_stats(predictions, smoothed_signals, "Regime-Aware")
        
        return smoothed_signals
        
    except Exception as e:
        print(f"⚠️ Regime-aware tracking failed: {e}")
        return predictions


def _count_signal_flips(signals: pd.Series) -> int:
    """Count the number of signal direction changes"""
    if len(signals) < 2:
        return 0
    directions = np.sign(signals)
    return sum(directions.iloc[i] != directions.iloc[i-1] for i in range(1, len(directions)))


def _report_stats(raw_signals: pd.Series, smooth_signals: pd.Series, method_name: str):
    """Report smoothing statistics"""
    raw_flips = _count_signal_flips(raw_signals)
    smooth_flips = _count_signal_flips(smooth_signals)
    reduction = (raw_flips - smooth_flips) / max(raw_flips, 1) * 100
    correlation = raw_signals.corr(smooth_signals)
    
    if np.isnan(correlation):
        correlation = 0.0
    
    # print(f"📊 {method_name} smoothing results:")
    # print(f"   - Signal flips: {raw_flips} → {smooth_flips} ({reduction:.1f}% reduction)")
    # print(f"   - Signal correlation: {correlation:.3f}")


def _optimize_parameters(training_data: Dict, config, method: str) -> object:
    """Optimize smoothing parameters using training data"""
    try:
        train_predictions = training_data.get('predictions')
        train_returns = training_data.get('returns')
        
        if train_predictions is None or train_returns is None or len(train_predictions) < 10:
            print("⚠️ Insufficient training data for optimization")
            return config
        
        iterations = getattr(config, 'smoothing_optimization_iterations', 30)
        best_score = -float('inf')
        best_params = {}
        
        # Define parameter ranges based on method
        if method == 'quadratic_tracking':
            param_ranges = {
                'turnover_penalty_lambda': (0.1, 1.5),
                'tracking_weight': (0.5, 2.0)
            }
        elif method == 'adaptive_quadratic':
            param_ranges = {
                'base_turnover_penalty': (0.1, 0.8),
                'adaptive_window': (5, 20)
            }
        elif method == 'regime_aware_tracking':
            param_ranges = {
                'regime_detection_window': (10, 30),
                'low_vol_penalty': (0.05, 0.4),
                'high_vol_penalty': (0.4, 1.2)
            }
        else:
            return config
        
        # Random search optimization
        for i in range(iterations):
            # Sample random parameters
            test_params = {}
            for param, (min_val, max_val) in param_ranges.items():
                if 'window' in param:
                    test_params[param] = int(np.random.uniform(min_val, max_val))
                else:
                    test_params[param] = np.random.uniform(min_val, max_val)
            
            # Test parameters
            try:
                test_config = _create_test_config(config, test_params)
                
                if method == 'quadratic_tracking':
                    smoothed = apply_quadratic_tracking(train_predictions, test_config)
                elif method == 'adaptive_quadratic':
                    smoothed = apply_adaptive_quadratic(train_predictions, test_config)
                else:
                    smoothed = apply_regime_aware_tracking(train_predictions, test_config)
                
                # Calculate performance score
                score = _calculate_performance(smoothed, train_returns)
                
                if score > best_score:
                    best_score = score
                    best_params = test_params.copy()
                    
            except:
                continue
        
        # Create optimized config
        optimized_config = _create_test_config(config, best_params)
        # print(f"📈 Best Sharpe ratio: {best_score:.4f}")
        # print(f"📊 Best parameters: {best_params}")
        
        return optimized_config
        
    except Exception as e:
        print(f"⚠️ Parameter optimization failed: {e}")
        return config


def _create_test_config(base_config, params: Dict):
    """Create test configuration with new parameters"""
    class TestConfig:
        def __init__(self, base_config, params):
            # Copy base config attributes
            for attr in dir(base_config):
                if not attr.startswith('_'):
                    try:
                        setattr(self, attr, getattr(base_config, attr))
                    except:
                        pass
            
            # Override with test parameters
            for key, value in params.items():
                setattr(self, key, value)
    
    return TestConfig(base_config, params)


def _calculate_performance(predictions: pd.Series, returns: pd.Series) -> float:
    """Calculate Sharpe ratio for performance evaluation"""
    try:
        # Align series
        common_index = predictions.index.intersection(returns.index)
        if len(common_index) < 5:
            return -float('inf')
        
        predictions = predictions.loc[common_index]
        returns = returns.loc[common_index]
        
        # Calculate strategy returns
        positions = np.sign(predictions)
        strategy_returns = positions.shift(1) * returns
        strategy_returns = strategy_returns.dropna()
        
        if len(strategy_returns) < 3 or strategy_returns.std() == 0:
            return -float('inf')
        
        return strategy_returns.mean() / strategy_returns.std() * np.sqrt(252)
        
    except:
        return -float('inf')


def analyze_signal_quality(raw_signals: pd.Series, smooth_signals: pd.Series) -> Dict[str, Any]:
    """Analyze signal quality improvement from smoothing"""
    if raw_signals.empty or smooth_signals.empty:
        return {}
    
    try:
        raw_flips = _count_signal_flips(raw_signals)
        smooth_flips = _count_signal_flips(smooth_signals)
        correlation = raw_signals.corr(smooth_signals)
        
        if np.isnan(correlation):
            correlation = 0.0
        
        flip_reduction = (raw_flips - smooth_flips) / max(raw_flips, 1) * 100
        
        return {
            'raw_signal_flips': raw_flips,
            'smooth_signal_flips': smooth_flips,
            'flip_reduction_pct': flip_reduction,
            'signal_correlation': correlation
        }
        
    except Exception as e:
        print(f"⚠️ Signal quality analysis failed: {e}")
        return {}
