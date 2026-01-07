# -*- coding: utf-8 -*-
"""
Backtesting framework for volatility trading strategies
Created on Oct 29, 2025

@author: CMBC
"""
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from .vol import BaseStrategy, VolatilityData


class StrategyBacktester:
    """
    Backtesting engine for volatility trading strategies
    """
    
    def __init__(self, vol_data: VolatilityData):
        """
        Initialize backtester
        
        Parameters:
        -----------
        vol_data : VolatilityData
            Volatility data container
        """
        self.vol_data = vol_data
        self.results = {}
        
    def backtest_strategy(
        self, 
        strategy: BaseStrategy,
        transaction_cost: float = 0.0
    ) -> pd.DataFrame:
        """
        Backtest a single strategy
        
        Parameters:
        -----------
        strategy : BaseStrategy
            Strategy to backtest
        transaction_cost : float
            Transaction cost per trade (as decimal)
            
        Returns:
        --------
        pd.DataFrame
            Backtest results with returns and cumulative performance
        """
        data = self.vol_data.get_data()
        
        # Get strategy signals
        signals = strategy.run(self.vol_data)
        
        # Calculate market return (using IV changes as proxy)
        market_return = data['IV_1M'].pct_change()
        
        # Strategy return = signal × market return
        # Note: short volatility (signal=-1) profits when IV declines
        strategy_return = signals.shift(1) * market_return
        
        # Apply transaction costs on signal changes
        signal_changes = (signals.diff() != 0).astype(int)
        strategy_return = strategy_return - (signal_changes * transaction_cost)
        
        # Calculate cumulative returns
        cumulative_return = (1 + strategy_return.fillna(0)).cumprod()
        
        # Create results DataFrame
        results = pd.DataFrame({
            'Signal': signals,
            'Market_Return': market_return,
            'Strategy_Return': strategy_return,
            'Cumulative_Return': cumulative_return
        }, index=data.index)
        
        # Store results
        self.results[strategy.name] = results
        
        return results
    
    def backtest_multiple(
        self,
        strategies: List[BaseStrategy],
        transaction_cost: float = 0.0
    ) -> Dict[str, pd.DataFrame]:
        """
        Backtest multiple strategies
        
        Parameters:
        -----------
        strategies : list
            List of strategies to backtest
        transaction_cost : float
            Transaction cost per trade
            
        Returns:
        --------
        dict
            Dictionary mapping strategy names to backtest results
        """
        results = {}
        for strategy in strategies:
            results[strategy.name] = self.backtest_strategy(strategy, transaction_cost)
        
        return results
    
    def calculate_metrics(self, strategy_name: str) -> Dict:
        """
        Calculate performance metrics for a strategy
        
        Parameters:
        -----------
        strategy_name : str
            Name of the strategy
            
        Returns:
        --------
        dict
            Dictionary of performance metrics
        """
        if strategy_name not in self.results:
            return {}
        
        results = self.results[strategy_name]
        returns = results['Strategy_Return'].dropna()
        cumulative = results['Cumulative_Return']
        
        if len(returns) == 0:
            return {}
        
        # Calculate metrics
        total_return = cumulative.iloc[-1] - 1
        
        # Annualized return
        num_periods = len(returns)
        years = num_periods / 252  # Assuming 252 trading days per year
        annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
        
        # Volatility (annualized)
        volatility = returns.std() * np.sqrt(252)
        
        # Sharpe ratio
        sharpe_ratio = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        
        # Win rate
        win_rate = (returns > 0).sum() / len(returns)
        
        # Max drawdown
        rolling_max = cumulative.expanding().max()
        drawdown = (cumulative / rolling_max - 1)
        max_drawdown = drawdown.min()
        
        # Number of trades
        num_trades = (results['Signal'].diff() != 0).sum()
        
        # Average return per trade
        avg_return = returns.mean()
        
        # Profit factor
        gains = returns[returns > 0].sum()
        losses = abs(returns[returns < 0].sum())
        profit_factor = gains / losses if losses > 0 else np.inf
        
        return {
            'Total_Return': total_return,
            'Annualized_Return': annualized_return,
            'Volatility': volatility,
            'Sharpe_Ratio': sharpe_ratio,
            'Win_Rate': win_rate,
            'Max_Drawdown': max_drawdown,
            'Num_Trades': num_trades,
            'Avg_Return_Per_Trade': avg_return,
            'Profit_Factor': profit_factor
        }
    
    def get_all_metrics(self) -> pd.DataFrame:
        """
        Get performance metrics for all backtested strategies
        
        Returns:
        --------
        pd.DataFrame
            DataFrame with metrics for all strategies
        """
        all_metrics = {}
        for strategy_name in self.results.keys():
            all_metrics[strategy_name] = self.calculate_metrics(strategy_name)
        
        return pd.DataFrame(all_metrics).T
    
    def print_metrics(self, strategy_name: Optional[str] = None):
        """
        Print performance metrics
        
        Parameters:
        -----------
        strategy_name : str, optional
            Strategy name. If None, prints all strategies
        """
        if strategy_name:
            self._print_single_metrics(strategy_name)
        else:
            self._print_all_metrics()
    
    def _print_single_metrics(self, strategy_name: str):
        """Print metrics for a single strategy"""
        metrics = self.calculate_metrics(strategy_name)
        
        if not metrics:
            print(f"No metrics available for {strategy_name}")
            return
        
        print(f"\n{'='*70}")
        print(f"Performance Metrics: {strategy_name}")
        print(f"{'='*70}")
        print(f"Total Return:            {metrics['Total_Return']:>10.2%}")
        print(f"Annualized Return:       {metrics['Annualized_Return']:>10.2%}")
        print(f"Volatility (Annual):     {metrics['Volatility']:>10.2%}")
        print(f"Sharpe Ratio:            {metrics['Sharpe_Ratio']:>10.2f}")
        print(f"Win Rate:                {metrics['Win_Rate']:>10.2%}")
        print(f"Max Drawdown:            {metrics['Max_Drawdown']:>10.2%}")
        print(f"Number of Trades:        {metrics['Num_Trades']:>10d}")
        print(f"Avg Return per Trade:    {metrics['Avg_Return_Per_Trade']:>10.4%}")
        print(f"Profit Factor:           {metrics['Profit_Factor']:>10.2f}")
    
    def _print_all_metrics(self):
        """Print metrics for all strategies"""
        print(f"\n{'='*80}")
        print("📊 Strategy Backtest Performance Comparison")
        print(f"{'='*80}")
        
        metrics_df = self.get_all_metrics()
        
        if metrics_df.empty:
            print("No backtest results available")
            return
        
        # Format for display
        display_df = metrics_df.copy()
        for col in display_df.columns:
            if 'Return' in col or 'Rate' in col or 'Drawdown' in col or 'Volatility' in col:
                display_df[col] = display_df[col].apply(lambda x: f"{x:.2%}")
            elif col in ['Sharpe_Ratio', 'Profit_Factor']:
                display_df[col] = display_df[col].apply(lambda x: f"{x:.2f}")
            elif col == 'Num_Trades':
                display_df[col] = display_df[col].astype(int)
            elif col == 'Avg_Return_Per_Trade':
                display_df[col] = display_df[col].apply(lambda x: f"{x:.4%}")
        
        print(display_df.to_string())
    
    def get_combined_results(self) -> pd.DataFrame:
        """
        Get combined DataFrame with all strategy returns
        
        Returns:
        --------
        pd.DataFrame
            DataFrame with returns from all strategies
        """
        if not self.results:
            return pd.DataFrame()
        
        combined = pd.DataFrame()
        
        for strategy_name, results in self.results.items():
            col_name = f"{strategy_name}_Return"
            combined[col_name] = results['Strategy_Return']
            
            col_name_cum = f"{strategy_name}_Cumulative"
            combined[col_name_cum] = results['Cumulative_Return']
        
        return combined
    
    def export_results(self, filepath: str):
        """
        Export backtest results to pickle file
        
        Parameters:
        -----------
        filepath : str
            Path to save pickle file
        """
        combined = self.get_combined_results()
        
        if combined.empty:
            print("No results to export")
            return
        
        # Add original volatility data
        original_data = self.vol_data.get_data()
        for col in original_data.columns:
            if col not in combined.columns:
                combined[col] = original_data[col]
        
        combined.to_pickle(filepath)
        print(f"\n✅ Backtest results saved to: {filepath}")


