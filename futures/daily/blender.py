# -*- coding: utf-8 -*-
"""
Strategy Blending Module

Optimize combination of multiple strategies.

@author: CMBC
"""
import pandas as pd
import numpy as np
from typing import Dict
from scipy.optimize import minimize


class StrategyBlender:
    """Optimize combination of multiple strategies."""
    
    def __init__(self, strategy_returns: Dict[str, pd.Series]):
        """
        Initialize strategy blender.
        
        Args:
            strategy_returns: Dict mapping strategy name to returns series
        """
        self.strategy_returns = pd.DataFrame(strategy_returns)
        self.optimal_weights = None
    
    def optimize_weights(
        self, 
        objective: str = 'sharpe',
        max_drawdown_constraint: float = None,
        min_weight: float = 0.0,
        max_weight: float = 1.0
    ) -> Dict[str, float]:
        """
        Optimize strategy weights.
        
        Args:
            objective: 'sharpe', 'return', or 'min_vol'
            max_drawdown_constraint: Maximum allowed drawdown (optional)
            min_weight: Minimum weight per strategy (e.g., 0.2 for 20% min)
            max_weight: Maximum weight per strategy (e.g., 0.8 for 80% max)
            
        Returns:
            Dict of optimal weights
        """
        n_strategies = len(self.strategy_returns.columns)
        
        def portfolio_returns(weights):
            """Calculate portfolio returns."""
            return (self.strategy_returns @ weights)
        
        def sharpe_ratio(weights):
            """Calculate negative Sharpe ratio (for minimization)."""
            ret = portfolio_returns(weights)
            ann_return = ret.mean() * 252
            ann_vol = ret.std() * np.sqrt(252)
            return -ann_return / ann_vol if ann_vol > 0 else 0
        
        def volatility(weights):
            """Calculate portfolio volatility."""
            ret = portfolio_returns(weights)
            return ret.std() * np.sqrt(252)
        
        def negative_return(weights):
            """Calculate negative return (for minimization)."""
            ret = portfolio_returns(weights)
            return -ret.mean() * 252
        
        def max_drawdown(weights):
            """Calculate maximum drawdown."""
            ret = portfolio_returns(weights)
            cum_ret = (1 + ret).cumprod()
            running_max = cum_ret.expanding().max()
            dd = ((cum_ret - running_max) / running_max).min()
            return dd
        
        # Set objective function
        if objective == 'sharpe':
            obj_func = sharpe_ratio
        elif objective == 'return':
            obj_func = negative_return
        elif objective == 'min_vol':
            obj_func = volatility
        else:
            raise ValueError(f"Unknown objective: {objective}")
        
        # Constraints
        constraints = [
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}  # Weights sum to 1
        ]
        
        # Add drawdown constraint if specified
        if max_drawdown_constraint:
            constraints.append({
                'type': 'ineq',
                'fun': lambda w: max_drawdown_constraint - abs(max_drawdown(w))
            })
        
        # Bounds: weights between min_weight and max_weight
        bounds = [(min_weight, max_weight) for _ in range(n_strategies)]
        
        # Initial guess: equal weights
        w0 = np.ones(n_strategies) / n_strategies
        
        # Optimize
        result = minimize(
            obj_func,
            w0,
            method='SLSQP',
            bounds=bounds,
            constraints=constraints,
            options={'maxiter': 1000}
        )
        
        if not result.success:
            print(f"Warning: Optimization did not converge: {result.message}")
        
        self.optimal_weights = dict(zip(self.strategy_returns.columns, result.x))
        return self.optimal_weights
    
    def get_blended_returns(self, weights: Dict[str, float] = None) -> pd.Series:
        """
        Get blended strategy returns.
        
        Args:
            weights: Strategy weights (uses optimal if None)
            
        Returns:
            Series of blended returns
        """
        if weights is None:
            weights = self.optimal_weights
        
        if weights is None:
            raise ValueError("No weights provided and no optimal weights calculated")
        
        weights_array = np.array([weights[col] for col in self.strategy_returns.columns])
        return (self.strategy_returns @ weights_array)
    
    def calculate_correlation(self) -> pd.DataFrame:
        """
        Calculate correlation matrix of strategy returns.
        
        Returns:
            Correlation matrix DataFrame
        """
        return self.strategy_returns.corr()
    
    def optimize_rolling_weights(
        self,
        lookback_window: int = 126,  # ~6 months
        min_correlation: float = -0.3,
        objective: str = 'sharpe'
    ) -> pd.DataFrame:
        """
        Calculate optimal weights using rolling window optimization.
        
        Args:
            lookback_window: Days to use for optimization
            min_correlation: Minimum required correlation for orthogonality
            objective: Optimization objective
            
        Returns:
            DataFrame with columns for each strategy's weight over time
        """
        n_periods = len(self.strategy_returns)
        n_strategies = len(self.strategy_returns.columns)
        
        weights_history = []
        
        for i in range(lookback_window, n_periods):
            # Get window data
            window_data = self.strategy_returns.iloc[i-lookback_window:i]
            
            # Create temporary blender for this window
            temp_blender = StrategyBlender({
                col: window_data[col] for col in window_data.columns
            })
            
            # Optimize weights
            try:
                optimal = temp_blender.optimize_weights(objective=objective)
                weights_history.append(optimal)
            except:
                # Fallback to equal weights
                weights_history.append({
                    col: 1.0/n_strategies for col in self.strategy_returns.columns
                })
        
        # Create DataFrame with proper index
        weights_df = pd.DataFrame(
            weights_history,
            index=self.strategy_returns.index[lookback_window:]
        )
        
        return weights_df
    
    def get_rolling_blended_returns(
        self,
        lookback_window: int = 126,
        objective: str = 'sharpe'
    ) -> pd.Series:
        """
        Get blended returns using rolling optimal weights.
        
        Args:
            lookback_window: Days to use for optimization
            objective: Optimization objective
            
        Returns:
            Series of blended returns
        """
        weights_df = self.optimize_rolling_weights(lookback_window, objective=objective)
        
        # Apply weights to get blended returns
        blended = pd.Series(0.0, index=weights_df.index)
        
        for i, idx in enumerate(weights_df.index):
            weights_array = weights_df.iloc[i].values
            returns_array = self.strategy_returns.loc[idx].values
            blended.loc[idx] = np.dot(weights_array, returns_array)
        
        return blended
    
    def analyze_diversification_benefit(self) -> Dict[str, float]:
        """
        Analyze diversification benefit from blending strategies.
        
        Returns:
            Dict with correlation, individual Sharpes, and blended Sharpe
        """
        results = {}
        
        # Calculate correlation
        corr_matrix = self.calculate_correlation()
        if len(corr_matrix.columns) == 2:
            results['correlation'] = corr_matrix.iloc[0, 1]
        
        # Individual strategy Sharpes
        for col in self.strategy_returns.columns:
            ret = self.strategy_returns[col]
            sharpe = ret.mean() / ret.std() * np.sqrt(252) if ret.std() > 0 else 0
            results[f'{col}_sharpe'] = sharpe
        
        # Optimize and get blended Sharpe
        if self.optimal_weights is None:
            self.optimize_weights(objective='sharpe')
        
        blended = self.get_blended_returns()
        blended_sharpe = blended.mean() / blended.std() * np.sqrt(252) if blended.std() > 0 else 0
        results['blended_sharpe'] = blended_sharpe
        results['optimal_weights'] = self.optimal_weights
        
        # Calculate diversification ratio
        individual_avg = np.mean([results[f'{col}_sharpe'] for col in self.strategy_returns.columns])
        results['sharpe_improvement'] = blended_sharpe - individual_avg
        
        return results
