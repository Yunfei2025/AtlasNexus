# -*- coding: utf-8 -*-
"""
Futures Portfolio Strategy System

Implements:
1. Diversified portfolio selection based on correlation analysis
2. Trend-following and mean-reversion strategies
3. Backtesting framework
4. Strategy combination optimization

@author: CMBC
Created on Thu Dec 11 19:08:28 2025
"""
import os
import sys
from pathlib import Path
import pandas as pd
import numpy as np
from typing import Dict, Tuple, List
from scipy.optimize import minimize

# Add project path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from settings.paths import DIR_INPUT

# ============================================================================
# 1. DATA LOADING & CORRELATION ANALYSIS
# ============================================================================

class FuturesPortfolioSelector:
    """Select diversified futures based on correlation analysis."""
    
    def __init__(self, data: Dict[str, pd.DataFrame], lookback_months: int = 12):
        """
        Initialize portfolio selector.
        
        Args:
            data: Dict mapping ticker to OHLC DataFrame
            lookback_months: Lookback period for correlation (months)
        """
        self.data = data
        self.lookback_months = lookback_months
        
    def calculate_returns(self, ticker: str, end_date: pd.Timestamp) -> pd.Series:
        """Calculate returns for a ticker up to end_date."""
        if ticker not in self.data:
            return pd.Series(dtype=float)
        
        df = self.data[ticker]
        if 'close' not in df.columns:
            return pd.Series(dtype=float)
        
        # Filter data up to end_date
        df_filtered = df[df.index <= end_date].copy()
        
        # Calculate returns
        returns = df_filtered['close'].pct_change().dropna()
        return returns
    
    def select_diversified_portfolio(
        self, 
        rebalance_date: pd.Timestamp, 
        n_assets: int = 5,
        min_history_days: int = 252
    ) -> List[str]:
        """
        Select top N most diversified futures based on correlation.
        
        Strategy: Greedy algorithm to minimize average correlation
        
        Args:
            rebalance_date: Date for portfolio selection
            n_assets: Number of assets to select
            min_history_days: Minimum history required (days)
            
        Returns:
            List of selected tickers
        """
        start_date = rebalance_date - pd.DateOffset(months=self.lookback_months)
        
        # Calculate returns for all tickers
        returns_dict = {}
        for ticker in self.data.keys():
            returns = self.calculate_returns(ticker, rebalance_date)
            
            # Filter to lookback window
            returns_window = returns[returns.index >= start_date]
            
            # Check if sufficient history
            if len(returns_window) >= min_history_days * 0.8:  # Allow 20% missing
                returns_dict[ticker] = returns_window
        
        if len(returns_dict) < n_assets:
            print(f"Warning: Only {len(returns_dict)} tickers have sufficient history")
            return list(returns_dict.keys())
        
        # Build returns matrix
        returns_df = pd.DataFrame(returns_dict).dropna()
        
        if returns_df.empty or len(returns_df.columns) < n_assets:
            return list(returns_dict.keys())[:n_assets]
        
        # Calculate correlation matrix
        corr_matrix = returns_df.corr()
        
        # Greedy selection: iteratively add asset with lowest avg correlation to selected
        selected = []
        remaining = list(corr_matrix.columns)
        
        # Start with asset having lowest average correlation to all others
        avg_corr = corr_matrix.mean()
        first_asset = avg_corr.idxmin()
        selected.append(first_asset)
        remaining.remove(first_asset)
        
        # Iteratively select assets with lowest correlation to portfolio
        for _ in range(n_assets - 1):
            if not remaining:
                break
            
            # Calculate average correlation to selected portfolio
            avg_corr_to_portfolio = {}
            for ticker in remaining:
                avg_corr_to_portfolio[ticker] = corr_matrix.loc[ticker, selected].mean()
            
            # Select asset with minimum average correlation
            next_asset = min(avg_corr_to_portfolio, key=avg_corr_to_portfolio.get)
            selected.append(next_asset)
            remaining.remove(next_asset)
        
        return selected
    
    def get_correlation_matrix(
        self, 
        tickers: List[str], 
        end_date: pd.Timestamp
    ) -> pd.DataFrame:
        """Get correlation matrix for given tickers."""
        start_date = end_date - pd.DateOffset(months=self.lookback_months)
        
        returns_dict = {}
        for ticker in tickers:
            returns = self.calculate_returns(ticker, end_date)
            returns_window = returns[returns.index >= start_date]
            returns_dict[ticker] = returns_window
        
        returns_df = pd.DataFrame(returns_dict).dropna()
        return returns_df.corr() if not returns_df.empty else pd.DataFrame()