class PerformanceAnalyzer:
    """
    Advanced performance analysis tools
    """
    
    @staticmethod
    def rolling_sharpe(returns: pd.Series, window: int = 20) -> pd.Series:
        """Calculate rolling Sharpe ratio"""
        rolling_mean = returns.rolling(window).mean()
        rolling_std = returns.rolling(window).std()
        return (rolling_mean / rolling_std) * np.sqrt(252)
    
    @staticmethod
    def calculate_var(returns: pd.Series, confidence: float = 0.95) -> float:
        """Calculate Value at Risk"""
        return returns.quantile(1 - confidence)
    
    @staticmethod
    def calculate_cvar(returns: pd.Series, confidence: float = 0.95) -> float:
        """Calculate Conditional Value at Risk (Expected Shortfall)"""
        var = PerformanceAnalyzer.calculate_var(returns, confidence)
        return returns[returns <= var].mean()
    
    @staticmethod
    def calculate_calmar_ratio(returns: pd.Series, cumulative: pd.Series) -> float:
        """Calculate Calmar ratio (return / max drawdown)"""
        total_return = cumulative.iloc[-1] - 1
        rolling_max = cumulative.expanding().max()
        drawdown = (cumulative / rolling_max - 1)
        max_drawdown = abs(drawdown.min())
        
        if max_drawdown == 0:
            return np.inf
        
        years = len(returns) / 252
        annualized_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
        
        return annualized_return / max_drawdown
    
    @staticmethod
    def analyze_drawdowns(cumulative: pd.Series, top_n: int = 5) -> pd.DataFrame:
        """
        Analyze top drawdown periods
        
        Returns:
        --------
        pd.DataFrame
            DataFrame with drawdown start, end, duration, and magnitude
        """
        rolling_max = cumulative.expanding().max()
        drawdown = (cumulative / rolling_max - 1)
        
        # Find drawdown periods
        is_drawdown = drawdown < 0
        drawdown_starts = is_drawdown & ~is_drawdown.shift(1, fill_value=False)
        drawdown_ends = ~is_drawdown & is_drawdown.shift(1, fill_value=False)
        
        drawdowns = []
        start_idx = None
        
        for idx, is_start in drawdown_starts.items():
            if is_start:
                start_idx = idx
        
        for idx, is_end in drawdown_ends.items():
            if is_end and start_idx is not None:
                dd_period = drawdown[start_idx:idx]
                min_dd = dd_period.min()
                min_dd_date = dd_period.idxmin()
                
                drawdowns.append({
                    'Start': start_idx,
                    'Bottom': min_dd_date,
                    'End': idx,
                    'Duration': (idx - start_idx).days,
                    'Magnitude': min_dd
                })
                start_idx = None
        
        if drawdowns:
            dd_df = pd.DataFrame(drawdowns)
            dd_df = dd_df.nlargest(top_n, 'Magnitude', keep='first')
            return dd_df.sort_values('Magnitude')
        
        return pd.DataFrame()
