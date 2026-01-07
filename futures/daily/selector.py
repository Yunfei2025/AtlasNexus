# -*- coding: utf-8 -*-
"""
Portfolio Selection Module

Diversified portfolio selection based on correlation analysis.

@author: CMBC
"""
import pandas as pd
from typing import Dict, List


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
        if 'Close' not in df.columns:
            return pd.Series(dtype=float)
        
        # Filter data up to end_date
        df_filtered = df[df.index <= end_date].copy()
        
        # Calculate returns
        returns = df_filtered['Close'].pct_change().dropna()

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
        start_date = (rebalance_date - pd.DateOffset(months=self.lookback_months)).date()
        
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