# ============================================================================
# 2. TRADING STRATEGIES
# ============================================================================

class TrendFollowingStrategy:
    """
    Trend-following strategy using dual moving average crossover.
    
    Signal:
    - Long: Fast MA > Slow MA
    - Short: Fast MA < Slow MA
    """
    
    def __init__(self, fast_period: int = 20, slow_period: int = 60):
        """
        Initialize trend-following strategy.
        
        Args:
            fast_period: Fast MA period (days)
            slow_period: Slow MA period (days)
        """
        self.fast_period = fast_period
        self.slow_period = slow_period
    
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        Generate trading signals.
        
        Args:
            df: OHLC DataFrame with 'close' column
            
        Returns:
            Series of signals: 1 (long), -1 (short), 0 (neutral)
        """
        close = df['close'].copy()
        
        # Calculate moving averages
        fast_ma = close.rolling(window=self.fast_period, min_periods=self.fast_period).mean()
        slow_ma = close.rolling(window=self.slow_period, min_periods=self.slow_period).mean()
        
        # Generate signals
        signals = pd.Series(0, index=df.index)
        signals[fast_ma > slow_ma] = 1   # Long
        signals[fast_ma < slow_ma] = -1  # Short
        
        return signals
    
    def calculate_returns(self, df: pd.DataFrame) -> pd.Series:
        """Calculate strategy returns."""
        signals = self.generate_signals(df)
        
        # Shift signals to avoid look-ahead bias
        positions = signals.shift(1)
        
        # Calculate returns
        price_returns = df['close'].pct_change()
        strategy_returns = positions * price_returns
        
        return strategy_returns.fillna(0)


class MeanReversionStrategy:
    """
    Mean-reversion strategy using Bollinger Bands.
    
    Signal:
    - Long: Price < Lower Band (oversold)
    - Short: Price > Upper Band (overbought)
    - Exit: Price crosses middle band
    """
    
    def __init__(self, period: int = 20, num_std: float = 2.0):
        """
        Initialize mean-reversion strategy.
        
        Args:
            period: Bollinger Band period (days)
            num_std: Number of standard deviations
        """
        self.period = period
        self.num_std = num_std
    
    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        """
        Generate trading signals.
        
        Args:
            df: OHLC DataFrame with 'close' column
            
        Returns:
            Series of signals: 1 (long), -1 (short), 0 (neutral)
        """
        close = df['close'].copy()
        
        # Calculate Bollinger Bands
        middle = close.rolling(window=self.period, min_periods=self.period).mean()
        std = close.rolling(window=self.period, min_periods=self.period).std()
        upper = middle + self.num_std * std
        lower = middle - self.num_std * std
        
        # Generate raw signals
        signals = pd.Series(0, index=df.index)
        signals[close < lower] = 1   # Oversold -> Long
        signals[close > upper] = -1  # Overbought -> Short
        
        # Hold position until price crosses middle band
        position = 0
        final_signals = []
        for i in range(len(signals)):
            if signals.iloc[i] != 0:
                position = signals.iloc[i]
            elif not pd.isna(middle.iloc[i]) and position != 0:
                # Exit if price crosses middle band
                if (position == 1 and close.iloc[i] > middle.iloc[i]) or \
                   (position == -1 and close.iloc[i] < middle.iloc[i]):
                    position = 0
            final_signals.append(position)
        
        return pd.Series(final_signals, index=df.index)
    
    def calculate_returns(self, df: pd.DataFrame) -> pd.Series:
        """Calculate strategy returns."""
        signals = self.generate_signals(df)
        
        # Shift signals to avoid look-ahead bias
        positions = signals.shift(1)
        
        # Calculate returns
        price_returns = df['close'].pct_change()
        strategy_returns = positions * price_returns
        
        return strategy_returns.fillna(0)


# ============================================================================
# 3. BACKTESTING FRAMEWORK
# ============================================================================

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


# ============================================================================
# 4. STRATEGY COMBINATION OPTIMIZER
# ============================================================================

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
        max_drawdown_constraint: float = None
    ) -> Dict[str, float]:
        """
        Optimize strategy weights.
        
        Args:
            objective: 'sharpe', 'return', or 'min_vol'
            max_drawdown_constraint: Maximum allowed drawdown (optional)
            
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
        
        # Bounds: weights between 0 and 1
        bounds = [(0, 1) for _ in range(n_strategies)]
        
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


