# -*- coding: utf-8 -*-
"""
Backtesting Module

Performance evaluation and strategy comparison.

@author: CMBC
"""
import pandas as pd
import numpy as np
from typing import Dict


class StrategyBacktester:
    """Backtest trading strategies."""
    
    def __init__(self, data: pd.DataFrame, initial_capital: float = 1000000):
        """
        Initialize backtester.
        
        Args:
            data: OHLC DataFrame
            initial_capital: Initial capital
        """
        self.data = data
        self.initial_capital = initial_capital
    
    def run_backtest(self, strategy_returns: pd.Series) -> Dict:
        """
        Run backtest and calculate performance metrics.
        
        Args:
            strategy_returns: Series of strategy returns
            
        Returns:
            Dict of performance metrics
        """
        # Calculate cumulative returns
        cum_returns = (1 + strategy_returns).cumprod()
        
        # Calculate metrics
        total_return = cum_returns.iloc[-1] - 1
        n_years = len(strategy_returns) / 252
        annualized_return = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0
        
        # Volatility
        annualized_vol = strategy_returns.std() * np.sqrt(252)
        
        # Sharpe ratio (assuming 0% risk-free rate)
        sharpe_ratio = annualized_return / annualized_vol if annualized_vol > 0 else 0
        
        # Maximum drawdown
        running_max = cum_returns.expanding().max()
        drawdown = (cum_returns - running_max) / running_max
        max_drawdown = drawdown.min()
        
        # Win rate
        winning_trades = (strategy_returns > 0).sum()
        total_trades = (strategy_returns != 0).sum()
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        return {
            'total_return': total_return,
            'annualized_return': annualized_return,
            'annualized_volatility': annualized_vol,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,
            'win_rate': win_rate,
            'n_trades': total_trades,
            'cum_returns': cum_returns
        }
    
    def compare_strategies(self, strategies: Dict[str, pd.Series]) -> pd.DataFrame:
        """
        Compare multiple strategies.
        
        Args:
            strategies: Dict mapping strategy name to returns series
            
        Returns:
            DataFrame of comparison metrics
        """
        results = {}
        for name, returns in strategies.items():
            metrics = self.run_backtest(returns)
            results[name] = {
                'Annual Return': f"{metrics['annualized_return']:.2%}",
                'Annual Vol': f"{metrics['annualized_volatility']:.2%}",
                'Sharpe Ratio': f"{metrics['sharpe_ratio']:.3f}",
                'Max Drawdown': f"{metrics['max_drawdown']:.2%}",
                'Win Rate': f"{metrics['win_rate']:.2%}",
                'N Trades': metrics['n_trades']
            }
        
        return pd.DataFrame(results).T