# ============================================================================
# MAIN EXECUTION
# ============================================================================

if __name__ == "__main__":
    # Load data
    file_path = os.path.join(DIR_INPUT, 'futures-dailyK_con.pkl')
    data = pd.read_pickle(file_path)
    
    print("="*80)
    print("FUTURES PORTFOLIO STRATEGY SYSTEM")
    print("="*80)
    
    # 1. Portfolio Selection
    print("\n1. DIVERSIFIED PORTFOLIO SELECTION")
    print("-" * 80)
    
    selector = FuturesPortfolioSelector(data, lookback_months=12)
    
    # Find a suitable date from the data
    sample_ticker = list(data.keys())[0]
    available_dates = data[sample_ticker].index
    rebalance_date = available_dates[-252]  # 1 year before end
    
    selected_tickers = selector.select_diversified_portfolio(
        rebalance_date=rebalance_date,
        n_assets=5
    )
    
    print(f"Selected tickers (as of {rebalance_date.date()}):")
    for ticker in selected_tickers:
        print(f"  - {ticker}")
    
    # Show correlation matrix
    corr_matrix = selector.get_correlation_matrix(selected_tickers, rebalance_date)
    if not corr_matrix.empty:
        print(f"\nCorrelation Matrix:")
        print(corr_matrix.round(3))
    
    # 2. Strategy Design & 3. Backtesting (using first selected ticker)
    print(f"\n2-3. STRATEGY BACKTESTING (Ticker: {selected_tickers[0]})")
    print("-" * 80)
    
    test_ticker = selected_tickers[0]
    test_data = data[test_ticker].copy()
    
    # Filter to last 5 years
    end_date = test_data.index.max()
    start_date = end_date - pd.DateOffset(years=5)
    test_data = test_data[test_data.index >= start_date]
    
    print(f"Backtest period: {test_data.index.min().date()} to {test_data.index.max().date()}")
    print(f"Total trading days: {len(test_data)}")
    
    # Initialize strategies
    trend_strategy = TrendFollowingStrategy(fast_period=20, slow_period=60)
    mr_strategy = MeanReversionStrategy(period=20, num_std=2.0)
    
    # Calculate strategy returns
    trend_returns = trend_strategy.calculate_returns(test_data)
    mr_returns = mr_strategy.calculate_returns(test_data)
    buy_hold_returns = test_data['close'].pct_change().fillna(0)
    
    # Backtest
    backtester = StrategyBacktester(test_data)
    
    strategies = {
        'Trend Following': trend_returns,
        'Mean Reversion': mr_returns,
        'Buy & Hold': buy_hold_returns
    }
    
    comparison = backtester.compare_strategies(strategies)
    print(f"\nStrategy Performance Comparison:")
    print(comparison)
    
    # 4. Strategy Combination
    print(f"\n4. STRATEGY COMBINATION OPTIMIZATION")
    print("-" * 80)
    
    blender = StrategyBlender({
        'Trend': trend_returns,
        'MeanRev': mr_returns
    })
    
    # Optimize for maximum Sharpe ratio
    optimal_weights_sharpe = blender.optimize_weights(objective='sharpe')
    print(f"\nOptimal Weights (Max Sharpe):")
    for strategy, weight in optimal_weights_sharpe.items():
        print(f"  {strategy}: {weight:.3f}")
    
    # Optimize with drawdown constraint
    optimal_weights_dd = blender.optimize_weights(
        objective='sharpe',
        max_drawdown_constraint=0.15  # Max 15% drawdown
    )
    print(f"\nOptimal Weights (Max Sharpe with 15% DD constraint):")
    for strategy, weight in optimal_weights_dd.items():
        print(f"  {strategy}: {weight:.3f}")
    
    # Backtest blended strategy
    blended_returns_sharpe = blender.get_blended_returns(optimal_weights_sharpe)
    blended_returns_dd = blender.get_blended_returns(optimal_weights_dd)
    
    strategies_with_blend = {
        'Trend Following': trend_returns,
        'Mean Reversion': mr_returns,
        'Blended (Max Sharpe)': blended_returns_sharpe,
        'Blended (DD Constrained)': blended_returns_dd,
        'Buy & Hold': buy_hold_returns
    }
    
    final_comparison = backtester.compare_strategies(strategies_with_blend)
    print(f"\nFinal Performance Comparison (Including Blended):")
    print(final_comparison)
    
    print("\n" + "="*80)
    print("ANALYSIS COMPLETE")
    print("="*80)
